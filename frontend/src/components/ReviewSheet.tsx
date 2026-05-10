import { useEffect, useRef, useState } from 'react'
import { colors, font, radius, spacing } from '../tokens'
import type { Task } from '../types'

interface Props {
  open: boolean
  initialTasks: Task[]
  onConfirm: (tasks: Task[]) => void
  onBack: () => void
}

function formatShortDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-SG', { day: 'numeric', month: 'short' })
}

export default function ReviewSheet({ open, initialTasks, onConfirm, onBack }: Props) {
  const [items, setItems] = useState<Task[]>([])
  const [editingId, setEditingId] = useState<string | null>(null)
  const editInputRef = useRef<HTMLInputElement>(null)

  // Hydrate when opened
  useEffect(() => {
    if (open) {
      setItems(initialTasks.map(t => ({ ...t })))
      setEditingId(null)
    }
  }, [open, initialTasks])

  useEffect(() => {
    if (editingId) {
      // focus next tick
      requestAnimationFrame(() => {
        editInputRef.current?.focus()
        editInputRef.current?.select()
      })
    }
  }, [editingId])

  const daily = items.filter(t => t.category === 'daily')
  const upcoming = items.filter(t => t.category === 'adhoc')

  function updateTitle(id: string, value: string) {
    setItems(prev => prev.map(t => t.id === id ? { ...t, title: value } : t))
  }

  function commitEdit(id: string) {
    setItems(prev => {
      const t = prev.find(x => x.id === id)
      if (t && !t.title.trim()) return prev.filter(x => x.id !== id)
      return prev
    })
    setEditingId(null)
  }

  function removeItem(id: string) {
    setItems(prev => prev.filter(t => t.id !== id))
  }

  function addRow(category: 'daily' | 'adhoc') {
    const newId = `new-${Date.now()}`
    const t: Task = {
      id: newId,
      category,
      title: '',
      completed: false,
      createdAt: new Date().toISOString(),
      ...(category === 'daily' ? { timeLabel: '' } : { dueDate: new Date(Date.now() + 7 * 86400000).toISOString() }),
    }
    setItems(prev => [...prev, t])
    setEditingId(newId)
  }

  return (
    <>
      <div
        onClick={onBack}
        style={{
          position: 'absolute',
          inset: 0,
          background: 'rgba(10,12,26,0.55)',
          opacity: open ? 1 : 0,
          pointerEvents: open ? 'auto' : 'none',
          visibility: open ? 'visible' : 'hidden',
          transition: 'opacity 0.32s ease',
          zIndex: 60,
        }}
      />
      <div style={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: 0,
        height: 'calc(100% - 60px)',
        background: colors.white,
        borderRadius: '22px 22px 0 0',
        zIndex: 61,
        transform: open ? 'translateY(0)' : 'translateY(106%)',
        transition: 'transform 0.40s cubic-bezier(0.4, 0, 0.2, 1)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        boxShadow: '0 -10px 40px rgba(13,13,18,0.18)',
        pointerEvents: open ? 'auto' : 'none',
        visibility: open ? 'visible' : 'hidden',
      }}>

        {/* Drag handle */}
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: spacing.md, paddingBottom: spacing.sm, flexShrink: 0 }}>
          <div style={{ width: 36, height: 4, borderRadius: radius.full, background: colors.divider }} />
        </div>

        {/* Header */}
        <div style={{ padding: `0 ${spacing.xl} ${spacing.lg}`, flexShrink: 0 }}>
          <p style={{
            margin: 0,
            fontSize: font.size.xs,
            fontWeight: font.weight.semibold,
            color: colors.accent,
            textTransform: 'uppercase',
            letterSpacing: '0.9px',
          }}>
            Care plan · review
          </p>
          <h2 style={{
            margin: '6px 0 8px',
            fontSize: '24px',
            fontWeight: font.weight.bold,
            color: colors.textPrimary,
            letterSpacing: '-0.5px',
            lineHeight: 1.15,
          }}>
            Review your care plan
          </h2>
          <p style={{
            margin: 0,
            fontSize: font.size.sm,
            color: colors.textSecondary,
            lineHeight: 1.5,
          }}>
            We extracted <strong style={{ color: colors.textPrimary }}>{daily.length} daily</strong> and <strong style={{ color: colors.textPrimary }}>{upcoming.length} upcoming</strong> items. Tap any title to edit, or remove anything that doesn't sound right.
          </p>
        </div>

        {/* Scrollable buckets */}
        <div style={{ flex: 1, overflowY: 'auto', minHeight: 0, paddingLeft: spacing.lg, paddingRight: spacing.lg, paddingBottom: spacing.lg }}>

          <Bucket
            label="Daily tasks"
            count={daily.length}
            accent={colors.primary}
          >
            {daily.map(t => (
              <ReviewRow
                key={t.id}
                chip={t.timeLabel ? t.timeLabel : (t.noFixedTime ? 'Anytime' : '—')}
                chipColor={t.noFixedTime ? colors.textSecondary : colors.accent}
                chipBg={t.noFixedTime ? colors.surface : colors.accentLight}
                title={t.title}
                editing={editingId === t.id}
                inputRef={editingId === t.id ? editInputRef : null}
                onTitleClick={() => setEditingId(t.id)}
                onTitleChange={v => updateTitle(t.id, v)}
                onCommit={() => commitEdit(t.id)}
                onDelete={() => removeItem(t.id)}
              />
            ))}
            <AddRow label="Add daily task" onClick={() => addRow('daily')} />
          </Bucket>

          <div style={{ height: spacing.xl }} />

          <Bucket
            label="Upcoming"
            count={upcoming.length}
            accent={colors.statusUrgent}
          >
            {upcoming.map(t => (
              <ReviewRow
                key={t.id}
                chip={t.dueDate ? formatShortDate(t.dueDate) : (t.backendType === 'ad_hoc_research_task' ? 'Research' : '—')}
                chipColor={colors.statusUrgent}
                chipBg={colors.statusUrgentLight}
                title={t.title}
                editing={editingId === t.id}
                inputRef={editingId === t.id ? editInputRef : null}
                onTitleClick={() => setEditingId(t.id)}
                onTitleChange={v => updateTitle(t.id, v)}
                onCommit={() => commitEdit(t.id)}
                onDelete={() => removeItem(t.id)}
              />
            ))}
            <AddRow label="Add upcoming item" onClick={() => addRow('adhoc')} />
          </Bucket>
        </div>

        {/* Sticky bottom CTA */}
        <div style={{
          flexShrink: 0,
          padding: `${spacing.md} ${spacing.lg} ${spacing.lg}`,
          borderTop: `1px solid ${colors.divider}`,
          background: colors.white,
          display: 'flex',
          flexDirection: 'column',
          gap: spacing.sm,
        }}>
          <button
            onClick={() => onConfirm(items.filter(t => t.title.trim()))}
            disabled={items.filter(t => t.title.trim()).length === 0}
            style={{
              width: '100%',
              height: 54,
              background: colors.primary,
              border: 'none',
              borderRadius: radius.md,
              color: 'white',
              fontFamily: font.family,
              fontSize: font.size.base,
              fontWeight: font.weight.semibold,
              cursor: 'pointer',
              boxShadow: '0 4px 18px rgba(27,45,107,0.30)',
              opacity: items.filter(t => t.title.trim()).length === 0 ? 0.4 : 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: spacing.sm,
            }}
          >
            Confirm & save
            <span style={{
              fontSize: font.size.xs,
              fontWeight: font.weight.medium,
              opacity: 0.85,
              fontVariantNumeric: 'tabular-nums',
            }}>
              {daily.filter(t => t.title.trim()).length} daily · {upcoming.filter(t => t.title.trim()).length} upcoming
            </span>
          </button>
          <button
            onClick={onBack}
            style={{
              width: '100%',
              height: 36,
              background: 'transparent',
              border: 'none',
              color: colors.textSecondary,
              fontFamily: font.family,
              fontSize: font.size.sm,
              fontWeight: font.weight.medium,
              cursor: 'pointer',
            }}
          >
            ← Back to transcript
          </button>
        </div>
      </div>
    </>
  )
}

