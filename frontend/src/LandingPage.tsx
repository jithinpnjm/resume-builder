import type { ApplicationRecord, StudyGuideEntry, TrendScanBatch } from "./types";

export default function LandingPage({
  applications,
  guides,
  scans,
  onBuild,
  onAnalysis,
  onStudyRoom,
}: {
  applications: ApplicationRecord[];
  guides: StudyGuideEntry[];
  scans: TrendScanBatch[];
  onBuild: () => void;
  onAnalysis: () => void;
  onStudyRoom: () => void;
}) {
  const inProgress = applications.filter((a) =>
    ["analyzing", "pending_review", "approved", "finalized"].includes(a.status)
  ).length;
  const weekAgo = new Date(Date.now() - 7 * 864e5).toISOString();
  const trendGapsThisWeek = scans
    .filter((s) => s.created_at >= weekAgo)
    .reduce((n, s) => n + s.review_items.length, 0);
  const stepsDone = guides.reduce(
    (n, g) => n + g.steps.filter((s) => s.done).length,
    0
  );

  return (
    <div className="content" style={{ maxWidth: 1080 }}>
      <h1 style={{ marginTop: 40 }}>resume-agent</h1>
      <p className="muted">
        Tailor without fabricating · archive everything · learn what the market keeps
        asking for.
      </p>
      <div className="card-grid" style={{ marginTop: 24 }}>
        <div className="card landing-card">
          <h2 style={{ border: "none", marginTop: 0 }}>1 · Build Resume</h2>
          <p>
            Full tailoring workflow for a specific company/role — gap review, approval
            diff, resume + cover letter, archived per company.
          </p>
          <p className="num muted">{inProgress} application(s) in progress</p>
          <button className="primary" onClick={onBuild}>
            Open
          </button>
        </div>
        <div className="card landing-card">
          <h2 style={{ border: "none", marginTop: 0 }}>2 · Job Market Analysis</h2>
          <p>
            Read-only dashboard: how you're performing against jobs you've{" "}
            <em>actually applied to</em>. Never diluted by trend scans.
          </p>
          <p className="num muted">
            {applications.filter((a) => a.status === "archived").length} archived
            application(s) feeding it
          </p>
          <button className="primary" onClick={onAnalysis}>
            Open
          </button>
        </div>
        <div className="card landing-card">
          <h2 style={{ border: "none", marginTop: 0 }}>3 · Market Trends &amp; Study Room</h2>
          <p>
            Bulk-paste postings you're curious about — no tailoring. Feeds skill-demand
            tracking and builds the real study curriculum.
          </p>
          <p className="num muted">
            {trendGapsThisWeek} trend gap(s) this week · {stepsDone} study step(s) done
          </p>
          <button className="primary" onClick={onStudyRoom}>
            Open
          </button>
        </div>
      </div>
    </div>
  );
}
