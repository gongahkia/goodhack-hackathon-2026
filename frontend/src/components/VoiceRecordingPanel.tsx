import { useEffect, useRef, useState } from 'react'
import { createTranscription } from '../api'
import { colors, font, radius, spacing } from '../tokens'

interface RecordingComplete {
  transcriptionSessionId: string
  transcriptId?: string
  displayTranscript: string
}

interface Props {
  open: boolean
  onComplete: (recording: RecordingComplete) => void | Promise<void>
  onCancel: () => void
}

type Phase = 'recording' | 'completing' | 'done'

type SpeechRecognitionLike = {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: { error?: string }) => void) | null
  start: () => void
  stop: () => void
  abort?: () => void
}

type SpeechRecognitionEventLike = {
  resultIndex: number
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

const BAR_HEIGHTS = [
  0.30, 0.60, 0.90, 0.50, 0.82, 0.42, 0.88, 0.56,
  0.72, 0.36, 0.94, 0.52, 0.68, 0.44, 0.78, 0.32,
  0.84, 0.62, 0.96, 0.40, 0.74, 0.50, 0.86, 0.34,
  0.66, 0.76, 0.46, 0.58,
]

function speechCtor(): SpeechRecognitionConstructor | undefined {
  const win = window as unknown as {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }
  return win.SpeechRecognition ?? win.webkitSpeechRecognition
}

export default function VoiceRecordingPanel({ open, onComplete, onCancel }: Props) {
  const [phase, setPhase] = useState<Phase>('recording')
  const [seconds, setSeconds] = useState(0)
  const [transcript, setTranscript] = useState('')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [transcriptId, setTranscriptId] = useState<string | undefined>()
  const [error, setError] = useState<string | null>(null)
  const [speechNotice, setSpeechNotice] = useState<string | null>(null)
  const [reviewing, setReviewing] = useState(false)
  const transcriptRef = useRef<HTMLDivElement>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const finalSpeechRef = useRef('')
  const cancelledRef = useRef(false)

  useEffect(() => {
    if (!open) return
    setPhase('recording')
    setSeconds(0)
    setTranscript('')
    setSessionId(null)
    setTranscriptId(undefined)
    setError(null)
    setSpeechNotice(null)
    setReviewing(false)
    chunksRef.current = []
    finalSpeechRef.current = ''
    cancelledRef.current = false
    void startCapture()
    return stopCapture
  }, [open])

  useEffect(() => {
    if (!open || phase === 'done') return
    const id = setInterval(() => setSeconds(s => s + 1), 1000)
    return () => clearInterval(id)
  }, [open, phase])

  useEffect(() => {
    if (transcriptRef.current) transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight
  }, [transcript])

  async function startCapture() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const recorder = new MediaRecorder(stream)
      recorderRef.current = recorder
      recorder.ondataavailable = event => {
        if (event.data.size > 0) chunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        if (!cancelledRef.current) void uploadRecording(recorder.mimeType || 'audio/webm')
      }
      recorder.start()
      if (!startSpeechTranscript()) {
        setSpeechNotice('Live transcript unavailable in this browser. Backend transcript will appear after stop.')
      }
    } catch (captureError) {
      setError(captureError instanceof Error ? captureError.message : 'Microphone capture failed')
      setPhase('done')
    }
  }

  function startSpeechTranscript() {
    const Ctor = speechCtor()
    if (!Ctor) return false
    try {
      const recognition = new Ctor()
      recognition.continuous = true
      recognition.interimResults = true
      recognition.lang = 'en-SG'
      recognition.onresult = event => {
        let interim = ''
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const text = event.results[i][0].transcript
          if (event.results[i].isFinal) finalSpeechRef.current += `${text} `
          else interim += text
        }
        setTranscript(`${finalSpeechRef.current}${interim}`.trim())
      }
      recognition.onerror = event => {
        setSpeechNotice(`Live transcript unavailable${event.error ? ` (${event.error})` : ''}. Backend transcript will appear after stop.`)
      }
      recognition.start()
      recognitionRef.current = recognition
      return true
    } catch {
      recognitionRef.current = null
      return false
    }
  }

  function stopCapture() {
    recognitionRef.current?.abort?.()
    recognitionRef.current = null
    streamRef.current?.getTracks().forEach(track => track.stop())
    streamRef.current = null
  }

  async function uploadRecording(contentType: string) {
    setPhase('completing')
    stopCapture()
    try {
      const audio = new Blob(chunksRef.current, { type: contentType })
      const result = await createTranscription(audio, 'en')
      setSessionId(result.transcription_session.id)
      setTranscriptId(result.transcript?.id)
      if (result.display_transcript?.trim()) setTranscript(result.display_transcript.trim())
      setPhase('done')
    } catch (uploadError) {
      console.warn('Audio upload failed', uploadError)
      setError('Transcription service unavailable. Try again.')
      setPhase('done')
    }
  }

  function stopRecording() {
    if (recorderRef.current?.state === 'recording') {
      setPhase('completing')
      recorderRef.current.stop()
    }
  }

  function cancel() {
    cancelledRef.current = true
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
    stopCapture()
    onCancel()
  }

  async function reviewPlan() {
    if (!sessionId) return
    setReviewing(true)
    try {
      await onComplete({ transcriptionSessionId: sessionId, transcriptId, displayTranscript: transcript })
    } finally {
      setReviewing(false)
    }
  }

  const fmt = (s: number) =>
    `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

  const isActive = phase === 'recording'
  const displayText = error || transcript || (isActive ? speechNotice || 'Listening...' : 'Backend transcription finished, but no display transcript was returned.')

  return (
    <>
      <style>{`
        @keyframes recPulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.3; transform: scale(0.75); }
        }
        @keyframes cur { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
        @keyframes w0 { 0%,100%{transform:scaleY(0.25)} 50%{transform:scaleY(1)} }
        @keyframes w1 { 0%,100%{transform:scaleY(0.8)}  50%{transform:scaleY(0.2)} }
        @keyframes w2 { 0%,100%{transform:scaleY(1)}    50%{transform:scaleY(0.4)} }
        @keyframes w3 { 0%,100%{transform:scaleY(0.4)}  50%{transform:scaleY(0.95)} }
        @keyframes w4 { 0%,100%{transform:scaleY(0.7)}  50%{transform:scaleY(0.3)} }
      `}</style>

      <div
        onClick={phase === 'recording' ? cancel : undefined}
        style={{
          position: 'absolute',
          inset: 0,
          background: 'rgba(10,12,26,0.60)',
          opacity: open ? 1 : 0,
          pointerEvents: open ? 'auto' : 'none',
          visibility: open ? 'visible' : 'hidden',
          transition: 'opacity 0.3s ease',
          zIndex: 50,
        }}
      />

      <div style={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: 0,
        height: 'calc(100% - 100px)',
        background: colors.white,
        borderRadius: '22px 22px 0 0',
        zIndex: 51,
        transform: open ? 'translateY(0)' : 'translateY(106%)',
        transition: 'transform 0.40s cubic-bezier(0.4, 0, 0.2, 1)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        pointerEvents: open ? 'auto' : 'none',
        visibility: open ? 'visible' : 'hidden',
      }}>
        <div style={{ paddingTop: spacing.md, paddingBottom: spacing.sm, display: 'flex', justifyContent: 'center', flexShrink: 0 }}>
          <div style={{ width: 36, height: 4, borderRadius: radius.full, background: colors.divider }} />
        </div>

        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingLeft: spacing.xl,
          paddingRight: spacing.xl,
          paddingBottom: spacing.md,
          flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm }}>
            <div style={{
              width: 9,
              height: 9,
              borderRadius: radius.full,
              background: isActive ? colors.statusUrgent : phase === 'completing' ? colors.accent : error ? colors.statusUrgent : colors.statusDone,
              animation: isActive ? 'recPulse 1.1s ease-in-out infinite' : 'none',
              transition: 'background 0.4s ease',
              flexShrink: 0,
            }} />
            <span style={{
              fontSize: font.size.sm,
              fontWeight: font.weight.bold,
              color: isActive ? colors.statusUrgent : phase === 'completing' ? colors.accent : error ? colors.statusUrgent : colors.statusDone,
              letterSpacing: '0.8px',
              transition: 'color 0.4s ease',
            }}>
              {isActive ? 'REC' : phase === 'completing' ? 'TRANSCRIBING' : error ? 'ERROR' : 'DONE'}
            </span>
          </div>
          <span style={{
            fontSize: font.size.md,
            fontWeight: font.weight.semibold,
            color: colors.textPrimary,
            fontVariantNumeric: 'tabular-nums',
            letterSpacing: '0.5px',
          }}>
            {fmt(seconds)}
          </span>
        </div>

        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 4,
          height: 48,
          flexShrink: 0,
          paddingLeft: spacing.xl,
          paddingRight: spacing.xl,
          marginBottom: spacing.sm,
        }}>
          {BAR_HEIGHTS.map((h, i) => (
            <div key={i} style={{
              flex: 1,
              height: `${h * 40}px`,
              borderRadius: 2,
              background: isActive ? colors.statusUrgent : colors.primary,
              opacity: isActive ? 0.7 + h * 0.3 : 0.25 + h * 0.35,
              animationName: isActive ? `w${i % 5}` : 'none',
              animationDuration: `${0.65 + (i % 4) * 0.10}s`,
              animationTimingFunction: 'ease-in-out',
              animationIterationCount: 'infinite',
              animationDelay: `${(i * 0.048).toFixed(2)}s`,
              transformOrigin: 'center',
              transition: 'background 0.5s ease, opacity 0.5s ease',
            }} />
          ))}
        </div>

        <div style={{
          flex: 1,
          minHeight: 0,
          marginLeft: spacing.lg,
          marginRight: spacing.lg,
          marginBottom: spacing.md,
          borderRadius: radius.md,
          background: colors.surface,
          border: `1.5px solid ${isActive ? colors.statusUrgent + '40' : error ? colors.statusUrgent + '60' : colors.divider}`,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          transition: 'border-color 0.4s ease',
          position: 'relative',
        }}>
          <div style={{
            paddingLeft: spacing.lg,
            paddingRight: spacing.lg,
            paddingTop: spacing.md,
            paddingBottom: spacing.sm,
            flexShrink: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}>
            <span style={{
              fontSize: font.size.xs,
              fontWeight: font.weight.semibold,
              color: isActive ? colors.statusUrgent : colors.textDisabled,
              textTransform: 'uppercase',
              letterSpacing: '0.7px',
              transition: 'color 0.4s ease',
            }}>
              Live transcript
            </span>
            {phase === 'done' && sessionId && !error && (
              <span style={{ fontSize: font.size.xs, fontWeight: font.weight.medium, color: colors.statusDone }}>
                Review before saving
              </span>
            )}
          </div>

          <div
            ref={transcriptRef}
            style={{
              flex: 1,
              overflowY: 'auto',
              minHeight: 0,
              paddingLeft: spacing.lg,
              paddingRight: spacing.lg,
              paddingBottom: spacing.lg,
            }}
          >
            <p style={{
              margin: 0,
              fontSize: font.size.sm,
              color: error ? colors.statusUrgent : transcript ? colors.textPrimary : colors.textDisabled,
              lineHeight: '1.75',
              fontWeight: font.weight.regular,
              whiteSpace: 'pre-wrap',
            }}>
              {displayText}
              {isActive && !error && (
                <span style={{
                  display: 'inline-block',
                  width: 2,
                  height: '1em',
                  background: colors.statusUrgent,
                  marginLeft: 3,
                  verticalAlign: 'text-bottom',
                  borderRadius: 1,
                  animation: 'cur 0.85s step-end infinite',
                }} />
              )}
            </p>
          </div>

          <div style={{
            position: 'absolute',
            left: 0,
            right: 0,
            bottom: 0,
            height: 36,
            background: `linear-gradient(to bottom, transparent, ${colors.surface})`,
            pointerEvents: 'none',
            borderRadius: `0 0 ${radius.md} ${radius.md}`,
          }} />
        </div>

        <div style={{
          paddingLeft: spacing.lg,
          paddingRight: spacing.lg,
          paddingBottom: spacing.xl,
          paddingTop: spacing.xs,
          flexShrink: 0,
          display: 'flex',
          gap: spacing.md,
        }}>
          {phase !== 'done' && (
            <button
              onClick={cancel}
              style={{
                width: 48,
                height: 56,
                borderRadius: radius.md,
                border: `1.5px solid ${colors.divider}`,
                background: 'transparent',
                color: colors.textSecondary,
                fontSize: font.size.xl,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              x
            </button>
          )}

          {phase === 'recording' && (
            <button
              onClick={stopRecording}
              style={{
                flex: 1,
                height: 56,
                borderRadius: radius.md,
                background: colors.statusUrgent,
                border: 'none',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: spacing.sm,
                fontFamily: font.family,
                boxShadow: '0 4px 16px rgba(196,52,28,0.28)',
              }}
            >
              <div style={{ width: 13, height: 13, borderRadius: 3, background: 'white', flexShrink: 0 }} />
              <span style={{ fontSize: font.size.base, fontWeight: font.weight.semibold, color: 'white' }}>
                Stop recording
              </span>
            </button>
          )}

          {phase === 'completing' && (
            <button
              disabled
              style={{
                flex: 1,
                height: 56,
                borderRadius: radius.md,
                background: colors.primaryLight,
                border: 'none',
                cursor: 'default',
                fontFamily: font.family,
                fontSize: font.size.base,
                fontWeight: font.weight.semibold,
                color: colors.textDisabled,
              }}
            >
              Transcribing...
            </button>
          )}

          {phase === 'done' && (
            <button
              onClick={sessionId ? () => void reviewPlan() : cancel}
              disabled={reviewing}
              style={{
                flex: 1,
                height: 56,
                borderRadius: radius.md,
                background: sessionId ? colors.primary : colors.surface,
                border: 'none',
                cursor: reviewing ? 'default' : 'pointer',
                fontFamily: font.family,
                fontSize: font.size.base,
                fontWeight: font.weight.semibold,
                color: sessionId ? 'white' : colors.textSecondary,
                boxShadow: sessionId ? '0 4px 20px rgba(27,45,107,0.30)' : 'none',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: spacing.sm,
                opacity: reviewing ? 0.65 : 1,
              }}
            >
              {sessionId ? (reviewing ? 'Extracting plan...' : 'Review extracted plan') : 'Close'}
              {sessionId && !reviewing && (
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M3 8h10M9 4l4 4-4 4" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              )}
            </button>
          )}
        </div>
      </div>
    </>
  )
}
