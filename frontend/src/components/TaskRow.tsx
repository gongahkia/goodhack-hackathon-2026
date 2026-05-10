import { useState } from 'react'
import { colors, font, radius, spacing } from '../tokens'
import type { Task } from '../types'

interface Props {
  task: Task
  onToggle: (id: string) => void
  onSelect: (task: Task) => void
  showDivider?: boolean
}

function formatDueDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-SG', { day: 'numeric', month: 'short', year: 'numeric' })
}

export default function TaskRow({ task, onToggle, onSelect, showDivider }: Props) {
  const [pressing, setPressing] = useState(false)

  const isUrgent = !!task.urgent && !task.completed

  return (
    <div
      onClick={() => onSelect(task)}
      style={{
        position: 'relative',
        paddingTop: '14px',
        paddingBottom: '14px',
        paddingRight: spacing.lg,
        paddingLeft: isUrgent ? '20px' : spacing.lg,
        display: 'flex',
        alignItems: 'flex-start',
        gap: spacing.md,
        borderBottom: showDivider ? `1px solid ${colors.divider}` : 'none',
        background: isUrgent ? colors.statusUrgentLight : 'transparent',
        transition: 'background 0.15s ease',
        cursor: 'pointer',
      }}
    >
      {/* Urgent left accent strip */}
      {isUrgent && (
        <div style={{
          position: 'absolute',
          left: 0,
          top: 0,
          bottom: 0,
          width: 3,
          background: colors.statusUrgent,
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
          width: 28,
          height: 28,
          minWidth: 28,
          borderRadius: radius.sm,
          border: `2px solid ${task.completed ? colors.statusDone : colors.divider}`,
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
            strokeWidth="2"
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
          marginBottom: task.detail ? '4px' : 0,
        }}>
          <span style={{
            fontSize: font.size.md,
            fontWeight: font.weight.medium,
            color: task.completed ? colors.textSecondary : colors.textPrimary,
            textDecoration: task.completed ? 'line-through' : 'none',
            textDecorationThickness: '2px',
            textDecorationColor: colors.textSecondary,
            lineHeight: '1.35',
          }}>
            {task.title}
          </span>

          {isUrgent && (
            <span style={{
              fontSize: font.size.xs,
              fontWeight: font.weight.semibold,
              color: colors.statusUrgent,
              border: `1px solid ${colors.statusUrgent}`,
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
            color: colors.textSecondary,
            lineHeight: '1.45',
          }}>
            {task.detail}
          </p>
        )}

        {task.dueDate && (
          <p style={{
            margin: '5px 0 0',
            fontSize: isUrgent ? font.size.base : font.size.sm,
            fontWeight: isUrgent ? font.weight.semibold : font.weight.medium,
            color: isUrgent ? colors.statusUrgent : colors.textSecondary,
          }}>
            By {formatDueDate(task.dueDate)}
          </p>
        )}
      </div>
    </div>
  )
}
