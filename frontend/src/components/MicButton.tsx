import { useState, useEffect } from 'react'
import { colors, font } from '../tokens'

interface Props {
  onRecordingComplete: (durationMs: number) => void
}

export default function MicButton({ onRecordingComplete }: Props) {
  const [recording, setRecording] = useState(false)
  const [pressing, setPressing] = useState(false)
  const [startTime, setStartTime] = useState<number | null>(null)
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (!recording) { setElapsed(0); return }
    const interval = setInterval(() => setElapsed(Date.now() - (startTime ?? Date.now())), 500)
    return () => clearInterval(interval)
  }, [recording, startTime])

  function handlePress() {
    if (recording) {
      const duration = startTime ? Date.now() - startTime : 0
      setRecording(false)
      setStartTime(null)
      onRecordingComplete(duration)
    } else {
      setRecording(true)
      setStartTime(Date.now())
    }
  }

  function formatElapsed(ms: number) {
    const s = Math.floor(ms / 1000)
    const m = Math.floor(s / 60)
    return `${m}:${String(s % 60).padStart(2, '0')}`
  }

  const bg = recording
    ? `linear-gradient(135deg, ${colors.recordingActive} 0%, #D9402A 100%)`
    : `linear-gradient(135deg, ${colors.primary} 0%, #2B4494 100%)`

  const glowColor = recording
    ? 'rgba(196,52,28,0.32)'
    : 'rgba(27,45,107,0.32)'

  return (
    <button
      onPointerDown={() => setPressing(true)}
      onPointerUp={() => { setPressing(false); handlePress() }}
      onPointerLeave={() => setPressing(false)}
      aria-label={recording ? 'Stop recording' : 'Start recording'}
      style={{
        width: '100%',
        height: 62,
        borderRadius: '16px',
        border: 'none',
        background: bg,
        boxShadow: `0 6px 20px ${glowColor}, 0 2px 6px rgba(0,0,0,0.12)`,
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        transform: pressing ? 'scale(0.97) translateY(1px)' : 'scale(1) translateY(0px)',
        transition: 'transform 0.1s ease, background 0.25s ease, box-shadow 0.25s ease',
      }}
    >
      {/* Icon */}
      <div style={{
        width: 36,
        height: 36,
        borderRadius: '50%',
        background: 'rgba(255,255,255,0.15)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
      }}>
        {recording ? (
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <rect x="1.5" y="1.5" width="11" height="11" rx="2.5" fill="white" />
          </svg>
        ) : (
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <rect x="7" y="1" width="6" height="11" rx="3" fill="white" />
            <path d="M3 9.5c0 3.866 3.134 7 7 7s7-3.134 7-7" stroke="white" strokeWidth="1.7" strokeLinecap="round" />
            <line x1="10" y1="16.5" x2="10" y2="19.5" stroke="white" strokeWidth="1.7" strokeLinecap="round" />
            <line x1="7" y1="19.5" x2="13" y2="19.5" stroke="white" strokeWidth="1.7" strokeLinecap="round" />
          </svg>
        )}
      </div>

      {/* Label */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
        <span style={{
          fontFamily: font.family,
          fontSize: font.size.base,
          fontWeight: font.weight.semibold,
          color: 'white',
          letterSpacing: '-0.2px',
          lineHeight: '1.2',
        }}>
          {recording ? 'Recording…' : 'Record consultation'}
        </span>
        {recording && (
          <span style={{
            fontFamily: font.family,
            fontSize: font.size.xs,
            fontWeight: font.weight.medium,
            color: 'rgba(255,255,255,0.7)',
            letterSpacing: '0.3px',
            marginTop: '1px',
          }}>
            {formatElapsed(elapsed)} · tap to stop
          </span>
        )}
      </div>
    </button>
  )
}
