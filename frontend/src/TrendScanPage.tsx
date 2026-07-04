import { useEffect, useState } from "react";
import * as api from "./api";
import type { GapStatus, TrendScanBatch } from "./types";

export default function TrendScanPage({ onGuidesChanged }: { onGuidesChanged: () => void }) {
  const [postings, setPostings] = useState<string[]>([""]);
  const [batches, setBatches] = useState<TrendScanBatch[]>([]);
  const [active, setActive] = useState<TrendScanBatch | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [completionMsg, setCompletionMsg] = useState<string | null>(null);

  useEffect(() => {
    api.listTrendScans().then((b) => {
      setBatches(b);
      const pending = b.find((x) => x.status === "pending_review");
      if (pending) setActive(pending);
    }).catch(() => {});
  }, []);

  async function scan() {
    setBusy("scan");
    setError(null);
    try {
      const batch = await api.createTrendScan(postings.filter((p) => p.trim()));
      setActive(batch);
      setBatches((b) => [batch, ...b]);
      setPostings([""]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed");
    } finally {
      setBusy(null);
    }
  }

  async function respond(index: number, status: GapStatus) {
    if (!active) return;
    const note = notes[index] ?? "";
    if ((status === "have_experience" || status === "partial_experience") && !note.trim()) {
      setError("Describe what you actually did — required for Yes/Partial.");
      return;
    }
    setBusy(`item${index}`);
    setError(null);
    try {
      const item = await api.respondTrendItem(active.id, index, status, note);
      const review_items = [...active.review_items];
      review_items[index] = item;
      setActive({ ...active, review_items });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(null);
    }
  }

  async function complete() {
    if (!active) return;
    setBusy("complete");
    setError(null);
    try {
      const res = await api.completeTrendScan(active.id);
      setCompletionMsg(
        res.study_guides_regenerated.length
          ? `Study guides refreshed: ${res.study_guides_regenerated.join(", ")}`
          : "Scan completed — demand recorded, no guides needed regeneration."
      );
      setActive({ ...active, status: "completed" });
      onGuidesChanged(); // Study Room refreshes without a page reload (DoD #4)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Complete failed");
    } finally {
      setBusy(null);
    }
  }

  const unreviewed =
    active?.review_items.filter((i) => i.user_response.status === "not_reviewed").length ?? 0;

  return (
    <div>
      <h1>Market Trends &amp; Study Room — intake</h1>
      <p className="muted">
        Paste one or many job postings you're curious about (no application, no
        tailoring). They feed skill-demand tracking and the Study Guide.
      </p>

      {!active || active.status === "completed" ? (
        <section>
          <h2>New scan</h2>
          {postings.map((p, i) => (
            <textarea
              key={i}
              rows={6}
              value={p}
              placeholder={`Job posting ${i + 1}`}
              onChange={(e) => {
                const next = [...postings];
                next[i] = e.target.value;
                setPostings(next);
              }}
            />
          ))}
          <p>
            <button onClick={() => setPostings([...postings, ""])}>＋ Add another posting</button>{" "}
            <button
              className="primary"
              onClick={scan}
              disabled={busy === "scan" || !postings.some((p) => p.trim())}
            >
              {busy === "scan"
                ? `Scanning ${postings.filter((p) => p.trim()).length} posting(s)… (minutes)`
                : `Scan ${postings.filter((p) => p.trim()).length || ""} posting(s)`}
            </button>
          </p>
          {completionMsg && <p className="pill ok">{completionMsg}</p>}
        </section>
      ) : (
        <section>
          <h2>
            Batch review — {active.posting_count} posting(s), one consolidated list{" "}
            <span className="num muted">
              {active.review_items.length - unreviewed}/{active.review_items.length}
            </span>
          </h2>
          <p className="muted">Roles scanned: {active.role_titles.join(" · ")}</p>
          {active.auto_counted.length > 0 && (
            <p className="reuse-banner">
              Already confirmed previously (counted silently, no re-asking):{" "}
              {active.auto_counted.join(", ")}
            </p>
          )}

          {active.review_items.map((item, i) => {
            const reviewed = item.user_response.status !== "not_reviewed";
            return (
              <div
                key={item.canonical_id}
                className={`card gap-card ${reviewed ? `gap-${item.user_response.status}` : ""}`}
              >
                <div className="gap-header">
                  <h3>{item.requirement}</h3>
                  <span className={`pill ${reviewed ? item.user_response.status : ""}`}>
                    {reviewed ? item.user_response.status.replace("_", " ") : "not reviewed"}
                  </span>
                </div>
                <p className="jd-context">
                  Seen in: {item.source_postings.join(" · ")} — “{item.jd_context}”
                </p>
                <div className="gap-education">
                  <p><strong>What it is:</strong> {item.education.what_it_is}</p>
                  <p><strong>How this role touches it:</strong> {item.education.typical_use_case_for_role}</p>
                  <p className="transfer"><strong>You already know:</strong> {item.education.closest_known_alternative}</p>
                </div>
                {/* Deliberately NO bullet drafting here — trend scans never touch ResumeJSON */}
                <textarea
                  rows={2}
                  placeholder="If yes/partial: what did you actually do? (your own words)"
                  value={notes[i] ?? item.user_response.user_note}
                  onChange={(e) => setNotes({ ...notes, [i]: e.target.value })}
                  disabled={busy === `item${i}`}
                />
                <div className="gap-actions">
                  <button onClick={() => respond(i, "have_experience")} disabled={busy === `item${i}`}>
                    Yes, I've done this
                  </button>
                  <button onClick={() => respond(i, "partial_experience")} disabled={busy === `item${i}`}>
                    Partial
                  </button>
                  <button onClick={() => respond(i, "no_experience")} disabled={busy === `item${i}`}>
                    No
                  </button>
                </div>
              </div>
            );
          })}

          <button
            className="primary"
            onClick={complete}
            disabled={busy === "complete" || unreviewed > 0}
          >
            {busy === "complete"
              ? "Completing… (regenerating study guides)"
              : unreviewed > 0
                ? `Review ${unreviewed} remaining first`
                : "Complete scan"}
          </button>
        </section>
      )}

      {batches.filter((b) => b.status === "completed").length > 0 && (
        <section>
          <h2>Past scans</h2>
          {batches
            .filter((b) => b.status === "completed")
            .map((b) => (
              <div key={b.id} className="card">
                <span className="num">{b.created_at.slice(0, 10)}</span> —{" "}
                {b.posting_count} posting(s): {b.role_titles.join(" · ")}{" "}
                <span className="pill archived">completed</span>
              </div>
            ))}
        </section>
      )}

      {error && <p className="error">{error}</p>}
    </div>
  );
}
