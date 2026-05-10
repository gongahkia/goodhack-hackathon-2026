import type { BackendNode, DayScheduleResponse, ProcessTranscriptionResponse, ScheduleConflict } from './api'
import type { ConflictItem } from './components/ConflictPanel'
import type { Task } from './types'

function str(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function bool(value: unknown): boolean {
  return value === true
}

function timeLabelFromHHMM(value: unknown): string | undefined {
  const raw = str(value)
  if (!raw) return undefined
  const match = raw.match(/^(\d{1,2}):(\d{2})$/)
  if (!match) return raw
  const hours = Number(match[1])
  const minutes = Number(match[2])
  const hour = hours % 12 || 12
  return `${hour}:${String(minutes).padStart(2, '0')} ${hours < 12 ? 'AM' : 'PM'}`
}

export function timeLabelToHHMM(value: string | undefined): string | undefined {
  if (!value) return undefined
  const match = value.trim().match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i)
  if (!match) return undefined
  let hours = Number(match[1])
  const minutes = Number(match[2])
  const period = match[3].toUpperCase()
  if (period === 'PM' && hours !== 12) hours += 12
  if (period === 'AM' && hours === 12) hours = 0
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

function nodeBase(node: BackendNode) {
  return {
    backendNodeId: node.id,
    backendType: node.type as Task['backendType'],
    backendStatus: node.status,
    createdAt: node.created_at,
  }
}

function taskDetail(node: BackendNode): string | undefined {
  return str(node.payload.user_visible_description)
    ?? str(node.payload.description)
    ?? str(node.payload.summary)
    ?? str(node.payload.basis)
    ?? str(node.payload.original_instruction_redacted)
}

function compact(value: string | undefined, max = 110): string | undefined {
  if (!value) return undefined
  return value.length > max ? `${value.slice(0, max - 3).trimEnd()}...` : value
}

function cleanResearchQuestion(value: string | undefined): string | undefined {
  return str(value?.replace(/^What support, grants, equipment, or care steps should be checked for:\s*/i, ''))
}

export function reviewTasksFromProcess(result: ProcessTranscriptionResponse): Task[] {
  const daily = result.daily_tasks.map(node => {
    const time = timeLabelFromHHMM(node.payload.scheduled_time ?? node.payload.time)
    return {
      id: node.id,
      category: 'daily' as const,
      title: str(node.payload.title) ?? 'Daily task',
      detail: taskDetail(node),
      consultationNote: str(node.payload.original_instruction_redacted),
      timeLabel: time,
      noFixedTime: !time,
      completed: false,
      ...nodeBase(node),
    }
  })
  const appointments = result.appointment_candidates.map(appointmentTask)
  const research = result.ad_hoc_research_tasks.map(researchTask)
  return [...daily, ...appointments, ...research]
}

export function tasksFromBackend(
  schedule: DayScheduleResponse,
  appointments: BackendNode[],
  researchTasks: BackendNode[],
  recommendations: BackendNode[],
  previous: Task[],
): Task[] {
  const completed = new Map(previous.filter(t => t.backendNodeId).map(t => [t.backendNodeId, t.completed]))
  const manual = previous.filter(t => !t.backendNodeId)
  const backendTasks = [
    ...schedule.items.map(item => ({
      id: item.node_id,
      category: 'daily' as const,
      title: item.title,
      detail: item.detail ?? undefined,
      timeLabel: item.bucket === 'scheduled' ? item.time_label : undefined,
      noFixedTime: item.bucket === 'goal',
      completed: completed.get(item.node_id) ?? false,
      createdAt: item.start_at ?? new Date().toISOString(),
      backendNodeId: item.node_id,
      backendType: 'daily_task' as const,
      backendStatus: item.status,
    })),
    ...appointments.map(appointmentTask),
    ...researchTasks.map(researchTask),
    ...recommendations.map(recommendationTask),
  ].map(task => ({ ...task, completed: task.backendNodeId ? completed.get(task.backendNodeId) ?? task.completed : task.completed }))
  return [...backendTasks, ...manual]
}

export function conflictsFromSchedule(schedule: DayScheduleResponse): ConflictItem[] {
  return schedule.conflicts
    .map(conflictToItem)
    .filter((item): item is ConflictItem => item !== null)
}

export function dailyPatchFromTask(task: Task): Record<string, unknown> {
  const patch: Record<string, unknown> = { title: task.title }
  if (task.detail !== undefined) patch.description = task.detail
  const scheduledTime = timeLabelToHHMM(task.timeLabel)
  if (scheduledTime) patch.scheduled_time = scheduledTime
  return patch
}

export function nodePatchFromTask(task: Task): Record<string, unknown> {
  if (task.backendType === 'ad_hoc_research_task') {
    return { display_title: task.title }
  }
  if (task.backendType === 'appointment_candidate') {
    return { title: task.title, date: task.dueDate, notes: task.detail ?? '' }
  }
  return { title: task.title, summary: task.detail ?? '' }
}

function appointmentTask(node: BackendNode): Task {
  const dueDate = str(node.payload.date)
  const timeLabel = timeLabelFromHHMM(node.payload.time)
  return {
    id: node.id,
    category: 'adhoc',
    title: str(node.payload.title) ?? 'Appointment',
    detail: taskDetail(node) ?? str(node.payload.location),
    dueDate,
    timeLabel,
    completed: false,
    urgent: str(node.payload.urgency) === 'urgent' || bool(node.payload.urgent),
    calendarWriteStatus: str(node.payload.calendar_write_status),
    nextSteps: node.payload.calendar_write_status === 'pending_user_approval' ? [{ label: 'Add to Google Calendar' }] : [],
    ...nodeBase(node),
  }
}

function researchTask(node: BackendNode): Task {
  const question = str(node.payload.question)
  const basis = str(node.payload.basis) ?? cleanResearchQuestion(question)
  return {
    id: node.id,
    category: 'adhoc',
    title: str(node.payload.display_title) ?? str(node.payload.title) ?? 'Research support options',
    detail: str(node.payload.summary) ?? (basis ? `Checking support options for: ${compact(basis)}` : taskDetail(node)),
    completed: false,
    researchStatus: str(node.payload.research_status) ?? node.status,
    nextSteps: [{ label: node.status === 'approved' ? 'Research ready' : 'Research running' }],
    ...nodeBase(node),
  }
}

function recommendationTask(node: BackendNode): Task {
  return {
    id: node.id,
    category: 'adhoc',
    title: str(node.payload.title) ?? 'Recommendation',
    detail: taskDetail(node),
    completed: false,
    recommendationId: node.id,
    nextSteps: recommendationNextSteps(node),
    ...nodeBase(node),
  }
}

function recommendationNextSteps(node: BackendNode) {
  const raw = node.payload.next_steps
  if (Array.isArray(raw)) {
    return raw.map(item => ({ label: String(item) })).filter(item => item.label.trim())
  }
  return []
}

function conflictToItem(conflict: ScheduleConflict): ConflictItem | null {
  const start = conflict.calendar_event_start_at ?? conflict.task_time?.start_at
  const end = conflict.calendar_event_end_at ?? conflict.task_time?.end_at
  if (!start || !end) return null
  const startDate = new Date(start)
  const endDate = new Date(end)
  return {
    id: conflict.id,
    eventTitle: conflict.calendar_event_title ?? 'Calendar event',
    startLabel: labelFromDate(startDate),
    endLabel: labelFromDate(endDate),
    startMin: startDate.getHours() * 60 + startDate.getMinutes(),
    endMin: endDate.getHours() * 60 + endDate.getMinutes(),
    acknowledged: false,
  }
}

function labelFromDate(value: Date): string {
  const hour = value.getHours() % 12 || 12
  return `${hour}:${String(value.getMinutes()).padStart(2, '0')} ${value.getHours() < 12 ? 'AM' : 'PM'}`
}
