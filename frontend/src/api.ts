import type {
  ApplicationRecord,
  AtsReport,
  CatalogEntry,
  GapItem,
  GapStatus,
  MarketFitReport,
  ResumeJSON,
  StudyGuideEntry,
  StudyPlan,
  TrendGapItem,
  TrendScanBatch,
  UserSettings,
} from "./types";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail ?? `Request failed: ${res.status}`);
  }
  return res.json();
}

export function saveBaseResume(resume: ResumeJSON) {
  return request<ResumeJSON>("/onboarding/resume", {
    method: "POST",
    body: JSON.stringify(resume),
  });
}

export function tagCore() {
  return request<{ core_bullet_ids: string[] }>("/onboarding/tag-core", { method: "POST" });
}

export function createApplication(company: string, jobDescription: string, companyContext = "") {
  return request<ApplicationRecord>("/applications", {
    method: "POST",
    body: JSON.stringify({
      company,
      job_description: jobDescription,
      company_context: companyContext,
    }),
  });
}

export function listApplications() {
  return request<ApplicationRecord[]>("/applications");
}

export function getApplication(id: string) {
  return request<ApplicationRecord>(`/applications/${id}`);
}

export function respondToGap(
  applicationId: string,
  gapIndex: number,
  status: GapStatus,
  userNote: string,
  targetExpId = ""
) {
  return request<GapItem>(`/applications/${applicationId}/gaps/${gapIndex}/respond`, {
    method: "POST",
    body: JSON.stringify({ status, user_note: userNote, target_exp_id: targetExpId }),
  });
}

export function editProposedBullet(applicationId: string, gapIndex: number, text: string) {
  return request<GapItem>(`/applications/${applicationId}/gaps/${gapIndex}/edit-proposal`, {
    method: "POST",
    body: JSON.stringify({ proposed_bullet: text }),
  });
}

export function generateStudyPlans(applicationId: string) {
  return request<StudyPlan[]>(`/applications/${applicationId}/study-plan`, { method: "POST" });
}

export function approveApplication(applicationId: string) {
  return request<ApplicationRecord>(`/applications/${applicationId}/approve`, {
    method: "POST",
  });
}

export function generateCoverLetter(applicationId: string) {
  return request<{ cover_letter_text: string; fabrication_check: Record<string, unknown> }>(
    `/applications/${applicationId}/cover-letter`,
    { method: "POST" }
  );
}

export function getAtsReport(applicationId: string) {
  return request<AtsReport>(`/applications/${applicationId}/ats-report`);
}

export function exportUrl(applicationId: string, kind: "docx" | "pdf") {
  return `${API_BASE}/applications/${applicationId}/resume.${kind}`;
}

export function reuseGap(applicationId: string, gapIndex: number, targetExpId = "") {
  return request<GapItem>(`/applications/${applicationId}/gaps/${gapIndex}/reuse`, {
    method: "POST",
    body: JSON.stringify({ target_exp_id: targetExpId }),
  });
}

export function finalizeApplication(applicationId: string) {
  return request<ApplicationRecord>(`/applications/${applicationId}/finalize`, {
    method: "POST",
  });
}

export function promoteGap(
  applicationId: string,
  gapIndex: number,
  decision: "add_to_base" | "this_application_only" | "not_yet"
) {
  return request<ResumeJSON>(`/applications/${applicationId}/gaps/${gapIndex}/promote`, {
    method: "POST",
    body: JSON.stringify({ decision }),
  });
}

export function archiveApplication(applicationId: string) {
  return request<ApplicationRecord>(`/applications/${applicationId}/archive`, {
    method: "POST",
  });
}

export function archivedFileUrl(applicationId: string, filename: string) {
  return `${API_BASE}/applications/${applicationId}/archived/${filename}`;
}

export function discardApplication(applicationId: string) {
  return request<ApplicationRecord>(`/applications/${applicationId}/discard`, {
    method: "POST",
  });
}

export function dismissPromoteSuggestion(canonicalId: string) {
  return request<{ dismissed: string }>(`/catalog/${canonicalId}/dismiss-suggestion`, {
    method: "POST",
  });
}

export function getCatalog() {
  return request<CatalogEntry[]>("/catalog");
}

export function listStudyGuides() {
  return request<StudyGuideEntry[]>("/study-guide");
}

export function curateStudyGuide(canonicalId: string) {
  return request<StudyGuideEntry>(`/study-guide/${canonicalId}/curate`, { method: "POST" });
}

export function markStudyStep(canonicalId: string, stepNumber: number, done: boolean) {
  return request<StudyGuideEntry>(`/study-guide/${canonicalId}/mark-step`, {
    method: "POST",
    body: JSON.stringify({ step_number: stepNumber, done }),
  });
}

export function getSettings() {
  return request<UserSettings>("/settings");
}

export function saveSettings(settings: UserSettings) {
  return request<UserSettings>("/settings", {
    method: "POST",
    body: JSON.stringify(settings),
  });
}

export function getMarketFit(refresh = false) {
  return request<MarketFitReport>(`/analysis/market-fit${refresh ? "?refresh=true" : ""}`);
}

export function createTrendScan(postings: string[]) {
  return request<TrendScanBatch>("/trend-scan", {
    method: "POST",
    body: JSON.stringify({ postings }),
  });
}

export function listTrendScans() {
  return request<TrendScanBatch[]>("/trend-scan");
}

export function respondTrendItem(
  batchId: string,
  itemIndex: number,
  status: GapStatus,
  userNote: string
) {
  return request<TrendGapItem>(`/trend-scan/${batchId}/items/${itemIndex}/respond`, {
    method: "POST",
    body: JSON.stringify({ status, user_note: userNote }),
  });
}

export function completeTrendScan(batchId: string) {
  return request<{ batch_id: string; study_guides_regenerated: string[] }>(
    `/trend-scan/${batchId}/complete`,
    { method: "POST" }
  );
}
