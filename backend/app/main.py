from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from . import archive, catalog, gemini_calls, role_fit, sources, store, studyguide
from .domain_personas import DOMAIN_PERSONAS
from .gaps import compute_skill_match_pct, detect_gaps, skills_master, suppress_false_positive_gaps
from .parser import SUPPORTED_EXTENSIONS, extract_text, parse_resume_to_json
from .renderer import render_docx, render_pdf
from .schemas import (
    ApplicationRecord,
    Bullet,
    CatalogEntry,
    DiffSummary,
    GapItem,
    MarketFitReport,
    ResumeJSON,
    StudyGuideEntry,
    StudyPlan,
    UserSettings,
)
from .segments import build_segments

APP_MODE = os.environ.get("APP_MODE", "local")  # local | cloud

app = FastAPI(title="Resume Tailoring Agent v2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before deploying past local dev
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": APP_MODE}


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

class LoadResumeRequest(BaseModel):
    local_path: str


class LoadResumeResponse(BaseModel):
    resume: ResumeJSON
    changed_from_stored: bool


def _parse_resume_bytes(filename: str, content: bytes) -> ResumeJSON:
    raw_text = extract_text(filename, content)
    if not raw_text.strip():
        raise HTTPException(422, "No extractable text found in the resume file")
    return parse_resume_to_json(raw_text)


def _load_resume_response(parsed: ResumeJSON) -> LoadResumeResponse:
    # Never silently overwrites the stored ResumeJSON — returns the parse
    # result and whether it differs; the user confirms the merge by POSTing
    # /onboarding/resume afterward.
    stored = store.get_base_resume()
    changed = parsed.model_dump() != stored.model_dump()
    return LoadResumeResponse(resume=parsed, changed_from_stored=changed)


# APP_MODE controls which code path (and which request shape) this endpoint
# uses: JSON {local_path} when running locally, multipart upload on Cloud Run.
if APP_MODE == "local":

    @app.post("/onboarding/load-resume", response_model=LoadResumeResponse)
    def load_resume_local(req: LoadResumeRequest) -> LoadResumeResponse:
        path = Path(req.local_path).expanduser()
        if not path.exists():
            raise HTTPException(404, f"File not found: {path}")
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise HTTPException(400, f"Unsupported file type. Use one of {SUPPORTED_EXTENSIONS}")
        return _load_resume_response(_parse_resume_bytes(path.name, path.read_bytes()))

else:

    @app.post("/onboarding/load-resume", response_model=LoadResumeResponse)
    async def load_resume_cloud(file: UploadFile) -> LoadResumeResponse:
        if not any(file.filename.lower().endswith(ext) for ext in SUPPORTED_EXTENSIONS):
            raise HTTPException(400, f"Unsupported file type. Use one of {SUPPORTED_EXTENSIONS}")
        return _load_resume_response(_parse_resume_bytes(file.filename, await file.read()))


@app.get("/onboarding/resume", response_model=ResumeJSON)
def get_base_resume() -> ResumeJSON:
    return store.get_base_resume()


@app.post("/onboarding/resume", response_model=ResumeJSON)
def save_base_resume(resume: ResumeJSON) -> ResumeJSON:
    _reconcile_segments(resume)
    store.save_base_resume(resume)
    return resume


def _reconcile_segments(resume: ResumeJSON) -> None:
    """If a bullet's text was edited in the UI, its carried-over segments are
    stale — regenerate them deterministically so the render never shows old
    text. Untouched bullets keep their original docx-extracted segments."""
    from .segments import flatten

    def fix(bullet) -> None:
        if bullet.segments and flatten(bullet.segments) != bullet.text:
            bullet.segments = build_segments(bullet.text, [])
        elif not bullet.segments and bullet.text:
            bullet.segments = build_segments(bullet.text, [])

    for b in resume.accomplishments:
        fix(b)
    for exp in resume.experience:
        for b in exp.bullets:
            fix(b)
    if resume.summary_segments:
        from .segments import flatten as _f

        if _f(resume.summary_segments) != resume.summary:
            resume.summary_segments = build_segments(resume.summary, [])
    elif resume.summary:
        resume.summary_segments = build_segments(resume.summary, [])


class TagCoreResponse(BaseModel):
    core_bullet_ids: list[str]


@app.post("/onboarding/tag-core", response_model=TagCoreResponse)
def tag_core() -> TagCoreResponse:
    """One-time Gemini pass proposing core flags. The proposal is returned for
    human review in the UI — it is not applied to the stored resume here."""
    resume = store.get_base_resume()
    return TagCoreResponse(core_bullet_ids=gemini_calls.tag_core_bullets(resume))


# ---------------------------------------------------------------------------
# Phase 1 — ANALYZING
# ---------------------------------------------------------------------------

class CreateApplicationRequest(BaseModel):
    company: str = ""
    job_description: str
    company_context: str = ""


@app.post("/applications", response_model=ApplicationRecord)
def create_application(req: CreateApplicationRequest) -> ApplicationRecord:
    if not req.job_description.strip():
        raise HTTPException(400, "job_description is required")

    resume = store.get_base_resume()
    jd_analysis = gemini_calls.analyze_jd(req.job_description)

    # Role-fit gate (patch §1): runs immediately after JD analysis, before
    # any tailoring or gap detection. "skip" refuses outright; "warn" is
    # carried on the record for the UI to surface but does not block.
    skill_match_pct = compute_skill_match_pct(resume, jd_analysis)
    fit = role_fit.assess(jd_analysis, skill_match_pct)
    if fit.decision == "skip":
        raise HTTPException(422, f"Skipped: {fit.decision_reason}")

    tailoring_plan = gemini_calls.build_tailoring_plan(resume, jd_analysis)

    gaps = detect_gaps(resume, jd_analysis, req.job_description)
    # Patch §4b: semantic double-check — can only remove false-positive gaps
    # already substantively covered under a different name/tool in the resume.
    gaps = suppress_false_positive_gaps(gaps, resume)
    master = skills_master(resume)
    role = jd_analysis.role_title
    # ONE canonicalization call for every gap in this JD, not one per gap —
    # same fix as Trend Scan's multi-JD batching, applied here since a JD
    # with many gaps hit the same per-requirement Gemini round-trip cost.
    resolved = catalog.resolve_batch([g.requirement for g in gaps])
    for gap in gaps:
        # v3 §5: check the cross-application catalog BEFORE re-asking or
        # re-educating. Known+confirmed → offer one-click reuse; known but
        # unconfirmed → reuse the stored education, bump demand only.
        entry = resolved.get(gap.requirement)
        if entry is None:
            entry = catalog.create_entry(
                gap.requirement, "", req.company, role,
                role_category=jd_analysis.role_category,
            )
            gap.canonical_id = entry.canonical_id
            gap.education = gemini_calls.educate_gap(
                gap.requirement, gap.jd_context, master,
                role_category=jd_analysis.role_category,
            )
        else:
            catalog.register_demand(
                entry, req.company, role, role_category=jd_analysis.role_category
            )
            gap.canonical_id = entry.canonical_id
            if entry.status_history:
                last = entry.status_history[-1]
                if last.status in ("have_experience", "partial_experience") and last.note:
                    gap.reusable_note = last.note
                    gap.reusable_status = last.status
                    gap.reused_from = last.source_application_id
            prior = _find_prior_education(entry.canonical_id)
            if prior is not None:
                gap.education = prior
            else:
                gap.education = gemini_calls.educate_gap(
                    gap.requirement, gap.jd_context, master,
                    role_category=jd_analysis.role_category,
                )

    persona = DOMAIN_PERSONAS.get(jd_analysis.role_category)
    interview_lens = (
        {"persona_title": persona["title"], **persona["interview_lens"]}
        if persona
        else None
    )
    record = ApplicationRecord(
        company=req.company,
        role_title=role,
        status="pending_review",
        created_at=datetime.now(timezone.utc).isoformat(),
        jd_analysis=jd_analysis,
        tailoring_plan=tailoring_plan,
        gaps=gaps,
        role_fit=fit,
        interview_lens=interview_lens,
    )
    # Persist immediately (v3 §5) — a crash or closed tab after this point
    # must not lose the analysis.
    return store.create_application(record)


def _find_prior_education(canonical_id: str):
    for app in store.list_applications():
        for gap in app.gaps:
            if gap.canonical_id == canonical_id and gap.education.what_it_is:
                return gap.education
    return None


@app.get("/applications", response_model=list[ApplicationRecord])
def list_applications() -> list[ApplicationRecord]:
    return store.list_applications()


def _get_record_or_404(application_id: str) -> ApplicationRecord:
    record = store.get_application(application_id)
    if record is None:
        raise HTTPException(404, "Application not found")
    return record


@app.get("/applications/{application_id}", response_model=ApplicationRecord)
def get_application(application_id: str) -> ApplicationRecord:
    return _get_record_or_404(application_id)


# ---------------------------------------------------------------------------
# Phase 2 — PENDING_REVIEW: the human-in-the-loop gap review
# ---------------------------------------------------------------------------

class GapResponseRequest(BaseModel):
    status: str  # have_experience | partial_experience | no_experience
    user_note: str = ""
    target_exp_id: str = ""  # where a proposed bullet would attach; defaults to most recent


@app.post(
    "/applications/{application_id}/gaps/{gap_index}/respond",
    response_model=GapItem,
)
def respond_to_gap(application_id: str, gap_index: int, req: GapResponseRequest) -> GapItem:
    record = _get_record_or_404(application_id)
    if record.status != "pending_review":
        raise HTTPException(409, f"Application is {record.status}, not pending_review")
    if not 0 <= gap_index < len(record.gaps):
        raise HTTPException(404, "Gap not found")
    if req.status not in ("have_experience", "partial_experience", "no_experience"):
        raise HTTPException(400, "status must be have_experience | partial_experience | no_experience")

    gap = record.gaps[gap_index]
    if req.status in ("have_experience", "partial_experience") and not req.user_note.strip():
        # Mechanical enforcement of "the app doesn't decide what I've done":
        # no note, no addition.
        raise HTTPException(400, "user_note is required when claiming experience")

    gap.user_response.status = req.status
    gap.user_response.user_note = req.user_note.strip()
    gap.user_response.reviewed_at = datetime.now(timezone.utc).isoformat()

    resume = store.get_base_resume()
    if req.status in ("have_experience", "partial_experience"):
        style_samples = [b.text for exp in resume.experience[:1] for b in exp.bullets[:4]]
        gap.proposed_bullet = gemini_calls.draft_gap_bullet(
            gap.requirement, gap.user_response.user_note, style_samples
        )
        gap.proposed_target_exp_id = req.target_exp_id or (
            resume.experience[0].id if resume.experience else ""
        )
    else:
        gap.proposed_bullet = ""
        gap.proposed_target_exp_id = ""

    # Written immediately (v3 §5) and carried into cross-application memory.
    store.save_application(record)
    catalog.record_user_response(gap, record.id)
    return gap


class ReuseGapRequest(BaseModel):
    target_exp_id: str = ""


@app.post(
    "/applications/{application_id}/gaps/{gap_index}/reuse",
    response_model=GapItem,
)
def reuse_gap_confirmation(
    application_id: str, gap_index: int, req: ReuseGapRequest
) -> GapItem:
    """One-click reuse of a previously confirmed note from the catalog —
    no re-asking, no re-typing (v3 §5 canonicalization flow)."""
    record = _get_record_or_404(application_id)
    if not 0 <= gap_index < len(record.gaps):
        raise HTTPException(404, "Gap not found")
    gap = record.gaps[gap_index]
    if not gap.reusable_note or gap.reusable_status not in (
        "have_experience", "partial_experience",
    ):
        raise HTTPException(409, "No reusable confirmation on file for this gap")
    return respond_to_gap(
        application_id,
        gap_index,
        GapResponseRequest(
            status=gap.reusable_status,
            user_note=gap.reusable_note,
            target_exp_id=req.target_exp_id,
        ),
    )


class EditProposedBulletRequest(BaseModel):
    proposed_bullet: str


@app.post(
    "/applications/{application_id}/gaps/{gap_index}/edit-proposal",
    response_model=GapItem,
)
def edit_proposed_bullet(
    application_id: str, gap_index: int, req: EditProposedBulletRequest
) -> GapItem:
    """User edits the drafted bullet text directly before approving."""
    record = _get_record_or_404(application_id)
    if not 0 <= gap_index < len(record.gaps):
        raise HTTPException(404, "Gap not found")
    gap = record.gaps[gap_index]
    if gap.user_response.status not in ("have_experience", "partial_experience"):
        raise HTTPException(409, "Cannot edit a proposal for an unconfirmed gap")
    gap.proposed_bullet = req.proposed_bullet.strip()
    store.save_application(record)
    return gap


@app.post("/applications/{application_id}/discard", response_model=ApplicationRecord)
def discard_application(application_id: str) -> ApplicationRecord:
    """Walk away from an application before finalize (patch §5). No GCS/BQ
    writes, no catalog rollback — the JD's requirements stay counted in
    requirements_catalog demand (that signal is still real), but nothing
    else happens. Callable from analyzing, pending_review, or approved."""
    record = _get_record_or_404(application_id)
    if record.status in ("finalized", "archived"):
        raise HTTPException(409, f"Application is {record.status} — nothing to discard")
    record.status = "discarded"
    store.save_application(record)
    return record


@app.post("/applications/{application_id}/study-plan", response_model=list[StudyPlan])
def generate_study_plans(application_id: str) -> list[StudyPlan]:
    """Study plans for every gap marked no_experience (Gemini Call 5)."""
    record = _get_record_or_404(application_id)
    resume = store.get_base_resume()
    master = skills_master(resume)
    plans = [
        gemini_calls.build_study_plan(gap.requirement, gap.jd_context, master)
        for gap in record.gaps
        if gap.user_response.status == "no_experience"
    ]
    record.study_plans = plans
    store.save_application(record)
    return plans


# ---------------------------------------------------------------------------
# Phase 2 → 3 — Approve (gates everything downstream)
# ---------------------------------------------------------------------------

@app.post("/applications/{application_id}/approve", response_model=ApplicationRecord)
def approve_application(application_id: str) -> ApplicationRecord:
    record = _get_record_or_404(application_id)
    if record.status != "pending_review":
        raise HTTPException(409, f"Application is {record.status}, not pending_review")

    unreviewed = [g.requirement for g in record.gaps if g.user_response.status == "not_reviewed"]
    if unreviewed:
        raise HTTPException(409, f"Unreviewed gaps remain: {unreviewed}")

    record.diff_summary = _build_diff_summary(record)
    record.status = "approved"
    record.approved_at = datetime.now(timezone.utc).isoformat()
    store.save_application(record)
    return record


def _build_diff_summary(record: ApplicationRecord) -> DiffSummary:
    resume = store.get_base_resume()
    originals = {b.id: b.text for exp in resume.experience for b in exp.bullets}
    originals.update({b.id: b.text for b in resume.accomplishments})

    diff = DiffSummary()
    plan = record.tailoring_plan
    if plan:
        for item in plan.bullet_plan:
            orig = originals.get(item.bullet_id, "")
            if item.final_text and item.final_text != orig:
                diff.reworded.append(f"{item.bullet_id}: '{orig}' -> '{item.final_text}'")
        for exp_id, order in plan.bullet_order.items():
            original_order = next(
                ([b.id for b in e.bullets] for e in resume.experience if e.id == exp_id), []
            )
            if order != original_order:
                diff.reordered.append(f"{exp_id}: {original_order} -> {order}")
    for gap in record.gaps:
        if gap.proposed_bullet and gap.user_response.status in (
            "have_experience", "partial_experience"
        ):
            diff.added.append(
                f"{gap.proposed_target_exp_id}: '{gap.proposed_bullet}' (confirmed gap: {gap.requirement})"
            )
    return diff


# ---------------------------------------------------------------------------
# Phase 3 — FINALIZE (render/export; only for approved applications)
# ---------------------------------------------------------------------------

def _require_approved(record: ApplicationRecord) -> None:
    if record.status not in ("approved", "finalized", "archived"):
        raise HTTPException(
            409, f"Application must be approved before rendering (currently {record.status})"
        )


@app.get("/applications/{application_id}/resume.docx")
def export_docx(application_id: str) -> Response:
    record = _get_record_or_404(application_id)
    _require_approved(record)
    docx_bytes = render_docx(store.get_base_resume(), record.tailoring_plan)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=resume.docx"},
    )


