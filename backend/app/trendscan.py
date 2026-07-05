"""Trend Scan — Button 3 (v3 rev2 §3a). Bulk JD intake, no tailoring.

JD text in → catalog signal + study material out. Deliberately shorter than
the Build Resume pipeline: no ApplicationRecord, no TailoringPlan, no cover
letter, no rendering, no company GCS folder. All writes tagged
source_type="trend_scan"; the Job Market Analysis dashboard never sees them.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from . import catalog, gemini_calls, role_fit, store
from .gaps import (
    compute_skill_match_pct,
    detect_gaps,
    skills_master,
    suppress_false_positive_gaps,
)
from .schemas import TrendGapItem, TrendScanBatch

BQ_DATASET = os.environ.get("BQ_DATASET", "resume_agent_analytics")

# priority_score movement that triggers a study-guide re-curation
_SCORE_DELTA_THRESHOLD = 0.1


def _batches_collection() -> str:
    return "resume_agent_trend_scans"


def save_batch(batch: TrendScanBatch) -> None:
    store._doc_set(_batches_collection(), batch.id, batch.model_dump())


def get_batch(batch_id: str) -> TrendScanBatch | None:
    data = store._doc_get(_batches_collection(), batch_id)
    return TrendScanBatch.model_validate(data) if data else None


def list_batches() -> list[TrendScanBatch]:
    batches = [
        TrendScanBatch.model_validate(d) for d in store._doc_list(_batches_collection())
    ]
    return sorted(batches, key=lambda b: b.created_at, reverse=True)


def run_scan(postings: list[str]) -> TrendScanBatch:
    """Analyze every posting, canonicalize every requirement, and produce ONE
    consolidated batch review (deduplicated across postings)."""
    resume = store.get_base_resume()
    master = skills_master(resume)

    review_by_canonical: dict[str, TrendGapItem] = {}
    auto_counted: list[str] = []
    role_titles: list[str] = []
    skipped_postings: list[dict] = []
    score_before: dict[str, float] = {e.canonical_id: e.priority_score for e in store.list_catalog()}

    for jd_text in postings:
        if not jd_text.strip():
            continue
        jd = gemini_calls.analyze_jd(jd_text)

        # Role-fit gate (patch §1), per posting — not per batch. One posting
        # in a batch of five might be a fit and the rest not; a "skip" here
        # excludes ONLY this posting (no gap detection, no catalog writes),
        # the rest of the batch still runs.
        skill_match_pct = compute_skill_match_pct(resume, jd)
        fit = role_fit.assess(jd, skill_match_pct)
        if fit.decision == "skip":
            skipped_postings.append(
                {"role_title": jd.role_title or "?", "reason": fit.decision_reason}
            )
            continue
        # "warn" postings still proceed — role_titles only tracks processed
        # postings so the batch header reflects what was actually reviewed.
        role_titles.append(jd.role_title or "?")

        # Gap detection against the resume decides what's worth reviewing;
        # requirements the resume already covers still count as demand signal.
        gaps = detect_gaps(resume, jd, jd_text)
        # Patch §4b: semantic double-check — can only remove false-positive
        # gaps already substantively covered under a different name/tool.
        gaps = suppress_false_positive_gaps(gaps, resume)
        gapped = {g.requirement for g in gaps}

        # ONE canonicalization call for this whole posting's requirements,
        # not one per requirement — this is what keeps multi-JD scans fast
        # as the catalog grows across postings.
        resolved = catalog.resolve_batch([r.requirement for r in jd.must_have_requirements])

        for req in jd.must_have_requirements:
            entry = resolved.get(req.requirement)
            if entry is None:
                entry = catalog.create_entry(
                    req.requirement, req.category, "", jd.role_title,
                    source_type="trend_scan", role_category=jd.role_category,
                )
            else:
                catalog.register_demand(
                    entry, "", jd.role_title,
                    source_type="trend_scan", role_category=jd.role_category,
                )

            if req.requirement not in gapped:
                continue  # resume covers it — demand counted, nothing to review
            if entry.user_status in ("have_experience", "partial_experience"):
                # Already confirmed via a real application or prior scan —
                # silently counted, never re-prompted (Trend Scan DoD #2).
                if entry.canonical_name not in auto_counted:
                    auto_counted.append(entry.canonical_name)
                continue

            if entry.canonical_id in review_by_canonical:
                item = review_by_canonical[entry.canonical_id]
                if jd.role_title not in item.source_postings:
                    item.source_postings.append(jd.role_title)
                continue

            gap_src = next(g for g in gaps if g.requirement == req.requirement)
            item = TrendGapItem(
                requirement=entry.canonical_name or req.requirement,
                jd_context=gap_src.jd_context,
                canonical_id=entry.canonical_id,
                source_postings=[jd.role_title],
            )
            prior = _prior_education(entry.canonical_id)
            item.education = prior or gemini_calls.educate_gap(
                req.requirement, item.jd_context, master,
                role_category=jd.role_category,
            )
            review_by_canonical[entry.canonical_id] = item

    batch = TrendScanBatch(
        id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
        posting_count=len([p for p in postings if p.strip()]),
        role_titles=role_titles,
        review_items=list(review_by_canonical.values()),
        auto_counted=auto_counted,
        skipped_postings=skipped_postings,
    )
    save_batch(batch)
    _write_trend_events(batch, score_before)  # demand events exist even before review
    return batch


def _prior_education(canonical_id: str):
    for app in store.list_applications():
        for gap in app.gaps:
            if gap.canonical_id == canonical_id and gap.education.what_it_is:
                return gap.education
    for b in list_batches():
        for item in b.review_items:
            if item.canonical_id == canonical_id and item.education.what_it_is:
                return item.education
    return None


def respond(batch_id: str, item_index: int, status: str, user_note: str) -> TrendGapItem:
    """A trend-scan answer updates the CATALOG (pre-answering future Button 1
    detections) — it never writes to ResumeJSON or any finalized resume."""
    batch = get_batch(batch_id)
    if batch is None:
        raise ValueError("Batch not found")
    item = batch.review_items[item_index]
    item.user_response.status = status
    item.user_response.user_note = user_note.strip()
    item.user_response.reviewed_at = datetime.now(timezone.utc).isoformat()
    save_batch(batch)

    entry = store.get_catalog_entry(item.canonical_id)
    if entry:
        from .schemas import StatusHistoryEntry

        entry.user_status = status
        entry.status_history.append(
            StatusHistoryEntry(
                date=item.user_response.reviewed_at,
                status=status,
                source_application_id=f"trend_scan:{batch_id}",
                note=item.user_response.user_note,
            )
        )
        entry.priority_score = catalog.priority_score(entry, 0)
        store.save_catalog_entry(entry)
    return item


def complete(batch_id: str) -> dict:
    """Close the batch: recompute scores and flag entries whose study guide
    is missing or stale (priority_score has moved enough to warrant a
    refresh). Deliberately does NOT call Gemini here — study-guide curation
    is a real cost (search-grounded research + structuring, ~2 calls per
    entry) and completing a scan can touch many entries at once. Flagging
    lets the Study Room surface exactly which entries need attention while
    leaving the actual (paid) curation call to an explicit user click, same
    as any other Build-curriculum action."""
    batch = get_batch(batch_id)
    if batch is None:
        raise ValueError("Batch not found")

    catalog.refresh_scores()

    stale: list[str] = []
    touched_ids = {i.canonical_id for i in batch.review_items} | {
        e.canonical_id
        for e in store.list_catalog()
        if e.canonical_name in batch.auto_counted
    }
    for cid in touched_ids:
        entry = store.get_catalog_entry(cid)
        if entry is None or entry.user_status not in ("no_experience", "partial_experience"):
            continue
        guide = store.get_study_guide(cid)
        needs = guide is None or abs(entry.priority_score - guide.priority_score) >= _SCORE_DELTA_THRESHOLD
        if needs:
            stale.append(cid)

    batch.status = "completed"
    batch.completed_at = datetime.now(timezone.utc).isoformat()
    save_batch(batch)
    return {"batch_id": batch_id, "study_guides_stale": stale}


def _write_trend_events(batch: TrendScanBatch, score_before: dict[str, float]) -> None:
    """BigQuery rows tagged source_type='trend_scan'. Best-effort: BQ absence
    (infra not applied yet) must not break the scan itself."""
    try:
        from google.cloud import bigquery

        client = bigquery.Client()
        now = batch.created_at
        rows = []
        for item in batch.review_items:
            rows.append(
                {
                    "application_id": f"trend_scan:{batch.id}",
                    "company": "",
                    "role_title": ";".join(item.source_postings)[:200],
                    "requirement": item.requirement,
                    "canonical_id": item.canonical_id,
                    "category": "",
                    "must_have": True,
                    "user_status": item.user_response.status,
                    "matched": False,
                    "source_type": "trend_scan",
                    "event_date": now,
                }
            )
        for name in batch.auto_counted:
            rows.append(
                {
                    "application_id": f"trend_scan:{batch.id}",
                    "company": "",
                    "role_title": "",
                    "requirement": name,
                    "canonical_id": "",
                    "category": "",
                    "must_have": True,
                    "user_status": "confirmed_previously",
                    "matched": True,
                    "source_type": "trend_scan",
                    "event_date": now,
                }
            )
        if rows:
            client.insert_rows_json(f"{BQ_DATASET}.requirement_events", rows)
    except Exception:
        pass
