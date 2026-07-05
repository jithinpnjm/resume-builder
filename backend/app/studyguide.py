"""Study Guide v2 (v3 §6): sequenced curriculum per catalog entry.

Curation pipeline: Medium RSS candidates + search-grounded research (live
URLs, not training-data recall) → JSON structuring → deterministic URL
validation that DROPS dead links → stored in Firestore keyed by canonical_id.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import gemini_calls, sources, store
from .gaps import skills_master
from .schemas import CatalogEntry, StudyGuideEntry


def _dominant_role_category(entry: CatalogEntry) -> str | None:
    """Most recent target-domain role_category among this entry's demand
    sources — used to ground the study curator in the right staff persona."""
    from .role_fit import TARGET_ROLE_CATEGORIES

    for source in reversed(entry.demand_sources):
        if source.role_category in TARGET_ROLE_CATEGORIES:
            return source.role_category
    return None


def _why_it_matters(entry: CatalogEntry) -> str:
    recent = entry.demand_sources[-1] if entry.demand_sources else None
    tail = (
        f", most recently {recent.company} ({recent.role}) on {recent.date[:10]}"
        if recent and recent.company
        else ""
    )
    return f"required in {entry.demand_count} of your target-role postings{tail}"


def curate(canonical_id: str) -> StudyGuideEntry:
    entry = store.get_catalog_entry(canonical_id)
    if entry is None:
        raise ValueError(f"No catalog entry for {canonical_id}")

    resume = store.get_base_resume()
    settings = store.get_settings()
    prefs = sources.source_preferences(settings)

    # Medium RSS candidates flavor the research; the curator may use or
    # ignore them, and everything is link-checked afterward regardless.
    medium_candidates = sources.medium_tag_feed(entry.canonical_name)
    if medium_candidates:
        prefs += " Candidate Medium articles (verify relevance before using): " + "; ".join(
            f"{c['title']} <{c['url']}>" for c in medium_candidates
        )

    research = gemini_calls.curate_study_guide_research(
        entry.canonical_name,
        _why_it_matters(entry),
        skills_master(resume),
        prefs,
        oreilly_access=settings.oreilly_access,
        role_category=_dominant_role_category(entry),
    )
    structured = gemini_calls.structure_study_guide(research, canonical_id)
    guide = StudyGuideEntry.model_validate(structured)
    guide.priority_score = entry.priority_score
    guide.why_it_matters = guide.why_it_matters or _why_it_matters(entry)
    guide.last_curated_at = datetime.now(timezone.utc).isoformat()

    guide = sources.validate_urls_in_guide(guide)
    store.save_study_guide(guide)
    return guide


def mark_step_done(canonical_id: str, step_number: int, done: bool = True) -> StudyGuideEntry:
    """Flip a step; when ALL steps are done, move the catalog entry from
    no_experience to partial_experience (feeding the promotion flow)."""
    guide = store.get_study_guide(canonical_id)
    if guide is None:
        raise ValueError(f"No study guide for {canonical_id}")
    for step in guide.steps:
        if step.step_number == step_number:
            step.done = done
    store.save_study_guide(guide)

    if guide.steps and all(s.done for s in guide.steps):
        entry = store.get_catalog_entry(canonical_id)
        if entry and entry.user_status == "no_experience":
            entry.user_status = "partial_experience"
            from .catalog import priority_score

            entry.priority_score = priority_score(entry, 0)
            store.save_catalog_entry(entry)
    return guide