@app.get("/applications/{application_id}/resume.pdf")
def export_pdf(application_id: str) -> Response:
    record = _get_record_or_404(application_id)
    _require_approved(record)
    pdf_bytes = render_pdf(store.get_base_resume(), record.tailoring_plan)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=resume.pdf"},
    )


class CoverLetterResponse(BaseModel):
    cover_letter_text: str
    fabrication_check: dict


@app.post("/applications/{application_id}/cover-letter", response_model=CoverLetterResponse)
def generate_cover_letter(application_id: str) -> CoverLetterResponse:
    record = _get_record_or_404(application_id)
    _require_approved(record)
    resume = store.get_base_resume()
    confirmed_notes = [
        {"requirement": g.requirement, "note": g.user_response.user_note}
        for g in record.gaps
        if g.user_response.status in ("have_experience", "partial_experience")
        and g.user_response.user_note
    ]
    text = gemini_calls.write_cover_letter(
        resume, record.tailoring_plan, record.jd_analysis, confirmed_notes
    )
    # Deterministic format validation (v3 §4 strict rules); one retry.
    if not _letter_format_ok(text):
        text = gemini_calls.write_cover_letter(
            resume, record.tailoring_plan, record.jd_analysis, confirmed_notes
        )
    check = gemini_calls.check_cover_letter(text, resume, confirmed_notes)
    check["format_ok"] = _letter_format_ok(text)
    record.cover_letter = text
    store.save_application(record)
    return CoverLetterResponse(cover_letter_text=text, fabrication_check=check)


