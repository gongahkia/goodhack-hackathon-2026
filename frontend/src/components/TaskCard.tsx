import { colors, radius, font, spacing, shadow } from '../tokens'
import type { Task } from '../types'

interface Props {
  task: Task
  onToggle: (id: string) => void
}

function formatDueDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('en-SG', { day: 'numeric', month: 'short', year: 'numeric' })
}

export default function TaskCard({ task, onToggle }: Props) {
  const isAdhoc = task.category === 'adhoc'

  return (
    <div
      style={{
        background: colors.white,
        border: `1.5px solid ${task.completed ? colors.divider : colors.divider}`,
        borderRadius: radius.md,
        padding: `${spacing.lg} ${spacing.lg}`,
        display: 'flex',
        gap: spacing.md,
        alignItems: 'flex-start',
        boxShadow: shadow.card,
        opacity: task.completed ? 0.6 : 1,
        transition: 'opacity 0.2s ease',
      }}
    >
      {/* Checkbox */}
      <button
        onClick={() => onToggle(task.id)}
        aria-label={task.completed ? 'Mark incomplete' : 'Mark complete'}
        style={{
          width: 24,
          height: 24,
          minWidth: 24,
          borderRadius: radius.sm,
          border: `2px solid ${task.completed ? colors.statusDone : colors.divider}`,
          background: task.completed ? colors.statusDone : colors.white,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginTop: 1,
          transition: 'all 0.15s ease',
          padding: 0,
        }}
      >
        {task.completed && (
          <svg width="13" height="10" viewBox="0 0 13 10" fill="none">
            <path d="M1.5 5L5 8.5L11.5 1.5" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </button>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap', marginBottom: task.detail ? spacing.xs : 0 }}>
          <span
            style={{
              fontFamily: font.family,
              fontSize: font.size.base,
              fontWeight: font.weight.semibold,
              color: task.completed ? colors.textDisabled : colors.textPrimary,
              textDecoration: task.completed ? 'line-through' : 'none',
              lineHeight: '1.4',
            }}
          >
            {task.title}
          </span>

          {task.timeLabel && !isAdhoc && (
            <span
              style={{
                fontFamily: font.family,
                fontSize: font.size.xs,
                fontWeight: font.weight.medium,
                color: colors.accent,
                background: colors.accentLight,
                padding: '2px 8px',
                borderRadius: radius.full,
                letterSpacing: '0.2px',
                whiteSpace: 'nowrap',
              }}
            >
              {task.timeLabel}
            </span>
          )}

          {task.urgent && (
            <span
              style={{
                fontFamily: font.family,
                fontSize: font.size.xs,
                fontWeight: font.weight.medium,
                color: colors.statusUrgent,
                background: colors.statusUrgentLight,
                padding: '2px 8px',
                borderRadius: radius.full,
                whiteSpace: 'nowrap',
              }}
            >
              Urgent
            </span>
          )}
        </div>

        {task.detail && (
          <p
            style={{
              fontFamily: font.family,
              fontSize: font.size.sm,
              color: colors.textSecondary,
              margin: 0,
              lineHeight: '1.5',
            }}
          >
            {task.detail}
          </p>
        )}

        {isAdhoc && task.dueDate && (
          <p
            style={{
              fontFamily: font.family,
              fontSize: font.size.sm,
              color: task.urgent ? colors.statusUrgent : colors.textSecondary,
              margin: `${spacing.xs} 0 0`,
              fontWeight: font.weight.medium,
            }}
          >
            By {formatDueDate(task.dueDate)}
          </p>
        )}
      </div>
    </div>
  )
}
