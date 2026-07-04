"""Gap detection: JD requirements with no ResumeJSON match.

Deterministic keyword matching — not a Gemini call. A requirement is a gap
when none of its keyword variants appear anywhere in the resume's text
(skills, bullets, summary, certifications). Cheap and predictable; the
expensive/subjective part (education content) happens per-gap in Gemini
Call 3 afterward.
"""
from __future__ import annotations

import re

from .schemas import GapItem, JDAnalysis, ResumeJSON


def _resume_full_text(resume: ResumeJSON) -> str:
    parts: list[str] = [resume.summary]
    for cat in resume.skills.categories:
        parts.append(cat.name)
        parts.extend(cat.items)
    for b in resume.accomplishments:
        parts.append(b.text)
    for exp in resume.experience:
        parts.append(f"{exp.company} {exp.title}")
        for b in exp.bullets:
            parts.append(b.text)
    for proj in resume.projects:
        parts.append(proj.name)
        for b in proj.bullets:
            parts.append(b.text)
    parts.extend(resume.certifications)
    return "\n".join(parts).lower()


def _word_present(word: str, text: str) -> bool:
    # Always match on word boundaries — a pure substring check lets "Vault"
    # match inside "Commvault", "Go" inside "Google", etc. This applies
    # regardless of word length; there's no length where substring matching
    # is actually safe.
    return re.search(rf"(?<![a-z0-9]){re.escape(word.lower())}(?![a-z0-9])", text) is not None


# Generic single words that, alone, are too weak to prove a requirement is
# covered — "Datadog monitoring" having only "monitoring" as a keyword_variant
# must not be satisfied by the resume's unrelated "implemented monitoring
# using CloudWatch" bullet. Multi-word variants and the full requirement
# string are unaffected; this only suppresses single generic-word matches.
_WEAK_MATCH_WORDS = {
    "monitoring", "management", "reporting", "operations", "administration",
    "development", "deployment", "automation", "governance", "optimization",
    "provisioning", "orchestration", "integration", "configuration",
}


def _term_present(term: str, text: str) -> bool:
    term = term.strip()
    if not term:
        return False
    if term.lower() in _WEAK_MATCH_WORDS:
        return False
    words = [w for w in re.split(r"[\s\-/]+", term) if len(w) > 2]
    if not words:
        return _word_present(term, text)
    # Multi-word phrases match word-by-word, not as a literal substring —
    # "cloud platform" should match a resume that says "Cloud, Platform,
    # DevOps, and SRE Engineer", while "federated monitoring" still fails
    # (no "federated" anywhere) and stays a gap.
    return all(_word_present(w, text) for w in words)


def skills_master(resume: ResumeJSON) -> list[str]:
    return [item for cat in resume.skills.categories for item in cat.items]


def _find_jd_line(variants: list[str], job_description: str) -> str:
    for line in job_description.splitlines():
        lower = line.lower()
        if any(v.strip().lower() in lower for v in variants if v.strip()):
            return line.strip()
    return ""


# Generic delivery-model / process / filler words. A requirement variant made
# up entirely of these is company context, not a learnable tool gap for a
# senior in this role family.
_GENERIC_WORDS = {
    "agile", "scrum", "kanban", "saas", "microservices", "devops", "sre",
    "cloud", "platform", "infrastructure", "solution", "solutions", "based",
    "engineering", "team", "releases", "systems", "large", "scale",
}


def _is_nameable_tech(req) -> bool:
    """A gap must be a nameable technology/methodology, not a responsibility
    sentence. Responsibility statements ("Assist an agile engineering team",
    "Build critical infrastructure used by millions") have no short variant —
    every phrasing is a long clause. Real tech requirements always have at
    least one variant of ~3 words or fewer (Kafka, MongoDB, "shell scripting",
    IoT, "federated monitoring")."""
    if req.category in ("soft-skill",):
        return False

    def is_generic(variant: str) -> bool:
        words = re.split(r"[\s\-/]+", variant.lower())
        return all(w in _GENERIC_WORDS for w in words if w)

    variants = [v.strip() for v in [req.requirement, *req.keyword_variants] if v.strip()]
    short = [v for v in variants if len(v.split()) <= 3]
    return any(not is_generic(v) for v in short)


def detect_gaps(
    resume: ResumeJSON, jd_analysis: JDAnalysis, job_description: str = ""
) -> list[GapItem]:
    text = _resume_full_text(resume)
    gaps: list[GapItem] = []
    for req in jd_analysis.must_have_requirements:
        if not _is_nameable_tech(req):
            continue
        variants = [req.requirement, *req.keyword_variants]
        if not any(_term_present(v, text) for v in variants):
            jd_line = _find_jd_line(req.keyword_variants or [req.requirement], job_description)
            gaps.append(
                GapItem(requirement=req.requirement, jd_context=jd_line or req.requirement)
            )
    return gaps
