"""Structured Gemini calls for the v2 three-phase pipeline.

ANALYZE -> REVIEW & CONFIRM (human-in-the-loop) -> FINALIZE

Every call returns JSON matching a fixed Pydantic schema — never prose, never
a rendered document. The LLM never gets the final word on what the candidate
knows: anything not already in ResumeJSON enters only through the
confirmed-gap insertion flow, gated on the user's own written note.
"""
from __future__ import annotations

import json

from .gemini_client import generate_json
from .schemas import (
    FabricationCheckItem,
    GapEducation,
    JDAnalysis,
    ResumeJSON,
    StudyPlan,
    TailoringPlan,
)

# ---------------------------------------------------------------------------
# Call 1 — JD Analyzer (unchanged from v1)
# ---------------------------------------------------------------------------

_JD_ANALYZER_SYSTEM_PROMPT = """You are a technical recruiter analyzing a job description. Extract ALL
requirements, both explicit and implied. Return ONLY valid JSON matching this schema:

{
  "role_title": "",
  "seniority_signal": "",
  "must_have_requirements": [
    { "requirement": "", "category": "tool|platform|methodology|domain|certification|soft-skill", "keyword_variants": ["k8s","Kubernetes"] }
  ],
  "nice_to_have_requirements": [ { "requirement": "", "category": "" } ],
  "ats_keywords": ["exact strings likely scanned by ATS - tool names, cert names, methodologies"],
  "company_context": { "industry": "", "product_signal": "" },
  "role_category": "senior_sre_devops_cloud|senior_mlops|senior_ai_platform|aiops_llmops|platform_engineering|related_adjacent|unrelated",
  "requires_deep_dev_skills": false,
  "core_dev_languages_required": [],
  "dev_skill_reasoning": ""
}

Rules:
- ats_keywords must include exact strings an ATS keyword scanner would look for
  (tool names, certifications, frameworks, methodologies) - pull literal terms
  from the JD, don't paraphrase them.
- Distinguish must-have vs nice-to-have based on language cues ("required" vs
  "bonus", "familiarity with").
- Atomize must_have_requirements: one concrete named technology/methodology per
  entry where possible ("Kafka", "MongoDB"), not whole responsibility sentences.
- keyword_variants must include common concrete equivalents a candidate's resume
  might use instead: "shell scripting" -> ["Bash", "sh", "zsh", "Shell"],
  "Google Kubernetes Engine" -> ["GKE"], "infrastructure as code" -> ["IaC",
  "Terraform", "CloudFormation"].
- Before finalizing keyword_variants, check every OTHER requirement you've
  extracted from this same JD: if a more general requirement (e.g.
  "containerization") is satisfied by a more specific one you've also listed
  (e.g. "Kubernetes", "Docker"), the general requirement's keyword_variants
  MUST include those specific technologies. Never leave an abstract skill
  category without its concrete, commonly-used implementations as variants.
- Generic delivery-model words (SaaS, agile, microservices) are company context,
  not requirements - categorize them "domain" only if truly load-bearing.

Also classify:
- role_category: one of "senior_sre_devops_cloud", "senior_mlops",
  "senior_ai_platform", "aiops_llmops", "platform_engineering",
  "related_adjacent", "unrelated". The candidate's target roles are Senior
  SRE/DevOps/Cloud Engineer, Senior MLOps, Senior AI Platform Engineer,
  AIOps/LLMOps, and Platform Engineering. "platform_engineering" is for
  roles building internal developer platforms, golden paths, and
  self-service infrastructure for general product/application teams -
  distinct from "senior_ai_platform", which is platforms built specifically
  for AI/ML teams (compute scheduling, model serving infra, feature
  stores), not general developer platforms. "related_adjacent" is for roles
  clearly in the same infrastructure/platform/ML-ops universe but not an
  exact fit (e.g. "Platform Reliability Lead", "ML Infrastructure
  Engineer"). "unrelated" is for roles with no meaningful connection (sales,
  frontend-only, pure data analyst, etc).
- requires_deep_dev_skills: true if the role's PRIMARY function is software
  development (writing application code as the main deliverable), not
  infrastructure/platform/ops work that happens to involve scripting.
- core_dev_languages_required: the actual programming languages this role
  needs as CORE skills (not incidental scripting). Python, Go, Bash, and SQL
  don't count as "deep dev skills" for this candidate even if required -
  they're already covered. Only flag languages beyond those.
- dev_skill_reasoning: one sentence justifying requires_deep_dev_skills.
"""


