import { useState } from "react";
import * as api from "./api";
import type { GapItem, GapStatus } from "./types";

export default function GapCard({
  applicationId,
  gapIndex,
  gap,
  onUpdated,
}: {
  applicationId: string;
  gapIndex: number;
  gap: GapItem;
  onUpdated: (gap: GapItem) => void;
}) {
  const [note, setNote] = useState(gap.user_response.user_note);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingProposal, setEditingProposal] = useState(false);
  const [proposalDraft, setProposalDraft] = useState(gap.proposed_bullet);
  const [justSaved, setJustSaved] = useState(false);

  const reviewed = gap.user_response.status !== "not_reviewed";

  async function reuse() {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.reuseGap(applicationId, gapIndex);
      setProposalDraft(updated.proposed_bullet);
      setNote(updated.user_response.user_note);
      onUpdated(updated);
      setJustSaved(true);
      setTimeout(() => setJustSaved(false), 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reuse failed");
    } finally {
      setBusy(false);
    }
  }

  async function respond(status: GapStatus) {
    if ((status === "have_experience" || status === "partial_experience") && !note.trim()) {
      setError("Describe what you actually did — the app never adds content without your own words.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await api.respondToGap(applicationId, gapIndex, status, note);
      setProposalDraft(updated.proposed_bullet);
      onUpdated(updated);
      setJustSaved(true);
      setTimeout(() => setJustSaved(false), 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save response");
    } finally {
      setBusy(false);
    }
  }

  async function saveProposalEdit() {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.editProposedBullet(applicationId, gapIndex, proposalDraft);
      setEditingProposal(false);
      onUpdated(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save edit");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className={`card gap-card ${reviewed ? `gap-${gap.user_response.status}` : ""} ${
        justSaved ? "just-saved" : ""
      }`}
    >
      <div className="gap-header">
        <h3>{gap.requirement}</h3>
        <span className={`pill ${reviewed ? gap.user_response.status : ""}`}>
          {reviewed ? gap.user_response.status.replace("_", " ") : "not reviewed"}
        </span>
      </div>
      {gap.jd_context && <p className="jd-context">JD: “{gap.jd_context}”</p>}

      {!reviewed && gap.reusable_note && (
        <div className="reuse-banner">
          You previously confirmed <strong>{gap.requirement}</strong>{" "}
          ({gap.reusable_status.replace("_", " ")}): “{gap.reusable_note}”
          <div className="gap-actions">
            <button className="primary" onClick={reuse} disabled={busy}>
              Reuse this confirmation
            </button>
          </div>
        </div>
      )}

      <div className="gap-education">
        <p><strong>What it is:</strong> {gap.education.what_it_is}</p>
        <p><strong>How this role touches it:</strong> {gap.education.typical_use_case_for_role}</p>
        <p><strong>Scenario:</strong> {gap.education.sample_scenario}</p>
        <p className="transfer"><strong>You already know:</strong> {gap.education.closest_known_alternative}</p>
        {gap.education.other_alternatives_in_market.length > 0 && (
          <p><strong>Comparable tools:</strong> {gap.education.other_alternatives_in_market.join(", ")}</p>
        )}
      </div>

      <div className="gap-prompt">
        <p><strong>Have you done anything like this?</strong></p>
        <textarea
          rows={2}
          placeholder="If yes or partial: what did you actually do? (your own words — required)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          disabled={busy}
        />
        <div className="gap-actions">
          <button onClick={() => respond("have_experience")} disabled={busy}>
            Yes, I've done this
          </button>
          <button onClick={() => respond("partial_experience")} disabled={busy}>
            Partial
          </button>
          <button onClick={() => respond("no_experience")} disabled={busy}>
            No
          </button>
        </div>
        {error && <p className="error">{error}</p>}
      </div>

      {gap.proposed_bullet && (
        <div className="proposal">
          <p><strong>Proposed addition</strong> (attaches to {gap.proposed_target_exp_id}; nothing is applied until you approve the diff):</p>
          {editingProposal ? (
            <>
              <textarea
                rows={3}
                value={proposalDraft}
                onChange={(e) => setProposalDraft(e.target.value)}
              />
              <button onClick={saveProposalEdit} disabled={busy}>Save edit</button>
              <button onClick={() => setEditingProposal(false)} disabled={busy}>Cancel</button>
            </>
          ) : (
            <>
              <p className="proposed-text">+ {gap.proposed_bullet}</p>
              <button onClick={() => { setProposalDraft(gap.proposed_bullet); setEditingProposal(true); }}>
                Edit text
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
