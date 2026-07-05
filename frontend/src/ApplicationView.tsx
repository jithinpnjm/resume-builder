import { useEffect, useState } from "react";
import * as api from "./api";
import GapCard from "./GapCard";
import type { ApplicationRecord, GapItem } from "./types";

export default function ApplicationView({
  appId,
  onChanged,
  onDiscarded,
}: {
  appId: string;
  onChanged: () => void;
  onDiscarded: () => void;
}) {
  const [record, setRecord] = useState<ApplicationRecord | null>(null);
  const [coverLetter, setCoverLetter] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [promoted, setPromoted] = useState<Record<number, string>>({});
  const [fitDismissed, setFitDismissed] = useState(false);

  useEffect(() => {
    api.getApplication(appId).then((r) => {
      setRecord(r);
      setCoverLetter(r.cover_letter || null);
    }).catch((e) => setError(e.message));
  }, [appId]);

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

  if (!record) return <p className="muted">{error ?? "Loading…"}</p>;

  function onGapUpdated(index: number, gap: GapItem) {
    if (!record) return;
    const gaps = [...record.gaps];
    gaps[index] = gap;
    setRecord({ ...record, gaps });
  }

  const unreviewed = record.gaps.filter(
    (g) => g.user_response.status === "not_reviewed"
  ).length;
  const confirmedGaps = record.gaps
    .map((g, i) => ({ gap: g, index: i }))
    .filter(
      ({ gap }) =>
        ["have_experience", "partial_experience"].includes(gap.user_response.status) &&
        gap.proposed_bullet
    );

  const added = record.diff_summary.added.length;
  const reworded = record.diff_summary.reworded.length;
  const removed = record.diff_summary.removed.length;

  async function refresh() {
    const r = await api.getApplication(appId);
    setRecord(r);
    setCoverLetter(r.cover_letter || null);
    onChanged();
  }

  return (
    <div>
      <h1>
        {record.company || "Application"} — {record.role_title}{" "}
        <span className={`pill ${record.status}`}>{record.status.replace("_", " ")}</span>
      </h1>

      {record.role_fit && record.role_fit.decision === "warn" && !fitDismissed && (
        <div className="reuse-banner" style={{ borderColor: "var(--status-partial)" }}>
          Outside your target roles and {Math.round(record.role_fit.skill_match_pct * 100)}%
          skill match — {record.role_fit.decision_reason} Proceeding anyway.
          <div className="gap-actions">
            <button onClick={() => setFitDismissed(true)}>Dismiss</button>
          </div>
        </div>
      )}

      {["analyzing", "pending_review", "approved"].includes(record.status) && (
        <p>
          <button
            className="danger-ghost"
            onClick={() =>
              run("discard", async () => {
                await api.discardApplication(record.id);
                onDiscarded();
              })
            }
            disabled={busy === "discard"}
          >
            {busy === "discard" ? "Discarding…" : "Discard — not a fit"}
          </button>
        </p>
      )}

      {record.interview_lens && (
        <details className="card">
          <summary>
            <strong>If you were interviewing for this role</strong> —{" "}
            {record.interview_lens.persona_title}'s perspective
          </summary>
          <div>
            <h4>What they'd probe for</h4>
            <ul>
              {record.interview_lens.what_id_probe.map((q) => (
                <li key={q}>{q}</li>
              ))}
            </ul>
            <h4>Red flags they'd watch for</h4>
            <ul>
              {record.interview_lens.red_flags.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
            <h4>What they'd reference if unsure</h4>
            <ul>
              {record.interview_lens.reference_points_if_unsure.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        </details>
      )}

      {record.status === "pending_review" && (
        <>
          <section>
            <h2>
              Gap review{" "}
              <span className="num muted">
                {record.gaps.length - unreviewed}/{record.gaps.length}
              </span>
            </h2>
            <p className="muted">
              Requirements with no match in your resume. Nothing is added without your
              own words; answers save immediately.
            </p>
            {record.gaps.length === 0 && (
              <p>No gaps — your resume covers every must-have requirement.</p>
            )}
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
            <p className="muted">
              Approving locks the plan and confirmed additions, and unlocks rendering.
              {unreviewed > 0 && ` ${unreviewed} gap(s) still need review.`}
            </p>
            <button
              className="primary"
              onClick={() =>
                run("approve", async () => {
                  await api.approveApplication(record.id);
                  await refresh();
                })
              }
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
            <h2>
              Changes{" "}
              <span className="diff-chip">
                <span className="add">+{added + reworded}</span>{" "}
                <span className="del">−{removed}</span>
              </span>
            </h2>
            <div className="diff-block">
              <div className="diff-file">resume — approved diff</div>
              {record.diff_summary.removed.map((line, i) => (
                <span key={`d${i}`} className="diff-line del">{line}</span>
              ))}
              {record.diff_summary.reworded.map((line, i) => (
                <span key={`w${i}`} className="diff-line add">{line}</span>
              ))}
              {record.diff_summary.added.map((line, i) => (
                <span key={`a${i}`} className="diff-line add">{line}</span>
              ))}
              {record.diff_summary.reordered.map((line, i) => (
                <span key={`r${i}`} className="diff-line ctx">reordered: {line}</span>
              ))}
              {added + reworded + removed + record.diff_summary.reordered.length === 0 && (
                <span className="diff-line ctx">no changes — resume used as-is</span>
              )}
            </div>
          </section>

          <section>
            <h2>Documents</h2>
            <p>
              <a href={api.exportUrl(record.id, "docx")}>resume.docx</a>
              {" · "}
              <a href={api.exportUrl(record.id, "pdf")}>resume.pdf</a>
              {record.gcs_path && (
                <>
                  {" · "}
                  <a href={api.archivedFileUrl(record.id, "report.html")} target="_blank" rel="noreferrer">
                    report.html (archive)
                  </a>
                </>
              )}
            </p>
            {record.status === "approved" && (
              <button
                onClick={() =>
                  run("cover-letter", async () => {
                    const res = await api.generateCoverLetter(record.id);
                    setCoverLetter(res.cover_letter_text);
                  })
                }
                disabled={busy === "cover-letter"}
              >
                {busy === "cover-letter" ? "Writing…" : coverLetter ? "Regenerate cover letter" : "Generate cover letter"}
              </button>
            )}
            {coverLetter && (
              <textarea
                rows={14}
                value={coverLetter}
                onChange={(e) => setCoverLetter(e.target.value)}
                aria-label="Cover letter"
              />
            )}
          </section>

          {record.status === "approved" && (
            <section>
              <h2>Finalize</h2>
              <p className="muted">Locks the letter and marks the application finalized.</p>
              <button
                className="primary"
                onClick={() =>
                  run("finalize", async () => {
                    await api.finalizeApplication(record.id);
                    await refresh();
                  })
                }
                disabled={busy === "finalize"}
              >
                {busy === "finalize" ? "Finalizing…" : "Finalize"}
              </button>
            </section>
          )}

          {record.status === "finalized" && (
            <>
              {confirmedGaps.length > 0 && (
                <section>
                  <h2>Promote to base resume</h2>
                  <p className="muted">
                    You confirmed these for this application. Add them permanently so
                    future applications don't ask again?
                  </p>
                  {confirmedGaps.map(({ gap, index }) => (
                    <div key={gap.requirement} className="card">
                      <strong>{gap.requirement}</strong>
                      <p className="proposed-text">+ {gap.proposed_bullet}</p>
                      {promoted[index] ? (
                        <span className="pill ok">{promoted[index]}</span>
                      ) : (
                        <div className="gap-actions">
                          <button
                            className="primary"
                            onClick={() =>
                              run(`promote${index}`, async () => {
                                await api.promoteGap(record.id, index, "add_to_base");
                                setPromoted((p) => ({ ...p, [index]: "added to base resume" }));
                              })
                            }
                          >
                            Add to base resume
                          </button>
                          <button
                            onClick={() =>
                              run(`promote${index}`, async () => {
                                await api.promoteGap(record.id, index, "this_application_only");
                                setPromoted((p) => ({ ...p, [index]: "this application only" }));
                              })
                            }
                          >
                            Keep this-application-only
                          </button>
                          <button
                            onClick={() =>
                              run(`promote${index}`, async () => {
                                await api.promoteGap(record.id, index, "not_yet");
                                setPromoted((p) => ({ ...p, [index]: "not yet — still shaky" }));
                              })
                            }
                          >
                            Not yet — still shaky
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </section>
              )}

              <section>
                <h2>Archive</h2>
                <p className="muted">
                  Uploads all documents to GCS and writes analytics rows — this is what
                  makes the application permanent and feeds Career Growth.
                </p>
                <button
                  className="primary"
                  onClick={() =>
                    run("archive", async () => {
                      await api.archiveApplication(record.id);
                      await refresh();
                    })
                  }
                  disabled={busy === "archive"}
                >
                  {busy === "archive" ? "Archiving…" : "Archive"}
                </button>
              </section>
            </>
          )}

          {record.status === "archived" && (
            <section>
              <h2>Archive</h2>
              <p>
                Stored at <code>{record.gcs_path}</code>
              </p>
              <p>
                {["resume.pdf", "resume.docx", "cover_letter.txt", "report.html", "gap_report.json"].map(
                  (f) => (
                    <span key={f}>
                      <a href={api.archivedFileUrl(record.id, f)} target="_blank" rel="noreferrer">
                        {f}
                      </a>
                      {" · "}
                    </span>
                  )
                )}
              </p>
            </section>
          )}
        </>
      )}

      {error && <p className="error">{error}</p>}
    </div>
  );
}
