import { useState, useRef, useEffect } from 'react'
import { colors, font, radius, spacing, shadow } from './tokens'
import type { Task, TaskCategory } from './types'
import DailyTaskRow from './components/DailyTaskRow'
import DailyGoalRow from './components/DailyGoalRow'
import TaskRow from './components/TaskRow'
import CaptureSheet from './components/CaptureSheet'
import VoiceRecordingPanel from './components/VoiceRecordingPanel'
import ReviewSheet from './components/ReviewSheet'
import StatusBar from './components/StatusBar'
import TaskDetailSheet from './components/TaskDetailSheet'
import ConflictPanel, { type ConflictItem } from './components/ConflictPanel'
import {
  approveAppointmentCalendarWrite,
  getAppointments,
  getNotifications,
  getRecommendations,
  getResearchTasks,
  getScheduleConflicts,
  getScheduleDay,
  processTranscription,
  runResearchTask,
  updateDailyTask,
  updateNode,
  updateNodeStatus,
} from './api'
import {
  conflictsFromSchedule,
  dailyPatchFromTask,
  nodePatchFromTask,
  reviewTasksFromProcess,
  tasksFromBackend,
} from './backendMapping'

// ─── Helpers ──────────────────────────────────────────────────────────────────

const TABS: { id: TaskCategory; label: string }[] = [
  { id: 'daily', label: 'Daily Tasks' },
  { id: 'adhoc', label: 'Upcoming' },
]

const CARD_GAP = 12

