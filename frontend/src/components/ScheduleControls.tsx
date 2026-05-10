import { useState, useEffect, useRef, useMemo } from 'react'
import { colors, font, radius, spacing } from '../tokens'
import type { Recurrence, ActivePeriod, RecurrenceMode } from '../types'

// ─── Shared helpers ───────────────────────────────────────────────────────────

const DAY_LETTERS = ['S', 'M', 'T', 'W', 'T', 'F', 'S']
const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]
const MONTH_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function isoOf(d: Date) { return d.toISOString().slice(0, 10) }
function dateOf(iso: string) {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}
function todayISO() { return isoOf(new Date()) }
function formatChipDate(iso: string) {
  const d = dateOf(iso)
  return `${MONTH_SHORT[d.getMonth()]} ${d.getDate()}`
}

/** Builds a grid of days for a given month, padded to a multiple of 7. */
function buildMonthGrid(year: number, month: number) {
  const first = new Date(year, month, 1)
  const startDow = first.getDay()
  const grid: { date: Date; inMonth: boolean }[] = []

  // back-fill leading days from previous month
  for (let i = startDow - 1; i >= 0; i--) {
    grid.push({ date: new Date(year, month, -i), inMonth: false })
  }
  // current month
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  for (let i = 1; i <= daysInMonth; i++) {
    grid.push({ date: new Date(year, month, i), inMonth: true })
  }
  // pad to next multiple of 7
  let n = 1
  while (grid.length % 7 !== 0) {
    grid.push({ date: new Date(year, month + 1, n++), inMonth: false })
  }
  return grid
}

/** Generates an array of {year, month} objects spanning backMonths before and forwardMonths after today. */
function generateMonths(backMonths: number, forwardMonths: number) {
  const now = new Date()
  const result: { year: number; month: number }[] = []
  for (let i = -backMonths; i <= forwardMonths; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() + i, 1)
    result.push({ year: d.getFullYear(), month: d.getMonth() })
  }
  return result
}

// ─── RecurrencePicker ─────────────────────────────────────────────────────────

const MODES: { id: RecurrenceMode; label: string }[] = [
  { id: 'daily', label: 'Daily' },
  { id: 'weekly', label: 'Weekly' },
  { id: 'custom', label: 'Custom' },
]

