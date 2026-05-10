import { useState } from 'react'
import { colors, font, spacing } from '../tokens'
import type { Task } from '../types'

interface Props {
  task: Task
  onToggle: (id: string) => void
  onSelect: (task: Task) => void
  showDivider?: boolean
}

export default function DailyGoalRow({ task, onToggle, onSelect, showDivider }: Props) {
  const [pressing, setPressing] = useState(false)

  return (
    <div
      onClick={() => onSelect(task)}
      style={{
        display: 'flex',
        cursor: 'pointer',
        paddingTop: '12px',
        paddingBottom: '12px',
        paddingLeft: spacing.lg,
        paddingRight: spacing.lg,
        gap: spacing.md,
        alignItems: 'flex-start',
        borderBottom: showDivider ? `1px solid ${colors.divider}` : 'none',
      }}
    >
      {/* Circle checkbox */}
      <button
        onPointerDown={e => { e.stopPropagation(); setPressing(true) }}
        onPointerUp={e => { e.stopPropagation(); setPressing(false); onToggle(task.id) }}
        onPointerLeave={() => setPressing(false)}
        onClick={e => e.stopPropagation()}
        aria-label={task.completed ? 'Mark incomplete' : 'Mark complete'}
        style={{
          width: 24,
          height: 24,
          minWidth: 24,
          borderRadius: '50%',
          border: `2px solid ${task.completed ? colors.statusDone : colors.divider}`,
          background: task.completed ? colors.statusDone : colors.white,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 0,
          marginTop: 1,
          transform: pressing ? 'scale(0.84)' : 'scale(1)',
          transition: 'transform 0.1s ease, background 0.15s ease, border-color 0.15s ease',
          flexShrink: 0,
        }}
      >
        {task.completed && (
          <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
            <path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </button>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <span style={{
          display: 'block',
          fontSize: font.size.md,
          fontWeight: font.weight.medium,
          color: task.completed ? colors.textSecondary : colors.textPrimary,
          textDecoration: task.completed ? 'line-through' : 'none',
          textDecorationThickness: '2px',
          textDecorationColor: colors.textSecondary,
          lineHeight: '1.3',
        }}>
          {task.title}
        </span>
        {task.detail && (
          <p style={{
            margin: '3px 0 0',
            fontSize: font.size.sm,
            color: colors.textSecondary,
            lineHeight: '1.45',
          }}>
            {task.detail}
          </p>
        )}
      </div>
    </div>
  )
}
