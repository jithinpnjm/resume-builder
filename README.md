# Resume Tailoring Agent

Personal tool that tailors a resume to a specific job description **without letting an
LLM invent, drop, or reformat anything** — and turns every application into compounding
knowledge about skill gaps and market fit.

Full design spec: [docs/v2_brief.md](docs/v2_brief.md).

## Core principles

1. **Layout is sacred.** The visual design lives in a docx template
   (`backend/app/templates/resume_template.docx`) built once from the real resume.
   Gemini only ever produces structured JSON; a deterministic renderer (docxtpl) fills
   the template. Same template in, same layout out, every time.
2. **The LLM never gets the final word on what you know.** Anything not already in your
   resume triggers an interactive gap review — the app asks *you*, educates you on the
   missing tech (scoped to how a senior SRE/DevOps engineer would actually operate it),
   and only your own written words can become new resume content.
3. **Nothing renders until you approve a diff.** Three-phase workflow:
   `ANALYZE → REVIEW & CONFIRM (human-in-the-loop) → FINALIZE`.

## Architecture

```
React/TS SPA (frontend/) ──► FastAPI (backend/) ──► Gemini API (2.5-flash, free tier)
                                   │
                                   ├─ docxtpl + LibreOffice headless → .docx / .pdf
                                   └─ local_state/ JSON (dev) · Firestore/GCS/BigQuery (planned)
```

- **Gemini calls** (all JSON-mode, schema-validated): JD analyzer · tailoring plan
  (reorder + terminology alignment only) · gap educator · confirmed-gap bullet drafting ·
  study plans · cover letter · fabrication/metric-loss checks.
- **Deterministic code** (no LLM): gap detection, diff summary, rendering, ATS keyword
  coverage, market-fit aggregation.

## Repo layout

```
backend/
  app/
    main.py          # API + workflow state machine (analyzing → pending_review → approved → …)
    schemas.py       # Pydantic contracts: ResumeJSON, TailoringPlan, GapItem, ApplicationRecord…
    gemini_calls.py  # every Gemini prompt, one place
    gaps.py          # deterministic JD-vs-resume gap detection
    renderer.py      # docxtpl render + LibreOffice PDF (layout fidelity)
    parser.py        # PDF/DOCX → ResumeJSON extraction
    store.py         # persistence (local JSON now, Firestore planned)
    templates/       # the one-and-only docx layout template
  scripts/build_template.py   # one-time template builder from the original resume
  fixtures/          # base ResumeJSON
frontend/            # Vite + React/TS: onboarding, gap review cards, approve/export
infra/               # deploy.sh + terraform for Cloud Run (GCP, scale-to-zero)
docs/v2_brief.md     # authoritative implementation spec
```

## Running locally

```bash
# backend  (needs backend/.env with GEMINI_API_KEY=…)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8000 --reload      # APP_MODE=local by default

# frontend
cd frontend
npm install && npm run dev                               # http://localhost:5173
```

PDF export needs LibreOffice (`brew install --cask libreoffice` locally; baked into the
Docker image for Cloud Run).

## Workflow (what you actually do)

1. **Onboard once**: load your resume (file path locally, upload in cloud), review the
   extracted JSON, optionally auto-tag *core* bullets (never removable by tailoring), save.
2. **New application**: paste company + JD → the app analyzes requirements, drafts a
   reorder-only tailoring plan, detects gaps, and writes a 90-second briefing per gap.
3. **Gap review**: for each gap — *"Have you done anything like this?"* Yes/Partial answers
   require your own description; a resume bullet is drafted from your words only, shown as
   an editable proposal. "No" queues a study plan.
4. **Approve** the full diff → export `.docx`/`.pdf`, generate a cover letter (checked
   against approved facts), see ATS keyword coverage.

## Deployment

```bash
cp infra/deploy.env.example infra/deploy.env   # set PROJECT_ID etc.
./infra/deploy.sh                              # Cloud Build → Cloud Run (scale-to-zero)
# then set the real key:
gcloud secrets versions add GEMINI_API_KEY --data-file=- <<< "$GEMINI_API_KEY"
```

The image serves the built frontend and the API from one URL. `APP_MODE=cloud` switches
resume input to file upload.

## Status

Steps 1–5 of the v2 build order are implemented and verified against real job postings
(KNIME, SWARCO). Pending: GCS archiving + report.html, dashboard shell, promotion flow
(confirmed gaps → permanent resume), BigQuery market-fit analytics, cross-application
requirements catalog, and the search-grounded Study Guide. See `docs/v2_brief.md`
build order + the session memory for exact next steps.
