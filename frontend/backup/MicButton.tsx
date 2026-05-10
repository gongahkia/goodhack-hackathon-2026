import { useState, useEffect } from 'react'
import { colors, font, radius, shadow } from '../tokens'

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

  return (
    <button
      onPointerDown={() => setPressing(true)}
      onPointerUp={() => { setPressing(false); handlePress() }}
      onPointerLeave={() => setPressing(false)}
      aria-label={recording ? 'Stop recording' : 'Start recording'}
      style={{
        width: '100%',
        height: 56,
        borderRadius: radius.pill,
        border: 'none',
        background: recording ? colors.recordingActive : colors.primary,
        boxShadow: shadow.fab,
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        transform: pressing ? 'scale(0.97)' : 'scale(1)',
        transition: 'transform 0.1s ease, background 0.2s ease',
      }}
    >
      {/* Icon */}
      {recording ? (
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <rect x="2" y="2" width="12" height="12" rx="3" fill="white" />
        </svg>
      ) : (
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <rect x="6" y="1" width="6" height="10" rx="3" fill="white" />
          <path d="M2.5 8.5c0 3.59 2.91 6.5 6.5 6.5s6.5-2.91 6.5-6.5" stroke="white" strokeWidth="1.6" strokeLinecap="round" />
          <line x1="9" y1="15" x2="9" y2="18" stroke="white" strokeWidth="1.6" strokeLinecap="round" />
          <line x1="6.5" y1="18" x2="11.5" y2="18" stroke="white" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      )}

      {/* Label */}
      <span style={{
        fontFamily: font.family,
        fontSize: font.size.base,
        fontWeight: font.weight.semibold,
        color: 'white',
        letterSpacing: '-0.1px',
      }}>
        {recording ? `Stop recording  ${formatElapsed(elapsed)}` : 'Record consultation  →'}
      </span>
    </button>
  )
}
