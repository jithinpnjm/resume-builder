"""requirements_catalog — cross-application memory (v3 §2/§5).

Gap detection consults this BEFORE creating GapItems: a requirement you've
already confirmed (or already been educated on) is never re-asked from
scratch. Every application updates demand_count/sources, which drives
priority_score — the single ranking shared by the Study Guide and the
Career Growth report.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from . import gemini_calls, store
from .schemas import CatalogEntry, DemandSource, GapItem, StatusHistoryEntry


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def priority_score(entry: CatalogEntry, days_since_last_seen: int) -> float:
    demand_weight = min(entry.demand_count / 10, 1.0)
    recency_weight = (
        1.0 if days_since_last_seen < 30 else 0.6 if days_since_last_seen < 90 else 0.3
    )
    gap_weight = (
        1.0
        if entry.user_status == "no_experience"
        else 0.3
        if entry.user_status == "partial_experience"
        else 0.0
    )
    return round(demand_weight * recency_weight * gap_weight, 3)


def _days_since(iso_date: str) -> int:
    if not iso_date:
        return 9999
    try:
        seen = datetime.fromisoformat(iso_date)
        return max((datetime.now(timezone.utc) - seen).days, 0)
    except ValueError:
        return 9999


def resolve(requirement: str) -> CatalogEntry | None:
    """Resolve a requirement string against the catalog: exact/alias match
    first (free), Gemini canonicalization (Call 2b) only when the cheap path
    misses and the catalog is non-empty."""
    entries = store.list_catalog()
    if not entries:
        return None

    req_slug = _slug(requirement)
    for entry in entries:
        names = [entry.canonical_name, entry.canonical_id, *entry.aliases]
        if any(_slug(n) == req_slug for n in names if n):
            return entry
        # a short canonical name appearing inside a longer requirement
        # sentence ("...technologies such as Kafka") is still a match
        if entry.canonical_name and re.search(
            rf"(?<![a-z0-9]){re.escape(entry.canonical_name.lower())}(?![a-z0-9])",
            requirement.lower(),
        ):
            return entry

    flat = [
        {"canonical_id": e.canonical_id, "name": e.canonical_name, "aliases": e.aliases}
        for e in entries
    ]
    result = gemini_calls.canonicalize_requirement(requirement, flat)
    matched_id = result.get("matched_canonical_id")
    if matched_id and result.get("confidence") == "high":
        return store.get_catalog_entry(matched_id)
    return None


def _local_match(requirement: str, entries: list[CatalogEntry]) -> CatalogEntry | None:
    """The cheap, free path from resolve() — exact/alias/substring match,
    no Gemini call."""
    req_slug = _slug(requirement)
    for entry in entries:
        names = [entry.canonical_name, entry.canonical_id, *entry.aliases]
        if any(_slug(n) == req_slug for n in names if n):
            return entry
        if entry.canonical_name and re.search(
            rf"(?<![a-z0-9]){re.escape(entry.canonical_name.lower())}(?![a-z0-9])",
            requirement.lower(),
        ):
            return entry
    return None


def resolve_batch(requirements: list[str]) -> dict[str, CatalogEntry | None]:
    """Resolve many requirements with AT MOST ONE Gemini call total (not one
    per requirement) — this is what keeps Trend Scan's multi-JD batches fast.
    Requirements that miss the free local match are canonicalized together
    in a single batched call against the catalog."""
    entries = store.list_catalog()
    results: dict[str, CatalogEntry | None] = {}
    unresolved: list[str] = []

    for req in requirements:
        local = _local_match(req, entries) if entries else None
        if local is not None:
            results[req] = local
        else:
            unresolved.append(req)

    if unresolved and entries:
        flat = [
            {"canonical_id": e.canonical_id, "name": e.canonical_name, "aliases": e.aliases}
            for e in entries
        ]
        matches = gemini_calls.canonicalize_requirements_batch(unresolved, flat)
        for req in unresolved:
            match = matches.get(req, {})
            matched_id = match.get("matched_canonical_id")
            if matched_id and match.get("confidence") == "high":
                results[req] = store.get_catalog_entry(matched_id)
            else:
                results[req] = None
    else:
        for req in unresolved:
            results[req] = None

    return results


def register_demand(
    entry: CatalogEntry, company: str, role: str, source_type: str = "application"
) -> CatalogEntry:
    now = datetime.now(timezone.utc).isoformat()
    entry.demand_count += 1
    entry.demand_sources.append(
        DemandSource(company=company, role=role, date=now, source_type=source_type)
    )
    entry.last_seen = now
    entry.priority_score = priority_score(entry, 0)
    store.save_catalog_entry(entry)
    return entry


def create_entry(
    requirement: str,
    category: str,
    company: str,
    role: str,
    source_type: str = "application",
) -> CatalogEntry:
    now = datetime.now(timezone.utc).isoformat()
    entry = CatalogEntry(
        canonical_id=_slug(requirement)[:60] or "unknown",
        canonical_name=requirement,
        category=category,
        demand_count=1,
        demand_sources=[
            DemandSource(company=company, role=role, date=now, source_type=source_type)
        ],
        last_seen=now,
    )
    entry.priority_score = priority_score(entry, 0)
    store.save_catalog_entry(entry)
    return entry


def record_user_response(gap: GapItem, application_id: str) -> None:
    """Carry a gap answer into the catalog (user's words verbatim)."""
    if not gap.canonical_id:
        return
    entry = store.get_catalog_entry(gap.canonical_id)
    if entry is None:
        return
    entry.user_status = gap.user_response.status
    entry.status_history.append(
        StatusHistoryEntry(
            date=gap.user_response.reviewed_at,
            status=gap.user_response.status,
            source_application_id=application_id,
            note=gap.user_response.user_note,
        )
    )
    entry.priority_score = priority_score(entry, _days_since(entry.last_seen))
    store.save_catalog_entry(entry)


def refresh_scores() -> None:
    for entry in store.list_catalog():
        entry.priority_score = priority_score(entry, _days_since(entry.last_seen))
        store.save_catalog_entry(entry)


def backfill_from_applications() -> int:
    """Retrofit: seed the catalog from every existing application so history
    isn't lost the first time the catalog runs."""
    count = 0
    for app in store.list_applications():
        for gap in app.gaps:
            existing = resolve(gap.requirement)
            if existing is None:
                entry = create_entry(gap.requirement, "", app.company, app.role_title)
                count += 1
            else:
                entry = register_demand(existing, app.company, app.role_title)
            gap.canonical_id = entry.canonical_id
            if gap.user_response.status != "not_reviewed":
                record_user_response(gap, app.id)
        store.save_application(app)
    return count
