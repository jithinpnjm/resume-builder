import { useCallback, useEffect, useState } from "react";
import type { ApplicationRecord, ResumeJSON, StudyGuideEntry, TrendScanBatch } from "./types";
import * as api from "./api";
import { API_BASE, saveBaseResume, tagCore } from "./api";
import Shell, { type View } from "./Shell";
import LandingPage from "./LandingPage";
import ApplicationView from "./ApplicationView";
import TrendScanPage from "./TrendScanPage";
import { CareerGrowthPage, HomePage, NewApplicationPage, SettingsPage, StudyGuidePage } from "./pages";
import "./App.css";

const EMPTY_RESUME: ResumeJSON = {
  contact: { name: "", location: "", email: "", phone: "", linkedin: "", github: "" },
  summary: "",
  summary_segments: [],
  accomplishments: [],
  skills: { categories: [] },
  experience: [],
  projects: [],
  education: [],
  languages: [],
  certifications: [],
};

const CRUMBS: Record<string, string> = {
  landing: "",
  home: "Build Resume",
  onboarding: "Base resume",
  "new-app": "Build Resume / new",
  application: "Build Resume / application",
  study: "Market Trends & Study Room",
  growth: "Job Market Analysis",
  settings: "Settings",
};

function App() {
  const [stack, setStack] = useState<View[]>([{ name: "landing" }]);
  const [applications, setApplications] = useState<ApplicationRecord[]>([]);
  const [guides, setGuides] = useState<StudyGuideEntry[]>([]);
  const [scans, setScans] = useState<TrendScanBatch[]>([]);
  const [guidesRefreshKey, setGuidesRefreshKey] = useState(0);

  const view = stack[stack.length - 1];

  const refreshData = useCallback(() => {
    api.listApplications().then(setApplications).catch(() => {});
    api.listStudyGuides().then(setGuides).catch(() => {});
    api.listTrendScans().then(setScans).catch(() => {});
  }, []);

  useEffect(() => {
    refreshData();
  }, [refreshData, view.name, guidesRefreshKey]);

  const navigate = (v: View) => setStack((s) => [...s, v]);
  const back = () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s));
  const home = () => setStack([{ name: "landing" }]);

  if (view.name === "landing") {
    return (
      <LandingPage
        applications={applications}
        guides={guides}
        scans={scans}
        onBuild={() => navigate({ name: "home" })}
        onAnalysis={() => navigate({ name: "growth" })}
        onStudyRoom={() => navigate({ name: "study" })}
      />
    );
  }

  return (
    <Shell
      view={view}
      applications={applications}
      crumb={CRUMBS[view.name] ?? ""}
      canGoBack={stack.length > 1}
      onNavigate={navigate}
      onBack={back}
      onHome={home}
    >
      {view.name === "home" && (
        <HomePage
          applications={applications}
          onOpen={(id) => navigate({ name: "application", appId: id })}
          onNew={() => navigate({ name: "new-app" })}
        />
      )}
      {view.name === "new-app" && (
        <NewApplicationPage
          onCreated={(id) => {
            refreshData();
            navigate({ name: "application", appId: id });
          }}
        />
      )}
      {view.name === "application" && view.appId && (
        <ApplicationView appId={view.appId} onChanged={refreshData} />
      )}
      {view.name === "onboarding" && (
        <OnboardingPage
          onConfirmed={() => {
            refreshData();
            navigate({ name: "home" });
          }}
        />
      )}
      {view.name === "study" && (
        <>
          <TrendScanPage onGuidesChanged={() => setGuidesRefreshKey((k) => k + 1)} />
          <hr style={{ border: "none", borderTop: "1px solid var(--border-subtle)", margin: "32px 0" }} />
          <StudyGuidePage key={guidesRefreshKey} />
        </>
      )}
      {view.name === "growth" && <CareerGrowthPage />}
      {view.name === "settings" && <SettingsPage />}
    </Shell>
  );
}

