# Resume Tailoring Agent — Consolidated Build Prompt (v3, FINAL, revision 2)

> Revision 2 (2026-07-04) adds: §0a three entry points (Build Resume / Job Market
> Analysis / Market Trends & Study Room), §3a Trend Scan workflow with
> source_type tagging ("application" | "trend_scan") and its DoD, Study Guide
> recommended_books + depth DoD + full curator prompt, landing-page design,
> BQ requirement_events.source_type column, revised build order (trend scan =
> step 7, second sign-off after step 7: verify Button 3 data never leaks into
> Button 2's numbers). Prior revision kept at docs/v3_brief_r1_superseded.md.

## 0a. Three entry points on the landing page — do not conflate these

1. **Build Resume** — full tailoring workflow for a specific company/role.
   Resume + cover letter, archived per company/role. All writes tagged
   source_type="application".
2. **Job Market Analysis** — READ-ONLY dashboard: performance against jobs
   ACTUALLY applied to. Queries application_snapshots + requirement_events
   WHERE source_type='application' ONLY — the filter must literally exist in
   the query, verified, not just documented.
3. **Market Trends & Study Room** — bulk JD intake, no tailoring, no
   ApplicationRecord, no cover letter, no GCS company folder. Feeds the shared
   requirements_catalog and builds/deepens the Study Guide library. All writes
   tagged source_type="trend_scan". The catalog and Study Guide deliberately
   blend both sources; only Button 2 filters.

## 3a. Trend Scan workflow (Button 3)

POST /trend-scan { postings: [JD text, ...] } — one or many.
Per posting: Call 1 JD Analyzer → per requirement Call 2b canonicalize:
- matched + already confirmed → increment demand_count, append demand_sources
  with source_type="trend_scan", NO user interaction;
- matched-but-not_reviewed or new → surfaces in ONE consolidated batch review
  across all postings (not per-posting): Gap Educator content + Yes/Partial/No,
  same component as Button 1's gap review but with NO resume-bullet drafting —
  a trend scan never writes to ResumeJSON. Answers update catalog user_status +
  note (pre-answering future Button 1 detections) but never retroactively edit
  finalized resumes.
On completing batch review: BQ requirement_events rows with
source_type="trend_scan", catalog updates, recompute priority_score for touched
entries, trigger Study Guide regeneration for entries whose score changed
materially or that lack a guide.

**Trend Scan DoD:**
- [ ] 5 pasted JDs → ONE batch review, not 5.
- [ ] A requirement confirmed via Button 1 does not re-prompt — silently
      increments demand_count.
- [ ] Nothing from this flow appears in Button 2's queries (verify the WHERE
      source_type='application' literally exists).
- [ ] Completing a scan visibly refreshes/creates Study Guide entries without
      a page reload.

## 6 (rev 2). Study Guide depth additions
- New field recommended_books: at least one genuinely authoritative book with
  authors + why it's right for this role level.
- Curator prompt (Call 5) demands: real progression (concepts → hands-on lab
  reusing skills_master → operate-like-production → interview-ready), each step
  a concrete checkable goal; hands_on_lab.repo_url = real, currently-maintained
  GitHub repo found via search, verified; official docs for foundations, deeper
  material for operational nuance; honest interview_talking_points (lab-level
  unless status_history shows production experience).
**Study Guide depth DoD (spot-check a sample):**
- [ ] ≥1 recommended_books entry with real title+author.
- [ ] ≥1 hands_on_lab with verified live repo URL.
- [ ] Steps form an actual progression, not four restatements.
- [ ] Every resource URL passed validate_urls.

## §8 addition — Landing page
Three cards, one per entry point, each with a live number once history exists
(applications in progress / trend gaps found this week / study steps completed)
— persistence made visible, not decoration.

## §9/§10 revision
requirement_events gains source_type STRING. application_snapshots written only
from Button 1 ARCHIVE. Button 2 queries filter source_type='application';
Button 3 aggregate demand does not filter.

