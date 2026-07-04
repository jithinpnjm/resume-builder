# Patch: Role-Fit Gate, Study Room Depth, Landing Page Consolidation

**Implement every numbered section below in full — do not skip, partially
implement, or silently drop any requirement, even ones that seem minor,
redundant, or already partly covered by existing code.** If something in this
document is ambiguous, unclear, or seems to conflict with existing code,
stop and ask rather than guessing or quietly omitting it. Before considering
this patch done, go back through each numbered section and verify the
corresponding code actually exists and behaves as specified — a section
that "mostly" works or was interpreted loosely is not complete. This has been
an issue before: treat every bullet point and schema field listed here as a
hard requirement, not a suggestion to use judgment on.

Targeted patch against the current `resume-builder` repo — references exact
files/classes that already exist. Not a rewrite; apply as a diff on top of
what's there.

---

## 1. Role-Fit Gate

**Problem:** nothing currently stops a JD for an unrelated or wrong-skillset
role from being fully processed — tailored, gap-reviewed, and fed into the
Study Room. Need a gate that runs right after JD analysis, before any gap
detection or catalog writes.

### Target role taxonomy

```python
# new file: backend/app/role_fit.py

TARGET_ROLE_CATEGORIES = {
    "senior_sre_devops_cloud",
    "senior_mlops",
    "senior_ai_platform",
    "aiops_llmops",
}
# "related_adjacent" and "unrelated" are the other two values role_category
# can take — anything not in TARGET_ROLE_CATEGORIES.

ALLOWED_DEV_LANGUAGES = {"python", "go", "golang", "bash", "shell", "sql"}
```

### Schema additions (`backend/app/schemas.py`)

Extend `JDAnalysis` (currently at line 126) with fields the JD Analyzer
already has full context to populate in the same call — no extra Gemini
round-trip:

```python
class JDAnalysis(BaseModel):
    role_title: str = ""
    seniority_signal: str = ""
    must_have_requirements: list[Requirement] = Field(default_factory=list)
    nice_to_have_requirements: list[NiceToHaveRequirement] = Field(default_factory=list)
    ats_keywords: list[str] = Field(default_factory=list)
    company_context: CompanyContext = Field(default_factory=CompanyContext)
    # --- new ---
    role_category: str = "unrelated"  # one of TARGET_ROLE_CATEGORIES | "related_adjacent" | "unrelated"
    requires_deep_dev_skills: bool = False
    core_dev_languages_required: list[str] = Field(default_factory=list)
    dev_skill_reasoning: str = ""
```

New result type:

```python
# backend/app/role_fit.py, continued

from .schemas import JDAnalysis


class RoleFitAssessment(BaseModel):
    role_category: str
    requires_deep_dev_skills: bool
    core_dev_languages_required: list[str] = []
    skill_match_pct: float = 0.0
    decision: str = "process"  # process | warn | skip
    decision_reason: str = ""


def assess(jd: JDAnalysis, skill_match_pct: float) -> RoleFitAssessment:
    langs = {l.lower() for l in jd.core_dev_languages_required}
    disallowed = langs - ALLOWED_DEV_LANGUAGES

    if jd.requires_deep_dev_skills and disallowed:
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
```

**`skill_match_pct` must be computed by a shared deterministic function** —
don't reimplement it a third time. `archive.py`'s `aggregate_market_fit` and
the BigQuery write path in `write_bigquery_rows` both already compute
matched-vs-total against `must_have_requirements`; extract that into one
function in `gaps.py` (near `skills_master`) and call it from all three
places:

```python
# backend/app/gaps.py, new function

def compute_skill_match_pct(resume: ResumeJSON, jd_analysis: JDAnalysis) -> float:
    must = jd_analysis.must_have_requirements
    if not must:
        return 1.0
    text = _resume_full_text(resume)
    matched = sum(
        1 for req in must
        if any(_term_present(v, text) for v in [req.requirement, *req.keyword_variants])
    )
    return matched / len(must)
```

### Wiring into `create_application` (Button 1, `main.py` ~line 162)

Insert the gate immediately after `jd_analysis = gemini_calls.analyze_jd(...)`,
before the tailoring plan or gap detection run:

