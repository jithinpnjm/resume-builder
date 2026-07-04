import { useEffect, useState } from "react";
import * as api from "./api";
import type {
  ApplicationRecord,
  MarketFitReport,
  StudyGuideEntry,
  UserSettings,
} from "./types";

// ---------------------------------------------------------------------------
// Home — application cards grouped by status
// ---------------------------------------------------------------------------

export function HomePage({
  applications,
  onOpen,
  onNew,
}: {
  applications: ApplicationRecord[];
  onOpen: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <div>
      <h1>Applications</h1>
      <p>
        <button className="primary" onClick={onNew}>
          ＋ New application
        </button>
      </p>
      {applications.length === 0 && (
        <p className="muted">Nothing yet — paste your first job description.</p>
      )}
      <div className="card-grid">
        {applications.map((app) => (
          <div key={app.id} className="card">
            <h3>
              {app.company || "?"} — {app.role_title}
            </h3>
            <p>
              <span className={`pill ${app.status}`}>{app.status.replace("_", " ")}</span>
            </p>
            <p className="muted num">
              {app.gaps.filter((g) => g.user_response.status !== "not_reviewed").length}/
              {app.gaps.length} gaps reviewed
              {app.created_at && ` · ${app.created_at.slice(0, 10)}`}
            </p>
            <button onClick={() => onOpen(app.id)}>Open</button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// New application
// ---------------------------------------------------------------------------

export function NewApplicationPage({ onCreated }: { onCreated: (id: string) => void }) {
  const [company, setCompany] = useState("");
  const [jd, setJd] = useState("");
  const [context, setContext] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function analyze() {
    setBusy(true);
    setError(null);
    try {
      const rec = await api.createApplication(company, jd, context);
      onCreated(rec.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1>New application</h1>
      <label>
        Company
        <input value={company} onChange={(e) => setCompany(e.target.value)} />
      </label>
      <label>
        Job description
        <textarea rows={12} value={jd} onChange={(e) => setJd(e.target.value)} />
      </label>
      <label>
        Company context (optional)
        <textarea rows={2} value={context} onChange={(e) => setContext(e.target.value)} />
      </label>
      <button className="primary" onClick={analyze} disabled={busy || !jd.trim()}>
        {busy ? "Analyzing… (a few minutes — JD analysis + gap briefings)" : "Analyze"}
      </button>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Study Guide — sequenced curriculum ordered by priority_score
// ---------------------------------------------------------------------------

export function StudyGuidePage() {
  const [guides, setGuides] = useState<StudyGuideEntry[]>([]);
  const [catalogIds, setCatalogIds] = useState<
    { canonical_id: string; name: string; score: number; status: string }[]
  >([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const [g, cat] = await Promise.all([api.listStudyGuides(), api.getCatalog()]);
      setGuides(g);
      setCatalogIds(
        cat
          .filter((c) => c.user_status === "no_experience" || c.user_status === "partial_experience")
          .map((c) => ({
            canonical_id: c.canonical_id,
            name: c.canonical_name,
            score: c.priority_score,
            status: c.user_status,
          }))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Load failed");
    }
  }

  useEffect(() => {
    load();
  }, []);

  const curated = new Set(guides.map((g) => g.canonical_id));
  const uncurated = catalogIds.filter((c) => !curated.has(c.canonical_id));

  async function curate(id: string) {
    setBusy(id);
    setError(null);
    try {
      await api.curateStudyGuide(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Curation failed");
    } finally {
      setBusy(null);
    }
  }

  async function toggleStep(id: string, step: number, done: boolean) {
    const updated = await api.markStudyStep(id, step, done);
    setGuides((gs) => gs.map((g) => (g.canonical_id === id ? updated : g)));
  }

  return (
    <div>
      <h1>Study Guide</h1>
      <p className="muted">
        One curriculum per recurring gap, ordered by priority (demand × recency ×
        gap severity). Links are search-grounded and validated — dead links are dropped.
      </p>
      {error && <p className="error">{error}</p>}

      {uncurated.length > 0 && (
        <section>
          <h2>Gaps without a curriculum yet</h2>
          {uncurated.map((c) => (
            <div key={c.canonical_id} className="card">
              <strong>{c.name}</strong>{" "}
              <span className={`pill ${c.status}`}>{c.status.replace("_", " ")}</span>{" "}
              <span className="score num">score {c.score.toFixed(2)}</span>
              <div className="gap-actions">
                <button onClick={() => curate(c.canonical_id)} disabled={busy !== null}>
                  {busy === c.canonical_id
                    ? "Curating… (search-grounded, ~1-2 min)"
                    : "Build curriculum"}
                </button>
              </div>
            </div>
          ))}
        </section>
      )}

      {guides.map((guide) => (
        <section key={guide.canonical_id}>
          <h2>
            {guide.canonical_id}{" "}
            <span className="score num">priority {guide.priority_score.toFixed(2)}</span>
          </h2>
          <p className="muted">{guide.why_it_matters}</p>
          {guide.recommended_books.length > 0 && (
            <div className="card">
              <strong>📚 Recommended reading</strong>
              {guide.recommended_books.map((b, i) => (
                <p key={i}>
                  <em>{b.title}</em> — {b.authors}
                  <br />
                  <span className="muted">{b.why}</span>
                </p>
              ))}
            </div>
          )}
          {guide.url_validation_status === "some_stale" && (
            <p className="muted">Some suggested links failed validation and were removed.</p>
          )}
          {guide.steps.map((step) => (
            <details key={step.step_number} className="study-step">
              <summary>
                <input
                  type="checkbox"
                  checked={step.done}
                  onChange={(e) =>
                    toggleStep(guide.canonical_id, step.step_number, e.target.checked)
                  }
                  onClick={(e) => e.stopPropagation()}
                  aria-label={`Mark step ${step.step_number} done`}
                />
                {step.step_number}. {step.title}
                <span className="muted num">~{step.est_hours}h</span>
              </summary>
              <div className="step-body">
                <p>
                  <strong>Goal:</strong> {step.goal}
                </p>
                {step.concepts.length > 0 && (
                  <p>
                    <strong>Concepts:</strong> {step.concepts.join(" · ")}
                  </p>
                )}
                {step.hands_on_lab && (
                  <p>
                    <strong>Lab:</strong> {step.hands_on_lab.title} (~
                    {step.hands_on_lab.est_hours}h) — {step.hands_on_lab.why_this_lab}{" "}
                    {step.hands_on_lab.repo_url && (
                      <a href={step.hands_on_lab.repo_url} target="_blank" rel="noreferrer">
                        repo
                      </a>
                    )}
                  </p>
                )}
                {step.resources.length > 0 && (
                  <ul>
                    {step.resources.map((r, i) => (
                      <li key={i}>
                        <a href={r.url} target="_blank" rel="noreferrer">
                          {r.title || r.url}
                        </a>{" "}
                        <span className="muted">({r.source})</span>
                      </li>
                    ))}
                  </ul>
                )}
                {step.interview_talking_points.length > 0 && (
                  <p>
                    <strong>Interview framing:</strong>{" "}
                    {step.interview_talking_points.join(" / ")}
                  </p>
                )}
              </div>
            </details>
          ))}
        </section>
      ))}

      {guides.length === 0 && uncurated.length === 0 && (
        <p className="muted">
          Nothing here yet — gaps marked “No experience” during application reviews
          will appear here for curriculum building.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Career Growth — match-rate trend + recurring gaps + promotables
// ---------------------------------------------------------------------------

export function CareerGrowthPage() {
  const [report, setReport] = useState<MarketFitReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(refresh: boolean) {
    setBusy(true);
    setError(null);
    try {
      setReport(await api.getMarketFit(refresh));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Load failed");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load(false);
  }, []);

  const points = (report?.match_rate_trend ?? []).filter((p) => p.match_pct !== null);

  return (
    <div>
      <h1>Career Growth</h1>
      <p>
        <button onClick={() => load(true)} disabled={busy}>
          {busy ? "Analyzing…" : "Refresh report"}
        </button>
        {report?.generated_at && (
          <span className="muted"> generated {report.generated_at.slice(0, 16)}</span>
        )}
      </p>
      {error && <p className="error">{error}</p>}
      {!report && !error && <p className="muted">Loading…</p>}

      {report && (
        <>
          <section>
            <h2>Match rate over time</h2>
            {points.length < 2 ? (
              <p className="muted">
                Needs at least two applications to draw a trend ({points.length} so far).
              </p>
            ) : (
              <svg className="trend-svg" viewBox="0 0 600 180" preserveAspectRatio="none" role="img" aria-label="match rate trend">
                {[0.25, 0.5, 0.75].map((y) => (
                  <line key={y} x1="0" x2="600" y1={170 - y * 160} y2={170 - y * 160} stroke="#30363d" strokeWidth="1" />
                ))}
                <polyline
                  fill="none"
                  stroke="#58a6ff"
                  strokeWidth="2"
                  points={points
                    .map(
                      (p, i) =>
                        `${20 + (i * 560) / Math.max(points.length - 1, 1)},${170 - (p.match_pct ?? 0) * 160}`
                    )
                    .join(" ")}
                />
                {points.map((p, i) => (
                  <circle
                    key={i}
                    cx={20 + (i * 560) / Math.max(points.length - 1, 1)}
                    cy={170 - (p.match_pct ?? 0) * 160}
                    r="4"
                    fill="#58a6ff"
                  >
                    <title>
                      {p.company}: {Math.round((p.match_pct ?? 0) * 100)}%
                    </title>
                  </circle>
                ))}
              </svg>
            )}
          </section>

          <section>
            <h2>Top recurring gaps</h2>
            {report.top_recurring_gaps.length === 0 && <p className="muted">None yet.</p>}
            {report.top_recurring_gaps.map((g) => (
              <div key={g.requirement} className="card gap-card gap-no_experience">
                <strong>{g.requirement}</strong>{" "}
                <span className={`pill ${g.priority === "high" ? "no_experience" : "partial_experience"}`}>
                  {g.priority}
                </span>
                <p className="muted num">
                  required {g.times_required}× · gapped {g.times_gapped}×
                </p>
                <p>{g.reasoning}</p>
              </div>
            ))}
          </section>

          <section>
            <h2>Confirmed but not in your base resume</h2>
            {report.promotable_experience_not_yet_in_base_resume.length === 0 && (
              <p className="muted">Nothing waiting for promotion.</p>
            )}
            {report.promotable_experience_not_yet_in_base_resume.map((p) => (
              <div key={p.requirement} className="card">
                <strong>{p.requirement}</strong>{" "}
                <span className="muted num">confirmed {p.confirmed_in_applications}×</span>
                <p>{p.suggested_action}</p>
                <p className="muted">
                  Promote from the application's Finalize screen (Promote to base resume).
                </p>
              </div>
            ))}
          </section>

          {report.resume_structural_suggestions.length > 0 && (
            <section>
              <h2>Structural suggestions</h2>
              <ul>
                {report.resume_structural_suggestions.map((s, i) => (
                  <li key={i}>{s.detail}</li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Settings — content sources (v3 §7)
// ---------------------------------------------------------------------------

const NEWSLETTERS = ["TLDR DevOps", "TLDR AI", "TLDR InfoSec", "Last Week in AWS", "KubeWeekly"];

export function SettingsPage() {
  const [settings, setSettings] = useState<UserSettings>({
    linkedin_url: "",
    medium_url: "",
    newsletters: [],
  });
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getSettings().then(setSettings).catch(() => {});
  }, []);

  async function save() {
    setError(null);
    try {
      await api.saveSettings(settings);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  return (
    <div>
      <h1>Settings</h1>
      <p className="muted">
        These flavor the Study Guide's search-grounded curation — no OAuth, no scraping.
      </p>
      <label>
        LinkedIn profile URL
        <input
          value={settings.linkedin_url}
          onChange={(e) => setSettings({ ...settings, linkedin_url: e.target.value })}
          placeholder="https://www.linkedin.com/in/…"
        />
      </label>
      <label>
        Medium profile URL
        <input
          value={settings.medium_url}
          onChange={(e) => setSettings({ ...settings, medium_url: e.target.value })}
          placeholder="https://medium.com/@…"
        />
      </label>
      <section>
        <h2>Newsletters you read</h2>
        {NEWSLETTERS.map((n) => (
          <label key={n} className="core-toggle">
            <input
              type="checkbox"
              checked={settings.newsletters.includes(n)}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  newsletters: e.target.checked
                    ? [...settings.newsletters, n]
                    : settings.newsletters.filter((x) => x !== n),
                })
              }
            />
            {n}
          </label>
        ))}
      </section>
      <p>
        <button className="primary" onClick={save}>
          Save settings
        </button>{" "}
        {saved && <span className="pill ok">saved</span>}
      </p>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