## Build order (rev 2)
1 persistence (sign-off) · 2 segments · 3 terraform (+source_type col) ·
4 landing page 3 cards + design system · 5 catalog (source_type="application")
· 6 Study Guide v2 (books+depth) · 7 Trend Scan (§3a; SECOND SIGN-OFF: prove
Button 3 never leaks into Button 2) · 8 settings+Medium RSS · 9 BQ ARCHIVE path
+ Button 2 SQL · 10 cover-letter dedicated check.

---

# Original v3 text (revision 1) follows

**Read this entire document before writing or modifying any code.** This
supersedes every previous draft of this prompt. If anything already built
contradicts what's written here, this document wins — don't try to reconcile
old and new logic, replace it. Where a section says "Definition of Done," that
is a literal checklist to verify against before considering the step finished,
not a description to skim.

---

## 0. What this app is

A personal tool that, given a job description, tailors your resume and cover
letter without ever inventing experience you don't have — and, critically,
**everything it produces is saved permanently** so you can review, revisit,
and build on it over time. Target roles: Senior Cloud Engineer, DevOps, SRE,
MLOps, AI Infrastructure, LLMOps.

Stack: React/TypeScript (Vite) frontend, Python/FastAPI backend, Firestore
(live state), BigQuery (analytics), GCS (documents), Gemini API (free tier),
deployed on Cloud Run in your existing GCP project, infra managed via your
existing Terraform repo.

---

## 1. Non-negotiable core principles

1. **The LLM never decides what experience you have.** It proposes; you
   confirm; only then does content enter your resume.
2. **Content is never silently lost.** Reordering and rewording are allowed;
   deletion of substance is not, ever, without your explicit action.
3. **Layout/formatting is never regenerated by an LLM.** A docx template
   built once from your real resume renders every version. Gemini only ever
   produces structured JSON, never a formatted document.
4. **Nothing is ephemeral.** Every application you tailor, every gap you
   review, every study plan generated — all of it persists in Firestore/GCS/
   BigQuery and must be retrievable in the UI after closing and reopening the
   app. This has been the actual failure so far — treat it as the top
   priority, not something that "should already be happening."

---

## 2. Data model

### `ResumeJSON` — your base resume, source of truth

Segments, not flat strings — mandatory. Original resume bolds phrases inline;
flat-string rendering collapses it (already happened once). Onboarding
extracts segments deterministically from docx runs:

```python
from docx import Document
def extract_segments(paragraph):
    return [{"text": run.text, "bold": bool(run.bold)} for run in paragraph.runs if run.text]
```

- `summary_segments: [{text, bold}]`, bullets carry `segments: [{text, bold}]`,
  plus `core: bool`, `tags`.
