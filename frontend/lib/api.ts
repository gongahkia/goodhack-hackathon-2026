import type { AppNotification, CarePlanReview, EventDetail, ForecastItem, KgNode, MemoryProfile, PatientSummary, ReasoningLog, VerifiedContent } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    },
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
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
  forecast: () => request<ForecastItem[]>("/forecast"),
  resourceSearch: (topic: string, condition?: string) =>
    request<VerifiedContent[]>(`/resources/search?topic=${encodeURIComponent(topic)}${condition ? `&condition=${encodeURIComponent(condition)}` : ""}`),
  grantSearch: (condition: string) => request<VerifiedContent[]>(`/grants/search?condition=${encodeURIComponent(condition)}`),
  notifications: () => request<AppNotification[]>("/notifications"),
  records: () => request<Array<KgNode & { forward_actions: KgNode[] }>>("/records"),
  audit: () => request<ReasoningLog[]>("/audit"),
  auditLog: (id: string) => request<ReasoningLog>(`/audit/${id}`),
  status: (id: string, status: string, feedback?: { usefulness_score?: number; feedback_note?: string; steer?: string }) =>
    request<KgNode>(`/nodes/${id}/status`, { method: "PATCH", body: JSON.stringify({ status, ...(feedback || {}) }) }),
  editNode: (id: string, payload: Record<string, any>) =>
    request<KgNode>(`/nodes/${id}`, { method: "PATCH", body: JSON.stringify({ payload, status: "edited" }) })
};