function getGreeting() {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

function todayIso() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

function parseTaskMinutes(timeLabel: string): number {
  const [time, period] = timeLabel.split(' ')
  const [h, m] = time.split(':').map(Number)
  let hours = h
  if (period === 'PM' && h !== 12) hours += 12
  if (period === 'AM' && h === 12) hours = 0
  return hours * 60 + m
}

function taskChanged(a: Task | undefined, b: Task) {
  return !a || a.title !== b.title || a.detail !== b.detail || a.timeLabel !== b.timeLabel || a.dueDate !== b.dueDate
}

function getCurrentTaskId(tasks: Task[]): string | null {
  const now = new Date()
  const nowMin = now.getHours() * 60 + now.getMinutes()
  const WINDOW = 10
  const candidates = tasks.filter(
    t =>
      t.category === 'daily' &&
      !t.completed &&
      !!t.timeLabel &&
      Math.abs(parseTaskMinutes(t.timeLabel) - nowMin) <= WINDOW,
  )
  if (!candidates.length) return null
  return candidates
    .map(t => ({ ...t, diff: Math.abs(parseTaskMinutes(t.timeLabel!) - nowMin) }))
    .reduce((a, b) => (a.diff < b.diff ? a : b)).id
}

// ─── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [tab, setTab] = useState<TaskCategory>('daily')
  const [tasks, setTasks] = useState<Task[]>([])
  const [captureOpen, setCaptureOpen] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [reviewOpen, setReviewOpen] = useState(false)
  const [reviewInitialTasks, setReviewInitialTasks] = useState<Task[]>([])
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)
  const [createDefaults, setCreateDefaults] = useState<{
    category: 'daily' | 'adhoc'
    noFixedTime?: boolean
  } | null>(null)
  const [goalsExpanded, setGoalsExpanded] = useState(false)

  // Conflict state
  const [conflicts, setConflicts] = useState<ConflictItem[]>([])
  const [bellOpen, setBellOpen] = useState(false)
  // Y position within app container when rail is tapped; null = closed
  const [conflictPopupY, setConflictPopupY] = useState<number | null>(null)

  // Swipe state
  const [dragDelta, setDragDelta] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const appRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(361)
  const touchStart = useRef<{ x: number; y: number } | null>(null)
  const lockDir = useRef<'h' | 'v' | null>(null)

  async function refreshFromBackend(extraManual: Task[] = []) {
    try {
      const [schedule, appointments, researchTasks, recommendations] = await Promise.all([
        getScheduleDay(todayIso()),
        getAppointments(),
        getResearchTasks(),
        getRecommendations(),
      ])
      await Promise.allSettled([getScheduleConflicts(), getNotifications()])
      setTasks(prev => tasksFromBackend(schedule, appointments, researchTasks, recommendations, [...prev, ...extraManual]))
      setConflicts(conflictsFromSchedule(schedule))
      if (schedule.calendar_error) console.warn('Calendar read failed', schedule.calendar_error)
      setApiError(null)
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Backend request failed')
    }
  }

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setContainerWidth(e.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    void refreshFromBackend()
  }, [])

  const tabIndex = tab === 'daily' ? 0 : 1
  const slideUnit = containerWidth + CARD_GAP
  const baseTranslate = -tabIndex * slideUnit
  const currentTranslate = baseTranslate + dragDelta
  const progress = Math.max(0, Math.min(1, -currentTranslate / slideUnit))
  const displayTab = progress < 0.5 ? 'daily' : 'adhoc'

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    touchStart.current = { x: e.clientX, y: e.clientY }
    lockDir.current = null
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!touchStart.current) return
    const dx = e.clientX - touchStart.current.x
    const dy = e.clientY - touchStart.current.y
    if (!lockDir.current) {
      if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 6) {
        lockDir.current = 'h'
        try {
          e.currentTarget.setPointerCapture(e.pointerId)
        } catch {}
      } else if (Math.abs(dy) > 6) {
        lockDir.current = 'v'
        return
      } else return
    }
    if (lockDir.current === 'v') return
    const clamped = tabIndex === 0 ? Math.min(0, dx) : Math.max(0, dx)
    setIsDragging(true)
    setDragDelta(clamped)
  }

  function onPointerUp() {
    if (lockDir.current === 'h' && Math.abs(dragDelta) > containerWidth * 0.22) {
      setTab(dragDelta < 0 ? 'adhoc' : 'daily')
    }
    setIsDragging(false)
    setDragDelta(0)
    touchStart.current = null
    lockDir.current = null
  }

  function toggleTask(id: string) {
    setTasks(prev => prev.map(t => (t.id === id ? { ...t, completed: !t.completed } : t)))
  }

  async function updateTask(updated: Task) {
    setTasks(prev => prev.map(t => (t.id === updated.id ? updated : t)))
    setSelectedTask(null)
    if (!updated.backendNodeId) return
    try {
      if (updated.backendType === 'daily_task') {
        await updateDailyTask(updated.backendNodeId, dailyPatchFromTask(updated))
      } else {
        await updateNode(updated.backendNodeId, nodePatchFromTask(updated), 'edited')
      }
      await refreshFromBackend()
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Task update failed')
    }
  }

  function createTask(t: Task) {
    setTasks(prev => [...prev, t])
    setCreateDefaults(null)
  }

  async function deleteTask(id: string) {
    const task = tasks.find(t => t.id === id)
    setTasks(prev => prev.filter(t => t.id !== id))
    setSelectedTask(null)
    if (!task?.backendNodeId) return
    try {
      await updateNodeStatus(task.backendNodeId, 'dismissed')
      await refreshFromBackend()
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Task delete failed')
    }
  }

  async function handleRecordingComplete(recording: { transcriptionSessionId: string }) {
    try {
      const result = await processTranscription(recording.transcriptionSessionId)
      setReviewInitialTasks(reviewTasksFromProcess(result))
      setReviewOpen(true)
      setApiError(null)
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Care-plan extraction failed')
    }
  }

  async function handleReviewConfirm(items: Task[]) {
    const kept = items.filter(t => t.title.trim())
    const keptBackendIds = new Set(kept.map(t => t.backendNodeId).filter(Boolean))
    const originalByBackendId = new Map(reviewInitialTasks.filter(t => t.backendNodeId).map(t => [t.backendNodeId, t]))
    const manual = kept.filter(t => !t.backendNodeId)
    try {
      await Promise.all(
        reviewInitialTasks
          .filter(t => t.backendNodeId && !keptBackendIds.has(t.backendNodeId))
          .map(t => updateNodeStatus(t.backendNodeId!, 'dismissed')),
      )
      for (const item of kept) {
        if (!item.backendNodeId) continue
        const original = originalByBackendId.get(item.backendNodeId)
        if (taskChanged(original, item)) {
          if (item.backendType === 'daily_task') {
            await updateDailyTask(item.backendNodeId, dailyPatchFromTask(item))
          } else {
            await updateNode(item.backendNodeId, nodePatchFromTask(item), 'edited')
          }
        }
        await updateNodeStatus(item.backendNodeId, 'approved')
      }
      setReviewOpen(false)
      setIsRecording(false)
      setCaptureOpen(false)
      await refreshFromBackend(manual)
      void runConfirmedResearch(kept)
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Review save failed')
    }
  }

  async function runConfirmedResearch(items: Task[]) {
    const ids = items.filter(t => t.backendType === 'ad_hoc_research_task' && t.backendNodeId).map(t => t.backendNodeId!)
    if (!ids.length) return
    await Promise.allSettled(ids.map(runResearchTask))
    await refreshFromBackend()
  }

  async function handleApproveCalendar(task: Task) {
    if (!task.backendNodeId) return
    try {
      await approveAppointmentCalendarWrite(task.backendNodeId)
      await refreshFromBackend()
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Calendar approval failed')
    }
  }

  /** Called by DailyTaskRow when user taps a conflicting rail line. */
  function handleConflictRailClick(clientY: number) {
    const rect = appRef.current?.getBoundingClientRect()
    if (!rect) return
    setConflictPopupY(clientY - rect.top)
  }

  // Derived
  const dailyTasks = tasks.filter(t => t.category === 'daily')
  const scheduledTasks = dailyTasks.filter(t => t.timeLabel && !t.noFixedTime)
  const goalTasks = dailyTasks.filter(t => t.noFixedTime)
  const adhocTasks = tasks.filter(t => t.category === 'adhoc')
  const currentTaskId = getCurrentTaskId(tasks)

  const nowMin = new Date().getHours() * 60 + new Date().getMinutes()
  function isTaskOverdue(task: Task) {
    return !task.completed && !!task.timeLabel && parseTaskMinutes(task.timeLabel) < nowMin
  }

  const activeConflict = conflicts.find(c => !c.acknowledged) ?? null
  const hasConflict = !!activeConflict

  const conflictedTaskIds = new Set(
    activeConflict
      ? scheduledTasks
          .filter(
            t =>
              t.timeLabel &&
              parseTaskMinutes(t.timeLabel) >= activeConflict.startMin &&
              parseTaskMinutes(t.timeLabel) <= activeConflict.endMin,
          )
          .map(t => t.id)
      : [],
  )

  return (
    <div
      ref={appRef}
      style={{
        position: 'relative',
        overflow: 'hidden',
        width: '393px',
        height: '852px',
        display: 'flex',
        flexDirection: 'column',
        background: colors.white,
        fontFamily: font.family,
        WebkitFontSmoothing: 'antialiased',
      }}
    >
      <StatusBar />
      {apiError && (
        <div
          style={{
            position: 'absolute',
            top: 48,
            left: spacing.lg,
            right: spacing.lg,
            zIndex: 20,
            padding: `${spacing.sm} ${spacing.md}`,
            borderRadius: radius.sm,
            background: colors.statusUrgentLight,
            color: colors.statusUrgent,
            fontSize: font.size.xs,
            fontWeight: font.weight.medium,
            lineHeight: 1.35,
          }}
        >
          {apiError}
        </div>
      )}

      {/* ── Header ── */}
      <div
        style={{
          flexShrink: 0,
          padding: `${spacing.xl} ${spacing.xl} ${spacing.lg}`,
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
        }}
      >
        <div>
          <p
            style={{
              margin: '0 0 8px',
              fontSize: font.size.sm,
              fontWeight: font.weight.medium,
              color: colors.textSecondary,
            }}
          >
            {getGreeting()} ·{' '}
            {new Date().toLocaleDateString('en-SG', {
              weekday: 'long',
              day: 'numeric',
              month: 'long',
            })}
          </p>
          <h1
            style={{
              margin: 0,
              fontSize: font.size.xxl,
              fontWeight: font.weight.bold,
              color: colors.textPrimary,
              letterSpacing: '-0.7px',
              lineHeight: 1.1,
              transition: 'opacity 0.2s ease',
            }}
          >
            {displayTab === 'daily' ? 'Daily Tasks' : 'Upcoming'}
          </h1>
        </div>

        {/* Right button cluster */}
        <div style={{ display: 'flex', alignItems: 'center', gap: spacing.md, marginTop: 6 }}>

          {/* Bell — solid icon, no background circle */}
          <div style={{ position: 'relative' }}>
            <button
              onClick={() => setBellOpen(p => !p)}
              aria-label="Conflicts"
              style={{
                background: 'none',
                border: 'none',
                padding: 6,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                opacity: hasConflict ? 1 : 0.35,
                transition: 'opacity 0.2s ease',
              }}
            >
              <BellSolid />
            </button>
            {hasConflict && (
              <div
                style={{
                  position: 'absolute',
                  top: 3,
                  right: 3,
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: colors.statusUrgent,
                  border: `2px solid ${colors.white}`,
                  pointerEvents: 'none',
                }}
              />
            )}
          </div>

          {/* Mic + plus — navy circle, white icon */}
          <button
            onClick={() => setCaptureOpen(true)}
            aria-label="Capture"
            style={{
              width: 50,
              height: 50,
              borderRadius: radius.full,
              border: 'none',
              background: colors.primary,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 4px 12px rgba(27,45,107,0.32)',
            }}
          >
            {/* Mic (solid fill) + plus (stroked) — white */}
            <svg width="30" height="28" viewBox="0 0 20 18" fill="none">
              {/* Mic body — solid fill */}
              <rect x="3.5" y="0.75" width="5" height="8.5" rx="2.5" fill="white" />
              {/* Arc */}
              <path
                d="M1.5 7C1.5 10.3 4 12.5 6 12.5C8 12.5 10.5 10.3 10.5 7"
                stroke="white"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
              {/* Stand */}
              <line x1="6" y1="12.5" x2="6" y2="14.5" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
              {/* Base */}
              <line x1="4" y1="14.5" x2="8" y2="14.5" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
              {/* Plus */}
              <line x1="15.5" y1="2" x2="15.5" y2="8" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
              <line x1="12.5" y1="5" x2="18.5" y2="5" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      </div>

      {/* ── Card carousel ── */}
      <div
        ref={containerRef}
        onPointerDown={tasks.length > 0 ? onPointerDown : undefined}
        onPointerMove={tasks.length > 0 ? onPointerMove : undefined}
        onPointerUp={tasks.length > 0 ? onPointerUp : undefined}
        onPointerCancel={tasks.length > 0 ? onPointerUp : undefined}
        style={{
          flex: 1,
          overflow: 'hidden',
          padding: `0 ${spacing.lg}`,
          touchAction: 'pan-y',
          minHeight: 0,
          userSelect: 'none',
        }}
      >
        {tasks.length === 0 ? (
          <div
            style={{
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: spacing.lg,
              background: colors.surface,
              borderRadius: radius.card,
              padding: spacing.xl,
              boxShadow: shadow.card,
            }}
          >
            <div
              style={{
                width: 72,
                height: 72,
                borderRadius: radius.full,
                background: colors.primaryLight,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <svg width="34" height="32" viewBox="0 0 34 32" fill="none">
                <rect x="6" y="1" width="9" height="15" rx="4.5" stroke={colors.primary} strokeWidth="2" />
                <path
                  d="M2.5 13C2.5 18.8 6.8 23 12 23C17.2 23 21.5 18.8 21.5 13"
                  stroke={colors.primary}
                  strokeWidth="2"
                  strokeLinecap="round"
                />
                <line x1="12" y1="23" x2="12" y2="27" stroke={colors.primary} strokeWidth="2" strokeLinecap="round" />
                <line x1="8" y1="27" x2="16" y2="27" stroke={colors.primary} strokeWidth="2" strokeLinecap="round" />
                <line x1="27" y1="3" x2="27" y2="13" stroke={colors.primary} strokeWidth="2.5" strokeLinecap="round" />
                <line x1="22" y1="8" x2="32" y2="8" stroke={colors.primary} strokeWidth="2.5" strokeLinecap="round" />
              </svg>
            </div>
            <div style={{ textAlign: 'center', maxWidth: 260 }}>
              <h2
                style={{
                  margin: '0 0 8px',
                  fontSize: font.size.lg,
                  fontWeight: font.weight.bold,
                  color: colors.textPrimary,
                  letterSpacing: '-0.3px',
                  lineHeight: 1.2,
                }}
              >
                Record your first consultation
              </h2>
              <p style={{ margin: 0, fontSize: font.size.sm, color: colors.textSecondary, lineHeight: 1.55 }}>
                CareNote listens to doctor appointments and turns them into a structured daily care plan.
              </p>
            </div>
            <button
              onClick={() => setCaptureOpen(true)}
              style={{
                marginTop: spacing.sm,
                height: 52,
                paddingLeft: spacing.xl,
                paddingRight: spacing.xl,
                borderRadius: radius.md,
                background: colors.primary,
                border: 'none',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: spacing.sm,
                fontFamily: font.family,
                boxShadow: '0 4px 16px rgba(27,45,107,0.28)',
              }}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <rect x="5" y="1" width="6" height="8" rx="3" stroke="white" strokeWidth="1.5" fill="rgba(255,255,255,0.18)" />
                <path
                  d="M2 7C2 10 4.7 12 8 12C11.3 12 14 10 14 7"
                  stroke="white"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
                <line x1="8" y1="12" x2="8" y2="14.5" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
                <line x1="5.5" y1="14.5" x2="10.5" y2="14.5" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              <span style={{ fontSize: font.size.base, fontWeight: font.weight.semibold, color: 'white' }}>
                Start recording
              </span>
            </button>
          </div>
        ) : (
          <div
            style={{
              display: 'flex',
              gap: CARD_GAP,
              height: '100%',
              transform: `translateX(${currentTranslate}px)`,
              transition: isDragging ? 'none' : 'transform 0.35s cubic-bezier(0.4, 0, 0.2, 1)',
              willChange: 'transform',
            }}
          >
            {/* ── Daily card ── */}
            <div
              style={{
                width: containerWidth,
                flexShrink: 0,
                display: 'flex',
                flexDirection: 'column',
                overflow: 'hidden',
                background: colors.surface,
                borderRadius: radius.card,
                boxShadow: shadow.card,
                position: 'relative',
              }}
            >
              <div style={{ padding: `${spacing.md} ${spacing.lg} ${spacing.sm}`, flexShrink: 0 }}>
                <span
                  style={{
                    fontSize: font.size.xs,
                    fontWeight: font.weight.semibold,
                    color: colors.primary,
                    textTransform: 'uppercase',
                    letterSpacing: '0.7px',
                    opacity: 0.7,
                  }}
                >
                  Today's schedule
                </span>
              </div>

              <div
                style={{
                  flex: 1,
                  minHeight: 0,
                  overflowY: 'auto',
                  background: colors.white,
                  margin: `0 ${spacing.sm} ${spacing.sm}`,
                  borderRadius: radius.md,
                  paddingBottom: goalTasks.length > 0 ? '88px' : 0,
                }}
              >
                {scheduledTasks.length === 0 ? (
                  <EmptyState message="No daily tasks yet" />
                ) : (
                  scheduledTasks.map((task, i) => (
                    <DailyTaskRow
                      key={task.id}
                      task={task}
                      onToggle={toggleTask}
                      onSelect={setSelectedTask}
                      isFirst={i === 0}
                      isLast={i === scheduledTasks.length - 1}
                      isCurrent={task.id === currentTaskId}
                      isOverdue={isTaskOverdue(task)}
                      isConflict={conflictedTaskIds.has(task.id)}
                      onConflictRailClick={handleConflictRailClick}
                    />
                  ))
                )}
                <AddTaskRow label="Add task" onClick={() => setCreateDefaults({ category: 'daily' })} />
              </div>

              {/* Scrim */}
              {goalTasks.length > 0 && (
                <div
                  onClick={() => setGoalsExpanded(false)}
                  style={{
                    position: 'absolute',
                    inset: 0,
                    background: 'rgba(26,18,9,0.38)',
                    opacity: goalsExpanded ? 1 : 0,
                    pointerEvents: goalsExpanded ? 'auto' : 'none',
                    transition: 'opacity 0.38s ease',
                    zIndex: 1,
                    borderRadius: radius.card,
                  }}
                />
              )}

              {/* Daily goals tray */}
              {goalTasks.length > 0 && (
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    right: 0,
                    bottom: 0,
                    background: colors.surface,
                    borderRadius: `${radius.md} ${radius.md} 0 0`,
                    boxShadow: '0 -6px 24px rgba(20,30,70,0.10)',
                    transform: goalsExpanded ? 'translateY(0)' : 'translateY(calc(100% - 80px))',
                    transition: 'transform 0.38s cubic-bezier(0.4, 0, 0.2, 1)',
                    display: 'flex',
                    flexDirection: 'column',
                    maxHeight: '72%',
                    zIndex: 2,
                  }}
                >
                  <div
                    onClick={() => setGoalsExpanded(prev => !prev)}
                    style={{
                      paddingTop: spacing.sm,
                      paddingBottom: spacing.sm,
                      paddingLeft: spacing.lg,
                      paddingRight: spacing.lg,
                      cursor: 'pointer',
                      userSelect: 'none',
                      flexShrink: 0,
                    }}
                  >
                    <div
                      style={{
                        width: 32,
                        height: 4,
                        borderRadius: radius.full,
                        background: colors.divider,
                        margin: `0 auto ${spacing.sm}`,
                      }}
                    />
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span
                        style={{
                          fontSize: font.size.xs,
                          fontWeight: font.weight.semibold,
                          color: colors.textSecondary,
                          textTransform: 'uppercase',
                          letterSpacing: '0.7px',
                        }}
                      >
                        Daily Goals
                      </span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm }}>
                        <span
                          style={{
                            fontSize: font.size.xs,
                            fontWeight: font.weight.medium,
                            color: colors.textDisabled,
                          }}
                        >
                          {goalTasks.filter(t => t.completed).length}/{goalTasks.length} done
                        </span>
                        <svg
                          width="14"
                          height="14"
                          viewBox="0 0 14 14"
                          fill="none"
                          style={{
                            transform: goalsExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                            transition: 'transform 0.35s ease',
                            flexShrink: 0,
                          }}
                        >
                          <path
                            d="M3 9L7 5L11 9"
                            stroke={colors.textSecondary}
                            strokeWidth="1.5"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </div>
                    </div>
                  </div>
                  <div
                    style={{
                      overflowY: 'auto',
                      flex: 1,
                      background: colors.white,
                      marginLeft: spacing.sm,
                      marginRight: spacing.sm,
                      marginBottom: spacing.sm,
                      borderRadius: radius.md,
                    }}
                  >
                    {goalTasks.map((task, i) => (
                      <DailyGoalRow
                        key={task.id}
                        task={task}
                        onToggle={toggleTask}
                        onSelect={setSelectedTask}
                        showDivider={i < goalTasks.length - 1}
                      />
                    ))}
                    <AddTaskRow
                      label="Add daily goal"
                      onClick={() => setCreateDefaults({ category: 'daily', noFixedTime: true })}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* ── Upcoming card ── */}
            <div
              style={{
                width: containerWidth,
                flexShrink: 0,
                display: 'flex',
                flexDirection: 'column',
                overflow: 'hidden',
                background: colors.surface,
                borderRadius: radius.card,
                boxShadow: shadow.card,
              }}
            >
              <div style={{ padding: `${spacing.md} ${spacing.lg} ${spacing.sm}`, flexShrink: 0 }}>
                <span
                  style={{
                    fontSize: font.size.xs,
                    fontWeight: font.weight.semibold,
                    color: colors.primary,
                    textTransform: 'uppercase',
                    letterSpacing: '0.7px',
                    opacity: 0.7,
                  }}
                >
                  Upcoming
                </span>
              </div>
              <div
                style={{
                  flex: 1,
                  overflowY: 'auto',
                  paddingBottom: spacing.lg,
                  background: colors.white,
                  margin: `0 ${spacing.sm} ${spacing.sm}`,
                  borderRadius: radius.md,
                }}
              >
                {adhocTasks.length === 0 ? (
                  <EmptyState message="No upcoming tasks yet" />
                ) : (
                  adhocTasks.map((task, i) => (
                    <TaskRow
                      key={task.id}
                      task={task}
                      onToggle={toggleTask}
                      onSelect={setSelectedTask}
                      showDivider={i < adhocTasks.length - 1}
                    />
                  ))
                )}
                <AddTaskRow
                  label="Add upcoming task"
                  onClick={() => setCreateDefaults({ category: 'adhoc' })}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Page dots ── */}
      <div
        style={{ flexShrink: 0, display: 'flex', justifyContent: 'center', gap: 6, padding: `${spacing.sm} 0` }}
      >
        {TABS.map((t, i) => {
          const isActive = i === 0 ? progress < 0.5 : progress >= 0.5
          return (
            <div
              key={t.id}
              onClick={() => setTab(t.id)}
              style={{
                width: 6,
                height: 6,
                borderRadius: radius.full,
                background: isActive ? colors.primary : colors.textDisabled,
                cursor: 'pointer',
                transition: 'background 0.25s ease',
              }}
            />
          )
        })}
      </div>

      {/* ── Sheets & overlays ── */}

      <TaskDetailSheet
        task={selectedTask}
        createDefaults={createDefaults}
        onClose={() => {
          setSelectedTask(null)
          setCreateDefaults(null)
        }}
        onUpdate={updateTask}
        onCreate={createTask}
        onDelete={deleteTask}
        onApproveCalendar={handleApproveCalendar}
      />

      <CaptureSheet
        open={captureOpen}
        onClose={() => setCaptureOpen(false)}
        onStartRecording={() => {
          setCaptureOpen(false)
          setIsRecording(true)
        }}
      />

      <VoiceRecordingPanel
        open={isRecording}
        onComplete={handleRecordingComplete}
        onCancel={() => {
          setIsRecording(false)
          setCaptureOpen(false)
        }}
      />

      <ReviewSheet
        open={reviewOpen}
        initialTasks={reviewInitialTasks}
        onBack={() => setReviewOpen(false)}
        onConfirm={items => void handleReviewConfirm(items)}
      />

      {/* Conflict rail popup — anchored near where user tapped */}
      {conflictPopupY !== null && (
        <>
          <div
            onClick={() => setConflictPopupY(null)}
            style={{
              position: 'absolute',
              inset: 0,
              background: 'rgba(13,13,18,0.32)',
              zIndex: 160,
            }}
          />
          <div
            style={{
              position: 'absolute',
              // Clamp vertically so the popup never clips top/bottom
              top: Math.max(110, Math.min(conflictPopupY - 28, 700)),
              // Left edge just past the rail (~card margin + inner margin + time col + half rail)
              left: 86,
              right: spacing.xl,
              zIndex: 161,
              background: colors.white,
              borderRadius: radius.md,
              padding: `${spacing.md} ${spacing.lg}`,
              boxShadow: '0 4px 24px rgba(20,30,70,0.18)',
            }}
          >
            {/* Left-pointing arrow anchoring popup to rail */}
            <div
              style={{
                position: 'absolute',
                left: -7,
                top: 18,
                width: 0,
                height: 0,
                borderTop: '7px solid transparent',
                borderBottom: '7px solid transparent',
                borderRight: `7px solid ${colors.white}`,
                filter: 'drop-shadow(-3px 0 2px rgba(20,30,70,0.1))',
              }}
            />
            <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, marginBottom: 8 }}>
              <div style={{ width: 7, height: 7, borderRadius: '50%', background: colors.accent, flexShrink: 0 }} />
              <span style={{ fontSize: font.size.xs, fontWeight: font.weight.semibold, color: colors.textSecondary, textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Calendar
              </span>
            </div>
            <p style={{ margin: `0 0 ${spacing.sm}`, fontSize: font.size.sm, color: colors.textPrimary, lineHeight: 1.5 }}>
              This conflicts with the following event in your calendar:
            </p>
            {activeConflict && (
              <ul style={{ margin: 0, padding: `0 0 0 ${spacing.md}`, listStyle: 'none' }}>
                <li style={{ display: 'flex', alignItems: 'baseline', gap: spacing.sm }}>
                  <span style={{ width: 5, height: 5, borderRadius: '50%', background: colors.accent, flexShrink: 0, display: 'inline-block', opacity: 0.7 }} />
                  <span style={{ fontSize: font.size.sm, color: colors.textPrimary, lineHeight: 1.45 }}>
                    <span style={{ fontWeight: font.weight.semibold }}>{activeConflict.eventTitle}</span>
                    <span style={{ color: colors.textSecondary }}> ({activeConflict.startLabel}–{activeConflict.endLabel})</span>
                  </span>
                </li>
              </ul>
            )}
          </div>
        </>
      )}

      {/* Bell conflict panel */}
      <ConflictPanel
        open={bellOpen}
        conflicts={conflicts.filter(c => !c.acknowledged)}
        scheduledTasks={scheduledTasks}
        onClose={() => setBellOpen(false)}
      />
    </div>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────

/** Solid filled bell icon — no circle container. */
function BellSolid() {
  return (
    <svg width="18" height="20" viewBox="0 0 18 20" fill="none">
      <path
        d="M9 0C8.45 0 8 .45 8 1v.29A7 7 0 0 0 2 8c0 3.5-1.8 5.35-1.8 5.35C-.2 14 0 15 1 15h16c1 0 1.2-1 .8-1.65C17.8 13.35 16 11.5 16 8A7 7 0 0 0 10 1.29V1c0-.55-.45-1-1-1z"
        fill={colors.textPrimary}
      />
      <path d="M6.5 16c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5H6.5z" fill={colors.textPrimary} />
    </svg>
  )
}

function AddTaskRow({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        width: '100%',
        background: 'transparent',
        border: 'none',
        borderTop: `1px dashed ${colors.divider}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: spacing.sm,
        padding: `${spacing.md} ${spacing.lg}`,
        cursor: 'pointer',
        fontFamily: font.family,
        fontSize: font.size.sm,
        fontWeight: font.weight.medium,
        color: colors.textSecondary,
        transition: 'color 0.15s ease, background 0.15s ease',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.color = colors.primary
        e.currentTarget.style.background = colors.primaryLight + '60'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.color = colors.textSecondary
        e.currentTarget.style.background = 'transparent'
      }}
    >
      <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
        <line x1="6.5" y1="1.5" x2="6.5" y2="11.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        <line x1="1.5" y1="6.5" x2="11.5" y2="6.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
      {label}
    </button>
  )
}

function EmptyState({ message }: { message: string }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: `${spacing.xxxl} ${spacing.xl}`,
        gap: spacing.md,
      }}
    >
      <div
        style={{
          width: 40,
          height: 40,
          borderRadius: radius.md,
          border: `1.5px dashed ${colors.divider}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <line x1="8" y1="3" x2="8" y2="13" stroke={colors.textDisabled} strokeWidth="1.5" strokeLinecap="round" />
          <line x1="3" y1="8" x2="13" y2="8" stroke={colors.textDisabled} strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </div>
      <p
        style={{
          margin: 0,
          fontSize: font.size.sm,
          color: colors.textDisabled,
          textAlign: 'center',
          lineHeight: 1.5,
        }}
      >
        {message}.<br />Tap the button below to record.
      </p>
    </div>
  )
}