def analyze_jd(job_description: str) -> JDAnalysis:
    data = generate_json(_JD_ANALYZER_SYSTEM_PROMPT, job_description)
    return JDAnalysis.model_validate(data)


# ---------------------------------------------------------------------------
# Call 2 — Reorder + terminology alignment (existing skills only)
# ---------------------------------------------------------------------------

_TAILORING_SYSTEM_PROMPT = """You are tailoring a resume to a job by REORDERING content and ALIGNING
TERMINOLOGY only. You may not add or remove any content. You will receive the candidate's
ResumeJSON and a JDAnalysis. Return ONLY JSON matching:

{
  "tailored_summary": "2-3 sentences, built ONLY from facts present in ResumeJSON",
  "experience_order": ["exp_1", "exp_3", "exp_2"],
  "bullet_order": { "exp_1": ["exp_1_b3", "exp_1_b1", "exp_1_b2"] },
  "skills_displayed": ["ordered list of skill category names, most JD-relevant first"],
  "skills_deprioritized": ["skill category names to place last for THIS application"],
  "bullet_plan": [
    { "bullet_id": "", "final_text": "", "keywords_injected": ["ArgoCD"], "injection_type": "renamed_existing" }
  ]
}

Hard rules:
- bullet_plan should ONLY contain bullets you actually changed. final_text may differ
  from the original ONLY to rename a tool/term the candidate genuinely has to the JD's
  exact wording (e.g. resume says "GKE", JD says "Google Kubernetes Engine" - spell it
  out once), or to surface an existing keyword earlier in the sentence. That is
  injection_type "renamed_existing". Nothing else justifies changing a bullet.
- Every specific number in an original bullet (percentages, counts, dollar amounts)
  MUST appear verbatim in final_text. Never drop or vague-ify a metric.
- Never mention any tool, technology, or experience that is not in ResumeJSON,
  anywhere - including the summary.
- Bullets with "core": true may be ordered lower but must appear in bullet_order
  for their experience entry - never omit them.
- bullet_order must list every bullet id of each experience entry exactly once.
- experience_order must contain every experience id exactly once.
- skills_displayed + skills_deprioritized together must cover every skill category
  name exactly once. Deprioritized means shown last, not hidden from the master list.
- Plain text only - no markdown, bullet characters, or bold markers.
"""


def build_tailoring_plan(resume: ResumeJSON, jd_analysis: JDAnalysis) -> TailoringPlan:
    user_content = (
        f"ResumeJSON:\n{resume.model_dump_json()}\n\n"
        f"JDAnalysis:\n{jd_analysis.model_dump_json()}"
    )
    data = generate_json(_TAILORING_SYSTEM_PROMPT, user_content)
    return TailoringPlan.model_validate(data)


# ---------------------------------------------------------------------------
# Call 2b — Canonicalization: resolve a requirement string against the
# cross-application catalog before creating a new GapItem.
# ---------------------------------------------------------------------------

_CANONICALIZE_SYSTEM_PROMPT = """Given a new requirement string extracted from a job description,
determine if it refers to the same real-world skill/tool as any entry in the existing
catalog. Return ONLY JSON:
{ "matched_canonical_id": "the id" or null, "confidence": "high|medium|low", "reasoning": "" }
If no match, matched_canonical_id must be null.
"""