def _letter_format_ok(text: str) -> bool:
    """v3 strict format: ~3 body paragraphs, 180-250 word body (tolerantly
    120-300 counting greeting/sign-off noise), <=2 quantified metrics."""
    import re as _re

    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    body_words = len(text.split())
    metrics = _re.findall(r"\d[\d,]*(?:\.\d+)?\s?(?:%|\+|x|K|M|B|\$)", text)
    return 3 <= len(paragraphs) <= 6 and 120 <= body_words <= 320 and len(metrics) <= 2


# ---------------------------------------------------------------------------
# FINALIZE → ARCHIVE (v3 §3): render + cover letter + checks, then GCS/BQ/
# catalog updates. Promotion of confirmed gaps into the base resume.
# ---------------------------------------------------------------------------

@app.post("/applications/{application_id}/finalize", response_model=ApplicationRecord)
def finalize_application(application_id: str) -> ApplicationRecord:
    record = _get_record_or_404(application_id)
    if record.status != "approved":
        raise HTTPException(409, f"Application is {record.status}, not approved")
    if not record.cover_letter:
        generate_cover_letter(application_id)
        record = _get_record_or_404(application_id)
    record.status = "finalized"
    store.save_application(record)
    return record


class PromoteGapRequest(BaseModel):
    decision: str  # add_to_base | this_application_only | not_yet


