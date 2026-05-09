import type { AppNotification, CaregiverNoteResult, CarePlanReview, EventDetail, ForecastItem, HumanEvalWorkflow, KgNode, MemoryProfile, PatientSummary, ReasoningLog, TranscriptionResult, VerifiedContent } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const API_WRITE_KEY = process.env.NEXT_PUBLIC_API_WRITE_KEY;
const CLINICIAN_REVIEW_KEY = process.env.NEXT_PUBLIC_CLINICIAN_REVIEW_KEY;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(API_WRITE_KEY ? { "X-API-Key": API_WRITE_KEY } : {}),
      ...(CLINICIAN_REVIEW_KEY ? { "X-Clinician-Key": CLINICIAN_REVIEW_KEY } : {}),
      ...(init?.headers || {})
    },
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

async function errorMessage(response: Response): Promise<string> {
  const body = await response.text();
  try {
    const parsed = JSON.parse(body);
    return typeof parsed.detail === "string" ? parsed.detail : body;
  } catch {
    return body;
  }
}

export const api = {
  health: () => request<{ ok: boolean; store: string }>("/health"),
  summary: () => request<PatientSummary>("/patient/summary"),
  reset: () => request<Record<string, any>>("/demo/reset", { method: "POST" }),
  events: () => request<KgNode[]>("/events"),
  event: (id: string) => request<EventDetail>(`/events/${id}`),
  calendarExportUrl: () => `${API_BASE}/calendar.ics`,
  calendarFeedUrl: () => `${API_BASE}/calendar/feed.ics`,
  memory: () => request<MemoryProfile>("/memory"),
  carePlanReview: () => request<CarePlanReview>("/care-plan/review"),
  carePlanRereason: () => request<{ reasoning_log_id: string; conclusion: string; review: CarePlanReview }>("/care-plan/rereason", { method: "POST" }),
  forecast: () => request<ForecastItem[]>("/forecast"),
  transcribe: async (audio: Blob) => {
    const response = await fetch(`${API_BASE}/transcribe`, {
      method: "POST",
      headers: {
        "Content-Type": audio.type || "audio/webm",
        ...(API_WRITE_KEY ? { "X-API-Key": API_WRITE_KEY } : {})
      },
      body: audio,
      cache: "no-store"
    });
    if (!response.ok) {
      throw new Error(await errorMessage(response));
    }
    return response.json() as Promise<TranscriptionResult>;
  },
  caregiverNote: (text: string) => request<CaregiverNoteResult>("/caregiver-notes", { method: "POST", body: JSON.stringify({ text }) }),
  clarifyIntent: (id: string, answer: string, payload_patch: Record<string, any>) =>
    request<{ node: KgNode; research_notes: KgNode[]; scheduled_actions: KgNode[] }>(`/care-intents/${id}/clarification`, {
      method: "PATCH",
      body: JSON.stringify({ answer, payload_patch })
    }),
  resourceSearch: (topic: string, condition?: string) =>
    request<VerifiedContent[]>(`/resources/search?topic=${encodeURIComponent(topic)}${condition ? `&condition=${encodeURIComponent(condition)}` : ""}`),
  grantSearch: (condition: string) => request<VerifiedContent[]>(`/grants/search?condition=${encodeURIComponent(condition)}`),
  notifications: () => request<AppNotification[]>("/notifications"),
  records: () => request<Array<KgNode & { forward_actions: KgNode[] }>>("/records"),
  audit: () => request<ReasoningLog[]>("/audit"),
  auditLog: (id: string) => request<ReasoningLog>(`/audit/${id}`),
  humanEval: () => request<HumanEvalWorkflow>("/eval/human"),
  submitHumanEval: (payload: {
    action_id: string;
    reviewer_role: string;
    provenance_score: number;
    reasoning_score: number;
    appropriateness_score: number;
    burden_score: number;
    notes?: string;
  }) => request<KgNode>("/eval/human", { method: "POST", body: JSON.stringify(payload) }),
  status: (id: string, status: string, feedback?: { usefulness_score?: number; feedback_note?: string; steer?: string }) =>
    request<KgNode>(`/nodes/${id}/status`, { method: "PATCH", body: JSON.stringify({ status, ...(feedback || {}) }) }),
  editNode: (id: string, payload: Record<string, any>) =>
    request<KgNode>(`/nodes/${id}`, { method: "PATCH", body: JSON.stringify({ payload, status: "edited" }) })
};
