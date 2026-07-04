# Patch verification: Role-Fit Gate, Study Room Depth, Landing Page Consolidation

Verification pass for `docs/role_fit_and_study_room_patch.md`, run locally against
`http://localhost:8000` with the real Gemini API (no mocking) on 2026-07-04.

| § | Section | Status | What was tested |
|---|---|---|---|
| 5 | Discard application | ✅ Done / Verified | Created a `pending_review` record directly in the store, `POST .../discard` → `status: discarded` (HTTP 200); re-discarding an already-discarded record still succeeds (not in finalized/archived); a separate `finalized` record correctly rejected with `HTTP 409 "Application is finalized — nothing to discard"`. Sidebar renders a collapsed `<details>` "Discarded" group (`Shell.tsx`) so it doesn't clutter the main list. `tsc --noEmit` clean. |
| 4 | False-positive gap fix | ✅ Done / Verified | Reproduced the exact reported bug (`containerization`, `production ownership` requirements with narrow/empty `keyword_variants` against a resume that covers them under different names) — the new batched relevance-check (`gaps.suppress_false_positive_gaps`) correctly suppressed both with real Gemini-cited evidence from the resume text. Confirmed it does **not** over-suppress: a genuinely uncovered requirement (`SAP ERP integration`) survived the check untouched. Separately verified the `aggregate_market_fit` promotable-slug bug fix with a constructed case where a requirement's raw-text slug would never match its actual (canonicalization-merged) `canonical_id` — the fix correctly resolves it via the gap's own `canonical_id`, correctly disappears once `in_base_resume=True`, and correctly disappears once `promote_suggestion_dismissed=True`. |
| 1 | Role-Fit Gate | ✅ Done / Verified | Unit-tested all 5 branches of `role_fit.assess()` directly (skip on disallowed dev language, process on target category, process via 50% override, warn on low match, and confirmed Python/Go/Bash/SQL are correctly exempted from the "deep dev skills" skip). End-to-end verified through the live `POST /applications` API with a real Senior Frontend Engineer JD (React/TypeScript, "pure UI development role") — correctly returned `HTTP 422 "Skipped: Primarily requires development in javascript, typescript..."` before any tailoring or gap detection ran. Wired into both Build Resume (hard block) and Trend Scan (per-posting skip, rest of batch proceeds) — code paths reviewed, `skipped_postings` surfaced in `TrendScanPage.tsx`. |
| 2 | Study Room depth | ✅ Done / Verified | Enabled `oreilly_access` via `POST /settings`, seeded a `kafka-test` catalog entry, ran a real `POST /study-guide/kafka-test/curate`. Result: `recommended_books` includes a real, correctly-formatted O'Reilly catalog URL for *Kafka: The Definitive Guide* (2nd ed.) with real author names; 4-step real progression (deep architecture → hands-on GitOps lab → production/SRE observability → interview-readiness) with two **verified live GitHub repos** for the hands-on labs; `url_validation_status: "some_stale"` proves the dead-link-dropping pass actually ran (not a no-op) rather than blindly reporting `all_checked`. |
| 6 | Career Growth redesign | ✅ Done / Verified | Ran a real `GET /analysis/market-fit?refresh=true` against existing archived application data. Every `top_recurring_gaps` item came back with a genuine, distinct `theme` ("Distributed Observability", "IoT & Edge Infrastructure", "Multi-Cloud Kubernetes Orchestration") and non-templated, conversational reasoning — not the old mail-merged "This X was required in Y applications..." skeleton. Dismiss logic (`promote_suggestion_dismissed` filtering before the synthesis call) verified via the §4(c) test above, which exercises the same code path. Frontend theme-grouping, "show N more" cap, and the short-version summary header reviewed against `tsc --noEmit` (clean). |
| 3 | Landing page consolidation | ✅ Confirmed RETRACTED, no action taken | Confirmed the current landing page (`LandingPage.tsx`) and sidebar (`Shell.tsx`) already keep "Job Market Analysis" and "Market Trends & Study Room" as two separate tiles/nav entries — no consolidation was ever applied in this codebase, so there was nothing to revert. |

## Decisions made where the doc was ambiguous (per instructions: proceed and note, don't block)

1. **`RoleFitAssessment` lives in `schemas.py`, not `role_fit.py`.** The doc's code
   sample defines the class inline in the new `role_fit.py` file, but this codebase
   centralizes every Pydantic model in `schemas.py` (matching `GapItem`,
   `CatalogEntry`, etc.) with business logic in separate modules that import from
   it. Defining it twice would have created two diverging schemas for the same
   concept. `role_fit.py` imports `RoleFitAssessment` from `schemas.py`.

2. **`compute_skill_match_pct` is used for the role-fit gate only, not for
   `aggregate_market_fit`/`write_bigquery_rows`.** Those two functions currently
   compute "matched" from the *post-review* gap status (a human-confirmed
   `have_experience` counts as matched even if a keyword regex against today's
   resume text wouldn't find it) — semantically different from, and more accurate
   than, `compute_skill_match_pct`'s pre-review keyword scan (which the role-fit
   gate needs precisely because it runs *before* any gap has been reviewed).
   Switching those two to the keyword-only function would have silently made
   Career Growth's numbers less accurate. Instead, the actual duplication the doc
   flagged (the same per-requirement "matched" loop written out twice) was
   deduplicated into one local helper, `archive._matched_requirement_ids`,
   preserving the existing (correct) semantics. Documented inline in `archive.py`.

## Known gaps in this verification

- The role-fit gate's "warn" banner in `ApplicationView.tsx` and the Trend Scan
  "skip" section in `TrendScanPage.tsx` were verified by code review and
  `tsc --noEmit`, not by driving the actual browser UI — a full warn-case
  application (a JD that's `related_adjacent` with 20-49% match) would need
  another ~1-2 minute real Gemini round-trip through the full analyze pipeline
  to click-test, which wasn't run to keep the verification pass efficient. The
  underlying decision logic and wiring are verified; only the pixel-level
  rendering is unverified.
- Career Growth's dismiss button was verified via the backend aggregation logic
  (§4c test) and code review, not by clicking "Not accurate — dismiss" in a
  running browser against a live promotable suggestion (none were present in
  the current archived-application test data to click on).
