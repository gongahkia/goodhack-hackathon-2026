import { useState, useRef, useEffect } from 'react'
import { colors, font, radius, spacing, shadow } from './tokens'
import type { Task, TaskCategory } from './types'
import { sampleTasks } from './data/sampleData'
import TaskRow from './components/TaskRow'
import MicButton from './components/MicButton'
import ImportSheet from './components/ImportSheet'
import RecordingToast from './components/RecordingToast'
import StatusBar from './components/StatusBar'
import TaskDetailSheet from './components/TaskDetailSheet'

const TABS: { id: TaskCategory; label: string }[] = [
  { id: 'daily', label: 'Daily Tasks' },
  { id: 'adhoc', label: 'Ad-Hoc' },
]

const CARD_GAP = 12

function getGreeting() {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

function parseTaskMinutes(timeLabel: string): number {
  const [time, period] = timeLabel.split(' ')
  const [h, m] = time.split(':').map(Number)
  let hours = h
  if (period === 'PM' && h !== 12) hours += 12
  if (period === 'AM' && h === 12) hours = 0
  return hours * 60 + m
}

function getCurrentTaskId(tasks: Task[]): string | null {
  const now = new Date()
  const nowMin = now.getHours() * 60 + now.getMinutes()
  const candidates = tasks.filter(t => t.category === 'daily' && !t.completed && t.timeLabel)
  if (!candidates.length) return null
  const withMin = candidates.map(t => ({ ...t, min: parseTaskMinutes(t.timeLabel!) }))
  // prefer the next upcoming task; fall back to most recent past task
  const upcoming = withMin.filter(t => t.min >= nowMin)
  const target = upcoming.length
    ? upcoming.reduce((a, b) => a.min < b.min ? a : b)
    : withMin.reduce((a, b) => a.min > b.min ? a : b)
  return target.id
}

export default function App() {
  const [tab, setTab] = useState<TaskCategory>('daily')
  const [tasks, setTasks] = useState<Task[]>(sampleTasks)
  const [importOpen, setImportOpen] = useState(false)
  const [lastRecordingMs, setLastRecordingMs] = useState<number | null>(null)
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)

  const [dragDelta, setDragDelta] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(361)
  const touchStart = useRef<{ x: number; y: number } | null>(null)
  const lockDir = useRef<'h' | 'v' | null>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setContainerWidth(e.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const tabIndex = tab === 'daily' ? 0 : 1
  const slideUnit = containerWidth + CARD_GAP
  const baseTranslate = -tabIndex * slideUnit
  const currentTranslate = baseTranslate + dragDelta
  const progress = Math.max(0, Math.min(1, -currentTranslate / slideUnit))
  // snap tab label to whichever card is dominant mid-drag
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
        try { e.currentTarget.setPointerCapture(e.pointerId) } catch {}
      } else if (Math.abs(dy) > 6) {
        lockDir.current = 'v'; return
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
    setTasks(prev => prev.map(t => t.id === id ? { ...t, completed: !t.completed } : t))
  }

  function updateTask(updated: Task) {
    setTasks(prev => prev.map(t => t.id === updated.id ? updated : t))
    setSelectedTask(null)
  }

  const dailyTasks = tasks.filter(t => t.category === 'daily')
  const adhocTasks = tasks.filter(t => t.category === 'adhoc')
  const currentTaskId = getCurrentTaskId(tasks)

  return (
    <div style={{
      position: 'relative',
      overflow: 'hidden',
      width: '393px',
      height: '852px',
      display: 'flex',
      flexDirection: 'column',
      background: colors.white,
      fontFamily: font.family,
      WebkitFontSmoothing: 'antialiased',
    }}>

      <StatusBar />

      {/* ── Header ── */}
      <div style={{
        flexShrink: 0,
        padding: `${spacing.xl} ${spacing.xl} ${spacing.lg}`,
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
      }}>
        <div>
          <p style={{
            margin: '0 0 4px',
            fontSize: font.size.sm,
            fontWeight: font.weight.medium,
            color: colors.textSecondary,
          }}>
            {getGreeting()} · {new Date().toLocaleDateString('en-SG', { weekday: 'long', day: 'numeric', month: 'long' })}
          </p>
          <h1 style={{
            margin: 0,
            fontSize: font.size.xxl,
            fontWeight: font.weight.bold,
            color: colors.textPrimary,
            letterSpacing: '-0.7px',
            lineHeight: 1.1,
            transition: 'opacity 0.2s ease',
          }}>
            {displayTab === 'daily' ? 'Daily Tasks' : 'Ad-Hoc'}
          </h1>
        </div>

        <button
          onClick={() => setImportOpen(true)}
          aria-label="Import"
          style={{
            width: 38,
            height: 38,
            borderRadius: radius.full,
            border: `1.5px solid ${colors.divider}`,
            background: colors.white,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginTop: 4,
            boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
          }}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <line x1="7" y1="1" x2="7" y2="13" stroke={colors.primary} strokeWidth="2" strokeLinecap="round" />
            <line x1="1" y1="7" x2="13" y2="7" stroke={colors.primary} strokeWidth="2" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      {/* ── Card carousel ── */}
      <div
        ref={containerRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        style={{
          flex: 1,
          overflow: 'hidden',
          padding: `0 ${spacing.lg}`,
          touchAction: 'pan-y',
          minHeight: 0,
          userSelect: 'none',
        }}
      >
        <div style={{
          display: 'flex',
          gap: CARD_GAP,
          height: '100%',
          transform: `translateX(${currentTranslate}px)`,
          transition: isDragging ? 'none' : 'transform 0.35s cubic-bezier(0.4, 0, 0.2, 1)',
          willChange: 'transform',
        }}>

          {/* Daily card */}
          <div style={{
            width: containerWidth,
            flexShrink: 0,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            background: colors.surface,
            borderRadius: radius.card,
            boxShadow: shadow.card,
          }}>
            <div style={{ padding: `${spacing.md} ${spacing.lg} ${spacing.sm}`, flexShrink: 0 }}>
              <span style={{ fontSize: font.size.xs, fontWeight: font.weight.semibold, color: colors.textSecondary, textTransform: 'uppercase', letterSpacing: '0.7px' }}>
                Today's tasks
              </span>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', background: colors.white, margin: `0 ${spacing.sm} ${spacing.sm}`, borderRadius: radius.md, overflow: 'hidden' }}>
              {dailyTasks.length === 0 ? <EmptyState message="No daily tasks yet" /> : (
                dailyTasks.map((task, i) => (
                  <TaskRow key={task.id} task={task} onToggle={toggleTask} onSelect={setSelectedTask} showDivider={i < dailyTasks.length - 1} isCurrent={task.id === currentTaskId} />
                ))
              )}
            </div>
          </div>

          {/* Ad-hoc card */}
          <div style={{
            width: containerWidth,
            flexShrink: 0,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            background: colors.surface,
            borderRadius: radius.card,
            boxShadow: shadow.card,
          }}>
            <div style={{ padding: `${spacing.lg} ${spacing.lg} ${spacing.md}`, flexShrink: 0 }}>
              <span style={{ fontSize: font.size.xs, fontWeight: font.weight.semibold, color: colors.textSecondary, textTransform: 'uppercase', letterSpacing: '0.7px' }}>
                Long-term considerations
              </span>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', paddingBottom: spacing.lg, background: colors.white, margin: `0 ${spacing.sm} ${spacing.sm}`, borderRadius: radius.md }}>
              {adhocTasks.length === 0 ? <EmptyState message="No ad-hoc tasks yet" /> : (
                adhocTasks.map((task, i) => (
                  <TaskRow key={task.id} task={task} onToggle={toggleTask} onSelect={setSelectedTask} showDivider={i < adhocTasks.length - 1} />
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── Page dots ── */}
      <div style={{ flexShrink: 0, display: 'flex', justifyContent: 'center', gap: 6, padding: `${spacing.sm} 0` }}>
        {TABS.map((t, i) => {
          const isActive = i === 0 ? progress < 0.5 : progress >= 0.5
          return (
            <div key={t.id} onClick={() => setTab(t.id)} style={{
              width: 6,
              height: 6,
              borderRadius: radius.full,
              background: isActive ? colors.primary : colors.textDisabled,
              cursor: 'pointer',
              transition: 'background 0.25s ease',
            }} />
          )
        })}
      </div>

      {/* ── Bottom: pill mic button ── */}
      <div style={{
        flexShrink: 0,
        padding: `${spacing.md} ${spacing.xl} ${spacing.xl}`,
      }}>
        <MicButton onRecordingComplete={(ms) => setLastRecordingMs(ms)} />
      </div>

      <TaskDetailSheet
        task={selectedTask}
        onClose={() => setSelectedTask(null)}
        onUpdate={updateTask}
      />

      <ImportSheet
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImport={(type) => { console.log('Import:', type); setImportOpen(false) }}
      />
      <RecordingToast
        durationMs={lastRecordingMs}
        onDismiss={() => setLastRecordingMs(null)}
      />
    </div>
  )
}

function EmptyState({ message }: { message: string }) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: `${spacing.xxxl} ${spacing.xl}`,
      gap: spacing.md,
    }}>
      <div style={{
        width: 40, height: 40,
        borderRadius: radius.md,
        border: `1.5px dashed ${colors.divider}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <line x1="8" y1="3" x2="8" y2="13" stroke={colors.textDisabled} strokeWidth="1.5" strokeLinecap="round" />
          <line x1="3" y1="8" x2="13" y2="8" stroke={colors.textDisabled} strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </div>
      <p style={{ margin: 0, fontSize: font.size.sm, color: colors.textDisabled, textAlign: 'center', lineHeight: 1.5 }}>
        {message}.<br />Tap the button below to record.
      </p>
    </div>
  )
}
