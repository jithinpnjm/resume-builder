"""Pydantic schemas for the resume tailoring pipeline.

These mirror the JSON contracts in the implementation brief exactly.
ResumeJSON is the single source of truth for resume content; every other
schema is derived from it or from a Gemini call keyed off it.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# ResumeJSON — built once during onboarding, edited only via explicit user
# review. Gemini never edits this in place.
# ---------------------------------------------------------------------------

class Contact(BaseModel):
    name: str = ""
    location: str = ""
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    github: str = ""


class SkillCategory(BaseModel):
    name: str
    items: list[str] = Field(default_factory=list)


class Skills(BaseModel):
    categories: list[SkillCategory] = Field(default_factory=list)


class Segment(BaseModel):
    text: str
    bold: bool = False


class Bullet(BaseModel):
    id: str
    text: str
    # Inline formatting from the original resume (bold metrics/key nouns),
    # extracted deterministically from docx runs — never LLM-derived. Empty
    # means "no formatting info": render falls back to plain text.
    segments: list[Segment] = Field(default_factory=list)
    # core=True marks baseline senior SRE/DevOps competency (incident response,
    # IaC, CI/CD, cost, security/compliance). Core bullets may be reordered
    # lower but never removed or hidden by any tailoring plan.
    core: bool = False
    tags: list[str] = Field(default_factory=list)


class Experience(BaseModel):
    id: str
    company: str = ""
    title: str = ""
    location: str = ""
    start: str = ""
    end: str = ""
    bullets: list[Bullet] = Field(default_factory=list)


class ProjectBullet(BaseModel):
    id: str
    text: str


class Project(BaseModel):
    id: str
    name: str = ""
    bullets: list[ProjectBullet] = Field(default_factory=list)


class Education(BaseModel):
    degree: str = ""
    institution: str = ""
    year: str = ""


class Language(BaseModel):
    name: str = ""
    level: str = ""


class ResumeJSON(BaseModel):
    contact: Contact = Field(default_factory=Contact)
    summary: str = ""
    summary_segments: list[Segment] = Field(default_factory=list)
    accomplishments: list[Bullet] = Field(default_factory=list)
    skills: Skills = Field(default_factory=Skills)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# JDAnalysis — Gemini call #1 output
# ---------------------------------------------------------------------------

class Requirement(BaseModel):
    requirement: str
    category: str = ""  # free-form: tool/platform/methodology/domain/certification/soft-skill/...
    keyword_variants: list[str] = Field(default_factory=list)


class NiceToHaveRequirement(BaseModel):
    requirement: str
    category: str = ""


class CompanyContext(BaseModel):
    industry: str = ""
    product_signal: str = ""

    @field_validator("industry", "product_signal", mode="before")
    @classmethod
    def _null_to_empty(cls, v):
        return v or ""


class JDAnalysis(BaseModel):
    role_title: str = ""
    seniority_signal: str = ""
    must_have_requirements: list[Requirement] = Field(default_factory=list)
    nice_to_have_requirements: list[NiceToHaveRequirement] = Field(default_factory=list)

    @field_validator("role_title", "seniority_signal", mode="before")
    @classmethod
    def _null_to_empty(cls, v):
        # Short/minimal JD text (common in trend-scan mini-postings) can lead
        # Gemini to return null here instead of omitting the field.
        return v or ""
    ats_keywords: list[str] = Field(default_factory=list)
    company_context: CompanyContext = Field(default_factory=CompanyContext)
    # --- role-fit gate (patch §1) ---
    role_category: str = "unrelated"  # one of TARGET_ROLE_CATEGORIES | "related_adjacent" | "unrelated"
    requires_deep_dev_skills: bool = False
    core_dev_languages_required: list[str] = Field(default_factory=list)
    dev_skill_reasoning: str = ""


# ---------------------------------------------------------------------------
# TailoringPlan v2 — Gemini call #2 output. Reorder + terminology alignment
# ONLY: it may resequence content and rename tools to the JD's exact terms
# (when the candidate genuinely has them), but it never adds or removes
# content. New content enters solely via the confirmed-gap insertion flow.
# ---------------------------------------------------------------------------

class BulletPlanItem(BaseModel):
    bullet_id: str
    final_text: str = ""  # empty means "unchanged from original" (LLM output)
    # Derived deterministically from final_text after integrity checks — the
    # LLM never decides bolding. Empty when the bullet is unchanged.
    final_segments: list[Segment] = Field(default_factory=list)
    keywords_injected: list[str] = Field(default_factory=list)
    injection_type: Literal["renamed_existing", "none"] = "none"


class TailoringPlan(BaseModel):
    tailored_summary: str = ""
    experience_order: list[str] = Field(default_factory=list)
    bullet_order: dict[str, list[str]] = Field(default_factory=dict)
    skills_displayed: list[str] = Field(default_factory=list)
    # Hidden for THIS application only — never deleted from ResumeJSON.
    skills_deprioritized: list[str] = Field(default_factory=list)
    bullet_plan: list[BulletPlanItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# SkillGapReport — derived from TailoringPlan.coverage_gaps, not a Gemini call
# ---------------------------------------------------------------------------

class MissingSkill(BaseModel):
    skill: str
    requirement_source: str = ""
    priority: Literal["high", "medium", "low"] = "medium"
    suggested_learning_path: str = ""


class SkillGapReport(BaseModel):
    missing_skills: list[MissingSkill] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Fabrication check — last-mile safety net (human approval is the primary
# control in v2)
# ---------------------------------------------------------------------------

class FabricationCheckItem(BaseModel):
    bullet_id: str
    fabricated: bool
    details: str = ""


# ---------------------------------------------------------------------------
# GapItem — one per JD requirement with no resume match. The tailoring engine
# may not derive any resume content from a gap until user_response.status is
# have_experience/partial_experience AND user_note is non-empty.
# ---------------------------------------------------------------------------

class GapEducation(BaseModel):
    what_it_is: str = ""
    typical_use_case_for_role: str = ""
    sample_scenario: str = ""
    closest_known_alternative: str = ""
    other_alternatives_in_market: list[str] = Field(default_factory=list)


class GapUserResponse(BaseModel):
    status: Literal[
        "have_experience", "partial_experience", "no_experience", "not_reviewed"
    ] = "not_reviewed"
    user_note: str = ""
    reviewed_at: str = ""


class GapItem(BaseModel):
    requirement: str
    jd_context: str = ""
    # Set by canonicalization (Call 2b) against requirements_catalog.
    canonical_id: str = ""
    # When the catalog already holds a confirmed status for this requirement,
    # the UI offers one-click reuse instead of re-asking/re-educating.
    reusable_note: str = ""
    reusable_status: str = ""
    reused_from: str = ""  # source application id when the user accepts reuse
    education: GapEducation = Field(default_factory=GapEducation)
    user_response: GapUserResponse = Field(default_factory=GapUserResponse)
    # Set by the confirmed-gap insertion flow; shown as a proposed diff line,
    # never auto-applied.
    proposed_bullet: str = ""
    proposed_target_exp_id: str = ""


# ---------------------------------------------------------------------------
# StudyPlan — generated for every gap marked no_experience
# ---------------------------------------------------------------------------

class HandsOnLab(BaseModel):
    title: str = ""
    why: str = ""
    est_hours: float = 0


class StudyResource(BaseModel):
    title: str = ""
    url: str = ""
    type: str = ""  # docs|course|video


class StudyPlan(BaseModel):
    requirement: str
    priority: Literal["high", "medium", "low"] = "medium"
    study_topics: list[str] = Field(default_factory=list)
    hands_on_labs: list[HandsOnLab] = Field(default_factory=list)
    interview_talking_points: list[str] = Field(default_factory=list)
    resources: list[StudyResource] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# requirements_catalog — cross-application memory (v3 §2). One entry per
# real-world skill/tool; gap detection checks this FIRST.
# ---------------------------------------------------------------------------

class DemandSource(BaseModel):
    company: str = ""
    role: str = ""
    date: str = ""
    # "application" (Button 1 real resume build) or "trend_scan" (Button 3
    # bulk JD intake). The catalog blends both; only the Job Market Analysis
    # dashboard filters to application-sourced signal.
    source_type: Literal["application", "trend_scan"] = "application"
    # JDAnalysis.role_category of the posting that surfaced this demand, so
    # the Study Guide curator can ground itself in the right domain persona.
    role_category: str = ""


class StatusHistoryEntry(BaseModel):
    date: str = ""
    status: str = ""
    source_application_id: str = ""
    note: str = ""  # user's own words, carried verbatim


class CatalogEntry(BaseModel):
    canonical_id: str
    canonical_name: str = ""
    aliases: list[str] = Field(default_factory=list)
    category: str = ""
    demand_count: int = 0
    demand_sources: list[DemandSource] = Field(default_factory=list)
    user_status: Literal[
        "have_experience", "partial_experience", "no_experience", "not_reviewed"
    ] = "not_reviewed"
    status_history: list[StatusHistoryEntry] = Field(default_factory=list)
    in_base_resume: bool = False
    priority_score: float = 0.0
    last_seen: str = ""
    # patch §6 — dismissing a promote-suggestion removes it from the report
    # entirely (filtered before the Gemini synthesis call), not just hidden
    # client-side.
    promote_suggestion_dismissed: bool = False


# ---------------------------------------------------------------------------
# StudyGuide v3 §6 — real, sequenced curriculum, one per catalog entry
# ---------------------------------------------------------------------------

class StudyGuideResource(BaseModel):
    type: str = ""  # docs|blog|course|video|book|portal|repo
    title: str = ""
    url: str = ""
    source: str = ""  # official|medium|linkedin|tldr|udemy|oreilly|acloudguru|kodekloud|...
    url_valid: bool = True


class StudyGuideLab(BaseModel):
    title: str = ""
    repo_url: str = ""
    why_this_lab: str = ""
    est_hours: float = 0


class StudyGuideSampleProject(BaseModel):
    title: str = ""
    repo_url: str = ""
    description: str = ""


class StudyGuideStep(BaseModel):
    step_number: int
    title: str = ""
    goal: str = ""
    concepts: list[str] = Field(default_factory=list)
    resources: list[StudyGuideResource] = Field(default_factory=list)
    hands_on_lab: StudyGuideLab | None = None
    sample_project: StudyGuideSampleProject | None = None
    interview_talking_points: list[str] = Field(default_factory=list)
    est_hours: float = 0
    done: bool = False


class RecommendedBook(BaseModel):
    title: str = ""
    authors: str = ""
    why: str = ""
    oreilly_url: str = ""     # O'Reilly/Safari catalog page if it exists
    publisher_url: str = ""   # fallback if not on O'Reilly (publisher/Amazon)


class StudyGuideEntry(BaseModel):
    canonical_id: str
    priority_score: float = 0.0
    why_it_matters: str = ""
    recommended_books: list[RecommendedBook] = Field(default_factory=list)
    steps: list[StudyGuideStep] = Field(default_factory=list)
    last_curated_at: str = ""
    url_validation_status: Literal["all_checked", "some_stale"] = "all_checked"


# ---------------------------------------------------------------------------
# Trend Scan (v3 rev2 §3a) — Button 3 bulk JD intake. No ApplicationRecord,
# no tailoring, no GCS folder: JD text in, catalog signal + study material out.
# ---------------------------------------------------------------------------

class TrendGapItem(BaseModel):
    requirement: str
    jd_context: str = ""
    canonical_id: str = ""
    source_postings: list[str] = Field(default_factory=list)  # role titles seen in
    education: GapEducation = Field(default_factory=GapEducation)
    user_response: GapUserResponse = Field(default_factory=GapUserResponse)


class TrendScanBatch(BaseModel):
    id: str = ""
    created_at: str = ""
    posting_count: int = 0
    role_titles: list[str] = Field(default_factory=list)
    # ONE consolidated review across all postings (deduplicated by canonical id)
    review_items: list[TrendGapItem] = Field(default_factory=list)
    # requirements auto-counted without user interaction (already confirmed)
    auto_counted: list[str] = Field(default_factory=list)
    # patch §1 — postings excluded entirely by the role-fit gate: no gap
    # detection, no catalog writes for that posting.
    skipped_postings: list[dict] = Field(default_factory=list)
    status: Literal["pending_review", "completed"] = "pending_review"
    completed_at: str = ""


# ---------------------------------------------------------------------------
# Settings — content-source linking (v3 §7). Plain URLs + newsletter tags,
# no OAuth. Flavors search-grounded curation queries.
# ---------------------------------------------------------------------------

class UserSettings(BaseModel):
    linkedin_url: str = ""
    medium_url: str = ""
    newsletters: list[str] = Field(default_factory=list)
    oreilly_access: bool = False
    preferred_portals: list[str] = Field(default_factory=list)  # e.g. ["A Cloud Guru", "KodeKloud"]


# ---------------------------------------------------------------------------
# MarketFitReport — v3 §8/Career Growth. Deterministic aggregation + one
# Gemini synthesis call.
# ---------------------------------------------------------------------------

class MatchRatePoint(BaseModel):
    date: str = ""
    company: str = ""
    match_pct: float | None = None


class RecurringGap(BaseModel):
    requirement: str = ""
    theme: str = ""  # e.g. "MLOps tooling", "Observability"
    times_required: int = 0
    times_gapped: int = 0
    priority: str = ""
    reasoning: str = ""


class PromotableExperience(BaseModel):
    requirement: str = ""
    canonical_id: str = ""  # needed so dismiss can target the right catalog entry
    theme: str = ""
    confirmed_in_applications: int = 0
    suggested_action: str = ""
    dismissed: bool = False


class StructuralSuggestion(BaseModel):
    detail: str = ""


class MarketFitReport(BaseModel):
    period: dict = Field(default_factory=dict)
    match_rate_trend: list[MatchRatePoint] = Field(default_factory=list)
    top_recurring_gaps: list[RecurringGap] = Field(default_factory=list)
    promotable_experience_not_yet_in_base_resume: list[PromotableExperience] = Field(
        default_factory=list
    )
    resume_structural_suggestions: list[StructuralSuggestion] = Field(default_factory=list)
    study_plan_priority_ranked: list[str] = Field(default_factory=list)
    generated_at: str = ""


# ---------------------------------------------------------------------------
# ApplicationRecord — workflow/state object for the v2 state machine
# ---------------------------------------------------------------------------

ApplicationStatus = Literal[
    "analyzing", "pending_review", "approved", "finalized", "archived", "discarded"
]


class RoleFitAssessment(BaseModel):
    role_category: str = "unrelated"
    requires_deep_dev_skills: bool = False
    core_dev_languages_required: list[str] = Field(default_factory=list)
    skill_match_pct: float = 0.0
    decision: str = "process"  # process | warn | skip
    decision_reason: str = ""


class DiffSummary(BaseModel):
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    reordered: list[str] = Field(default_factory=list)
    reworded: list[str] = Field(default_factory=list)


class ApplicationRecord(BaseModel):
    id: str = ""
    company: str = ""
    role_title: str = ""
    status: ApplicationStatus = "analyzing"
    created_at: str = ""  # ISO timestamp; market-fit trend analysis keys on this
    jd_analysis: JDAnalysis | None = None
    tailoring_plan: TailoringPlan | None = None
    gaps: list[GapItem] = Field(default_factory=list)
    study_plans: list[StudyPlan] = Field(default_factory=list)
    diff_summary: DiffSummary = Field(default_factory=DiffSummary)
    cover_letter: str = ""
    approved_at: str | None = None
    gcs_path: str = ""
    role_fit: RoleFitAssessment | None = None
    # Static staff-engineer interview lens for this JD's role_category —
    # copied verbatim from domain_personas.DOMAIN_PERSONAS at analysis time,
    # not LLM-generated. None for related_adjacent/unrelated roles.
    interview_lens: dict | None = None


# ---------------------------------------------------------------------------
# ResumeVersion — snapshot every time the base resume changes. This is what
# makes longitudinal market-fit analysis possible: you need to know what the
# resume claimed on a given date. Promotion of confirmed gap experience into
# the base resume creates one of these.
# ---------------------------------------------------------------------------

class ResumeVersion(BaseModel):
    version: int
    created_at: str = ""
    # e.g. "promoted MongoDB bullet from SWARCO application" | "manual edit"
    #      | "re-onboarded from updated PDF"
    change_reason: str = ""
    resume_json_snapshot: ResumeJSON