def canonicalize_requirement(requirement: str, catalog_flat: list[dict]) -> dict:
    user_content = json.dumps(
        {"new_requirement": requirement, "existing_catalog": catalog_flat}
    )
    return generate_json(_CANONICALIZE_SYSTEM_PROMPT, user_content)


_CANONICALIZE_BATCH_SYSTEM_PROMPT = """For EACH new requirement string in the list, determine if it refers to
the same real-world skill as any entry in the existing catalog. Return ONLY a JSON object
keyed by the exact original requirement string, each value matching:
{ "matched_canonical_id": "the id" or null, "confidence": "high|medium|low" }
Every requirement in the input list must appear as a key in the output.
"""


def canonicalize_requirements_batch(
    requirements: list[str], catalog_flat: list[dict]
) -> dict[str, dict]:
    """Same resolution as canonicalize_requirement but for many requirements
    in ONE call — this is what keeps multi-JD trend scans from making one
    Gemini round-trip per requirement as the catalog grows."""
    user_content = json.dumps(
        {"new_requirements": requirements, "existing_catalog": catalog_flat}
    )
    return generate_json(_CANONICALIZE_BATCH_SYSTEM_PROMPT, user_content)


# ---------------------------------------------------------------------------
# Relevance check (patch §4b) — a semantic double-check pass for candidate
# gaps that failed deterministic keyword matching. This can only ever
# SUPPRESS a wrongly-created gap (removing false noise); it never adds
# content to the resume or lets the LLM claim experience on the candidate's
# behalf. One batched call per JD, not per requirement.
# ---------------------------------------------------------------------------

_RELEVANCE_CHECK_PROMPT = """For each candidate gap below, check the candidate's
actual resume content (not just a keyword list) and decide whether it is
ALREADY substantively covered under a different name, tool, or phrasing.
Be conservative: only mark "already_covered" when the resume content clearly
demonstrates the underlying skill, not when it's merely plausible or adjacent.

Each candidate gap has a fixed "idx" integer. You MUST key your output by that
same "idx" — do not echo the requirement string back, and do not rely on
string identity, since your own output text may normalize casing/whitespace
differently than the input.

Return ONLY JSON matching: [{ "idx": 0, "already_covered": false,
  "covering_evidence": "the specific resume text that covers it, or empty" }]
Every idx in the input list must appear exactly once in the output.
"""


def check_gap_relevance(
    candidate_gaps: list[str], resume_text: str
) -> list[dict]:
    if not candidate_gaps:
        return []
    indexed = [{"idx": i, "requirement": g} for i, g in enumerate(candidate_gaps)]
    user_content = json.dumps({"candidate_gaps": indexed, "resume_text": resume_text})
    return generate_json(_RELEVANCE_CHECK_PROMPT, user_content)


# ---------------------------------------------------------------------------
# Call 3 — Gap Educator (once per gap)
# ---------------------------------------------------------------------------

_GAP_EDUCATOR_SYSTEM_PROMPT = """You are helping a Senior Cloud/DevOps/SRE/MLOps/LLMOps engineer
understand a technology gap between their resume and a job description. Explain
it the way a senior peer would, not a generic tutorial. Return ONLY JSON matching:

{
  "what_it_is": "2-3 sentence plain explanation",
  "typical_use_case_for_role": "how a Senior SRE/DevOps/Cloud/MLOps engineer specifically touches this operationally day-to-day - not what a backend developer does with it",
  "sample_scenario": "a concrete short scenario: 'if you were asked to operate {requirement} at this company, you'd likely be doing X, Y, Z'",
  "closest_known_alternative": "MUST name specific tools from the candidate's actual skills list and explain the conceptual overlap - never a generic 'similar to other databases' statement",
  "other_alternatives_in_market": ["2-4 comparable tools"]
}

Rules:
- typical_use_case_for_role must be scoped to the target role family's operational
  perspective: deployment, scaling, monitoring, backup/restore, failure modes, cost.
- closest_known_alternative MUST reference specific items from the candidate's
  skills list by name and say what transfers directly.
- Keep the whole thing readable by a senior engineer in 90 seconds.
- Plain text only in every field - no markdown, no ** bold markers.
"""


