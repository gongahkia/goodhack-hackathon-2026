import { useEffect, useState } from 'react'
import { colors, font, radius, spacing, shadow } from '../tokens'

interface Props {
  durationMs: number | null
  onDismiss: () => void
}

export default function RecordingToast({ durationMs, onDismiss }: Props) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (durationMs === null) { setVisible(false); return }
    setVisible(true)
    const t = setTimeout(() => { setVisible(false); setTimeout(onDismiss, 300) }, 4000)
    return () => clearTimeout(t)
  }, [durationMs])

  function formatDuration(ms: number) {
    const s = Math.round(ms / 1000)
    if (s < 60) return `${s}s`
    return `${Math.floor(s / 60)}m ${s % 60}s`
  }

  return (
    <div style={{
      position: 'absolute',
      top: 80,
      left: '50%',
      transform: `translateX(-50%) translateY(${visible ? '0' : '-12px'})`,
      opacity: visible ? 1 : 0,
      transition: 'opacity 0.25s ease, transform 0.25s ease',
      zIndex: 200,
      pointerEvents: visible ? 'auto' : 'none',
    }}>
      <div style={{
        background: colors.primary,
        borderRadius: radius.md,
        padding: `${spacing.md} ${spacing.lg}`,
        boxShadow: shadow.fab,
        display: 'flex',
        alignItems: 'center',
        gap: spacing.md,
        minWidth: 240,
      }}>
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <circle cx="9" cy="9" r="8" stroke="rgba(255,255,255,0.5)" strokeWidth="1.5" />
          <path d="M5.5 9.5L7.5 11.5L12.5 6.5" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <div>
          <p style={{ fontFamily: font.family, fontSize: font.size.sm, fontWeight: font.weight.semibold, color: 'white', margin: 0 }}>
            Recording saved
          </p>
          {durationMs !== null && (
            <p style={{ fontFamily: font.family, fontSize: font.size.xs, color: 'rgba(255,255,255,0.7)', margin: `2px 0 0` }}>
              {formatDuration(durationMs)} · Processing…
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
