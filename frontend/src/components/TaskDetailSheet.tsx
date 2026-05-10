import { useState, useEffect, useRef } from 'react'
import { colors, font, radius, spacing, shadow } from '../tokens'
import type { Task, NextStep, Recurrence, ActivePeriod } from '../types'
import { RecurrencePicker, PeriodPicker } from './ScheduleControls'

const DAY_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTH_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function defaultRecurrence(): Recurrence { return { mode: 'daily', weekdays: [0, 1, 2, 3, 4, 5, 6] } }
function defaultActivePeriod(): ActivePeriod {
  return { start: new Date().toISOString().slice(0, 10), end: null }
}

function summarizeRecurrence(r: Recurrence): string {
  if (r.mode === 'daily') return 'Every day'
  if (r.mode === 'weekdays') return 'Mon–Fri'
  const days = (r.weekdays ?? []).map(i => DAY_SHORT[i].slice(0, 3))
  if (!days.length) return r.mode === 'weekly' ? 'Weekly' : 'Custom'
  return days.join(' · ')
}

function summarizePeriod(p: ActivePeriod): string {
  const startD = new Date(p.start + 'T00:00:00')
  const startTxt = `${MONTH_SHORT[startD.getMonth()]} ${startD.getDate()}`
  if (!p.end) return `From ${startTxt} · ongoing`
  const endD = new Date(p.end + 'T00:00:00')
  const endTxt = `${MONTH_SHORT[endD.getMonth()]} ${endD.getDate()}`
  return `${startTxt} — ${endTxt}`
}

interface CreateDefaults {
  category: 'daily' | 'adhoc'
  noFixedTime?: boolean
}

interface Props {
  task: Task | null
  createDefaults?: CreateDefaults | null
  onClose: () => void
  onUpdate: (task: Task) => void | Promise<void>
  onCreate?: (task: Task) => void
  onDelete?: (id: string) => void | Promise<void>
  onApproveCalendar?: (task: Task) => void | Promise<void>
}

function formatDueDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-SG', { day: 'numeric', month: 'long', year: 'numeric' })
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  fontFamily: font.family,
  fontSize: font.size.base,
  color: colors.textPrimary,
  background: colors.surface,
  border: `1.5px solid ${colors.divider}`,
  borderRadius: radius.md,
  padding: `${spacing.sm} ${spacing.md}`,
  outline: 'none',
  boxSizing: 'border-box',
}

const textareaStyle: React.CSSProperties = {
  ...inputStyle,
  resize: 'none',
  lineHeight: '1.5',
  minHeight: 80,
}

const sectionLabel: React.CSSProperties = {
  fontSize: font.size.xs,
  fontWeight: font.weight.semibold,
  color: colors.textSecondary,
  textTransform: 'uppercase',
  letterSpacing: '0.7px',
  marginBottom: spacing.sm,
}

