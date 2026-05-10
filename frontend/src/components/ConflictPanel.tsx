import { useEffect, useState } from 'react'
import { colors, font, radius, spacing } from '../tokens'
import type { Task } from '../types'

export interface ConflictItem {
  id: string
  eventTitle: string
  startLabel: string
  endLabel: string
  startMin: number
  endMin: number
  acknowledged: boolean
}

interface Props {
  open: boolean
  conflicts: ConflictItem[]
  scheduledTasks: Task[]
  onClose: () => void
}

function parseLabelMin(label: string): number {
  const [time, p] = label.split(' ')
  const [h, m] = time.split(':').map(Number)
  let hours = h
  if (p === 'PM' && h !== 12) hours += 12
  if (p === 'AM' && h === 12) hours = 0
  return hours * 60 + m
}

export default function ConflictPanel({ open, conflicts, scheduledTasks, onClose }: Props) {
  const [visible, setVisible] = useState(false)
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    if (open) {
      setMounted(true)
      requestAnimationFrame(() => requestAnimationFrame(() => setVisible(true)))
    } else {
      setVisible(false)
      const t = setTimeout(() => setMounted(false), 300)
      return () => clearTimeout(t)
    }
  }, [open])

  if (!mounted) return null

  return (
    <>
      {/* Darkened backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'absolute',
          inset: 0,
          background: visible ? 'rgba(13,13,18,0.5)' : 'rgba(13,13,18,0)',
          zIndex: 180,
          transition: 'background 0.25s ease',
        }}
      />

      {/* Dropdown panel — slides down from header */}
      <div
        style={{
          position: 'absolute',
          top: 140,
          left: spacing.lg,
          right: spacing.lg,
          zIndex: 181,
          background: colors.white,
          borderRadius: radius.card,
          boxShadow: '0 8px 40px rgba(20,30,70,0.22)',
          transform: visible ? 'translateY(0)' : 'translateY(-14px)',
          opacity: visible ? 1 : 0,
          transition: 'transform 0.27s cubic-bezier(0.4,0,0.2,1), opacity 0.2s ease',
          overflow: 'hidden',
        }}
      >
        {/* Panel header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: `14px ${spacing.lg}`,
            borderBottom: `1px solid ${colors.divider}`,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: colors.accent, flexShrink: 0 }} />
            <span style={{ fontSize: font.size.sm, fontWeight: font.weight.semibold, color: colors.textPrimary, letterSpacing: '-0.1px' }}>
              Today's Conflicts
            </span>
          </div>
          <button
            onClick={onClose}
            style={{
              width: 28, height: 28,
              background: colors.surface,
              border: 'none',
              borderRadius: '50%',
              cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
              <path d="M1 1l8 8M9 1L1 9" stroke={colors.textSecondary} strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* No conflicts state */}
        {conflicts.length === 0 && (
          <p style={{
            padding: `${spacing.lg} ${spacing.xl}`,
            margin: 0,
            fontSize: font.size.sm,
            color: colors.textDisabled,
            textAlign: 'center',
            lineHeight: 1.5,
          }}>
            No conflicts today.
          </p>
        )}

        {/* Conflict items */}
        {conflicts.map((c, i) => {
          const tasksInWindow = scheduledTasks.filter(
            t =>
              t.timeLabel &&
              parseLabelMin(t.timeLabel) >= c.startMin &&
              parseLabelMin(t.timeLabel) <= c.endMin,
          )

          return (
            <div
              key={c.id}
              style={{
                padding: `${spacing.md} ${spacing.lg}`,
                borderBottom: i < conflicts.length - 1 ? `1px solid ${colors.divider}` : 'none',
              }}
            >
              {/* Event header line */}
              <p style={{
                margin: `0 0 ${spacing.sm}`,
                fontSize: font.size.sm,
                color: colors.textPrimary,
                lineHeight: 1.5,
              }}>
                <span style={{ fontWeight: font.weight.semibold, color: colors.accent }}>{c.eventTitle}</span>
                <span style={{ color: colors.textSecondary }}> ({c.startLabel}–{c.endLabel})</span>
                {' '}overlaps with the following tasks:
              </p>

              {/* Task bullet list */}
              {tasksInWindow.length === 0 ? (
                <p style={{
                  margin: 0,
                  fontSize: font.size.sm,
                  color: colors.textDisabled,
                  fontStyle: 'italic',
                  paddingLeft: spacing.md,
                }}>
                  No tasks scheduled in this window.
                </p>
              ) : (
                <ul style={{ margin: 0, padding: `0 0 0 ${spacing.lg}`, listStyle: 'none' }}>
                  {tasksInWindow.map(t => (
                    <li
                      key={t.id}
                      style={{
                        display: 'flex',
                        alignItems: 'baseline',
                        gap: spacing.sm,
                        marginBottom: 4,
                      }}
                    >
                      {/* Custom bullet */}
                      <span style={{
                        width: 5, height: 5,
                        borderRadius: '50%',
                        background: colors.accent,
                        flexShrink: 0,
                        marginTop: 1,
                        display: 'inline-block',
                        opacity: 0.7,
                      }} />
                      <span style={{
                        fontSize: font.size.sm,
                        color: colors.textPrimary,
                        lineHeight: 1.45,
                      }}>
                        {t.title}
                        <span style={{ color: colors.textSecondary }}> · {t.timeLabel}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )
        })}
      </div>
    </>
  )
}
