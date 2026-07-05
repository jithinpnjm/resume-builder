"""Role-Fit Gate (patch §1).

Runs right after JD analysis, before any gap detection or catalog writes,
so a JD for an unrelated or wrong-skillset role never gets fully tailored,
gap-reviewed, and fed into the Study Room.
"""
from __future__ import annotations

from .schemas import JDAnalysis, RoleFitAssessment

TARGET_ROLE_CATEGORIES = {
    "senior_sre_devops_cloud",
    "senior_mlops",
    "senior_ai_platform",
    "aiops_llmops",
    "platform_engineering",
}
# "related_adjacent" and "unrelated" are the other two values role_category
# can take — anything not in TARGET_ROLE_CATEGORIES.

ALLOWED_DEV_LANGUAGES = {"python", "go", "golang", "bash", "shell", "sql"}

# A JD demanding this many genuinely distinct, hire-worthy specializations
# simultaneously (see JDAnalysis.distinct_specialist_domains) is a signal of
# unrealistic scope/poor work-life balance, not a study opportunity — skip
# rather than gap-analyze it. Not a proxy for requirement count: a JD with
# 20 requirements in ONE coherent domain stays well under this threshold.
SUPERHUMAN_DOMAIN_THRESHOLD = 3


def assess(jd: JDAnalysis, skill_match_pct: float) -> RoleFitAssessment:
    langs = {l.lower() for l in jd.core_dev_languages_required}
    disallowed = langs - ALLOWED_DEV_LANGUAGES

    if len(jd.distinct_specialist_domains) >= SUPERHUMAN_DOMAIN_THRESHOLD:
        decision, reason = "skip", (
            f"Unrealistic scope — spans {len(jd.distinct_specialist_domains)} distinct "
            f"specialist domains as hard requirements ({', '.join(jd.distinct_specialist_domains)}). "
            "This is a signal of poor work-life balance/growth prospects, not a skill gap to study toward."
        )
    elif jd.requires_deep_dev_skills and disallowed:
        decision, reason = "skip", (
            f"Primarily requires development in {', '.join(sorted(disallowed))} — "
            "outside target skillset (Python/Go/Bash are fine)."
        )
    elif jd.role_category in TARGET_ROLE_CATEGORIES:
        decision, reason = "process", "Matches a target role category."
    elif skill_match_pct >= 0.5:
        decision, reason = "process", (
            f"Related role with {skill_match_pct:.0%} skill match — "
            "meets the 50% override threshold."
        )
    else:
        decision, reason = "warn", (
            f"Outside target role categories and only {skill_match_pct:.0%} "
            "skill match against your current resume."
        )

    return RoleFitAssessment(
        role_category=jd.role_category,
        requires_deep_dev_skills=jd.requires_deep_dev_skills,
        core_dev_languages_required=jd.core_dev_languages_required,
        skill_match_pct=skill_match_pct,
        decision=decision,
        decision_reason=reason,
    )