- Unmodified/reordered-only bullets: original segments carried forward untouched.
- Reworded/new bullets: segments regenerated by a deterministic rule — bold every
  number/metric match, bold at most 1-2 newly-injected keywords, cap ~3 bold spans
  total (match the original's restraint).
- `core: true` = baseline senior competency (incident response, IaC, CI/CD
  ownership, cost optimization, security compliance). Core bullets can be
  reordered but never removed or hidden.

### `ResumeVersion` — snapshot on every base-resume change
`{version, created_at, change_reason, resume_json_snapshot}`

### `JDAnalysis` — Call 1 output
`{role_title, seniority_signal, must_have_requirements[{requirement,category}],
nice_to_have_requirements, ats_keywords (exact literal strings), company_context}`

### `TailoringPlan` — Call 2 output. Reorder + terminology-align only.
`{experience_order, bullet_order{exp_id:[ids]}, skills_displayed,
skills_deprioritized, bullet_plan[{bullet_id, final_segments, keywords_injected,
injection_type: renamed_existing|none}]}`

**Hard rule enforced in code, not just the prompt:** every bullet id from every
experience entry must appear in `bullet_plan`. If any is missing, or if any
bullet's flattened `final_segments` text is missing a number/metric that appeared
in the original, reject the response and retry once, then fall back to
`final_segments = original segments` for that bullet. Never render a resume where
this check hasn't passed.

### `GapItem`
`{requirement, jd_context, education{what_it_is, typical_use_case_for_role,
sample_scenario, closest_known_alternative, other_alternatives_in_market},
user_response{status: have|partial|no|not_reviewed, user_note, reviewed_at}}`

**No addition to any resume without a non-empty user_note from
have_experience/partial_experience.**

### `requirements_catalog/{canonical_id}` — cross-application memory
`{canonical_id, canonical_name, aliases, category, demand_count,
demand_sources[{company,role,date}], user_status, status_history[{date,status,
source_application_id,note}], in_base_resume, priority_score}`

Before creating any new GapItem, canonicalize against this catalog first
(Call 2b). If matched with confirmed status on file, don't re-ask — offer
one-click reuse of the stored note.

```python
def priority_score(entry, days_since_last_seen):
    demand_weight = min(entry["demand_count"] / 10, 1.0)
    recency_weight = 1.0 if days_since_last_seen < 30 else 0.6 if days_since_last_seen < 90 else 0.3
    gap_weight = 1.0 if entry["user_status"] == "no_experience" else 0.3 if entry["user_status"] == "partial_experience" else 0.0
    return round(demand_weight * recency_weight * gap_weight, 3)
```

### `StudyGuide/{canonical_id}` — real, sequenced curriculum (§6)

### `ApplicationRecord`
`{id, company, role_title, status: analyzing|pending_review|approved|finalized|
archived, jd_analysis, tailoring_plan, gaps, diff_summary{added,removed,
reordered,reworded}, approved_at, gcs_path}`

---

## 3. Workflow (state machine — do not let the UI skip states)

```
ANALYZING
  → Call 1 (JD Analyzer) → jd_analysis
  → Call 2 (Reorder + terminology align) → tailoring_plan (draft)
  → Gap detection: check requirements_catalog first, canonicalize new ones,
    run Gap Educator (Call 3) only for genuinely new/unconfirmed gaps
  → PERSIST ApplicationRecord to Firestore with status=pending_review —
    immediately, not after review. Crash/tab-close must not lose analysis.

PENDING_REVIEW (interactive)
  → Each gap: education + Yes/Partial/No — every answer written to Firestore
    immediately on click, not batched
  → Confirmed gaps → confirmed-gap insertion (bullet from user's own words
    only) → proposed diff line
  → No-experience gaps → StudyGuide generated/linked (Call 5)
  → Full diff_summary (before/after per item) → user clicks Approve

APPROVED → FINALIZED
  → docxtpl + RichText renders final resume
  → Cover letter (Call 4) — strict format (§4)
  → Fabrication check re-run specifically against the cover letter output
    (its own check, not reuse of the bullet-level one)

FINALIZED → ARCHIVED
  → Upload to gs://{bucket}/{company_slug}/{role_slug}/: resume.docx,
    resume.pdf, cover_letter.txt, jd_analysis.json, gap_report.json,
    study_guide_snapshot.json, report.html
  → BigQuery rows: requirement_events, application_snapshots,
    (resume_versions if a promotion happened)
  → Update requirements_catalog demand_count/sources for every requirement seen
```

---

## 4. Gemini prompts

**Call 1 — JD Analyzer:** extract ALL requirements, ats_keywords exact literal
strings, must-have vs nice-to-have from language cues.

**Call 2 — Tailoring Plan:** may reorder + inject exact JD term ONLY if the
skill already exists in skills_master. May NOT shorten/remove bullets, drop
metrics, or add claims. final_segments text length >= original length.

**Call 2b — Canonicalization:** does new requirement match a catalog entry?
`{matched_canonical_id|null, confidence: high|medium|low}`.

**Call 3 — Gap Educator:** senior-peer explanation, role-scoped operationally,
closest_known_alternative MUST name a specific skills_master tool, 90-second read.

**Call 4 — Cover Letter (strict):** Subject line, greeting, exactly 3 body
paragraphs, sign-off. Body 180-250 words. Max 2 quantified metrics in the
ENTIRE letter (most JD-relevant). P1: role + one-line positioning, no stats.
P2: 1-2 proof points tied to the JD's actual stated problem. P3: name 1-2
genuine gaps honestly, bridge to adjacent real experience, end with one
sentence of specific motivation using company_context — never "I'm excited to
apply." Never restate more than 3 tools by name. ONLY facts from
ResumeJSON/TailoringPlan/confirmed gaps.

**Call 5 — Study Guide Curator:** §6, search grounding, not memory recall.

---

## 5. Persistence — Definition of Done (verify every item)

- [ ] Every ApplicationRecord write happens the moment its data exists —
      after JD analysis, after each gap answer, after approval, after
      finalize. Not batched, not save-on-exit.
- [ ] Closing the tab mid-review and reopening restores the exact
      pending_review state — same gaps, same answers, nothing lost.
- [ ] The sidebar (§8) lists every application ever created, grouped by
      status, on every page load — the actual proof persistence works.
- [ ] Every finalized application's resume.docx/pdf, cover_letter.txt,
      report.html fetchable from GCS via signed URL or backend proxy,
      indefinitely — test by finalizing, restarting the backend, re-fetching.
- [ ] requirements_catalog and StudyGuide entries survive across unrelated
      sessions — finish one application, start a second, shared requirement
      shows accumulated demand_count from both.
- [ ] BigQuery rows exist after ARCHIVE — verify with actual SELECT *.

If any of these fail, that's a P0 bug, not a follow-up item.

---

## 6. Study Guide — real, sequenced, linked

Replace flat topic lists with an actual curriculum, ordered by priority_score,
one entry per requirements_catalog item:

```json
{
  "canonical_id": "kafka", "priority_score": 0.85,
  "why_it_matters": "required in 5 of your last 12 target-role postings, most recently {company} on {date}",
  "steps": [
    { "step_number": 1, "title": "Understand the core model",
      "goal": "explain topics/partitions/consumer groups without notes",
      "concepts": ["topics & partitions", "producers/consumers", "consumer groups & offsets"],
      "resources": [{ "type": "docs", "title": "…", "url": "", "source": "official" }],
      "est_hours": 2, "done": false },
    { "step_number": 2, "title": "Hands-on: run a cluster",
      "goal": "working 3-broker cluster you can break and fix",
      "hands_on_lab": { "title": "Deploy 3-broker Kafka on GKE with Strimzi", "repo_url": "",
        "why_this_lab": "reuses your GKE/K8s operator experience", "est_hours": 4 },
      "done": false },
    { "step_number": 3, "title": "Operate it like production",
      "goal": "simulate broker failure and recover; what an SRE watches",
      "concepts": ["replication factor & ISR", "consumer lag monitoring"],
      "resources": [{ "type": "blog", "url": "", "source": "medium" }],
      "sample_project": { "title": "", "repo_url": "", "description": "" },
      "est_hours": 3, "done": false },
    { "step_number": 4, "title": "Interview-ready",
      "goal": "60-second honest answer grounded in labs 1-3",
      "interview_talking_points": ["…"], "done": false }
  ],
  "last_curated_at": "", "url_validation_status": "all_checked|some_stale"
}
```

- Every url validated before storage (httpx HEAD, follow_redirects, drop dead
  links — don't ship them). Search grounding for finding them, never memory.
- Re-curate + re-validate when priority_score crosses threshold or every 60
  days for anything still no_experience.
- hands_on_lab.repo_url must be a real, findable GitHub repo (search, verify
  exists + recent activity).
- "Mark step done" flips done:true; all steps done → prompts promotion flow
  (§2 ResumeVersion), moving the requirement from no_experience toward
  honestly claimable.

---

## 7. Content-source linking (LinkedIn / Medium / TLDR / Udemy)

Cheap version first, upgrade only if insufficient:

**Settings page (new):**
- Paste LinkedIn profile URL and Medium profile URL (plain text, no OAuth).
- Checkboxes/tags for newsletters read (TLDR DevOps, TLDR AI, …) — metadata
  that flavors search queries, not a live integration.

**Feeding the Study Guide curator (Call 5):**
- Medium: poll `medium.com/feed/tag/{topic}` — public RSS, zero auth. Pull
  recent articles per topic, pass titles+links to the curator as candidate
  resources (still URL-validated before storage).
- LinkedIn/Udemy: no practical free personal API. Instruct search-grounded
  curation to prefer `linkedin.com/pulse` and `udemy.com` results by name,
  referencing stated newsletter preferences for tone. No scrapers, no
  disproportionate auth flows.
- Revisit with a proper connector only if this proves insufficient in real use.

---

## 8. UI / Visual design

### Concept: "the infra you already read all day"
Belongs next to Grafana/GitHub/ArgoCD, not a generic SaaS template.
- **Diff/approval screen styled exactly like a GitHub PR diff** (red
  strikethrough removed, green highlight added, "+12 −3" summary chip) — the
  correct mental model: reviewing a change before it merges into your resume.
- **Gap cards styled like alert/incident cards** (colored left border by
  severity, status pill: no_experience=red, partial=amber, have=green).

### Tokens
Color (dark surface, semantic status colors):
`--bg-canvas:#0D1117` `--bg-panel:#161B22` `--border-subtle:#30363D`
`--text-primary:#E6EDF3` `--text-muted:#8B949E` `--status-confirmed:#3FB950`
`--status-partial:#E8A33D` `--status-gap:#F85149` `--accent-primary:#58A6FF`

Type: IBM Plex Mono for display/headers/section labels/scores (restrained);
Inter for prose. Numeric data in tabular figures in the mono face.

Layout: fixed left sidebar ~240px (applications grouped In Review / Finalized
/ Archived, Study Guide, Career Growth, Settings — IDE-sidebar style). Main
panel: card grid for lists, single-column focused view for active workflow.
Top bar minimal: breadcrumb + search.

Signature element: the diff view. Everything else quiet and disciplined.

Motion: minimal/functional — brief highlight flash when a gap answer saves
(proof persistence happened), smooth expand/collapse for study steps. Nothing
decorative.

Accessibility floor (non-negotiable): visible keyboard focus states, color
never the only status signal (always pair with text label/icon), responsive
to tablet width.

### Design Definition of Done
- [ ] Diff screen reads as a PR review, not a before/after table.
- [ ] Every status has color AND text label.
- [ ] Sidebar reflects real persisted data.
- [ ] Two-face typography applied consistently, no system-font fallback left.

---

## 9. Storage architecture recap
Firestore: ApplicationRecord, ResumeJSON+versions, requirements_catalog,
StudyGuide. BigQuery (resume_agent_analytics): requirement_events,
application_snapshots, resume_versions — written only on ARCHIVE. GCS: blobs.

## 10. Terraform
Append to existing infra repo. New: Cloud Run service, GCS bucket, BQ dataset
+ 3 tables, SA with datastore.user, bigquery.dataEditor, bigquery.jobUser,
storage.objectAdmin. Reuse existing Gemini secret. Match existing conventions.

## 11. Build order
1. **Fix persistence first** — verify §5 DoD before any new feature. SIGN-OFF GATE.
2. Segment-based ResumeJSON + onboarding extraction + RichText render.
3. Terraform: GCS bucket, BQ dataset/tables, Cloud Run service.
4. UI design system (§8) applied to existing screens before adding new ones.
5. requirements_catalog + canonicalization wired into gap detection.
6. Study Guide v2 (§6): sequenced steps, search-grounded + validated resources.
7. Settings page + Medium RSS integration (§7).
8. BigQuery write path on ARCHIVE + Career Growth report as real SQL.
9. Cover letter fabrication check as its own pass.
