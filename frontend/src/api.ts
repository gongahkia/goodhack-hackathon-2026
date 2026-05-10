export interface BackendNode {
  id: string
  type: string
  payload: Record<string, unknown>
  created_at: string
  status: string
}

export interface CreateTranscriptionResponse {
  transcription_session: BackendNode
  transcript: BackendNode
  display_transcript?: string
}

export interface ProcessTranscriptionResponse {
  daily_tasks: BackendNode[]
  appointment_candidates: BackendNode[]
  ad_hoc_research_tasks: BackendNode[]
}

export interface ScheduleConflict {
  id: string
  node_id: string
  calendar_event_id: string | null
  calendar_event_title: string | null
  calendar_event_start_at: string | null
  calendar_event_end_at: string | null
  classification: string
  reason: string
  task_time?: { start_at?: string; end_at?: string }
  suggested_time?: string | null
  source: string
}

export interface ScheduleItem {
  node_id: string
  title: string
  detail?: string | null
  status: string
  bucket: 'scheduled' | 'goal'
  start_at?: string | null
  end_at?: string | null
  time_label: string
  schedule_source: string
  conflict?: ScheduleConflict | null
}

export interface CalendarEvent {
  id: string
  title: string
  start_at: string
  end_at: string
  busy: boolean
}

export interface DayScheduleResponse {
  date: string
  timezone: string
  items: ScheduleItem[]
  calendar_events: CalendarEvent[]
  conflicts: ScheduleConflict[]
  calendar_error?: { provider?: string; status_code?: number | null; message?: string } | null
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
const API_KEY = import.meta.env.VITE_API_KEY || ''

function apiUrl(path: string) {
  return `${API_BASE_URL}${path}`
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (API_KEY) headers.set('X-API-Key', API_KEY)
  const response = await fetch(apiUrl(path), { ...init, headers })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `Request failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function createTranscription(audio: Blob, language = 'en') {
  return request<CreateTranscriptionResponse>(`/transcriptions?language=${encodeURIComponent(language)}&include_display_text=true`, {
    method: 'POST',
    body: audio,
    headers: { 'Content-Type': audio.type || 'audio/webm' },
  })
}

export function processTranscription(sessionId: string) {
  return request<ProcessTranscriptionResponse>(`/transcriptions/${sessionId}/process`, { method: 'POST' })
}

export function getScheduleDay(date: string) {
  return request<DayScheduleResponse>(`/schedule/day?date=${encodeURIComponent(date)}`)
}

export function getAppointments() {
  return request<BackendNode[]>('/appointments')
}

export function getResearchTasks() {
  return request<BackendNode[]>('/research/tasks')
}

export function getRecommendations() {
  return request<BackendNode[]>('/recommendations')
}

export function getScheduleConflicts() {
  return request<BackendNode[]>('/schedule-conflicts')
}

export function getNotifications() {
  return request<unknown[]>('/notifications')
}

export function updateNodeStatus(nodeId: string, status: 'approved' | 'dismissed' | 'edited' | 'pending_review') {
  return request<BackendNode>(`/nodes/${nodeId}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  })
}

export function updateNode(nodeId: string, payload: Record<string, unknown>, status: 'edited' | 'approved' = 'edited') {
  return request<BackendNode>(`/nodes/${nodeId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ payload, status }),
  })
}

export function updateDailyTask(nodeId: string, payload: Record<string, unknown>) {
  return request<{ daily_task: BackendNode }>(`/tasks/daily/${nodeId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function runResearchTask(nodeId: string) {
  return request<unknown>(`/research/tasks/${nodeId}/run`, { method: 'POST' })
}

export function approveAppointmentCalendarWrite(nodeId: string) {
  return request<unknown>(`/appointments/${nodeId}/approve-calendar-write`, { method: 'POST' })
}