```python
jd_analysis = gemini_calls.analyze_jd(req.job_description)

skill_match_pct = compute_skill_match_pct(resume, jd_analysis)
fit = role_fit.assess(jd_analysis, skill_match_pct)
if fit.decision == "skip":
    raise HTTPException(422, f"Skipped: {fit.decision_reason}")
# "warn" does NOT block — it's carried on the record for the UI to surface,
# per the request: warn, don't silently refuse, except for the hard dev-skill case.

tailoring_plan = gemini_calls.build_tailoring_plan(resume, jd_analysis)
...
record = ApplicationRecord(
    ...,
    role_fit=fit,   # new field, see below
)
```

Add `role_fit: RoleFitAssessment | None = None` to `ApplicationRecord` in
`schemas.py`.

### Wiring into Trend Scan (Button 3, `trendscan.py`)

Per-posting, not per-batch — one posting in a batch of five might be a fit
and the rest not:

```python
# inside run_scan(), per posting, after JD analysis for that posting
skill_match_pct = compute_skill_match_pct(store.get_base_resume(), jd_analysis)
fit = role_fit.assess(jd_analysis, skill_match_pct)
if fit.decision == "skip":
    batch.skipped_postings.append({"role_title": jd_analysis.role_title, "reason": fit.decision_reason})
    continue  # excluded entirely: no gap detection, no catalog writes for this posting
# "warn" postings still proceed — attach fit to the batch for the UI to show
```

Add `skipped_postings: list[dict] = Field(default_factory=list)` to
`TrendScanBatch` in `schemas.py`.

### Frontend surfacing

