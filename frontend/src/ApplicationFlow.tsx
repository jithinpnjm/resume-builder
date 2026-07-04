import { useEffect, useState } from "react";
import * as api from "./api";
import GapCard from "./GapCard";
import type { ApplicationRecord, GapItem, StudyPlan } from "./types";

export default function ApplicationFlow() {
  const [company, setCompany] = useState("");
  const [jobDescription, setJobDescription] = useState("");
  const [companyContext, setCompanyContext] = useState("");
  const [record, setRecord] = useState<ApplicationRecord | null>(null);
  const [savedApplications, setSavedApplications] = useState<ApplicationRecord[]>([]);

  useEffect(() => {
    // Persistence proof (v3 §5): every application ever created must be
    // listed on every load, and clicking one restores its exact state.
    if (record === null) {
      api.listApplications().then(setSavedApplications).catch(() => {});
    }
  }, [record]);
  const [studyPlans, setStudyPlans] = useState<StudyPlan[]>([]);
  const [coverLetter, setCoverLetter] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run<T>(label: string, fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(label);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : `${label} failed`);
    } finally {
      setBusy(null);
    }
  }

  async function handleAnalyze() {
    const rec = await run("analyze", () =>
      api.createApplication(company, jobDescription, companyContext)
    );
    if (rec) {
      setRecord(rec);
      setStudyPlans([]);
      setCoverLetter(null);
    }
  }

  function onGapUpdated(index: number, gap: GapItem) {
    if (!record) return;
    const gaps = [...record.gaps];
    gaps[index] = gap;
    setRecord({ ...record, gaps });
  }

  async function handleApprove() {
    if (!record) return;
    const rec = await run("approve", () => api.approveApplication(record.id));
    if (rec) setRecord(rec);
  }

  async function handleStudyPlans() {
    if (!record) return;
    const plans = await run("study-plan", () => api.generateStudyPlans(record.id));
    if (plans) setStudyPlans(plans);
  }

  async function handleCoverLetter() {
    if (!record) return;
    const res = await run("cover-letter", () => api.generateCoverLetter(record.id));
    if (res) setCoverLetter(res.cover_letter_text);
  }

  if (!record) {
    return (
      <div className="page">
        <h1>New Application</h1>
        <input
          placeholder="Company name"
          value={company}
          onChange={(e) => setCompany(e.target.value)}
        />
        <textarea
          value={jobDescription}
          onChange={(e) => setJobDescription(e.target.value)}
          rows={12}
          placeholder="Paste the job description here"
        />
        <textarea
          value={companyContext}
          onChange={(e) => setCompanyContext(e.target.value)}
          rows={2}
          placeholder="Optional: anything you know about the company"
        />
        <button onClick={handleAnalyze} disabled={busy === "analyze" || !jobDescription.trim()}>
          {busy === "analyze" ? "Analyzing… (JD analysis + gap education, takes a few minutes)" : "Analyze"}
        </button>
        {error && <p className="error">{error}</p>}

        {savedApplications.length > 0 && (
          <section>
            <h2>Your applications</h2>
            {savedApplications.map((app) => (
              <div key={app.id} className="card app-list-item">
                <button onClick={() => setRecord(app)}>
                  {app.company || "?"} — {app.role_title}{" "}
                  <span className="status-badge">{app.status}</span>
                </button>
                <small>
                  {app.gaps.filter((g) => g.user_response.status !== "not_reviewed").length}/
                  {app.gaps.length} gaps reviewed
                  {app.created_at && ` · ${app.created_at.slice(0, 10)}`}
                </small>
              </div>
            ))}
          </section>
        )}
      </div>
    );
  }

  const unreviewed = record.gaps.filter((g) => g.user_response.status === "not_reviewed").length;
  const noExperience = record.gaps.filter((g) => g.user_response.status === "no_experience").length;

  return (
    <div className="page">
      <h1>
        {record.company || "Application"} — {record.role_title}{" "}
        <span className="status-badge">{record.status}</span>
      </h1>
      <button onClick={() => setRecord(null)}>← New application</button>

      {record.status === "pending_review" && (
        <>
          <section>
            <h2>Gap review ({record.gaps.length - unreviewed}/{record.gaps.length} reviewed)</h2>
            <p>
              These JD requirements have no match in your resume. For each one: read the
              briefing, then tell the app what you've actually done. Nothing is added to
              your resume without your own words.
            </p>
            {record.gaps.length === 0 && <p>No gaps — your resume covers every must-have requirement.</p>}
            {record.gaps.map((gap, i) => (
              <GapCard
                key={gap.requirement}
                applicationId={record.id}
                gapIndex={i}
                gap={gap}
                onUpdated={(g) => onGapUpdated(i, g)}
              />
            ))}
          </section>

          <section>
            <h2>Approve</h2>
            <p>
              Approving locks the tailoring plan and confirmed additions, and unlocks
              rendering/export. {unreviewed > 0 && `Review the remaining ${unreviewed} gap(s) first.`}
            </p>
            <button
              className="confirm"
              onClick={handleApprove}
              disabled={busy === "approve" || unreviewed > 0}
            >
              {busy === "approve" ? "Approving…" : "Approve tailoring plan"}
            </button>
          </section>
        </>
      )}

      {record.status !== "pending_review" && (
        <>
          <section>
            <h2>Diff summary (approved)</h2>
            {(["added", "removed", "reordered", "reworded"] as const).map((kind) =>
              record.diff_summary[kind].length > 0 ? (
                <div key={kind}>
                  <h3>{kind}</h3>
                  <ul>
                    {record.diff_summary[kind].map((line, i) => (
                      <li key={i} className={`diff-${kind}`}>{line}</li>
                    ))}
                  </ul>
                </div>
              ) : null
            )}
          </section>

          <section>
            <h2>Export</h2>
            <p>
              <a href={api.exportUrl(record.id, "docx")}>Download .docx</a>
              {" | "}
              <a href={api.exportUrl(record.id, "pdf")}>Download .pdf</a>
            </p>
            <button onClick={handleCoverLetter} disabled={busy === "cover-letter"}>
              {busy === "cover-letter" ? "Writing…" : "Generate cover letter"}
            </button>
            {coverLetter && (
              <textarea rows={14} value={coverLetter} onChange={(e) => setCoverLetter(e.target.value)} />
            )}
          </section>
        </>
      )}

      {noExperience > 0 && (
        <section>
          <h2>Study plans</h2>
          <button onClick={handleStudyPlans} disabled={busy === "study-plan"}>
            {busy === "study-plan" ? "Generating…" : `Generate study plans (${noExperience} gap${noExperience > 1 ? "s" : ""})`}
          </button>
          {studyPlans.map((plan) => (
            <div key={plan.requirement} className="card">
              <h3>
                {plan.requirement} <em>({plan.priority} priority)</em>
              </h3>
              <p><strong>Topics:</strong> {plan.study_topics.join(" · ")}</p>
              {plan.hands_on_labs.map((lab, i) => (
                <p key={i}>
                  <strong>Lab:</strong> {lab.title} (~{lab.est_hours}h) — {lab.why}
                </p>
              ))}
              {plan.interview_talking_points.length > 0 && (
                <p><strong>Interview framing:</strong> {plan.interview_talking_points.join(" / ")}</p>
              )}
            </div>
          ))}
        </section>
      )}

      {error && <p className="error">{error}</p>}
    </div>
  );
}