@app.post(
    "/applications/{application_id}/gaps/{gap_index}/promote",
    response_model=ResumeJSON,
)
def promote_gap(application_id: str, gap_index: int, req: PromoteGapRequest) -> ResumeJSON:
    """CV improvement loop: append a confirmed-gap bullet to the permanent
    base resume (new ResumeVersion) — or record the user's decision not to."""
    record = _get_record_or_404(application_id)
    if not 0 <= gap_index < len(record.gaps):
        raise HTTPException(404, "Gap not found")
    gap = record.gaps[gap_index]
    resume = store.get_base_resume()

    if req.decision == "add_to_base":
        if gap.user_response.status not in ("have_experience", "partial_experience"):
            raise HTTPException(409, "Only confirmed gaps can be promoted")
        if not gap.proposed_bullet:
            raise HTTPException(409, "No drafted bullet to promote")
        target = next(
            (e for e in resume.experience if e.id == gap.proposed_target_exp_id),
            resume.experience[0] if resume.experience else None,
        )
        if target is None:
            raise HTTPException(409, "No experience entry to attach to")
        new_id = f"{target.id}_b{len(target.bullets) + 1}"
        target.bullets.append(
            Bullet(
                id=new_id,
                text=gap.proposed_bullet,
                segments=build_segments(gap.proposed_bullet, [gap.requirement]),
                core=False,
            )
        )
        store.save_base_resume(
            resume,
            change_reason=f"promoted {gap.requirement} bullet from {record.company or record.id} application",
        )
        if gap.canonical_id:
            entry = store.get_catalog_entry(gap.canonical_id)
            if entry:
                entry.in_base_resume = True
                store.save_catalog_entry(entry)
    elif req.decision == "not_yet":
        if gap.canonical_id:
            entry = store.get_catalog_entry(gap.canonical_id)
            if entry:
                entry.user_status = "partial_experience"
                store.save_catalog_entry(entry)
    elif req.decision != "this_application_only":
        raise HTTPException(400, "decision must be add_to_base | this_application_only | not_yet")

    return store.get_base_resume()