export default function TaskDetailSheet({ task, createDefaults, onClose, onUpdate, onCreate, onDelete, onApproveCalendar }: Props) {
  const [visible, setVisible] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Task | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const confirmTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const backdropRef = useRef<HTMLDivElement>(null)

  const isCreating = !task && !!createDefaults

  function armDeleteConfirm() {
    setConfirmingDelete(true)
    if (confirmTimer.current) clearTimeout(confirmTimer.current)
    confirmTimer.current = setTimeout(() => setConfirmingDelete(false), 4000)
  }

  function cancelDeleteConfirm() {
    setConfirmingDelete(false)
    if (confirmTimer.current) { clearTimeout(confirmTimer.current); confirmTimer.current = null }
  }

  function performDelete() {
    if (!task) return
    cancelDeleteConfirm()
    onDelete?.(task.id)
    handleClose()
  }

  // Reset confirm state whenever editing toggles or sheet closes
  useEffect(() => {
    if (!editing) cancelDeleteConfirm()
    return () => { if (confirmTimer.current) clearTimeout(confirmTimer.current) }
  }, [editing])

  useEffect(() => {
    if (task) {
      setDraft({ ...task, nextSteps: task.nextSteps ? [...task.nextSteps.map(s => ({ ...s }))] : [] })
      setEditing(false)
      requestAnimationFrame(() => requestAnimationFrame(() => setVisible(true)))
    } else if (createDefaults) {
      const blank: Task = {
        id: `new-${Date.now()}`,
        category: createDefaults.category,
        title: '',
        completed: false,
        noFixedTime: createDefaults.noFixedTime,
        createdAt: new Date().toISOString(),
        nextSteps: [],
      }
      setDraft(blank)
      setEditing(true)
      requestAnimationFrame(() => requestAnimationFrame(() => setVisible(true)))
    } else {
      setVisible(false)
    }
  }, [task, createDefaults])

  if ((!task && !createDefaults) || !draft) return null

  function handleClose() {
    setVisible(false)
    setTimeout(onClose, 320)
  }

  function handleSave() {
    if (!draft) return
    if (isCreating) {
      if (!draft.title.trim()) return
      onCreate?.(draft)
      handleClose()
    } else {
      onUpdate(draft)
      setEditing(false)
    }
  }

  function handleComplete() {
    if (!draft) return
    const updated = { ...draft, completed: !draft.completed }
    onUpdate(updated)
    handleClose()
  }

  function updateNextStep(i: number, value: string) {
    if (!draft) return
    const steps = [...(draft.nextSteps ?? [])]
    steps[i] = { ...steps[i], label: value }
    setDraft({ ...draft, nextSteps: steps })
  }

  function addNextStep() {
    if (!draft) return
    setDraft({ ...draft, nextSteps: [...(draft.nextSteps ?? []), { label: '' }] })
  }

  function removeNextStep(i: number) {
    if (!draft) return
    const steps = [...(draft.nextSteps ?? [])]
    steps.splice(i, 1)
    setDraft({ ...draft, nextSteps: steps })
  }

  const isAdhoc = draft.category === 'adhoc'
  const canApproveCalendar = draft.backendType === 'appointment_candidate' && draft.calendarWriteStatus === 'pending_user_approval'

  return (
    <div
      ref={backdropRef}
      onClick={e => { if (e.target === backdropRef.current) handleClose() }}
      style={{
        position: 'absolute',
        inset: 0,
        background: visible ? 'rgba(13,13,18,0.45)' : 'rgba(13,13,18,0)',
        backdropFilter: visible ? 'blur(4px)' : 'blur(0px)',
        WebkitBackdropFilter: visible ? 'blur(4px)' : 'blur(0px)',
        zIndex: 200,
        display: 'flex',
        alignItems: 'flex-end',
        transition: 'background 0.3s ease, backdrop-filter 0.3s ease',
      }}
    >
      <div style={{
        width: '100%',
        maxHeight: '88%',
        background: colors.white,
        borderRadius: `${radius.card} ${radius.card} 0 0`,
        boxShadow: shadow.sheet,
        display: 'flex',
        flexDirection: 'column',
        transform: visible ? 'translateY(0)' : 'translateY(100%)',
        transition: 'transform 0.32s cubic-bezier(0.4, 0, 0.2, 1)',
        overflow: 'hidden',
      }}>

        {/* Drag handle */}
        <div style={{ display: 'flex', justifyContent: 'center', padding: `${spacing.md} 0 0` }}>
          <div style={{ width: 36, height: 4, borderRadius: radius.full, background: colors.divider }} />
        </div>

        {/* Header */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: `${spacing.md} ${spacing.xl}`,
          borderBottom: `1px solid ${colors.divider}`,
          flexShrink: 0,
        }}>
          <button onClick={handleClose} style={{
            background: colors.surface,
            border: 'none',
            borderRadius: radius.full,
            width: 32, height: 32,
            cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M1 1l12 12M13 1L1 13" stroke={colors.textSecondary} strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>

          <div style={{ display: 'flex', gap: spacing.sm }}>
            {editing ? (
              <>
                <button onClick={() => {
                  if (isCreating) { handleClose(); return }
                  if (task) setDraft({ ...task, nextSteps: task.nextSteps ? [...task.nextSteps] : [] })
                  setEditing(false)
                }}
                  style={{ ...ghostBtn, color: colors.textSecondary }}>
                  Cancel
                </button>
                <button
                  onClick={handleSave}
                  disabled={isCreating && !draft.title.trim()}
                  style={{
                    ...solidBtn,
                    opacity: (isCreating && !draft.title.trim()) ? 0.4 : 1,
                    cursor: (isCreating && !draft.title.trim()) ? 'default' : 'pointer',
                  }}>
                  {isCreating ? 'Create' : 'Save'}
                </button>
              </>
            ) : (
              <button onClick={() => setEditing(true)} style={{ ...ghostBtn }}>
                Edit
              </button>
            )}
          </div>
        </div>

        {/* Scrollable content */}
        <div style={{ overflowY: 'auto', flex: 1, padding: `${spacing.lg} ${spacing.xl} ${spacing.xl}` }}>

          {/* Title */}
          <div style={{ marginBottom: spacing.lg }}>
            {editing ? (
              <>
                <p style={sectionLabel}>Title</p>
                <input
                  value={draft.title}
                  onChange={e => setDraft({ ...draft, title: e.target.value })}
                  style={{ ...inputStyle, fontSize: font.size.lg, fontWeight: font.weight.semibold }}
                />
              </>
            ) : (
              <h2 style={{
                margin: 0,
                fontSize: '22px',
                fontWeight: font.weight.bold,
                color: colors.textPrimary,
                letterSpacing: '-0.4px',
                lineHeight: 1.2,
              }}>
                {draft.title}
              </h2>
            )}
          </div>

          {/* Badges row */}
          {!editing && (
            <div style={{ display: 'flex', gap: spacing.sm, flexWrap: 'wrap', marginBottom: spacing.xl }}>
              {draft.timeLabel && !isAdhoc && (
                <Badge color={colors.accent} bg={colors.accentLight}>{draft.timeLabel}</Badge>
              )}
              {draft.dueDate && (
                <Badge color={colors.textSecondary} bg={colors.surface}>By {formatDueDate(draft.dueDate)}</Badge>
              )}
              {draft.urgent && (
                <Badge color={colors.statusUrgent} bg={colors.statusUrgentLight}>Urgent</Badge>
              )}
              {draft.completed && (
                <Badge color={colors.statusDone} bg={colors.statusDoneLight}>Completed</Badge>
              )}
              {canApproveCalendar && (
                <Badge color={colors.primary} bg={colors.primaryLight}>Calendar pending</Badge>
              )}
            </div>
          )}

          {/* Time (edit mode, daily only) */}
          {editing && !isAdhoc && (
            <div style={{ marginBottom: spacing.lg }}>
              <p style={sectionLabel}>Scheduled time</p>
              <input
                value={draft.timeLabel ?? ''}
                onChange={e => setDraft({ ...draft, timeLabel: e.target.value })}
                placeholder="e.g. 8:00 AM"
                style={inputStyle}
              />
            </div>
          )}

          {/* Repeats (edit mode, daily only) */}
          {editing && !isAdhoc && (
            <div style={{ marginBottom: spacing.lg }}>
              <p style={sectionLabel}>Repeats</p>
              <RecurrencePicker
                value={draft.recurrence ?? defaultRecurrence()}
                onChange={v => setDraft({ ...draft, recurrence: v })}
              />
            </div>
          )}

          {/* Active period (edit mode, daily only) */}
          {editing && !isAdhoc && (
            <div style={{ marginBottom: spacing.lg }}>
              <p style={sectionLabel}>Active period</p>
              <PeriodPicker
                value={draft.activePeriod ?? defaultActivePeriod()}
                onChange={v => setDraft({ ...draft, activePeriod: v })}
              />
            </div>
          )}

          {/* View-mode summary chips for recurrence + period (daily only) */}
          {!editing && !isAdhoc && (draft.recurrence || draft.activePeriod) && (
            <div style={{
              display: 'flex',
              gap: spacing.sm,
              flexWrap: 'wrap',
              marginBottom: spacing.lg,
              marginTop: -spacing.sm,
            }}>
              {draft.recurrence && (
                <span style={summaryChip}>
                  <svg width="11" height="11" viewBox="0 0 11 11" fill="none">
                    <path d="M2 4.5a3.5 3.5 0 0 1 6.5-1.5M9 6.5a3.5 3.5 0 0 1-6.5 1.5" stroke={colors.primary} strokeWidth="1.4" strokeLinecap="round" />
                    <path d="M8.5 1v3h-3M2.5 10V7h3" stroke={colors.primary} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  {summarizeRecurrence(draft.recurrence)}
                </span>
              )}
              {draft.activePeriod && (
                <span style={summaryChip}>
                  <svg width="11" height="11" viewBox="0 0 11 11" fill="none">
                    <rect x="1.5" y="2" width="8" height="7" rx="1" stroke={colors.primary} strokeWidth="1.3" />
                    <line x1="1.5" y1="4.2" x2="9.5" y2="4.2" stroke={colors.primary} strokeWidth="1.3" />
                  </svg>
                  {summarizePeriod(draft.activePeriod)}
                </span>
              )}
            </div>
          )}

          {/* Due date (edit mode, adhoc only) */}
          {editing && isAdhoc && (
            <div style={{ marginBottom: spacing.lg }}>
              <p style={sectionLabel}>Due date</p>
              <input
                type="date"
                value={draft.dueDate ?? ''}
                onChange={e => setDraft({ ...draft, dueDate: e.target.value })}
                style={inputStyle}
              />
            </div>
          )}

          {/* Detail / context */}
          <div style={{ marginBottom: spacing.lg }}>
            <p style={sectionLabel}>{isAdhoc ? 'Context' : 'Instructions'}</p>
            {editing ? (
              <textarea
                value={draft.detail ?? ''}
                onChange={e => setDraft({ ...draft, detail: e.target.value })}
                style={textareaStyle}
                rows={3}
              />
            ) : draft.detail ? (
              <p style={{ margin: 0, fontSize: font.size.base, color: colors.textPrimary, lineHeight: '1.55' }}>
                {draft.detail}
              </p>
            ) : null}
          </div>

          {/* Consultation note (daily only) */}
          {!isAdhoc && (
            <div style={{ marginBottom: spacing.lg }}>
              <p style={sectionLabel}>Doctor's notes</p>
              {editing ? (
                <textarea
                  value={draft.consultationNote ?? ''}
                  onChange={e => setDraft({ ...draft, consultationNote: e.target.value })}
                  style={textareaStyle}
                  rows={4}
                />
              ) : draft.consultationNote ? (
                <div style={{
                  background: colors.primaryLight,
                  borderRadius: radius.md,
                  padding: spacing.lg,
                  borderLeft: `3px solid ${colors.primary}`,
                }}>
                  <p style={{ margin: 0, fontSize: font.size.sm, color: colors.textPrimary, lineHeight: '1.6' }}>
                    {draft.consultationNote}
                  </p>
                </div>
              ) : null}
            </div>
          )}

          {/* Next steps (adhoc only) */}
          {isAdhoc && (
            <div style={{ marginBottom: spacing.lg }}>
              <p style={sectionLabel}>Next steps</p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.sm }}>
                {(editing ? draft.nextSteps : draft.nextSteps)?.map((step, i) => (
                  editing ? (
                    <div key={i} style={{ display: 'flex', gap: spacing.sm, alignItems: 'flex-start' }}>
                      <div style={{
                        width: 24, height: 24, minWidth: 24,
                        borderRadius: radius.full,
                        background: colors.primaryLight,
                        color: colors.primary,
                        fontSize: font.size.xs,
                        fontWeight: font.weight.bold,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        marginTop: 6,
                      }}>
                        {i + 1}
                      </div>
                      <input
                        value={step.label}
                        onChange={e => updateNextStep(i, e.target.value)}
                        style={{ ...inputStyle, flex: 1 }}
                        placeholder="Describe the next step…"
                      />
                      <button onClick={() => removeNextStep(i)} style={{
                        width: 32, height: 32, minWidth: 32,
                        background: colors.statusUrgentLight,
                        border: 'none', borderRadius: radius.sm,
                        cursor: 'pointer', marginTop: 4,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>
                        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                          <path d="M1 1l8 8M9 1L1 9" stroke={colors.statusUrgent} strokeWidth="1.6" strokeLinecap="round" />
                        </svg>
                      </button>
                    </div>
                  ) : (
                    <NextStepRow key={i} step={step} index={i} />
                  )
                ))}

                {editing && (
                  <button onClick={addNextStep} style={{
                    display: 'flex', alignItems: 'center', gap: spacing.sm,
                    background: 'none', border: `1.5px dashed ${colors.divider}`,
                    borderRadius: radius.md, padding: spacing.md,
                    cursor: 'pointer', color: colors.textSecondary,
                    fontFamily: font.family, fontSize: font.size.sm,
                    fontWeight: font.weight.medium,
                  }}>
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <line x1="7" y1="1" x2="7" y2="13" stroke={colors.textSecondary} strokeWidth="1.8" strokeLinecap="round" />
                      <line x1="1" y1="7" x2="13" y2="7" stroke={colors.textSecondary} strokeWidth="1.8" strokeLinecap="round" />
                    </svg>
                    Add step
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Delete (edit mode, existing task only) */}
          {editing && !isCreating && task && onDelete && (
            <div style={{
              marginTop: spacing.lg,
              paddingTop: spacing.lg,
              borderTop: `1px solid ${colors.divider}`,
            }}>
              {!confirmingDelete ? (
                <button
                  onClick={armDeleteConfirm}
                  style={{
                    width: '100%',
                    height: 48,
                    background: 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                    fontFamily: font.family,
                    fontSize: font.size.sm,
                    fontWeight: font.weight.semibold,
                    color: colors.statusUrgent,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: spacing.sm,
                    letterSpacing: '0.2px',
                  }}
                >
                  <svg width="14" height="15" viewBox="0 0 14 15" fill="none">
                    <path d="M2 3.5h10M5 3.5V2a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1.5M3.5 3.5l.6 9.2a1 1 0 0 0 1 .8h3.8a1 1 0 0 0 1-.8l.6-9.2" stroke={colors.statusUrgent} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Delete task
                </button>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.sm }}>
                  <p style={{
                    margin: 0,
                    textAlign: 'center',
                    fontSize: font.size.sm,
                    color: colors.textSecondary,
                    lineHeight: 1.45,
                  }}>
                    Delete this task? This can't be undone.
                  </p>
                  <div style={{ display: 'flex', gap: spacing.sm }}>
                    <button
                      onClick={cancelDeleteConfirm}
                      style={{
                        flex: 1,
                        height: 48,
                        background: colors.surface,
                        border: 'none',
                        borderRadius: radius.md,
                        cursor: 'pointer',
                        fontFamily: font.family,
                        fontSize: font.size.sm,
                        fontWeight: font.weight.semibold,
                        color: colors.textSecondary,
                      }}
                    >
                      Cancel
                    </button>
                    <button
                      onClick={performDelete}
                      style={{
                        flex: 2,
                        height: 48,
                        background: colors.statusUrgent,
                        border: 'none',
                        borderRadius: radius.md,
                        cursor: 'pointer',
                        fontFamily: font.family,
                        fontSize: font.size.sm,
                        fontWeight: font.weight.semibold,
                        color: colors.white,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: spacing.sm,
                        boxShadow: '0 3px 12px rgba(196,52,28,0.28)',
                      }}
                    >
                      <svg width="14" height="15" viewBox="0 0 14 15" fill="none">
                        <path d="M2 3.5h10M5 3.5V2a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1.5M3.5 3.5l.6 9.2a1 1 0 0 0 1 .8h3.8a1 1 0 0 0 1-.8l.6-9.2" stroke="white" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      Delete permanently
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Mark complete / incomplete */}
          {!editing && !isCreating && (
            <>
            {canApproveCalendar && (
              <button onClick={() => { onApproveCalendar?.(draft); handleClose() }} style={{
                width: '100%',
                height: 50,
                borderRadius: radius.pill,
                border: 'none',
                background: colors.primary,
                color: colors.white,
                fontFamily: font.family,
                fontSize: font.size.base,
                fontWeight: font.weight.semibold,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: spacing.sm,
                marginTop: spacing.md,
              }}>
                Add to Google Calendar
              </button>
            )}
            <button onClick={handleComplete} style={{
              width: '100%',
              height: 50,
              borderRadius: radius.pill,
              border: draft.completed
                ? `1.5px solid ${colors.divider}`
                : 'none',
              background: draft.completed ? colors.white : colors.statusDone,
              color: draft.completed ? colors.textSecondary : colors.white,
              fontFamily: font.family,
              fontSize: font.size.base,
              fontWeight: font.weight.semibold,
              cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: spacing.sm,
              marginTop: spacing.md,
              transition: 'all 0.15s ease',
            }}>
              {draft.completed ? (
                <>
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                    <path d="M1 1l14 14M15 1L1 15" stroke={colors.textSecondary} strokeWidth="1.8" strokeLinecap="round" />
                  </svg>
                  Mark as incomplete
                </>
              ) : (
                <>
                  <svg width="16" height="12" viewBox="0 0 16 12" fill="none">
                    <path d="M1.5 6L6 10.5L14.5 1.5" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Mark as complete
                </>
              )}
            </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function Badge({ children, color, bg }: { children: React.ReactNode; color: string; bg: string }) {
  return (
    <span style={{
      fontSize: font.size.xs,
      fontWeight: font.weight.semibold,
      color,
      background: bg,
      padding: '4px 10px',
      borderRadius: radius.full,
      whiteSpace: 'nowrap',
    }}>
      {children}
    </span>
  )
}

function NextStepRow({ step, index }: { step: NextStep; index: number }) {
  const hasLink = !!(step.url || step.phone)
  const href = step.url ?? (step.phone ? `tel:${step.phone.replace(/\s/g, '')}` : undefined)

  const inner = (
    <div style={{
      display: 'flex',
      alignItems: 'flex-start',
      gap: spacing.md,
      padding: spacing.md,
      background: colors.surface,
      borderRadius: radius.md,
      border: `1px solid ${colors.divider}`,
      cursor: hasLink ? 'pointer' : 'default',
      textDecoration: 'none',
    }}>
      {/* Step number */}
      <div style={{
        width: 24, height: 24, minWidth: 24,
        borderRadius: radius.full,
        background: colors.primaryLight,
        color: colors.primary,
        fontSize: font.size.xs,
        fontWeight: font.weight.bold,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        marginTop: 1,
        flexShrink: 0,
      }}>
        {index + 1}
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{
          margin: 0,
          fontSize: font.size.sm,
          fontWeight: font.weight.medium,
          color: colors.textPrimary,
          lineHeight: '1.45',
        }}>
          {step.label}
        </p>
        {step.phone && (
          <p style={{ margin: '3px 0 0', fontSize: font.size.xs, color: colors.primary, fontWeight: font.weight.medium }}>
            {step.phone}
          </p>
        )}
        {step.url && (
          <p style={{ margin: '3px 0 0', fontSize: font.size.xs, color: colors.primary, fontWeight: font.weight.medium }}>
            Open link ↗
          </p>
        )}
      </div>

      {/* Link icon */}
      {hasLink && (
        <div style={{ flexShrink: 0, paddingTop: 2 }}>
          {step.phone ? (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M13.5 10.5l-2-2a1 1 0 0 0-1.4 0l-.8.8a7.2 7.2 0 0 1-3.1-3.1l.8-.8a1 1 0 0 0 0-1.4l-2-2A1 1 0 0 0 3.6 2L2.5 3.1C1.7 3.9 2 5.6 3.5 7.6c.9 1.2 2 2.4 3.2 3.3 2 1.4 3.7 1.7 4.5.9l1.1-1.1a1 1 0 0 0-.8-1.2Z" fill={colors.primary} />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M6 2H2a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V8" stroke={colors.primary} strokeWidth="1.5" strokeLinecap="round" />
              <path d="M9 1h4v4M13 1L7 7" stroke={colors.primary} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </div>
      )}
    </div>
  )

  if (href) {
    return (
      <a href={href} target={step.url ? '_blank' : undefined} rel="noreferrer" style={{ textDecoration: 'none', display: 'block' }}>
        {inner}
      </a>
    )
  }
  return inner
}

const summaryChip: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  fontSize: font.size.xs,
  fontWeight: font.weight.semibold,
  color: colors.primary,
  background: colors.primaryLight,
  padding: '5px 10px',
  borderRadius: radius.full,
  whiteSpace: 'nowrap',
  letterSpacing: '0.2px',
}

const ghostBtn: React.CSSProperties = {
  background: colors.surface,
  border: 'none',
  borderRadius: radius.md,
  padding: `${spacing.sm} ${spacing.md}`,
  fontFamily: font.family,
  fontSize: font.size.sm,
  fontWeight: font.weight.semibold,
  color: colors.primary,
  cursor: 'pointer',
}

const solidBtn: React.CSSProperties = {
  background: colors.primary,
  border: 'none',
  borderRadius: radius.md,
  padding: `${spacing.sm} ${spacing.md}`,
  fontFamily: font.family,
  fontSize: font.size.sm,
  fontWeight: font.weight.semibold,
  color: colors.white,
  cursor: 'pointer',
}