function Bucket({ label, count, accent, children }: { label: string; count: number; accent: string; children: React.ReactNode }) {
  return (
    <div style={{ paddingTop: spacing.lg }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: spacing.sm,
        marginBottom: spacing.sm,
        paddingLeft: spacing.xs,
      }}>
        <div style={{
          width: 3,
          height: 18,
          borderRadius: 2,
          background: accent,
        }} />
        <span style={{
          fontSize: font.size.xs,
          fontWeight: font.weight.bold,
          color: colors.textPrimary,
          textTransform: 'uppercase',
          letterSpacing: '0.9px',
        }}>
          {label}
        </span>
        <span style={{
          fontSize: font.size.xs,
          fontWeight: font.weight.semibold,
          color: colors.textSecondary,
          background: colors.surface,
          padding: '2px 8px',
          borderRadius: radius.full,
          marginLeft: 2,
        }}>
          {count}
        </span>
      </div>
      <div style={{
        background: colors.surface,
        borderRadius: radius.md,
        overflow: 'hidden',
      }}>
        {children}
      </div>
    </div>
  )
}

function ReviewRow({
  chip,
  chipColor,
  chipBg,
  title,
  editing,
  inputRef,
  onTitleClick,
  onTitleChange,
  onCommit,
  onDelete,
}: {
  chip: string
  chipColor: string
  chipBg: string
  title: string
  editing: boolean
  inputRef: React.RefObject<HTMLInputElement | null> | null
  onTitleClick: () => void
  onTitleChange: (v: string) => void
  onCommit: () => void
  onDelete: () => void
}) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'flex-start',
      gap: spacing.md,
      paddingTop: spacing.md,
      paddingBottom: spacing.md,
      paddingLeft: spacing.md,
      paddingRight: spacing.sm,
      borderBottom: `1px solid ${colors.divider}`,
    }}>
      {/* Chip */}
      <span style={{
        fontSize: font.size.xs,
        fontWeight: font.weight.semibold,
        color: chipColor,
        background: chipBg,
        padding: '4px 9px',
        borderRadius: radius.sm,
        whiteSpace: 'nowrap',
        flexShrink: 0,
        marginTop: 1,
        letterSpacing: '0.2px',
        minWidth: 60,
        textAlign: 'center',
      }}>
        {chip || '—'}
      </span>

      {/* Title */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {editing ? (
          <input
            ref={inputRef ?? undefined}
            value={title}
            onChange={e => onTitleChange(e.target.value)}
            onBlur={onCommit}
            onKeyDown={e => {
              if (e.key === 'Enter') { e.preventDefault(); (e.target as HTMLInputElement).blur() }
              if (e.key === 'Escape') { onCommit() }
            }}
            placeholder="Describe the task…"
            style={{
              width: '100%',
              fontFamily: font.family,
              fontSize: font.size.sm,
              fontWeight: font.weight.medium,
              color: colors.textPrimary,
              background: colors.white,
              border: `1.5px solid ${colors.primary}`,
              borderRadius: radius.sm,
              padding: '5px 8px',
              outline: 'none',
              lineHeight: 1.35,
            }}
          />
        ) : (
          <p
            onClick={onTitleClick}
            style={{
              margin: 0,
              fontSize: font.size.sm,
              fontWeight: font.weight.medium,
              color: title ? colors.textPrimary : colors.textDisabled,
              lineHeight: 1.4,
              cursor: 'text',
              padding: '5px 0',
            }}
          >
            {title || 'Empty — tap to write'}
          </p>
        )}
      </div>

      {/* Delete */}
      <button
        onClick={onDelete}
        aria-label="Remove"
        style={{
          width: 28,
          height: 28,
          background: 'transparent',
          border: 'none',
          borderRadius: radius.sm,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          color: colors.textDisabled,
          transition: 'color 0.15s ease, background 0.15s ease',
        }}
        onMouseEnter={e => { e.currentTarget.style.color = colors.statusUrgent; e.currentTarget.style.background = colors.statusUrgentLight }}
        onMouseLeave={e => { e.currentTarget.style.color = colors.textDisabled; e.currentTarget.style.background = 'transparent' }}
      >
        <svg width="13" height="14" viewBox="0 0 14 15" fill="none">
          <path d="M2 3.5h10M5 3.5V2a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1.5M3.5 3.5l.6 9.2a1 1 0 0 0 1 .8h3.8a1 1 0 0 0 1-.8l.6-9.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </div>
  )
}

function AddRow({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        width: '100%',
        background: 'transparent',
        border: 'none',
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
      onMouseEnter={e => { e.currentTarget.style.color = colors.primary; e.currentTarget.style.background = colors.primaryLight + '60' }}
      onMouseLeave={e => { e.currentTarget.style.color = colors.textSecondary; e.currentTarget.style.background = 'transparent' }}
    >
      <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
        <line x1="6.5" y1="1.5" x2="6.5" y2="11.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        <line x1="1.5" y1="6.5" x2="11.5" y2="6.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
      {label}
    </button>
  )
}