function OnboardingPage({ onConfirmed }: { onConfirmed: () => void }) {
  const [resume, setResume] = useState<ResumeJSON | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"local" | "cloud">("cloud");
  const [localPath, setLocalPath] = useState("");
  const [changedFromStored, setChangedFromStored] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((r) => r.json())
      .then((d) => setMode(d.mode === "local" ? "local" : "cloud"))
      .catch(() => setMode("cloud"));
  }, []);

  async function loadParsed(res: Response) {
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail ?? `Request failed: ${res.status}`);
    }
    const data = await res.json();
    setResume(data.resume);
    setChangedFromStored(data.changed_from_stored);
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      await loadParsed(
        await fetch(`${API_BASE}/onboarding/load-resume`, { method: "POST", body: formData })
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleLocalPath() {
    setLoading(true);
    setError(null);
    try {
      await loadParsed(
        await fetch(`${API_BASE}/onboarding/load-resume`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ local_path: localPath }),
        })
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Load failed");
    } finally {
      setLoading(false);
    }
  }

  async function loadSavedResume() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/onboarding/resume`);
      if (!res.ok) throw new Error(`Request failed: ${res.status}`);
      setResume(await res.json());
      setChangedFromStored(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load saved resume");
    } finally {
      setLoading(false);
    }
  }

  if (!resume) {
    return (
      <div>
        <h1>Base resume</h1>
        {mode === "cloud" ? (
          <>
            <p>Upload your resume (PDF or DOCX) to extract a structured, editable draft.</p>
            <input type="file" accept=".pdf,.docx" onChange={handleUpload} disabled={loading} />
          </>
        ) : (
          <>
            <p>Enter the filesystem path to your resume (PDF or DOCX).</p>
            <input
              placeholder="/Users/you/resumes/base.docx"
              value={localPath}
              onChange={(e) => setLocalPath(e.target.value)}
              disabled={loading}
            />
            <button onClick={handleLocalPath} disabled={loading || !localPath.trim()}>
              Load
            </button>
          </>
        )}
        {loading && <p>Parsing…</p>}
        {error && <p className="error">{error}</p>}
        <p>
          <button onClick={loadSavedResume}>Load previously saved resume</button>{" "}
          <button onClick={() => setResume(structuredClone(EMPTY_RESUME))}>
            Start from a blank form
          </button>
        </p>
      </div>
    );
  }

  return (
    <>
      {changedFromStored && (
        <p className="error">
          This parse differs from your stored base resume. Review below — confirming
          overwrites the stored version (a version snapshot is kept).
        </p>
      )}
      <ResumeReview
        resume={resume}
        onChange={setResume}
        onReset={() => setResume(null)}
        onConfirm={async () => {
          await saveBaseResume(resume);
          onConfirmed();
        }}
      />
    </>
  );
}
function ResumeReview({
  resume,
  onChange,
  onReset,
  onConfirm,
}: {
  resume: ResumeJSON;
  onChange: (r: ResumeJSON) => void;
  onReset: () => void;
  onConfirm: () => void | Promise<void>;
}) {
  const update = (patch: Partial<ResumeJSON>) => onChange({ ...resume, ...patch });
  const [tagging, setTagging] = useState(false);

  async function autoTagCore() {
    setTagging(true);
    try {
      // Save first so the backend tags the resume you're looking at.
      await saveBaseResume(resume);
      const { core_bullet_ids } = await tagCore();
      const coreIds = new Set(core_bullet_ids);
      onChange({
        ...resume,
        accomplishments: resume.accomplishments.map((b) => ({ ...b, core: coreIds.has(b.id) })),
        experience: resume.experience.map((exp) => ({
          ...exp,
          bullets: exp.bullets.map((b) => ({ ...b, core: coreIds.has(b.id) })),
        })),
      });
    } finally {
      setTagging(false);
    }
  }

  return (
    <div className="page">
      <h1>Review Extracted Resume</h1>
      <p>Extraction is lossy — correct anything that's wrong before confirming.</p>
      <button onClick={onReset}>Start over</button>{" "}
      <button onClick={autoTagCore} disabled={tagging} title="Gemini proposes which bullets are baseline senior competency; you review the checkboxes afterward">
        {tagging ? "Tagging…" : "Auto-tag core bullets"}
      </button>

      <section>
        <h2>Contact</h2>
        <div className="grid">
          {(Object.keys(resume.contact) as (keyof typeof resume.contact)[]).map((field) => (
            <label key={field}>
              {field}
              <input
                value={resume.contact[field]}
                onChange={(e) =>
                  update({ contact: { ...resume.contact, [field]: e.target.value } })
                }
              />
            </label>
          ))}
        </div>
      </section>

      <section>
        <h2>Summary</h2>
        <textarea
          value={resume.summary}
          onChange={(e) => update({ summary: e.target.value })}
          rows={3}
        />
      </section>

      <section>
        <h2>Accomplishments</h2>
        {resume.accomplishments.map((acc, i) => (
          <div key={acc.id} className="bullet-row">
            <textarea
              value={acc.text}
              rows={2}
              onChange={(e) => {
                const accomplishments = [...resume.accomplishments];
                accomplishments[i] = { ...acc, text: e.target.value };
                update({ accomplishments });
              }}
            />
            <button
              onClick={() =>
                update({ accomplishments: resume.accomplishments.filter((_, idx) => idx !== i) })
              }
            >
              Remove
            </button>
          </div>
        ))}
        <button
          onClick={() =>
            update({
              accomplishments: [
                ...resume.accomplishments,
                { id: `acc${resume.accomplishments.length + 1}`, text: "", core: false, tags: [] },
              ],
            })
          }
        >
          + Add accomplishment
        </button>
      </section>

      <section>
        <h2>Languages</h2>
        {resume.languages.map((lang, i) => (
          <div key={i} className="grid card">
            <label>
              Language
              <input
                value={lang.name}
                onChange={(e) => {
                  const languages = [...resume.languages];
                  languages[i] = { ...lang, name: e.target.value };
                  update({ languages });
                }}
              />
            </label>
            <label>
              Level
              <input
                value={lang.level}
                onChange={(e) => {
                  const languages = [...resume.languages];
                  languages[i] = { ...lang, level: e.target.value };
                  update({ languages });
                }}
              />
            </label>
            <button
              onClick={() => update({ languages: resume.languages.filter((_, idx) => idx !== i) })}
            >
              Remove
            </button>
          </div>
        ))}
        <button
          onClick={() => update({ languages: [...resume.languages, { name: "", level: "" }] })}
        >
          + Add language
        </button>
      </section>

      <section>
        <h2>Skills</h2>
        {resume.skills.categories.map((cat, i) => (
          <div key={i} className="card">
            <input
              value={cat.name}
              placeholder="Category name"
              onChange={(e) => {
                const categories = [...resume.skills.categories];
                categories[i] = { ...cat, name: e.target.value };
                update({ skills: { categories } });
              }}
            />
            <input
              value={cat.items.join(", ")}
              placeholder="Comma-separated skills"
              onChange={(e) => {
                const categories = [...resume.skills.categories];
                categories[i] = {
                  ...cat,
                  items: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                };
                update({ skills: { categories } });
              }}
            />
            <button
              onClick={() => {
                const categories = resume.skills.categories.filter((_, idx) => idx !== i);
                update({ skills: { categories } });
              }}
            >
              Remove category
            </button>
          </div>
        ))}
        <button
          onClick={() =>
            update({
              skills: {
                categories: [...resume.skills.categories, { name: "", items: [] }],
              },
            })
          }
        >
          + Add skill category
        </button>
      </section>

      <section>
        <h2>Experience</h2>
        {resume.experience.map((exp, i) => (
          <div key={exp.id} className="card">
            <div className="grid">
              <label>
                Company
                <input
                  value={exp.company}
                  onChange={(e) => {
                    const experience = [...resume.experience];
                    experience[i] = { ...exp, company: e.target.value };
                    update({ experience });
                  }}
                />
              </label>
              <label>
                Title
                <input
                  value={exp.title}
                  onChange={(e) => {
                    const experience = [...resume.experience];
                    experience[i] = { ...exp, title: e.target.value };
                    update({ experience });
                  }}
                />
              </label>
              <label>
                Location
                <input
                  value={exp.location}
                  onChange={(e) => {
                    const experience = [...resume.experience];
                    experience[i] = { ...exp, location: e.target.value };
                    update({ experience });
                  }}
                />
              </label>
              <label>
                Start
                <input
                  value={exp.start}
                  onChange={(e) => {
                    const experience = [...resume.experience];
                    experience[i] = { ...exp, start: e.target.value };
                    update({ experience });
                  }}
                />
              </label>
              <label>
                End
                <input
                  value={exp.end}
                  onChange={(e) => {
                    const experience = [...resume.experience];
                    experience[i] = { ...exp, end: e.target.value };
                    update({ experience });
                  }}
                />
              </label>
            </div>

            <h4>Bullets</h4>
            {exp.bullets.map((b, bi) => (
              <div key={b.id} className="bullet-row">
                <textarea
                  value={b.text}
                  rows={2}
                  onChange={(e) => {
                    const experience = [...resume.experience];
                    const bullets = [...exp.bullets];
                    bullets[bi] = { ...b, text: e.target.value };
                    experience[i] = { ...exp, bullets };
                    update({ experience });
                  }}
                />
                <label className="core-toggle" title="Core bullets can be reordered lower but never removed or hidden by tailoring">
                  <input
                    type="checkbox"
                    checked={b.core}
                    onChange={(e) => {
                      const experience = [...resume.experience];
                      const bullets = [...exp.bullets];
                      bullets[bi] = { ...b, core: e.target.checked };
                      experience[i] = { ...exp, bullets };
                      update({ experience });
                    }}
                  />
                  core
                </label>
                <button
                  onClick={() => {
                    const experience = [...resume.experience];
                    experience[i] = {
                      ...exp,
                      bullets: exp.bullets.filter((_, idx) => idx !== bi),
                    };
                    update({ experience });
                  }}
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              onClick={() => {
                const experience = [...resume.experience];
                const nextId = `b${exp.bullets.length + 1}`;
                experience[i] = {
                  ...exp,
                  bullets: [...exp.bullets, { id: nextId, text: "", core: false, tags: [] }],
                };
                update({ experience });
              }}
            >
              + Add bullet
            </button>

            <div>
              <button
                onClick={() =>
                  update({ experience: resume.experience.filter((_, idx) => idx !== i) })
                }
              >
                Remove this experience entry
              </button>
            </div>
          </div>
        ))}
        <button
          onClick={() =>
            update({
              experience: [
                ...resume.experience,
                {
                  id: `exp_${resume.experience.length + 1}`,
                  company: "",
                  title: "",
                  location: "",
                  start: "",
                  end: "",
                  bullets: [],
                },
              ],
            })
          }
        >
          + Add experience entry
        </button>
      </section>

      <section>
        <h2>Education</h2>
        {resume.education.map((ed, i) => (
          <div key={i} className="grid card">
            <label>
              Degree
              <input
                value={ed.degree}
                onChange={(e) => {
                  const education = [...resume.education];
                  education[i] = { ...ed, degree: e.target.value };
                  update({ education });
                }}
              />
            </label>
            <label>
              Institution
              <input
                value={ed.institution}
                onChange={(e) => {
                  const education = [...resume.education];
                  education[i] = { ...ed, institution: e.target.value };
                  update({ education });
                }}
              />
            </label>
            <label>
              Year
              <input
                value={ed.year}
                onChange={(e) => {
                  const education = [...resume.education];
                  education[i] = { ...ed, year: e.target.value };
                  update({ education });
                }}
              />
            </label>
          </div>
        ))}
        <button
          onClick={() =>
            update({ education: [...resume.education, { degree: "", institution: "", year: "" }] })
          }
        >
          + Add education entry
        </button>
      </section>

      <section>
        <h2>Certifications</h2>
        <textarea
          value={resume.certifications.join(", ")}
          onChange={(e) =>
            update({ certifications: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })
          }
          rows={2}
        />
      </section>

      <button className="confirm" onClick={onConfirm}>
        Confirm and start applying
      </button>
    </div>
  );
}

export default App;