@app.post("/applications/{application_id}/archive", response_model=ApplicationRecord)
def archive_application(application_id: str) -> ApplicationRecord:
    record = _get_record_or_404(application_id)
    if record.status != "finalized":
        raise HTTPException(409, f"Application is {record.status}, not finalized")

    resume = store.get_base_resume()
    docx_bytes = render_docx(resume, record.tailoring_plan)
    pdf_bytes = render_pdf(resume, record.tailoring_plan)

    record.gcs_path = archive.upload_archive(record, docx_bytes, pdf_bytes)
    versions = store.list_resume_versions()
    archive.write_bigquery_rows(record, versions[-1].version if versions else None)

    record.status = "archived"
    store.save_application(record)
    return record


@app.get("/applications/{application_id}/archived/{filename}")
def fetch_archived(application_id: str, filename: str) -> Response:
    """Backend proxy for archived GCS files (v3 §5 DoD: fetchable
    indefinitely, surviving backend restarts)."""
    record = _get_record_or_404(application_id)
    if not record.gcs_path:
        raise HTTPException(404, "Application has no archive")
    allowed = {
        "resume.docx", "resume.pdf", "cover_letter.txt", "report.html",
        "jd_analysis.json", "gap_report.json", "study_guide_snapshot.json",
        "metadata.json",
    }
    if filename not in allowed:
        raise HTTPException(404, "Unknown archive file")
    content = archive.fetch_archived_file(record.gcs_path, filename)
    media = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".html": "text/html",
        ".txt": "text/plain",
        ".json": "application/json",
    }[Path(filename).suffix]
    return Response(content=content, media_type=media)