- `NewApplicationPage` / `ApplicationView.tsx`: if `record.role_fit.decision == "warn"`,
  show a dismissible banner above the gap review: *"Outside your target roles
  and X% skill match — {reason}. Proceeding anyway."* No confirmation gate
  needed (per your instruction — warn, don't block), just visibility.
- `TrendScanPage.tsx`: render `batch.skipped_postings` as its own small
  section ("Skipped — outside target skillset") so skips are visible, not
  silent.

### Extend the JD Analyzer prompt (`gemini_calls.py`, `analyze_jd`)

Add to the existing system prompt (don't create a second call):

```
Also classify:
- role_category: one of "senior_sre_devops_cloud", "senior_mlops",
  "senior_ai_platform", "aiops_llmops", "related_adjacent", "unrelated".
  The candidate's target roles are Senior SRE/DevOps/Cloud Engineer, Senior
  MLOps, Senior AI Platform Engineer, and AIOps/LLMOps. "related_adjacent"
  is for roles clearly in the same infrastructure/platform/ML-ops universe
  but not an exact fit (e.g. "Platform Reliability Lead", "ML Infrastructure
  Engineer"). "unrelated" is for roles with no meaningful connection (sales,
  frontend-only, pure data analyst, etc).
- requires_deep_dev_skills: true if the role's PRIMARY function is software
  development (writing application code as the main deliverable), not
  infrastructure/platform/ops work that happens to involve scripting.
- core_dev_languages_required: the actual programming languages this role
  needs as CORE skills (not incidental scripting). Python, Go, Bash, and SQL
  don't count as "deep dev skills" for this candidate even if required —
  they're already covered. Only flag languages beyond those.
- dev_skill_reasoning: one sentence justifying requires_deep_dev_skills.
```

---

## 2. Study Room depth — O'Reilly, portals, real docs

**Problem:** `RecommendedBook` (schemas.py line 336) has no URL field at all
— a recommended book currently can't be clicked through to anywhere. Resource
types are also under-specified (`docs|blog|course|video` in the
`StudyGuideResource` comment) with no explicit "book" or "portal" category
and no O'Reilly awareness anywhere in the settings or prompts.

### Schema changes

```python
class RecommendedBook(BaseModel):
    title: str = ""
    authors: str = ""
    why: str = ""
    oreilly_url: str = ""     # new — O'Reilly/Safari catalog page if it exists
    publisher_url: str = ""   # new — fallback if not on O'Reilly (publisher/Amazon)


class StudyGuideResource(BaseModel):
    type: str = ""  # docs | blog | course | video | book | portal | repo
    title: str = ""
    url: str = ""
    source: str = ""  # official | medium | linkedin | tldr | udemy | oreilly | acloudguru | kodekloud | ...
    url_valid: bool = True


class UserSettings(BaseModel):
    linkedin_url: str = ""
    medium_url: str = ""
    newsletters: list[str] = Field(default_factory=list)
    oreilly_access: bool = False               # new
    preferred_portals: list[str] = Field(default_factory=list)  # new — e.g. ["A Cloud Guru", "KodeKloud", "Coursera"]
```

### `sources.py` — extend `source_preferences()`

```python
def source_preferences(settings: UserSettings) -> str:
    parts = []
    if settings.oreilly_access:
        parts.append(
            "the user has O'Reilly/Safari Books Online access — for every "
            "recommended book, search for its O'Reilly catalog page "
            "(learning.oreilly.com or oreilly.com) and include that URL; "
            "fall back to the publisher or a well-known bookseller page only "
            "if it's not on O'Reilly"
        )
    if settings.preferred_portals:
        parts.append(
            "prefer structured courses from these platforms when relevant: "
            + ", ".join(settings.preferred_portals)
        )
    if settings.medium_url:
        parts.append(f"prefer medium.com articles (user's profile: {settings.medium_url})")
    if settings.linkedin_url:
        parts.append("prefer linkedin.com/pulse articles when relevant")
    if settings.newsletters:
        parts.append(
            "match the coverage style of these newsletters the user reads: "
            + ", ".join(settings.newsletters)
        )
    return "Source preferences: " + "; ".join(parts) + "." if parts else ""
```

### `validate_urls_in_guide` — also validate book links

Currently only checks `step.resources`, `hands_on_lab.repo_url`, and
`sample_project.repo_url` — books are never validated because they never had
a URL to validate. Add:

```python
def check_book(book) -> None:
    if book.oreilly_url and not check(book.oreilly_url):
        book.oreilly_url = ""
    if book.publisher_url and not check(book.publisher_url):
        book.publisher_url = ""

for book in entry.recommended_books:
    check_book(book)
```

### Curator research prompt (`gemini_calls.py`, `_CURATOR_RESEARCH_PROMPT`)

Strengthen point 1 and add a new point for portals:

```
1. At least one genuinely authoritative BOOK — real title, real authors, and
   a specific reason it's right for this role level. Search for its O'Reilly
   catalog page ({oreilly_note}) and include the URL. If genuinely not on
   O'Reilly, find its publisher or a well-established bookseller page instead
   — never leave a book without a URL.
...
6. If a structured course/portal (O'Reilly Learning Platform, A Cloud Guru,
   KodeKloud, Linux Foundation Training, Coursera, Pluralsight) has strong,
   currently-available coverage of this topic, include it as a "portal"
   resource with a real, verified URL — this candidate uses structured
   platforms, not only ad-hoc blog posts.
```

Where `{oreilly_note}` is filled from `source_preferences()` output so the
prompt only pushes O'Reilly when `settings.oreilly_access` is actually true.

### Settings page (frontend)

Add to the existing Settings form: an "I have O'Reilly/Safari access"
checkbox, and a multi-select or tag input for `preferred_portals` (seed the
options list with A Cloud Guru, KodeKloud, Linux Foundation Training,
Coursera, Pluralsight, Udemy — free text entry too, not locked to a list).

### `StudyGuidePage` (`pages.tsx` ~line 195) — render the new book links

```tsx
{guide.recommended_books.map((b, i) => (
  <p key={i}>
    <em>{b.title}</em> — {b.authors}
    {b.oreilly_url && <> · <a href={b.oreilly_url} target="_blank" rel="noreferrer">O'Reilly</a></>}
    {!b.oreilly_url && b.publisher_url && <> · <a href={b.publisher_url} target="_blank" rel="noreferrer">Publisher</a></>}
    <br />
    <span className="muted">{b.why}</span>
  </p>
))}
```

---

## 3. Landing page — RETRACTED, keep tiles separate

Per feedback: tiles 2 and 3 stay as two distinct landing page entries and two
distinct sidebar nav items, exactly as currently built. Do not apply any
consolidation — this section is void. (Reasoning for keeping them separate:
now that the Career Growth report itself is getting a real redesign in §6
below, the two pages read as clearly different tools rather than
similar-looking dashboards, which was the actual source of the "these look
duplicated" feeling — fixing the report's presentation solves the root cause
better than merging entry points would have.)

This is a pure frontend refactor — `CareerGrowthPage`, `TrendScanPage`, and
`StudyGuidePage` components themselves don't change, only what routes to them.

---

## 4. Fix: false-positive gaps for skills already in the resume

**Real bug, confirmed against a live report.** "Solid working knowledge of
containerization" and "Experience owning production systems" were flagged as
confirmed-but-unpromoted gaps for a candidate whose resume extensively covers
Kubernetes and PayPal production ownership. This is not a vague accuracy
issue — it's a specific, traceable failure in gap detection, and it's what
generated the misleading "promote this" suggestions in the screenshot.

### Root cause

`detect_gaps()` (`gaps.py`) is deterministic word-matching by design — a
requirement is a gap only if none of its `keyword_variants` (plus the literal
requirement string) appear anywhere in the resume text. That determinism is
the right call for *content safety* (it's what stops the LLM from inventing
experience), but it depends entirely on the JD Analyzer populating
`keyword_variants` richly enough to cover how a resume might phrase the same
skill. In this run it didn't: "containerization" as a standalone requirement
almost certainly didn't carry `["Kubernetes", "Docker", "container
orchestration"]` as variants — likely because the JD Analyzer atomized
"Kubernetes" as its own separate requirement elsewhere in the same JD and
never cross-referenced that Kubernetes *is* a containerization technology,
satisfying both. Same story for "production systems": the resume's actual
phrasing ("Owned and operated GKE clusters," "delivering high availability
for critical platforms") never triggered the word-match because the
requirement's variant list was too narrow.

The MLOps gap in the same report was correct precisely because pure keyword
matching happened to work there — the resume genuinely doesn't cover it. The
bug is specific to cases where the resume covers the underlying skill under a
**different concrete name** than the JD used, which literal word-matching
structurally cannot bridge no matter how good the regex is.

### Fix — two changes, not one

**(a) Tighten the JD Analyzer prompt** (`gemini_calls.py`,
`_JD_ANALYZER_SYSTEM_PROMPT`) to explicitly require cross-referencing between
extracted requirements:

```
- Before finalizing keyword_variants, check every OTHER requirement you've
  extracted from this same JD: if a more general requirement (e.g.
  "containerization") is satisfied by a more specific one you've also listed
  (e.g. "Kubernetes", "Docker"), the general requirement's keyword_variants
  MUST include those specific technologies. Never leave an abstract skill
  category without its concrete, commonly-used implementations as variants.
```

**(b) Add a semantic double-check pass for near-misses** — this is the real
fix, since (a) alone is prompt-tuning and will still miss cases. Before a
requirement that fails the deterministic keyword match becomes a `GapItem`
shown to the user, run ONE additional batched Gemini call across all
candidate gaps for that JD, checking each against the candidate's actual
resume content:

```python
# gaps.py or a new small module — one call per JD, not per requirement

_RELEVANCE_CHECK_PROMPT = """For each candidate gap below, check the candidate's
actual resume content (not just a keyword list) and decide whether it is
ALREADY substantively covered under a different name, tool, or phrasing.
Be conservative: only mark "already_covered" when the resume content clearly
demonstrates the underlying skill, not when it's merely plausible or adjacent.

Return JSON: [{ "requirement": "", "already_covered": bool,
  "covering_evidence": "the specific resume text that covers it, or empty" }]

Candidate gaps: {gaps}
Resume experience + skills (full text): {resume_text}
"""
```

This does NOT weaken the core safety principle — it only ever *suppresses* a
wrongly-created gap (removing false noise), it never adds content to the
resume or lets the LLM claim experience on the candidate's behalf. That
guarantee (no addition without the user's own written note) stays completely
intact; this call can only make a gap disappear, never create resume content.

Wire it into `detect_gaps()`'s caller in `main.py`'s `create_application`
(and the equivalent spot in `trendscan.py`): after the deterministic pass
produces candidate gaps, run the relevance check, drop any marked
`already_covered`, and only educate/show the remainder.

**(c) Also fix the `promotable` slug bug from the earlier audit** while
someone's in this exact code path (`archive.py`,
`aggregate_market_fit`) — it independently contributes to the same visible
symptom by re-slugifying raw requirement text instead of using the gap's
resolved `canonical_id`. Both bugs were compounding in the screenshot you
sent: a false-positive gap got created, you correctly confirmed it during
review (you do know Kubernetes!), and then the promotable-check's slug
mismatch made it look unpromoted even if it technically shouldn't have shown
up as a suggestion at all once (b) is in place.

---

## 5. New feature: discard an application without processing

**Problem:** the only exit from `pending_review` is `approve` — if a JD turns
out to be a bad fit partway through review, there's no way to walk away
without either finishing the flow or letting it sit as permanent clutter.

### Schema change (`schemas.py`)

```python
ApplicationStatus = Literal[
    "analyzing", "pending_review", "approved", "finalized", "archived", "discarded"
]
```

### Endpoint (`main.py`)

```python
@app.post("/applications/{application_id}/discard", response_model=ApplicationRecord)
def discard_application(application_id: str) -> ApplicationRecord:
    record = _get_record_or_404(application_id)
    if record.status in ("finalized", "archived"):
        raise HTTPException(409, f"Application is {record.status} — nothing to discard")
    record.status = "discarded"
    store.save_application(record)
    return record
```

No GCS/BigQuery writes, no catalog rollback — the JD's requirements stay
counted in `requirements_catalog` demand (you did see this posting, that
signal is still real), but nothing else happens. This can be called from any
state before finalize: `analyzing`, `pending_review`, or `approved`.

### Frontend (`ApplicationView.tsx`, next to the existing Approve button ~line 104)

```tsx
<button
  className="danger-ghost"
  onClick={() => run("discard", async () => {
    await api.discardApplication(record.id);
    onDiscarded(); // navigate back to home/list
  })}
  disabled={busy === "discard"}
>
  {busy === "discard" ? "Discarding…" : "Discard — not a fit"}
</button>
```

Place this visibly during `pending_review` (so you can bail out mid-review,
which is the main use case), not only next to the final Approve action.

### Sidebar (`Shell.tsx`)

Add a fourth, collapsed-by-default status group so discarded applications
don't clutter the main list but aren't silently deleted either:

```tsx
{ label: "Discarded", statuses: ["discarded"] }
```

---

## 6. Career Growth report — group into themes, fix the robotic tone, add dismiss

**Three real problems in the report you pasted, not one:**

1. **No grouping.** "ML orchestration frameworks," "feature stores," and "ML
   lifecycle tooling" are three separate flat line items that are all
   obviously the same underlying story (MLOps tooling gap) — but the report
   presents them as unrelated bullets, forcing you to mentally re-group them
   yourself every time. This is exactly the "ever-growing list" worry: as
   more applications accumulate, flat items multiply faster than themes do,
   and the page becomes unreadable long before it becomes useless.
2. **Templated, repetitive phrasing.** Every single item follows the same
   sentence skeleton ("This X was required in Y applications and identified
   as a gap in Z instances...") because `_MARKET_FIT_SYSTEM_PROMPT`
   (`gemini_calls.py` line 355) gives no instruction about tone or variation
   — it only asks the model to "rank and explain," so it defaults to the
   most mechanical possible phrasing, repeated verbatim-structure per item.
3. **No way to dismiss a wrong suggestion.** Some "confirmed" entries
   (containerization, production ownership) were false positives from the
   gap-detection bug fixed in §4 — but fixing detection going forward doesn't
   retroactively clean data already written to Firestore/BigQuery from past
   applications. Without a dismiss action, a stale wrong suggestion nags
   forever, which is its own path to you eventually ignoring this page.

### Schema: add a theme field + dismissal

```python
class RecurringGap(BaseModel):
    requirement: str = ""
    theme: str = ""              # new — e.g. "MLOps tooling", "Observability"
    times_required: int = 0
    times_gapped: int = 0
    priority: str = ""
    reasoning: str = ""

class PromotableExperience(BaseModel):
    requirement: str = ""
    canonical_id: str = ""       # new — needed so dismiss can target the right catalog entry
    theme: str = ""              # new
    confirmed_in_applications: int = 0
    suggested_action: str = ""
    dismissed: bool = False      # new
```

Add a `dismissed_suggestions: set[str]` (canonical_ids) tracked on
`CatalogEntry` in `schemas.py`, checked when building the report:

```python
class CatalogEntry(BaseModel):
    ...
    promote_suggestion_dismissed: bool = False  # new
```

### Endpoint (`main.py`)

```python
@app.post("/catalog/{canonical_id}/dismiss-suggestion")
def dismiss_promote_suggestion(canonical_id: str) -> dict:
    entry = store.get_catalog_entry(canonical_id)
    if entry is None:
        raise HTTPException(404, "Not found")
    entry.promote_suggestion_dismissed = True
    store.save_catalog_entry(entry)
    return {"dismissed": canonical_id}
```

Filter dismissed entries out of `aggregate_market_fit`'s
`confirmed_not_promoted_counts` (`archive.py`) before they ever reach the
Gemini synthesis call — dismissal should make an item disappear from the
report entirely, not just visually hide it client-side.

### Rewrite `_MARKET_FIT_SYSTEM_PROMPT` (`gemini_calls.py`)

```python
_MARKET_FIT_SYSTEM_PROMPT = """You are a career advisor giving a Senior Cloud/DevOps/
SRE/MLOps engineer a genuinely useful read on their job-market position — not a status
report generator. Work from PRE-COMPUTED aggregation data; do not re-derive counts.

CRITICAL — group before you write:
- Cluster related requirements into THEMES before producing output (e.g. "ML
  orchestration frameworks," "feature stores," and "ML lifecycle tooling" are
  one theme: "MLOps tooling"; "Datadog for observability" alongside
  Prometheus/Grafana gaps would be one theme: "Observability tooling").
  Each theme should read as one coherent insight, not a pile of near-duplicate
  bullets. Assign every item a `theme` field.
- Vary your sentence structure. Do not reuse the same phrasing pattern across
  items — write the way a sharp colleague would talk through this over coffee,
  not the way a compliance report reads. Each item should sound like a
  distinct observation, not a mail-merged template.
- Be direct and specific, not padded. If something is a one-off, say so
  plainly instead of dressing it up with a full sentence of hedging.

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
```

### Frontend redesign (`pages.tsx`, `CareerGrowthPage`)

Replace the flat item lists with theme-grouped sections, a plain-language
summary header, and a dismiss control:

```tsx
// Group by theme before rendering
const gapsByTheme = groupBy(report.top_recurring_gaps, (g) => g.theme || "Other");
const promotableByTheme = groupBy(
  report.promotable_experience_not_yet_in_base_resume.filter((p) => !p.dismissed),
  (p) => p.theme || "Other"
);
```

```tsx
<section>
  <h2>The short version</h2>
  <p className="muted">
    {Object.keys(gapsByTheme).length} theme{Object.keys(gapsByTheme).length === 1 ? "" : "s"} worth
    your attention, {Object.keys(promotableByTheme).length} thing{"s"} already confirmed that
    your resume doesn't mention yet.
  </p>
</section>

<section>
  <h2>Top recurring gaps</h2>
  {Object.entries(gapsByTheme).map(([theme, items]) => (
    <div key={theme} className="card">
      <h3>{theme}</h3>
      {items.map((g) => (
        <p key={g.requirement}>
          <strong>{g.requirement}</strong>{" "}
          <span className={`pill ${g.priority === "high" ? "no_experience" : "partial_experience"}`}>
            {g.priority}
          </span>
          <br />
          <span className="muted">{g.reasoning}</span>
        </p>
      ))}
    </div>
  ))}
</section>

<section>
  <h2>Confirmed but not in your base resume</h2>
  {Object.entries(promotableByTheme).map(([theme, items]) => (
    <div key={theme} className="card">
      <h3>{theme}</h3>
      {items.map((p) => (
        <div key={p.requirement} className="bullet-row">
          <div>
            <strong>{p.requirement}</strong>
            <br />
            <span className="muted">{p.suggested_action}</span>
          </div>
          <button
            className="danger-ghost"
            onClick={() => dismissSuggestion(p.canonical_id)}
          >
            Not accurate — dismiss
          </button>
        </div>
      ))}
    </div>
  ))}
</section>
```

Cap each theme's visible items at ~3 with a "show N more" toggle if it grows
past that — the point of grouping is that the page should feel like a small,
readable set of themes even after fifty applications, not a list that scales
linearly with your application count forever.