def educate_gap(
    requirement: str,
    jd_context: str,
    skills_master: list[str],
    role_family: str = "Cloud Engineer / DevOps / SRE / MLOps / AI Infrastructure / LLMOps",
) -> GapEducation:
    user_content = json.dumps(
        {
            "requirement": requirement,
            "jd_context": jd_context,
            "candidate_skills_master": skills_master,
            "target_role_family": role_family,
        }
    )
    data = generate_json(_GAP_EDUCATOR_SYSTEM_PROMPT, user_content)
    return GapEducation.model_validate(data)


# ---------------------------------------------------------------------------
# Confirmed-gap insertion — the ONLY path by which new content enters the
# resume. Requires the user's own written note; output is a proposal, never
# auto-applied.
# ---------------------------------------------------------------------------

_GAP_INSERTION_SYSTEM_PROMPT = """The candidate confirmed direct experience with a technology that was
missing from their resume. Draft ONE resume bullet in their existing resume's voice/style,
using ONLY facts from their own description below - do not add tools, scale, or outcomes
they didn't state. If their description lacks a metric, write the bullet without a number
rather than invent one. Plain text, no markdown. Return ONLY JSON matching:

{ "proposed_bullet": "" }
"""


def draft_gap_bullet(
    requirement: str, user_note: str, style_reference_bullets: list[str]
) -> str:
    user_content = json.dumps(
        {
            "requirement": requirement,
            "candidate_own_description": user_note,
            "style_reference_bullets": style_reference_bullets,
        }
    )
    data = generate_json(_GAP_INSERTION_SYSTEM_PROMPT, user_content)
    return data.get("proposed_bullet", "")


# ---------------------------------------------------------------------------
# Call 5 — Study plan for gaps marked no_experience
# ---------------------------------------------------------------------------

_STUDY_PLAN_SYSTEM_PROMPT = """Create a focused study plan for a Senior Cloud/DevOps/SRE engineer to
close a specific technology gap. Bias hands-on labs toward exercising skills they already
have (their skills list is provided) on the new technology - that's the fastest transfer
path. Return ONLY JSON matching:

{
  "requirement": "",
  "priority": "high|medium|low",
  "study_topics": ["3-6 topics, ordered"],
  "hands_on_labs": [
    { "title": "", "why": "why this lab, referencing their existing skills", "est_hours": 3 }
  ],
  "interview_talking_points": ["honest ways to frame partial/lab exposure if asked"],
  "resources": [{ "title": "", "url": "", "type": "docs|course|video" }]
}

Rules:
- priority reflects how central the requirement is to the JD context given.
- 2-3 labs max, each under ~4 hours.
- resources: prefer official docs; only include URLs you are confident exist.
"""


def build_study_plan(
    requirement: str, jd_context: str, skills_master: list[str]
) -> StudyPlan:
    user_content = json.dumps(
        {
            "requirement": requirement,
            "jd_context": jd_context,
            "candidate_skills_master": skills_master,
        }
    )
    data = generate_json(_STUDY_PLAN_SYSTEM_PROMPT, user_content)
    data.setdefault("requirement", requirement)
    return StudyPlan.model_validate(data)


# ---------------------------------------------------------------------------
# Call 5 — Study Guide Curator (v3 §6). Two-step because Gemini's search
# grounding cannot be combined with JSON mode: (1) grounded research call
# returns prose with live URLs, (2) plain JSON-mode call structures it.
# URL validation (sources.validate_urls) runs afterward and drops dead links.
# ---------------------------------------------------------------------------