# ---------------------------------------------------------------------------
# Study Guide (v3 §6) + requirements catalog
# ---------------------------------------------------------------------------

@app.get("/catalog", response_model=list[CatalogEntry])
def get_catalog() -> list[CatalogEntry]:
    return store.list_catalog()


@app.post("/catalog/backfill")
def backfill_catalog() -> dict:
    created = catalog.backfill_from_applications()
    return {"created_entries": created}


@app.post("/catalog/{canonical_id}/dismiss-suggestion")
def dismiss_promote_suggestion(canonical_id: str) -> dict:
    """Patch §6: dismissing a wrong promote-suggestion removes it from the
    Career Growth report entirely (filtered in aggregate_market_fit before
    the Gemini synthesis call), not just hidden client-side."""
    entry = store.get_catalog_entry(canonical_id)
    if entry is None:
        raise HTTPException(404, "Not found")
    entry.promote_suggestion_dismissed = True
    store.save_catalog_entry(entry)
    return {"dismissed": canonical_id}


@app.get("/study-guide", response_model=list[StudyGuideEntry])
def list_study_guides() -> list[StudyGuideEntry]:
    return store.list_study_guides()


@app.post("/study-guide/{canonical_id}/curate", response_model=StudyGuideEntry)
def curate_study_guide(canonical_id: str) -> StudyGuideEntry:
    try:
        return studyguide.curate(canonical_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


class MarkStepRequest(BaseModel):
    step_number: int
    done: bool = True


@app.post("/study-guide/{canonical_id}/mark-step", response_model=StudyGuideEntry)
def mark_study_step(canonical_id: str, req: MarkStepRequest) -> StudyGuideEntry:
    try:
        return studyguide.mark_step_done(canonical_id, req.step_number, req.done)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


# ---------------------------------------------------------------------------
# Trend Scan — Button 3 (v3 rev2 §3a)
# ---------------------------------------------------------------------------

from . import trendscan  # noqa: E402
from .schemas import TrendGapItem, TrendScanBatch  # noqa: E402


class TrendScanRequest(BaseModel):
    postings: list[str]


@app.post("/trend-scan", response_model=TrendScanBatch)
def create_trend_scan(req: TrendScanRequest) -> TrendScanBatch:
    postings = [p for p in req.postings if p.strip()]
    if not postings:
        raise HTTPException(400, "At least one posting is required")
    return trendscan.run_scan(postings)


@app.get("/trend-scan", response_model=list[TrendScanBatch])
def list_trend_scans() -> list[TrendScanBatch]:
    return trendscan.list_batches()


@app.get("/trend-scan/{batch_id}", response_model=TrendScanBatch)
def get_trend_scan(batch_id: str) -> TrendScanBatch:
    batch = trendscan.get_batch(batch_id)
    if batch is None:
        raise HTTPException(404, "Batch not found")
    return batch


class TrendRespondRequest(BaseModel):
    status: str
    user_note: str = ""


@app.post("/trend-scan/{batch_id}/items/{item_index}/respond", response_model=TrendGapItem)
def respond_trend_item(batch_id: str, item_index: int, req: TrendRespondRequest) -> TrendGapItem:
    if req.status not in ("have_experience", "partial_experience", "no_experience"):
        raise HTTPException(400, "invalid status")
    if req.status in ("have_experience", "partial_experience") and not req.user_note.strip():
        raise HTTPException(400, "user_note is required when claiming experience")
    try:
        return trendscan.respond(batch_id, item_index, req.status, req.user_note)
    except (ValueError, IndexError) as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/trend-scan/{batch_id}/complete")
def complete_trend_scan(batch_id: str) -> dict:
    try:
        return trendscan.complete(batch_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


# ---------------------------------------------------------------------------
# Settings (v3 §7) + Career Growth (v3 §8)
# ---------------------------------------------------------------------------

@app.get("/settings", response_model=UserSettings)
def get_settings() -> UserSettings:
    return store.get_settings()


@app.post("/settings", response_model=UserSettings)
def save_settings(settings: UserSettings) -> UserSettings:
    store.save_settings(settings)
    return settings


@app.get("/analysis/market-fit", response_model=MarketFitReport)
def market_fit(since: str = "", refresh: bool = False) -> MarketFitReport:
    if not refresh:
        cached = store.latest_market_report()
        if cached is not None:
            return cached
    return archive.build_market_fit_report(since)


class AtsReportResponse(BaseModel):
    covered: list[str]
    missing: list[str]
    coverage_ratio: float


@app.get("/applications/{application_id}/ats-report", response_model=AtsReportResponse)
def ats_report(application_id: str) -> AtsReportResponse:
    record = _get_record_or_404(application_id)
    _require_approved(record)
    docx_bytes = render_docx(store.get_base_resume(), record.tailoring_plan)
    rendered_text = extract_text("resume.docx", docx_bytes).lower()

    covered, missing = [], []
    for keyword in record.jd_analysis.ats_keywords:
        (covered if keyword.lower() in rendered_text else missing).append(keyword)
    total = len(record.jd_analysis.ats_keywords)
    return AtsReportResponse(
        covered=covered, missing=missing, coverage_ratio=len(covered) / total if total else 0.0
    )


# ---------------------------------------------------------------------------
# Frontend — the Vite build is baked into the image at /app/static so a single
# Cloud Run URL serves both UI and API. Mounted last so API routes win.
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if _STATIC_DIR.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="frontend")
