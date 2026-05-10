import { useState } from 'react'
import { colors, font, radius } from '../tokens'
import type { Task } from '../types'

interface Props {
  task: Task
  onToggle: (id: string) => void
  onSelect: (task: Task) => void
  isFirst: boolean
  isLast: boolean
  isCurrent: boolean
  isOverdue: boolean
  isConflict?: boolean
  onConflictRailClick?: (clientY: number) => void
}

export default function DailyTaskRow({ task, onToggle, onSelect, isFirst, isLast, isCurrent, isOverdue, isConflict, onConflictRailClick }: Props) {
  const [pressing, setPressing] = useState(false)

  const showNow = isCurrent && !isOverdue && !task.completed
  const showOverdue = isOverdue && !task.completed
  const [timeNum, timeMeridiem] = task.timeLabel ? task.timeLabel.split(' ') : ['', '']
  const AMBER = 'rgba(224,122,32,0.55)'
  const railColor = isConflict && !task.completed
    ? AMBER
    : task.completed
    ? colors.statusDone + '55'
    : colors.divider

  return (
    <div
      onClick={() => onSelect(task)}
      style={{
        display: 'flex',
        cursor: 'pointer',
        background: isConflict && !task.completed
          ? 'rgba(224,122,32,0.07)'
          : showNow
          ? colors.primaryLight
          : 'transparent',
        transition: 'background 0.15s ease',
        minHeight: 60,
      }}
    >
      {/* Time + rail wrapper — full left zone is tappable for conflict */}
      <div
        onClick={isConflict && onConflictRailClick
          ? (e) => { e.stopPropagation(); onConflictRailClick(e.clientY) }
          : undefined}
        style={{
          display: 'flex',
          cursor: isConflict && onConflictRailClick ? 'pointer' : undefined,
        }}
      >

      {/* Time column */}
      <div style={{
        width: 58,
        flexShrink: 0,
        paddingTop: 16,
        paddingRight: 10,
        textAlign: 'right',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-end',
        gap: 2,
      }}>
        <span style={{
          display: 'block',
          fontSize: '13px',
          fontWeight: font.weight.semibold,
          color: showNow ? colors.primary : showOverdue ? colors.statusUrgent : task.completed ? colors.textDisabled : colors.textSecondary,
          lineHeight: '1.2',
          transition: 'color 0.15s ease',
        }}>
          {timeNum}
        </span>
        <span style={{
          display: 'block',
          fontSize: '10px',
          fontWeight: font.weight.medium,
          color: showNow ? colors.primary : showOverdue ? colors.statusUrgent : task.completed ? colors.textDisabled : colors.textSecondary,
          letterSpacing: '0.4px',
          transition: 'color 0.15s ease',
        }}>
          {timeMeridiem}
        </span>
        {showNow && (
          <span style={{
            fontSize: '9px',
            fontWeight: font.weight.bold,
            color: colors.primary,
            background: colors.primaryLight,
            border: `1px solid ${colors.primary}`,
            padding: '1px 5px',
            borderRadius: radius.full,
            letterSpacing: '0.5px',
            marginTop: 2,
          }}>
            NOW
          </span>
        )}
        {showOverdue && (
          <span style={{
            fontSize: '9px',
            fontWeight: font.weight.bold,
            color: colors.statusUrgent,
            border: `1px solid ${colors.statusUrgent}`,
            padding: '1px 5px',
            borderRadius: radius.full,
            letterSpacing: '0.5px',
            marginTop: 2,
          }}>
            Late
          </span>
        )}
      </div>

      {/* Rail column */}
      <div style={{
        width: 28,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
      }}>
        {/* Line above node */}
        <div style={{
          width: 2,
          height: 16,
          background: isFirst ? 'transparent' : railColor,
          flexShrink: 0,
          transition: 'background 0.15s ease',
        }} />

        {/* Node / checkbox */}
        <button
          onPointerDown={e => { e.stopPropagation(); setPressing(true) }}
          onPointerUp={e => { e.stopPropagation(); setPressing(false); onToggle(task.id) }}
          onPointerLeave={() => setPressing(false)}
          onClick={e => e.stopPropagation()}
          aria-label={task.completed ? 'Mark incomplete' : 'Mark complete'}
          style={{
            width: 22,
            height: 22,
            borderRadius: '50%',
            border: `2px solid ${task.completed ? colors.statusDone : showNow ? colors.primary : showOverdue ? colors.statusUrgent : colors.divider}`,
            background: task.completed ? colors.statusDone : colors.white,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 0,
            flexShrink: 0,
            transform: pressing ? 'scale(0.84)' : 'scale(1)',
            transition: 'transform 0.1s ease, background 0.15s ease, border-color 0.15s ease',
            position: 'relative',
            zIndex: 1,
          }}
        >
          {task.completed ? (
            <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
              <path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          ) : showNow ? (
            <div style={{ width: 7, height: 7, borderRadius: '50%', background: colors.primary }} />
          ) : null}
        </button>

        {/* Line below node */}
        <div style={{
          width: 2,
          flex: 1,
          minHeight: 14,
          background: isLast ? 'transparent' : railColor,
          flexShrink: 0,
          transition: 'background 0.15s ease',
        }} />
      </div>

      </div>{/* end time+rail wrapper */}

      {/* Content */}
      <div style={{
        flex: 1,
        padding: '12px 16px 14px 4px',
        minWidth: 0,
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '6px',
          marginBottom: task.detail ? '4px' : 0,
        }}>
          <span style={{
            fontSize: font.size.md,
            fontWeight: showNow ? font.weight.semibold : font.weight.medium,
            color: task.completed ? colors.textSecondary : colors.textPrimary,
            textDecoration: task.completed ? 'line-through' : 'none',
            textDecorationThickness: '2px',
            textDecorationColor: colors.textSecondary,
            lineHeight: '1.3',
          }}>
            {task.title}
          </span>

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
      </div>
    </div>
  )
}