_CURATOR_RESEARCH_PROMPT = """Build a complete study curriculum for a Senior Cloud/DevOps/SRE/MLOps/LLMOps
engineer to genuinely learn {requirement}, not skim it. This is reference material they
will return to repeatedly, not a one-time overview - treat it with the thoroughness of a
real course syllabus. Use Google Search for everything current - never rely on memory for
URLs, book editions, or repo names. {source_preferences}

Research and write up (plain prose, include full URLs inline):
1. At least one genuinely authoritative BOOK on this topic - real title, real authors, and
   a specific reason it's right for this role level. Search for its O'Reilly catalog page
   ({oreilly_note}) and include the URL. If genuinely not on O'Reilly, find its publisher
   or a well-established bookseller page instead - never leave a book without a URL.
2. A real progression of 3-4 steps: foundational concepts -> a hands-on lab that reuses
   the candidate's existing skills where possible -> operate-it-like-production
   (failure simulation, what an SRE watches) -> interview-readiness. Each step needs a
   concrete, CHECKABLE goal ("explain X without notes", "recover from a killed broker"),
   not "learn about X".
3. For the hands-on lab: search for and verify a real, currently-maintained GitHub repo
   suited to it (recent commits/stars) - include its URL. Do not invent one.
4. Resources per step: official documentation for foundational steps, deeper blogs/
   talks for operational nuance. Full URLs inline for everything.
5. Honest interview talking points - lab-level exposure framed as lab-level, unless the
   candidate's history shows real production experience.
6. If a structured course/portal (O'Reilly Learning Platform, A Cloud Guru, KodeKloud,
   Linux Foundation Training, Coursera, Pluralsight) has strong, currently-available
   coverage of this topic, include it as a "portal" resource with a real, verified URL -
   this candidate uses structured platforms, not only ad-hoc blog posts.

Requirement: {requirement}
Why it matters to this candidate (demand context): {why_it_matters}
Candidate's existing skills (for lab-reuse suggestions): {skills}
{persona_note}
"""

_CURATOR_STRUCTURE_PROMPT = """Convert this research write-up into JSON matching exactly:

{
  "canonical_id": "",
  "why_it_matters": "",
  "recommended_books": [ { "title": "", "authors": "", "why": "", "oreilly_url": "", "publisher_url": "" } ],
  "steps": [
    {
      "step_number": 1, "title": "", "goal": "",
      "concepts": [""],
      "resources": [{ "type": "docs|blog|course|video|book|portal|repo", "title": "", "url": "", "source": "official|medium|linkedin|tldr|udemy|oreilly|acloudguru|kodekloud|github|other" }],
      "hands_on_lab": { "title": "", "repo_url": "", "why_this_lab": "", "est_hours": 4 },
      "sample_project": { "title": "", "repo_url": "", "description": "" },
      "interview_talking_points": [""],
      "est_hours": 2, "done": false
    }
  ]
}

Rules: only include URLs that literally appear in the research text - never invent or
"fix" a URL. recommended_books must carry the real title/authors from the research, plus
oreilly_url if an O'Reilly catalog page was found, else publisher_url as the fallback -
never leave both empty if the research found ANY book URL. hands_on_lab/sample_project
may be null on steps where they don't apply. Goals must be checkable actions, not vague
intentions. Return ONLY the JSON object.
"""


def curate_study_guide_research(
    requirement: str,
    why_it_matters: str,
    skills: list[str],
    source_preferences: str = "",
    oreilly_access: bool = False,
    role_category: str | None = None,
) -> str:
    from .domain_personas import DOMAIN_PERSONAS
    from .gemini_client import generate_grounded_text

    oreilly_note = (
        "the user has O'Reilly/Safari access, so this is worth doing"
        if oreilly_access
        else "only if it exists — the user hasn't confirmed O'Reilly access"
    )
    persona = DOMAIN_PERSONAS.get(role_category or "")
    persona_note = (
        f"What actually matters at staff level in this domain ({persona['title']}): "
        f"{persona['study_priorities']}"
        if persona
        else ""
    )
    prompt = _CURATOR_RESEARCH_PROMPT.format(
        requirement=requirement,
        why_it_matters=why_it_matters,
        skills=", ".join(skills),
        source_preferences=source_preferences,
        oreilly_note=oreilly_note,
        persona_note=persona_note,
    )
    return generate_grounded_text(prompt)


