export interface Contact {
  name: string;
  location: string;
  email: string;
  phone: string;
  linkedin: string;
  github: string;
}

export interface SkillCategory {
  name: string;
  items: string[];
}

export interface Skills {
  categories: SkillCategory[];
}

export interface Bullet {
  id: string;
  text: string;
  core: boolean;
  tags: string[];
}

export interface Experience {
  id: string;
  company: string;
  title: string;
  location: string;
  start: string;
  end: string;
  bullets: Bullet[];
}

export interface ProjectBullet {
  id: string;
  text: string;
}

export interface Project {
  id: string;
  name: string;
  bullets: ProjectBullet[];
}

export interface Education {
  degree: string;
  institution: string;
  year: string;
}

export interface Language {
  name: string;
  level: string;
}

export interface Segment {
  text: string;
  bold: boolean;
}

export interface ResumeJSON {
  contact: Contact;
  summary: string;
  summary_segments: Segment[];
  accomplishments: Bullet[];
  skills: Skills;
  experience: Experience[];
  projects: Project[];
  education: Education[];
  languages: Language[];
  certifications: string[];
}

export interface Requirement {
  requirement: string;
  category: string;
  keyword_variants: string[];
}

export interface NiceToHaveRequirement {
  requirement: string;
  category: string;
}

export interface JDAnalysis {
  role_title: string;
  seniority_signal: string;
  must_have_requirements: Requirement[];
  nice_to_have_requirements: NiceToHaveRequirement[];
  ats_keywords: string[];
  company_context: { industry: string; product_signal: string };
}

export interface BulletPlanItem {
  bullet_id: string;
  final_text: string;
  keywords_injected: string[];
  injection_type: "renamed_existing" | "none";
}

export interface TailoringPlan {
  tailored_summary: string;
  experience_order: string[];
  bullet_order: Record<string, string[]>;
  skills_displayed: string[];
  skills_deprioritized: string[];
  bullet_plan: BulletPlanItem[];
}

export interface GapEducation {
  what_it_is: string;
  typical_use_case_for_role: string;
  sample_scenario: string;
  closest_known_alternative: string;
  other_alternatives_in_market: string[];
}

export type GapStatus =
  | "have_experience"
  | "partial_experience"
  | "no_experience"
  | "not_reviewed";

export interface GapUserResponse {
  status: GapStatus;
  user_note: string;
  reviewed_at: string;
}

export interface GapItem {
  requirement: string;
  jd_context: string;
  canonical_id: string;
  reusable_note: string;
  reusable_status: string;
  reused_from: string;
  education: GapEducation;
  user_response: GapUserResponse;
  proposed_bullet: string;
  proposed_target_exp_id: string;
}

export interface HandsOnLab {
  title: string;
  why: string;
  est_hours: number;
}

export interface StudyResource {
  title: string;
  url: string;
  type: string;
}

export interface StudyPlan {
  requirement: string;
  priority: "high" | "medium" | "low";
  study_topics: string[];
  hands_on_labs: HandsOnLab[];
  interview_talking_points: string[];
  resources: StudyResource[];
}

export type ApplicationStatus =
  | "analyzing"
  | "pending_review"
  | "approved"
  | "finalized"
  | "archived"
  | "discarded";

export interface DiffSummary {
  added: string[];
  removed: string[];
  reordered: string[];
  reworded: string[];
}

export interface RoleFitAssessment {
  role_category: string;
  requires_deep_dev_skills: boolean;
  core_dev_languages_required: string[];
  skill_match_pct: number;
  decision: "process" | "warn" | "skip";
  decision_reason: string;
}

export interface InterviewLens {
  persona_title: string;
  what_id_probe: string[];
  red_flags: string[];
  reference_points_if_unsure: string[];
}

export interface ApplicationRecord {
  id: string;
  company: string;
  role_title: string;
  status: ApplicationStatus;
  created_at: string;
  jd_analysis: JDAnalysis | null;
  tailoring_plan: TailoringPlan | null;
  gaps: GapItem[];
  study_plans: StudyPlan[];
  diff_summary: DiffSummary;
  cover_letter: string;
  approved_at: string | null;
  gcs_path: string;
  role_fit: RoleFitAssessment | null;
  interview_lens: InterviewLens | null;
}

export interface AtsReport {
  covered: string[];
  missing: string[];
  coverage_ratio: number;
}

export interface CatalogEntry {
  canonical_id: string;
  canonical_name: string;
  aliases: string[];
  category: string;
  demand_count: number;
  demand_sources: { company: string; role: string; date: string }[];
  user_status: GapStatus;
  status_history: { date: string; status: string; source_application_id: string; note: string }[];
  in_base_resume: boolean;
  priority_score: number;
  last_seen: string;
  promote_suggestion_dismissed: boolean;
}

export interface StudyGuideLab {
  title: string;
  repo_url: string;
  why_this_lab: string;
  est_hours: number;
}

export interface StudyGuideStep {
  step_number: number;
  title: string;
  goal: string;
  topics: string[];
  hands_on_lab: StudyGuideLab | null;
  sample_project: { title: string; repo_url: string; description: string } | null;
  interview_talking_points: string[];
  est_hours: number;
  done: boolean;
}

export interface RecommendedBook {
  title: string;
  authors: string;
  why: string;
  oreilly_url: string;
  publisher_url: string;
}

export interface CuratedResource {
  type: "blog" | "youtube" | "udemy";
  title: string;
  url: string;
  why_this_one: string;
  url_valid: boolean;
}

export interface StudyGuideEntry {
  canonical_id: string;
  priority_score: number;
  why_it_matters: string;
  recommended_books: RecommendedBook[];
  steps: StudyGuideStep[];
  curated_resources: CuratedResource[];
  interview_readiness_checklist: string[];
  last_curated_at: string;
  url_validation_status: string;
}

export interface TrendGapItem {
  requirement: string;
  jd_context: string;
  canonical_id: string;
  source_postings: string[];
  education: GapEducation;
  user_response: GapUserResponse;
}

export interface TrendScanBatch {
  id: string;
  created_at: string;
  posting_count: number;
  role_titles: string[];
  review_items: TrendGapItem[];
  auto_counted: string[];
  skipped_postings: { role_title: string; reason: string }[];
  status: "pending_review" | "completed";
  completed_at: string;
}

export interface UserSettings {
  linkedin_url: string;
  medium_url: string;
  newsletters: string[];
  oreilly_access: boolean;
  preferred_portals: string[];
}

export interface RecurringGap {
  requirement: string;
  theme: string;
  times_required: number;
  times_gapped: number;
  priority: string;
  reasoning: string;
}

export interface PromotableExperience {
  requirement: string;
  canonical_id: string;
  theme: string;
  confirmed_in_applications: number;
  suggested_action: string;
  dismissed: boolean;
}

export interface MarketFitReport {
  period: { start?: string; end?: string; applications_analyzed?: number };
  match_rate_trend: { date: string; company: string; match_pct: number | null }[];
  top_recurring_gaps: RecurringGap[];
  promotable_experience_not_yet_in_base_resume: PromotableExperience[];
  resume_structural_suggestions: { detail: string }[];
  study_plan_priority_ranked: string[];
  generated_at: string;
}
