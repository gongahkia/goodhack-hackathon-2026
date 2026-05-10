import { useState } from 'react'
import { colors, font, radius, spacing } from '../tokens'
import type { Task } from '../types'

interface Props {
  task: Task
  onToggle: (id: string) => void
  onSelect: (task: Task) => void
  showDivider?: boolean
  isCurrent?: boolean
}

function formatDueDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-SG', { day: 'numeric', month: 'short', year: 'numeric' })
}

export default function TaskRow({ task, onToggle, onSelect, showDivider, isCurrent }: Props) {
  const [pressing, setPressing] = useState(false)

  return (
    <div
      onClick={() => onSelect(task)}
      style={{
        position: 'relative',
        padding: `${spacing.md} ${spacing.lg}`,
        paddingLeft: isCurrent ? '20px' : spacing.lg,
        display: 'flex',
        alignItems: 'flex-start',
        gap: spacing.md,
        borderBottom: showDivider ? `1px solid ${colors.divider}` : 'none',
        background: isCurrent ? colors.primaryLight : 'transparent',
        opacity: task.completed ? 0.42 : 1,
        transition: 'opacity 0.3s ease, background 0.15s ease',
        cursor: 'pointer',
      }}>

      {/* Left accent strip for current task */}
      {isCurrent && (
        <div style={{
          position: 'absolute',
          left: 0,
          top: 0,
          bottom: 0,
          width: 3,
          background: colors.primary,
          borderRadius: `0 ${radius.xs} ${radius.xs} 0`,
        }} />
      )}

      {/* Checkbox */}
      <button
        onPointerDown={e => { e.stopPropagation(); setPressing(true) }}
        onPointerUp={e => { e.stopPropagation(); setPressing(false); onToggle(task.id) }}
        onPointerLeave={() => setPressing(false)}
        onClick={e => e.stopPropagation()}
        aria-label={task.completed ? 'Mark incomplete' : 'Mark complete'}
        style={{
          width: 22,
          height: 22,
          minWidth: 22,
          borderRadius: radius.sm,
          border: `1.8px solid ${task.completed ? colors.statusDone : colors.divider}`,
          background: task.completed ? colors.statusDone : colors.white,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginTop: 1,
          padding: 0,
          transform: pressing ? 'scale(0.84)' : 'scale(1)',
          transition: 'transform 0.1s ease, background 0.15s ease, border-color 0.15s ease',
          flexShrink: 0,
        }}
      >
        <svg width="12" height="9" viewBox="0 0 12 9" fill="none" style={{ overflow: 'visible' }}>
          <path
            d="M1.5 4.5L4.5 7.5L10.5 1.5"
            stroke="white"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray="14"
            strokeDashoffset={task.completed ? 0 : 14}
            style={{ transition: 'stroke-dashoffset 0.2s cubic-bezier(0.4, 0, 0.2, 1)' }}
          />
        </svg>
      </button>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: spacing.sm,
          marginBottom: task.detail ? '3px' : 0,
        }}>
          <span style={{
            fontSize: font.size.base,
            fontWeight: isCurrent ? font.weight.semibold : font.weight.medium,
            color: colors.textPrimary,
            textDecoration: task.completed ? 'line-through' : 'none',
            lineHeight: '1.35',
          }}>
            {task.title}
          </span>

          {/* "Now" badge replaces time badge for current task */}
          {isCurrent && !task.completed && (
            <span style={{
              fontSize: font.size.xs,
              fontWeight: font.weight.bold,
              color: colors.primary,
              background: colors.primaryLight,
              border: `1px solid ${colors.primary}`,
              padding: '2px 7px',
              borderRadius: radius.full,
              whiteSpace: 'nowrap',
              letterSpacing: '0.2px',
            }}>
              Now
            </span>
          )}

          {task.timeLabel && task.category === 'daily' && !isCurrent && (
            <span style={{
              fontSize: font.size.xs,
              fontWeight: font.weight.semibold,
              color: colors.accent,
              background: colors.accentLight,
              padding: '2px 7px',
              borderRadius: radius.full,
              letterSpacing: '0.1px',
              whiteSpace: 'nowrap',
            }}>
              {task.timeLabel}
            </span>
          )}

          {task.timeLabel && task.category === 'daily' && isCurrent && (
            <span style={{
              fontSize: font.size.xs,
              fontWeight: font.weight.medium,
              color: colors.textSecondary,
              whiteSpace: 'nowrap',
            }}>
              {task.timeLabel}
            </span>
          )}

          {task.urgent && (
            <span style={{
              fontSize: font.size.xs,
              fontWeight: font.weight.semibold,
              color: colors.statusUrgent,
              background: colors.statusUrgentLight,
              padding: '2px 7px',
              borderRadius: radius.full,
              whiteSpace: 'nowrap',
            }}>
              Urgent
            </span>
          )}
        </div>

        {task.detail && (
          <p style={{
            margin: 0,
            fontSize: font.size.sm,
            color: isCurrent ? colors.textSecondary : colors.textSecondary,
            lineHeight: '1.45',
          }}>
            {task.detail}
          </p>
        )}

        {task.category === 'adhoc' && task.dueDate && (
          <p style={{
            margin: '3px 0 0',
            fontSize: font.size.sm,
            fontWeight: font.weight.medium,
            color: task.urgent ? colors.statusUrgent : colors.textSecondary,
          }}>
            By {formatDueDate(task.dueDate)}
          </p>
        )}
      </div>
    </div>
  )
}