def structure_study_guide(research_text: str, canonical_id: str) -> dict:
    data = generate_json(_CURATOR_STRUCTURE_PROMPT, research_text)
    data["canonical_id"] = canonical_id
    return data


# ---------------------------------------------------------------------------
# Market-fit synthesis (v3 §8) — turns deterministic aggregation counts into
# a ranked, readable narrative. It does not decide what counts as a gap.
# ---------------------------------------------------------------------------

_MARKET_FIT_SYSTEM_PROMPT = """You are a career advisor giving a Senior Cloud/DevOps/
SRE/MLOps engineer a genuinely useful read on their job-market position - not a status
report generator. Work from PRE-COMPUTED aggregation data; do not re-derive counts.

CRITICAL - group before you write:
- Cluster related requirements into THEMES before producing output (e.g. "ML
  orchestration frameworks," "feature stores," and "ML lifecycle tooling" are
  one theme: "MLOps tooling"; "Datadog for observability" alongside
  Prometheus/Grafana gaps would be one theme: "Observability tooling").
  Each theme should read as one coherent insight, not a pile of near-duplicate
  bullets. Assign every item a `theme` field.
- Vary your sentence structure. Do not reuse the same phrasing pattern across
  items - write the way a sharp colleague would talk through this over coffee,
  not the way a compliance report reads. Each item should sound like a
  distinct observation, not a mail-merged template.
- Be direct and specific, not padded. If something is a one-off, say so
  plainly instead of dressing it up with a full sentence of hedging.

The promotable-experience input already carries each item's canonical_id - copy it
through verbatim into your output, never invent or omit it.

Return ONLY valid JSON matching:
{
  "top_recurring_gaps": [
    { "requirement": "", "theme": "", "times_required": 0, "times_gapped": 0,
      "priority": "high|medium|low", "reasoning": "" }
  ],
  "promotable_experience_not_yet_in_base_resume": [
    { "requirement": "", "canonical_id": "", "theme": "",
      "confirmed_in_applications": 0, "suggested_action": "" }
  ],
  "resume_structural_suggestions": [ { "detail": "" } ],
  "study_plan_priority_ranked": ["requirement names, most urgent first"]
}
"""


def synthesize_market_fit(aggregation: dict, dominant_role_category: str | None = None) -> dict:
    from .domain_personas import DOMAIN_PERSONAS

    persona = DOMAIN_PERSONAS.get(dominant_role_category or "")
    lens_note = (
        f"\n\nGrouping lens for this candidate's domain ({persona['title']}): "
        f"{persona['requirement_grouping_lens']}"
        if persona
        else ""
    )
    return generate_json(_MARKET_FIT_SYSTEM_PROMPT + lens_note, json.dumps(aggregation))


# ---------------------------------------------------------------------------
# One-time onboarding call — tag core bullets (human-reviewed afterward)
# ---------------------------------------------------------------------------

_CORE_TAGGER_SYSTEM_PROMPT = """You are reviewing a senior SRE/DevOps/Cloud engineer's resume bullets.
Mark each bullet id as core (true/false). Core = baseline senior competency relevant to
essentially every job in the Cloud/DevOps/SRE/MLOps family: on-call/incident response,
infrastructure as code, CI/CD ownership, cost optimization, security/compliance,
observability fundamentals. Specialized or niche items (a specific GPU model, a specific
vendor product) are not core. Return ONLY JSON:

{ "core_bullet_ids": ["exp_1_b2", "acc1", ...] }
"""


def tag_core_bullets(resume: ResumeJSON) -> list[str]:
    bullets = [
        {"id": b.id, "text": b.text}
        for exp in resume.experience
        for b in exp.bullets
    ] + [{"id": b.id, "text": b.text} for b in resume.accomplishments]
    data = generate_json(_CORE_TAGGER_SYSTEM_PROMPT, json.dumps(bullets))
    return data.get("core_bullet_ids", [])