export function RecurrencePicker({
  value,
  onChange,
}: {
  value: Recurrence
  onChange: (v: Recurrence) => void
}) {
  const selected = value.weekdays ?? []

  function pickMode(mode: RecurrenceMode) {
    if (mode === value.mode) return
    if (mode === 'daily') {
      onChange({ mode: 'daily', weekdays: [0, 1, 2, 3, 4, 5, 6] })
    } else if (mode === 'weekly') {
      // Monday selected by default
      onChange({ mode: 'weekly', weekdays: [1] })
    } else {
      // custom — start with nothing selected
      onChange({ mode: 'custom', weekdays: [] })
    }
  }

  function toggleDay(i: number) {
    const next = selected.includes(i)
      ? selected.filter(d => d !== i)
      : [...selected, i].sort((a, b) => a - b)

    if (next.length === 0) return // never allow fully empty

    // Auto-promote / demote mode based on selection count
    let newMode: RecurrenceMode
    if (next.length === 7) newMode = 'daily'
    else if (next.length === 1) newMode = 'weekly'
    else newMode = 'custom'

    onChange({ mode: newMode, weekdays: next })
  }

  return (
    <div>
      {/* Mode chips */}
      <div style={{ display: 'flex', gap: spacing.xs, flexWrap: 'wrap', marginBottom: spacing.md }}>
        {MODES.map(m => {
          const active = m.id === value.mode
          return (
            <button
              key={m.id}
              onClick={() => pickMode(m.id)}
              style={{
                background: active ? colors.primary : colors.surface,
                color: active ? colors.white : colors.textSecondary,
                border: active ? 'none' : `1px solid ${colors.divider}`,
                borderRadius: radius.full,
                padding: '7px 14px',
                fontFamily: font.family,
                fontSize: font.size.sm,
                fontWeight: font.weight.semibold,
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
            >
              {m.label}
            </button>
          )
        })}
      </div>

      {/* Day dots — always visible */}
      <div style={{ display: 'flex', gap: 6, paddingLeft: 2 }}>
        {DAY_LETTERS.map((letter, i) => {
          const on = selected.includes(i)
          return (
            <button
              key={i}
              onClick={() => toggleDay(i)}
              aria-label={`Toggle ${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][i]}`}
              style={{
                width: 32,
                height: 32,
                borderRadius: radius.full,
                background: on ? colors.primary : colors.surface,
                color: on ? colors.white : colors.textDisabled,
                border: on ? 'none' : `1px solid ${colors.divider}`,
                fontFamily: font.family,
                fontSize: font.size.xs,
                fontWeight: font.weight.bold,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.15s ease',
              }}
            >
              {letter}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ─── PeriodPicker ─────────────────────────────────────────────────────────────

export function PeriodPicker({
  value,
  onChange,
}: {
  value: ActivePeriod
  onChange: (v: ActivePeriod) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [pickPhase, setPickPhase] = useState<'start' | 'end'>('start')
  // Separate "ongoing" intent from "custom with no end picked yet"
  // (both share end === null in the data model)
  const [isCustomMode, setIsCustomMode] = useState(() => value.end !== null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const isOngoing = !isCustomMode
  const today = todayISO()

  // 1 month back, 24 months forward = 26 months total
  const months = useMemo(() => generateMonths(1, 24), [])

  // Scroll to today's month whenever the calendar opens
  useEffect(() => {
    if (!expanded || !scrollRef.current) return
    const todayYM = today.slice(0, 7) // "YYYY-MM"
    const el = scrollRef.current.querySelector(
      `[data-ym="${todayYM}"]`,
    ) as HTMLElement | null
    if (el) {
      // Use offsetTop relative to the scroll container
      scrollRef.current.scrollTop = el.offsetTop - 8
    }
  }, [expanded])

  function chipLabel() {
    if (isOngoing) return `${formatChipDate(value.start)} — Ongoing`
    if (!value.end) return `${formatChipDate(value.start)} — pick end…`
    return `${formatChipDate(value.start)} — ${formatChipDate(value.end)}`
  }

  function handleSetOngoing() {
    setIsCustomMode(false)
    onChange({ ...value, end: null })
    setPickPhase('start')
  }

  function handleSetCustom() {
    if (!isCustomMode) {
      // Switching from ongoing → custom: start a fresh range from today
      setIsCustomMode(true)
      onChange({ start: today, end: null })
      setPickPhase('end')
    }
    // Already in custom mode — user is already picking, do nothing
  }

  function selectDay(iso: string) {
    if (isOngoing) return // calendar is read-only in ongoing mode
    if (pickPhase === 'start') {
      onChange({ start: iso, end: null })
      setPickPhase('end')
    } else {
      // end phase
      if (iso < value.start) {
        // Tapped before start → restart range from this day
        onChange({ start: iso, end: null })
        setPickPhase('end')
      } else {
        onChange({ start: value.start, end: iso })
        setPickPhase('start')
      }
    }
  }

  // Caption under the calendar
  function helperText() {
    if (!value.end) {
      return pickPhase === 'start' ? 'Tap a start date.' : 'Now tap an end date.'
    }
    return 'Tap a day to set a new start date.'
  }

  return (
    <div
      style={{
        background: colors.surface,
        border: `1px solid ${colors.divider}`,
        borderRadius: radius.md,
        overflow: 'hidden',
      }}
    >
      {/* Collapsed header / pill */}
      <button
        onClick={() => setExpanded(p => !p)}
        style={{
          width: '100%',
          background: 'transparent',
          border: 'none',
          padding: `${spacing.sm} ${spacing.md}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          fontFamily: font.family,
        }}
      >
        <span
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: spacing.sm,
            fontSize: font.size.base,
            fontWeight: font.weight.semibold,
            color: colors.textPrimary,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          <CalendarIcon />
          {chipLabel()}
        </span>
        <ChevronIcon down={expanded} />
      </button>

      {/* Expandable body */}
      <div
        style={{
          maxHeight: expanded ? 440 : 0,
          overflow: 'hidden',
          transition: 'max-height 0.32s cubic-bezier(0.4, 0, 0.2, 1)',
        }}
      >
        <div style={{ borderTop: `1px solid ${colors.divider}` }}>

          {/* Segmented toggle: Ongoing / Custom */}
          <div style={{ display: 'flex', gap: spacing.xs, padding: `${spacing.sm} ${spacing.md}` }}>
            <ToggleChip label="Ongoing" active={isOngoing} onClick={handleSetOngoing} />
            <ToggleChip label="Custom" active={!isOngoing} onClick={handleSetCustom} />
          </div>

          {/* Scrollable month list */}
          <div
            ref={scrollRef}
            style={{
              height: 320,
              overflowY: 'auto',
              padding: `0 ${spacing.md} ${spacing.sm}`,
              opacity: isOngoing ? 0.38 : 1,
              pointerEvents: isOngoing ? 'none' : 'auto',
              transition: 'opacity 0.2s ease',
            }}
          >
            {months.map(({ year, month }) => {
              const ym = `${year}-${String(month + 1).padStart(2, '0')}`
              const grid = buildMonthGrid(year, month)

              return (
                <div key={ym} data-ym={ym} style={{ marginBottom: 20 }}>
                  {/* Month label */}
                  <p
                    style={{
                      margin: `0 0 6px`,
                      fontSize: font.size.sm,
                      fontWeight: font.weight.semibold,
                      color: colors.textSecondary,
                      letterSpacing: '0.3px',
                    }}
                  >
                    {MONTH_NAMES[month]} {year}
                  </p>

                  {/* Weekday headers */}
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(7, 1fr)',
                      marginBottom: 2,
                    }}
                  >
                    {DAY_LETTERS.map((l, i) => (
                      <div
                        key={i}
                        style={{
                          textAlign: 'center',
                          fontSize: '10px',
                          fontWeight: font.weight.semibold,
                          color: colors.textDisabled,
                          letterSpacing: '0.5px',
                        }}
                      >
                        {l}
                      </div>
                    ))}
                  </div>

                  {/* Day cells */}
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(7, 1fr)',
                      rowGap: 1,
                    }}
                  >
                    {grid.map(({ date, inMonth }, idx) => {
                      const iso = isoOf(date)
                      const isStart = iso === value.start
                      const isEnd = iso === value.end
                      const inRange =
                        !isOngoing &&
                        !!value.end &&
                        iso > value.start &&
                        iso < value.end
                      const isToday = iso === today
                      const isEndpoint = isStart || isEnd

                      return (
                        <div
                          key={idx}
                          style={{
                            position: 'relative',
                            height: 32,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}
                        >
                          {/* Range fill band */}
                          {(inRange || (!!value.end && (isStart || isEnd))) && (
                            <div
                              style={{
                                position: 'absolute',
                                inset: '3px 0',
                                background: colors.primaryLight,
                                borderTopLeftRadius: isStart ? radius.full : 0,
                                borderBottomLeftRadius: isStart ? radius.full : 0,
                                borderTopRightRadius: isEnd ? radius.full : 0,
                                borderBottomRightRadius: isEnd ? radius.full : 0,
                              }}
                            />
                          )}

                          <button
                            onClick={() => selectDay(iso)}
                            style={{
                              position: 'relative',
                              width: 28,
                              height: 28,
                              borderRadius: radius.full,
                              border: 'none',
                              background: isEndpoint ? colors.primary : 'transparent',
                              color: isEndpoint
                                ? colors.white
                                : inMonth
                                ? colors.textPrimary
                                : colors.textDisabled,
                              fontFamily: font.family,
                              fontSize: font.size.sm,
                              fontWeight:
                                isEndpoint || isToday
                                  ? font.weight.bold
                                  : font.weight.medium,
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              transition: 'background 0.12s ease',
                            }}
                          >
                            {date.getDate()}
                            {/* Today indicator dot */}
                            {isToday && !isEndpoint && (
                              <span
                                style={{
                                  position: 'absolute',
                                  bottom: 3,
                                  width: 3,
                                  height: 3,
                                  borderRadius: radius.full,
                                  background: colors.primary,
                                }}
                              />
                            )}
                          </button>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Helper caption */}
          {!isOngoing && (
            <p
              style={{
                margin: 0,
                padding: `0 ${spacing.md} ${spacing.md}`,
                fontSize: font.size.xs,
                color: colors.textSecondary,
                textAlign: 'center',
                lineHeight: 1.45,
              }}
            >
              {helperText()}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Small sub-components ─────────────────────────────────────────────────────

function CalendarIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <rect x="1.5" y="2.5" width="11" height="10" rx="1.5" stroke={colors.primary} strokeWidth="1.4" />
      <line x1="1.5" y1="5.5" x2="12.5" y2="5.5" stroke={colors.primary} strokeWidth="1.4" />
      <line x1="4.5" y1="1" x2="4.5" y2="3.5" stroke={colors.primary} strokeWidth="1.4" strokeLinecap="round" />
      <line x1="9.5" y1="1" x2="9.5" y2="3.5" stroke={colors.primary} strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  )
}

function ChevronIcon({ down }: { down: boolean }) {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 14 14"
      fill="none"
      style={{
        transform: down ? 'rotate(180deg)' : 'rotate(0deg)',
        transition: 'transform 0.25s ease',
      }}
    >
      <path
        d="M3 5L7 9L11 5"
        stroke={colors.textSecondary}
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function ToggleChip({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      style={{
        background: active ? colors.primary : colors.white,
        color: active ? colors.white : colors.textSecondary,
        border: active ? 'none' : `1px solid ${colors.divider}`,
        borderRadius: radius.full,
        padding: '5px 14px',
        fontFamily: font.family,
        fontSize: font.size.sm,
        fontWeight: font.weight.semibold,
        cursor: 'pointer',
        transition: 'all 0.15s ease',
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </button>
  )
}
