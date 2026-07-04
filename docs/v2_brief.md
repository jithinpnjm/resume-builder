# Resume Tailoring Agent v2 — Implementation Brief (authoritative copy)

Pasted by Jithin 2026-07-03 (third revision). Supersedes v1. Key points preserved
verbatim below where they drive implementation; see git history of this file for edits.

## Core principle
The LLM never gets the final word on what the candidate knows. Three-phase workflow:
ANALYZE → REVIEW & CONFIRM (human-in-the-loop) → FINALIZE. Nothing rendered until
phase 2 complete and a diff is explicitly approved.

## Schemas (implemented in backend/app/schemas.py)
- ResumeJSON bullets get `core: bool` — core bullets can be reordered lower but never
  removed/hidden. Auto-tagged once via Gemini (human-reviewed), manual toggle in UI.
- TailoringPlan v2: reorder + terminology alignment ONLY. Fields: tailored_summary,
  experience_order, bullet_order {exp_id: [bullet_ids]}, skills_displayed,
  skills_deprioritized (hidden per-application, never deleted), bullet_plan
  [{bullet_id, final_text, keywords_injected, injection_type: renamed_existing|none}].
- GapItem: requirement, jd_context (exact JD line), education {what_it_is,
  typical_use_case_for_role, sample_scenario, closest_known_alternative (MUST name
  candidate's actual tools), other_alternatives_in_market}, user_response {status:
  have_experience|partial_experience|no_experience|not_reviewed, user_note, reviewed_at},
  proposed_bullet, proposed_target_exp_id.
  HARD RULE: no resume content derived from a gap unless status is have/partial AND
  user_note non-empty.
- StudyPlan per no_experience gap: priority, study_topics, hands_on_labs
  (bias toward exercising existing skills on new tech), interview_talking_points, resources.
- ApplicationRecord: id, company, role_title, status (analyzing|pending_review|approved|
  finalized|archived), created_at, jd_analysis, tailoring_plan, gaps[], study_plans[],
  diff_summary {added,removed,reordered,reworded}, cover_letter, approved_at, gcs_path.
- ResumeVersion: version, created_at, change_reason, resume_json_snapshot. Snapshot on
  every base-resume change.

## Workflow state machine
1. ANALYZING: Call 1 JD Analyzer → Call 2 tailoring (reorder+terminology, existing skills
   only) → deterministic gap detection → Call 3 Gap Educator per gap → pending_review.
2. PENDING_REVIEW: per gap show education + "Have you done anything like this?
   [Yes, describe][Partial][No]". have/partial + note → Confirmed-gap insertion call drafts
   ONE bullet from user's own words only (no invented metrics), shown as proposed diff,
   user-editable, never auto-applied. no_experience → StudyPlan (Call 5). Full diff shown.
   User clicks Approve → approved.
3. APPROVED→FINALIZED: docxtpl render; cover letter (Call 4) from approved content only —
   confirmed gaps referenced honestly, unconfirmed never; fabrication checks as last-mile
   safety net (re-run specifically against cover letter — that's where leaks happened).
4. FINALIZED→ARCHIVED: upload resume.docx/pdf, cover_letter.txt, jd_analysis.json,
   gap_report.json, study_plan.md, report.html (Jinja2 server-side, self-contained,
   inline SVG donut for coverage), metadata.json to
   gs://{bucket}/{company_slug}/{role_slug}/. On re-application, offer reuse of prior
   gap_report.

## Resume input
POST /onboarding/load-resume. APP_MODE=local → JSON {local_path}, read from disk.
APP_MODE=cloud → multipart upload. Diff against stored ResumeJSON; flag changes; user
confirms merge (never silently overwrite).

## CV improvement loop
On FINALIZE, for each have/partial gap: prompt "Add to base resume? [Add][This-application-
only][Not yet]". Add → append drafted bullet to experience entry, new ResumeVersion,
core=false. Not-yet → treated as partial in future detection.

## Market fit / longitudinal analysis
GET /analysis/market-fit?since=... Deterministic aggregation (requirement_counts,
requirement_gap_counts, match_rate_by_date) + ONE Gemini call to synthesize into
MarketFitReport {period, match_rate_trend, top_recurring_gaps, 
promotable_experience_not_yet_in_base_resume, resume_structural_suggestions,
study_plan_priority_ranked}. Career Growth dashboard page: SVG trend chart, recurring
gaps, one-click promote.

## Cross-application requirements catalog (NEW in rev 3)
requirements_catalog/{canonical_id}: canonical_name, aliases, category, demand_count,
demand_sources[{company,role,date}], user_status, status_history (user's words carried
verbatim), in_base_resume, priority_score.
Canonicalization Gemini call resolves new requirement strings against catalog
(matched_canonical_id|null, confidence). High-confidence + have/partial on file → skip
education, offer one-click reuse ("You confirmed MongoDB for SWARCO on {date}: '{note}'.
Reuse?"). High-confidence + no_experience → skip re-education, increment demand_count,
feed top_recurring_gaps. priority_score = demand_weight(min(count/10,1)) ×
recency_weight(1/.6/.3 by <30/<90/else days) × gap_weight(1/.3/0 by no/partial/have).
Backfill catalog + BQ from already-archived applications when first built.

## Real study guide (NEW in rev 3)
study_guide/{canonical_id}: priority_score, why_it_matters, concepts_to_study
[{concept,depth}], hands_on_labs [{title,why_this_lab (reference existing skills),
repo_url,est_hours}], sample_projects, resources [{type,title,url,source}],
last_curated_at, url_validation_status.
Resources via Gemini SEARCH GROUNDING (not memory) + deterministic httpx HEAD link-check
before storing; drop/flag dead links; re-curate every 60 days for no_experience or on
priority threshold. Personalization v1: settings page where user pastes Medium/LinkedIn
profile URLs + newsletters (TLDR DevOps etc.); curation prompt prefers those sources.
v2 only if needed: Medium RSS per tag (medium.com/feed/tag/{topic}), no auth.
Study Guide page ordered by priority_score, expandable, "mark concept studied" checkbox
moves no_experience→partial_experience and triggers promotion flow.

## Storage architecture
- Firestore: live state (ApplicationRecord, ResumeJSON+versions, requirements_catalog,
  study_guide).
- BigQuery dataset resume_agent_analytics: requirement_events (application_id, company,
  role_title, requirement, canonical_id, category, must_have, user_status-at-finalize,
  matched, event_date), application_snapshots (…match_pct, must_have_count, matched_count,
  resume_version), resume_versions (version, created_at, change_reason, skills_flat,
  core_bullet_count, total_bullet_count). Write ONLY on FINALIZE/ARCHIVE via
  insert_rows_json. market-fit becomes SQL GROUP BY.
- GCS: blobs only (docx/pdf/txt/html + raw JSON exports).

## Terraform
Append to existing infra (match conventions): Cloud Run service resume-agent, GCS bucket
${project}-resume-agent-archive (uniform access, no lifecycle), BQ dataset + 3 tables,
SA roles: datastore.user, bigquery.dataEditor, bigquery.jobUser, storage.objectAdmin.
Reuse existing GEMINI_API_KEY secret.

## Dashboard (frontend shell)
Sidebar (apps grouped by status) · Search (flattened study_topics index) · Study Guide
page (replaces flat Study Library) · New Application flow · Career Growth page.

## Build order (rev 3)
1. Terraform first (bucket, BQ, Cloud Run). 2. core flag+UI. 3. load-resume dual-mode.
4. Gap detection+educator+review UI (SIGN-OFF GATE after this). 5. Confirmed-gap
insertion. 6. Diff view+Approve gate. 7. StudyPlan call. 8. GCS+report.html.
9. Dashboard shell. 10. Cover letter gated+fab check. 11. ResumeVersion+promotion.
12. BQ write path+market-fit SQL+Career Growth. 13. requirements_catalog+canonicalization
+backfill. 14. study_guide search-grounded+URL validation+sources settings. 15. Study
Guide page+mark-as-studied loop.
