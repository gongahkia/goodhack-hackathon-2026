export type TaskCategory = 'daily' | 'adhoc'

export interface NextStep {
  label: string
  url?: string
  phone?: string
}

export type RecurrenceMode = 'daily' | 'weekdays' | 'weekly' | 'custom'

export interface Recurrence {
  mode: RecurrenceMode
  weekdays?: number[]  // 0=Sun..6=Sat — used by 'weekly'/'custom'
}

export interface ActivePeriod {
  start: string  // ISO date YYYY-MM-DD
  end: string | null  // null = ongoing / no end
}

export interface Task {
  id: string
  category: TaskCategory
  title: string
  detail?: string
  consultationNote?: string
  timeLabel?: string
  noFixedTime?: boolean
  dueDate?: string
  completed: boolean
  urgent?: boolean
  createdAt: string
  nextSteps?: NextStep[]
  recurrence?: Recurrence
  activePeriod?: ActivePeriod
  backendNodeId?: string
  backendType?: 'daily_task' | 'appointment_candidate' | 'ad_hoc_research_task' | 'synthesized_recommendation'
  backendStatus?: string
  calendarWriteStatus?: string
  researchStatus?: string
  recommendationId?: string
}

export interface Recording {
  id: string
  sourceType: 'voice' | 'photo'
  label: string
  createdAt: string
  transcript?: string
}
