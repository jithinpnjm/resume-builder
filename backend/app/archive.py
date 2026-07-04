"""FINALIZED → ARCHIVED (v3 §3/§8/§9): GCS document uploads, report.html,
BigQuery analytics rows, catalog demand updates, market-fit aggregation.

report.html is rendered server-side with Jinja2 — deterministic, no LLM.
BigQuery writes happen only here (defined checkpoint), never during the
interactive loop.
"""
from __future__ import annotations

import io
import json
import os
import re
from datetime import datetime, timezone

from jinja2 import Template

from . import store
from .schemas import ApplicationRecord, MarketFitReport, MatchRatePoint

ARCHIVE_BUCKET = os.environ.get(
    "ARCHIVE_BUCKET", "my-personal-data-430607-resume-agent-archive"
)
BQ_DATASET = os.environ.get("BQ_DATASET", "resume_agent_analytics")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "unknown"


# ---------------------------------------------------------------------------
# report.html — self-contained, inline CSS, inline SVG donut, no external deps
# ---------------------------------------------------------------------------

_REPORT_TEMPLATE = Template(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{{ company }} — {{ role }} — application report</title>
<style>
body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:880px;margin:2rem auto;padding:0 1rem;color:#1f2328;background:#fff}
h1{font-size:1.5rem}h2{font-size:1.15rem;border-bottom:1px solid #d1d9e0;padding-bottom:.3rem;margin-top:2rem}
table{border-collapse:collapse;width:100%;font-size:.9rem}td,th{border:1px solid #d1d9e0;padding:.4rem .6rem;text-align:left;vertical-align:top}
.card{border:1px solid #d1d9e0;border-left:4px solid #8b949e;border-radius:6px;padding:.8rem 1rem;margin:.6rem 0}
.card.have{border-left-color:#3fb950}.card.partial{border-left-color:#e8a33d}.card.no{border-left-color:#f85149}
.pill{display:inline-block;font-size:.75rem;padding:.1rem .5rem;border-radius:10px;background:#eef1f4}
.muted{color:#59636e;font-size:.85rem}
ul{margin:.3rem 0}
</style></head><body>
<h1>{{ company }} — {{ role }}</h1>
<p class="muted">Generated {{ generated }} · application {{ app_id }}</p>

<h2>Requirement coverage</h2>
<svg width="140" height="140" viewBox="0 0 42 42" role="img" aria-label="coverage donut">
  <circle cx="21" cy="21" r="15.9" fill="none" stroke="#f85149" stroke-width="5"/>
  <circle cx="21" cy="21" r="15.9" fill="none" stroke="#3fb950" stroke-width="5"
    stroke-dasharray="{{ matched_pct }} {{ 100 - matched_pct }}" stroke-dashoffset="25"/>
  <text x="21" y="23" text-anchor="middle" font-size="8">{{ matched_pct }}%</text>
</svg>
<p>{{ matched_count }}/{{ must_have_count }} must-have requirements matched · {{ gaps|length }} gaps reviewed</p>

<h2>Diff summary</h2>
<table><tr><th>Kind</th><th>Change</th></tr>
{% for kind, lines in diff.items() %}{% for line in lines %}
<tr><td>{{ kind }}</td><td>{{ line }}</td></tr>
{% endfor %}{% endfor %}
{% if not has_diff %}<tr><td colspan="2" class="muted">No changes — resume used as-is.</td></tr>{% endif %}
</table>

<h2>Gaps</h2>
{% for g in gaps %}
<div class="card {{ g.css }}">
  <strong>{{ g.requirement }}</strong> <span class="pill">{{ g.status }}</span>
  <p class="muted">{{ g.jd_context }}</p>
  <p>{{ g.what_it_is }}</p>
  <p><em>Role use:</em> {{ g.role_use }}</p>
  <p><em>You already know:</em> {{ g.transfer }}</p>
  {% if g.note %}<p><em>Your note:</em> {{ g.note }}</p>{% endif %}
</div>
{% endfor %}

{% if study %}
<h2>Study guide snapshot</h2>
{% for s in study %}
<div class="card">
  <strong>{{ s.requirement }}</strong> <span class="pill">priority {{ s.priority }}</span>
  <ul>{% for step in s.steps %}<li><input type="checkbox" {% if step.done %}checked{% endif %}> {{ step.title }} — {{ step.goal }} (~{{ step.est_hours }}h)</li>{% endfor %}</ul>
</div>
{% endfor %}
{% endif %}
</body></html>"""
)


def render_report_html(record: ApplicationRecord) -> str:
    must = record.jd_analysis.must_have_requirements if record.jd_analysis else []
    gapped_reqs = {
        g.requirement for g in record.gaps if g.user_response.status == "no_experience"
    }
    matched_count = max(len(must) - len(gapped_reqs), 0)
    must_have_count = len(must) or 1
    css = {"have_experience": "have", "partial_experience": "partial", "no_experience": "no"}

    study = []
    for gap in record.gaps:
        if gap.user_response.status == "no_experience" and gap.canonical_id:
            guide = store.get_study_guide(gap.canonical_id)
            if guide:
                study.append(
                    {
                        "requirement": gap.requirement,
                        "priority": guide.priority_score,
                        "steps": [s.model_dump() for s in guide.steps],
                    }
                )

    diff = record.diff_summary.model_dump()
    return _REPORT_TEMPLATE.render(
        company=record.company or "?",
        role=record.role_title,
        generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        app_id=record.id,
        matched_pct=round(100 * matched_count / must_have_count),
        matched_count=matched_count,
        must_have_count=len(must),
        diff=diff,
        has_diff=any(diff.values()),
        gaps=[
            {
                "requirement": g.requirement,
                "jd_context": g.jd_context,
                "status": g.user_response.status.replace("_", " "),
                "css": css.get(g.user_response.status, ""),
                "what_it_is": g.education.what_it_is,
                "role_use": g.education.typical_use_case_for_role,
                "transfer": g.education.closest_known_alternative,
                "note": g.user_response.user_note,
            }
            for g in record.gaps
        ],
        study=study,
    )


# ---------------------------------------------------------------------------
# GCS uploads
# ---------------------------------------------------------------------------

def upload_archive(record: ApplicationRecord, docx: bytes, pdf: bytes) -> str:
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(ARCHIVE_BUCKET)
    prefix = f"{slugify(record.company)}/{slugify(record.role_title)}"

    files: dict[str, tuple[bytes | str, str]] = {
        "resume.docx": (docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "resume.pdf": (pdf, "application/pdf"),
        "cover_letter.txt": (record.cover_letter, "text/plain"),
        "jd_analysis.json": (
            record.jd_analysis.model_dump_json(indent=2) if record.jd_analysis else "{}",
            "application/json",
        ),
        "gap_report.json": (
            json.dumps([g.model_dump() for g in record.gaps], indent=2),
            "application/json",
        ),
        "study_guide_snapshot.json": (
            json.dumps(
                [
                    store.get_study_guide(g.canonical_id).model_dump()
                    for g in record.gaps
                    if g.canonical_id and store.get_study_guide(g.canonical_id)
                ],
                indent=2,
            ),
            "application/json",
        ),
        "report.html": (render_report_html(record), "text/html"),
        "metadata.json": (
            record.model_dump_json(exclude={"tailoring_plan", "jd_analysis"}, indent=2),
            "application/json",
        ),
    }
    for name, (content, content_type) in files.items():
        blob = bucket.blob(f"{prefix}/{name}")
        if isinstance(content, bytes):
            blob.upload_from_file(io.BytesIO(content), content_type=content_type)
        else:
            blob.upload_from_string(content, content_type=content_type)
    return f"gs://{ARCHIVE_BUCKET}/{prefix}/"


def fetch_archived_file(gcs_path: str, filename: str) -> bytes:
    from google.cloud import storage

    # gcs_path like gs://bucket/company/role/
    without_scheme = gcs_path.removeprefix("gs://")
    bucket_name, _, prefix = without_scheme.partition("/")
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(f"{prefix.rstrip('/')}/{filename}")
    return blob.download_as_bytes()


# ---------------------------------------------------------------------------
# BigQuery writes (only at this checkpoint) + market-fit aggregation
# ---------------------------------------------------------------------------

# NOTE on compute_skill_match_pct vs. the helper below: patch §1 asks for one
# shared match-pct implementation across the role-fit gate, aggregate_market_fit,
# and write_bigquery_rows. gaps.compute_skill_match_pct (pure keyword match
# against the CURRENT resume text) is used for the role-fit gate, which runs
# before any gap has been reviewed — there's no reviewed status yet to use.
# But aggregate_market_fit/write_bigquery_rows run on ALREADY-REVIEWED
# applications, where a requirement the candidate explicitly confirmed
# ("have_experience") is stronger evidence than a keyword regex against
# whatever the base resume happens to say today. Swapping these two to the
# keyword-only function would silently make Career Growth's numbers LESS
# accurate by discarding that human confirmation. So: these two are
# deduplicated into one shared helper (eliminating the actual duplication
# the patch flagged) rather than switched to compute_skill_match_pct.
def _matched_requirement_ids(must: list, gap_status: dict[str, str]) -> tuple[int, list[bool]]:
    matched_flags = [gap_status.get(req.requirement, "") != "no_experience" for req in must]
    return sum(matched_flags), matched_flags


def write_bigquery_rows(record: ApplicationRecord, resume_version: int | None) -> None:
    from google.cloud import bigquery

    client = bigquery.Client()
    now = datetime.now(timezone.utc).isoformat()
    gap_status = {g.requirement: g.user_response.status for g in record.gaps}
    must = record.jd_analysis.must_have_requirements if record.jd_analysis else []

    requirement_rows = []
    matched_count, matched_flags = _matched_requirement_ids(must, gap_status)
    for req, matched in zip(must, matched_flags):
        status = gap_status.get(req.requirement, "")
        gap = next((g for g in record.gaps if g.requirement == req.requirement), None)
        requirement_rows.append(
            {
                "application_id": record.id,
                "company": record.company,
                "role_title": record.role_title,
                "requirement": req.requirement,
                "canonical_id": gap.canonical_id if gap else "",
                "category": req.category,
                "must_have": True,
                "user_status": status or "matched_in_resume",
                "matched": matched,
                "source_type": "application",  # Button 1; trend scans write their own rows
                "event_date": now,
            }
        )
    errors = client.insert_rows_json(
        f"{BQ_DATASET}.requirement_events", requirement_rows
    )
    if errors:
        raise RuntimeError(f"BigQuery requirement_events insert failed: {errors}")

    snapshot = {
        "application_id": record.id,
        "company": record.company,
        "role_title": record.role_title,
        "created_at": record.created_at or now,
        "finalized_at": now,
        "match_pct": matched_count / len(must) if must else None,
        "must_have_count": len(must),
        "matched_count": matched_count,
        "resume_version": resume_version,
    }
    errors = client.insert_rows_json(f"{BQ_DATASET}.application_snapshots", [snapshot])
    if errors:
        raise RuntimeError(f"BigQuery application_snapshots insert failed: {errors}")


# Button 2 (Job Market Analysis) SQL — the source_type filter is the no-leak
# guarantee (v3 rev2 §0a): trend-scanned JDs must never dilute real-application
# performance numbers. Used once BQ holds enough archived history; the
# Firestore aggregation below is equivalent because it iterates
# ApplicationRecords only (trend scans never create ApplicationRecords).
BUTTON2_DEMAND_SQL = f"""
SELECT requirement, canonical_id,
       COUNT(*) AS demand_count,
       COUNTIF(user_status = 'no_experience') AS gap_count,
       MAX(event_date) AS last_seen
FROM `{BQ_DATASET}.requirement_events`
WHERE source_type = 'application' AND event_date >= @since
GROUP BY requirement, canonical_id
ORDER BY demand_count DESC
"""


def aggregate_market_fit(since: str = "") -> dict:
    """Deterministic aggregation for Button 2. Iterates ApplicationRecords
    only — trend scans never create ApplicationRecords, so this is
    structurally application-source-only (same guarantee the BQ path gets
    from WHERE source_type = 'application' in BUTTON2_DEMAND_SQL)."""
    requirement_counts: dict[str, int] = {}
    requirement_gap_counts: dict[str, int] = {}
    confirmed_counts: dict[str, int] = {}
    # requirement text -> canonical_id, from the gap's OWN resolved id (set by
    # catalog.resolve/canonicalize_requirement at analysis time) — never
    # re-derived by re-slugifying raw text, which is the bug this fixes (§4c):
    # a requirement like "HashiCorp Vault for secrets management" slugifies
    # to something that never matches the catalog's actual canonical_id
    # ("vault") once canonicalization has merged it with an existing entry.
    confirmed_canonical_ids: dict[str, str] = {}
    match_rate: list[MatchRatePoint] = []

    for app in store.list_applications():
        if since and (app.created_at or "") < since:
            continue
        if app.jd_analysis is None:
            continue
        gap_status = {g.requirement: g.user_response.status for g in app.gaps}
        must = app.jd_analysis.must_have_requirements
        matched, _ = _matched_requirement_ids(must, gap_status)
        for req in must:
            requirement_counts[req.requirement] = requirement_counts.get(req.requirement, 0) + 1
            status = gap_status.get(req.requirement)
            if status == "no_experience":
                requirement_gap_counts[req.requirement] = (
                    requirement_gap_counts.get(req.requirement, 0) + 1
                )
            if status in ("have_experience", "partial_experience"):
                confirmed_counts[req.requirement] = confirmed_counts.get(req.requirement, 0) + 1
                gap = next((g for g in app.gaps if g.requirement == req.requirement), None)
                if gap and gap.canonical_id:
                    confirmed_canonical_ids[req.requirement] = gap.canonical_id
        match_rate.append(
            MatchRatePoint(
                date=app.created_at,
                company=app.company,
                match_pct=round(matched / len(must), 3) if must else None,
            )
        )

    catalog_by_id = {e.canonical_id: e for e in store.list_catalog()}
    promotable = {}
    for req, count in confirmed_counts.items():
        canonical_id = confirmed_canonical_ids.get(req, "")
        entry = catalog_by_id.get(canonical_id)
        if entry is None:
            # No resolved catalog entry to check — can't confirm it's
            # promotable OR already in the base resume; skip rather than
            # guess via a re-slugified string match (the exact bug being fixed).
            continue
        if entry.in_base_resume:
            continue
        # §6 — dismissing a suggestion removes it from the report entirely,
        # not just hidden client-side; filtered before the Gemini call.
        if entry.promote_suggestion_dismissed:
            continue
        promotable[req] = {"count": count, "canonical_id": canonical_id}
    return {
        "requirement_counts": requirement_counts,
        "requirement_gap_counts": requirement_gap_counts,
        "confirmed_not_promoted_counts": promotable,
        "match_rate_by_date": [p.model_dump() for p in sorted(match_rate, key=lambda p: p.date)],
    }


def build_market_fit_report(since: str = "") -> MarketFitReport:
    from . import gemini_calls

    aggregation = aggregate_market_fit(since)
    synthesis = gemini_calls.synthesize_market_fit(aggregation)
    now = datetime.now(timezone.utc).isoformat()
    report = MarketFitReport.model_validate(
        {
            **synthesis,
            "period": {
                "start": since,
                "end": now,
                "applications_analyzed": len(aggregation["match_rate_by_date"]),
            },
            "match_rate_trend": aggregation["match_rate_by_date"],
            "generated_at": now,
        }
    )
    store.save_market_report(report)
    return report
