export type NodeStatus = "pending_review" | "approved" | "dismissed" | "edited";

export type KgNode = {
  id: string;
  type: string;
  payload: Record<string, any>;
  created_by: "agent" | "system" | "user";
  created_at: string;
  reasoning_log_id?: string | null;
  status: NodeStatus;
};

export type KgEdge = {
  id: string;
  from_node: string;
  to_node: string;
  type: string;
  created_at: string;
};

export type ReasoningLog = {
  id: string;
  trigger: string;
  steps: Array<Record<string, any>>;
  conclusion?: string | null;
  created_at: string;
};

export type EventDetail = KgNode & {
  source_records: KgNode[];
  related_nodes: KgNode[];
  related_edges: KgEdge[];
  reasoning_log?: ReasoningLog | null;
  reasoning_narrative?: string[];
  appointment_prep?: AppointmentPrep | null;
};

export type EvidenceSummary = {
  id: string;
  type: string;
  title?: string | null;
  recorded_at?: string | null;
};

export type AppointmentPrep = {
  appointment_id: string;
  generated_at: string;
  title?: string | null;
  symptoms_to_mention: string[];
  medication_notes: string[];
  therapy_mobility_notes: string[];
  questions_for_clinician: string[];
  long_term_concerns: string[];
  recurring_concerns: string[];
  previous_questions: string[];
  unresolved_advice: string[];
  revisit_next_time: string[];
  evidence: EvidenceSummary[];
};

export type MemoryProfile = {
  feedback_count: number;
  by_status: Record<string, number>;
  by_action_type: Record<string, Record<string, number>>;
  average_scores: Record<string, number>;
  steering: Record<string, Record<string, number>>;
  learned_preferences: Array<{ kind: string; action_type: string; reason: string }>;
  recent_edits: Array<{ target_node_id: string; title?: string | null; fields: string[]; created_at: string }>;
};

export type VerifiedContent = {
  title: string;
  source: string;
  url?: string | null;
  snippet: string;
  published_at?: string | null;
  retrieved_at: string;
  verification_status: "safe_to_show" | "needs_review" | "reject";
  recency_status?: "current" | "aging" | "old" | "unknown" | string;
  secondary_verification?: "openai" | "not_run" | "failed_open" | "not_returned" | string;
  reason: string;
};

export type CarePlanReview = {
  generated_at: string;
  record_count: number;
  condition_count: number;
  pending_review_count: number;
  upcoming_30_day_count: number;
  next_actions: Array<{ id: string; title?: string; action_type?: string; start_at?: string; status: NodeStatus }>;
  memory: MemoryProfile;
  memory_instructions: string[];
  narrative: string[];
};

export type ForecastItem = {
  id: string;
  title: string;
  category: "grant" | "equipment" | "care_service" | "home_modification" | string;
  status: NodeStatus;
  target_date?: string | null;
  summary?: string | null;
  agency?: string | null;
  apply_url?: string | null;
  missing_documents: string[];
  deadline_conflicts: string[];
  capacity: { weekly_action_count: number; risk: "low" | "medium" | "high" | string; note: string };
  timeline: Array<{ label: string; detail: string }>;
  evidence: EvidenceSummary[];
};

export type PatientSummary = {
  patient_id: string;
  name: string;
  age: number;
  citizenship: string;
  caregiver: string;
  living_arrangement: string;
  key_conditions: string[];
};

export type AppNotification = {
  id: string;
  kind: "review" | "approved" | "dismissed" | "edited" | "system" | string;
  title: string;
  body: string;
  created_at: string;
  href?: string | null;
  source_node_id?: string | null;
  node_status?: NodeStatus | null;
  occurred_at?: string | null;
};