# ---------------------------------------------------------------------------
# Call 4 — Cover letter (only approved content; confirmed gaps may be
# referenced honestly, unconfirmed gaps never)
# ---------------------------------------------------------------------------

_COVER_LETTER_SYSTEM_PROMPT = """Write a cover letter. Format rules are strict, not suggestions:
- Structure: subject line, greeting, EXACTLY 3 body paragraphs, sign-off.
- Body length: 180-250 words total.
- Maximum 2 quantified metrics in the ENTIRE letter - pick the 2 most relevant to this
  JD's stated problems, not the most impressive in isolation.
- Paragraph 1: role + one-line positioning. No stats.
- Paragraph 2: 1-2 proof points tied to the JD's actual stated problem.
- Paragraph 3: name 1-2 genuine gaps honestly, bridge to adjacent real experience, end
  with one sentence of specific motivation using company_context - never generic
  "I'm excited to apply."
- Never restate more than 3 tools/technologies by name - the resume already lists them.
- Use ONLY facts present in ResumeJSON/TailoringPlan/confirmed gap notes. NEVER mention
  unconfirmed gaps or invent exposure.
Return ONLY JSON: { "cover_letter": "subject line + full letter text" }
"""


def write_cover_letter(
    resume: ResumeJSON,
    plan: TailoringPlan,
    jd_analysis: JDAnalysis,
    confirmed_gap_notes: list[dict],
    company_context: str = "",
) -> str:
    user_content = (
        f"ResumeJSON:\n{resume.model_dump_json()}\n\n"
        f"TailoringPlan:\n{plan.model_dump_json()}\n\n"
        f"JDAnalysis:\n{jd_analysis.model_dump_json()}\n\n"
        f"Confirmed gap notes (candidate's own words):\n{json.dumps(confirmed_gap_notes)}\n\n"
        f"Company context:\n{company_context}"
    )
    data = generate_json(_COVER_LETTER_SYSTEM_PROMPT, user_content)
    return data["cover_letter"]


# ---------------------------------------------------------------------------
# Fabrication / metric-loss check — last-mile safety net (human approval is
# the primary control in v2). Also run against the cover letter.
# ---------------------------------------------------------------------------

_FABRICATION_SYSTEM_PROMPT = """Compare each bullet pair (original vs tailored). Set "fabricated": true if
EITHER of these happened:
1. The tailored version asserts any fact, tool, number, or outcome not present in the original.
2. The tailored version DROPS or VAGUE-IFIES a specific number from the original - a percentage,
   count, dollar amount, or scale figure that appeared in "original" but is missing, rounded away,
   or replaced with a vague word (e.g. "significant", "extensive") in "tailored". Losing a metric
   is just as bad as inventing one.

Return ONLY a JSON array matching:
[{ "bullet_id": "", "fabricated": false, "details": "" }]
"""


def check_fabrication(pairs: list[dict]) -> list[FabricationCheckItem]:
    """pairs: [{"bullet_id": str, "original": str, "tailored": str}, ...]"""
    if not pairs:
        return []
    data = generate_json(_FABRICATION_SYSTEM_PROMPT, json.dumps(pairs))
    return [FabricationCheckItem.model_validate(item) for item in data]


_COVER_LETTER_CHECK_SYSTEM_PROMPT = """Check this cover letter against the candidate's approved resume facts
and confirmed gap notes. Flag any claim of experience with a tool, technology, metric, or
outcome that appears in the letter but in neither the resume nor the confirmed notes.
Return ONLY JSON: { "fabricated": false, "details": "" }
"""


def check_cover_letter(
    cover_letter: str, resume: ResumeJSON, confirmed_gap_notes: list[dict]
) -> dict:
    user_content = json.dumps(
        {
            "cover_letter": cover_letter,
            "resume": resume.model_dump(),
            "confirmed_gap_notes": confirmed_gap_notes,
        }
    )
    return generate_json(_COVER_LETTER_CHECK_SYSTEM_PROMPT, user_content)
