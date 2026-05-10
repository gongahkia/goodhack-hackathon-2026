import { useState, useEffect, useRef } from 'react'
import { colors, font, radius, spacing } from '../tokens'

interface Props {
  open: boolean
  onComplete: () => void
  onCancel: () => void
}

const TRANSCRIPT = `Dr Rajendran: Good morning. I've reviewed Mdm Ang's discharge summary and recent progress notes. Overall she's tracking well, which is encouraging.

Medications: continue Aspirin 100mg with Atorvastatin 40mg every morning at 8, taken together with breakfast — never on an empty stomach. Target LDL below 1.8 mmol/L. Recheck at the 3-month lipid panel. Do not crush or split the tablets.

Blood pressure monitoring: morning reading at 8:30, after 5 minutes rest, before medications. Target 130 to 140 systolic, 80 to 90 diastolic. Omron upper-arm device, record both readings. If systolic exceeds 160 or drops below 110, call the clinic. Evening reading at 5 PM before dinner and before the Warfarin dose. Flag to me if the gap between morning and evening exceeds 20 systolic.

Warfarin 2mg — strictly at 6 PM every day. Target INR 2.0 to 3.0. Next INR check in 2 weeks, around 20 May at Toa Payoh Polyclinic. Watch for unusual bruising, blood in urine, prolonged bleeding from cuts. Keep leafy vegetables consistent in the diet.

Physiotherapy with Ms Wong — 30-minute sessions at 10 AM. Ankle pumps, knee raises each leg, shoulder shrugs, assisted standing at the bed rail for 3 sets of 30 seconds. Stop immediately if she reports dizziness, chest tightness, or pain. Progress to corridor walks once standing balance holds for 3 consecutive days.

Speech therapy with Ms Priya — 15 minutes at 11:30. Oral motor drills, lip exercises, pa-ta-ka repetitions times 3 sets, read-aloud from the newspaper. Document any choking episodes or difficulty swallowing.

Daily monitoring: fluid intake 6 to 8 cups thickened liquid throughout the day, Thick-It powder at nectar consistency. Thin liquids must be supervised. Skin check daily — sacrum, both heels, elbows, back of head — apply Sudocrem barrier cream after each check. Walking practice 2 to 3 corridor rounds with the quad cane, watch carefully for left foot drop, never leave unattended.

Follow-ups: neurology outpatient 25 May, urgent — first post-discharge review, bring BP log and medication list, I'll refer for repeat brain MRI at that appointment. INR at Toa Payoh Polyclinic around 20 May, no referral needed. Speech and Language Therapy formal swallow assessment by 5 June. OT home visit around 10 June for fall risk and mobility aids assessment. Medical Social Worker consultation by 15 June for CareShield Life claims and home nursing subsidy options.

Any questions from the family?`

// 28 bars for a richer waveform
const BAR_HEIGHTS = [
  0.30, 0.60, 0.90, 0.50, 0.82, 0.42, 0.88, 0.56,
  0.72, 0.36, 0.94, 0.52, 0.68, 0.44, 0.78, 0.32,
  0.84, 0.62, 0.96, 0.40, 0.74, 0.50, 0.86, 0.34,
  0.66, 0.76, 0.46, 0.58,
]

type Phase = 'recording' | 'completing' | 'done'

export default function VoiceRecordingPanel({ open, onComplete, onCancel }: Props) {
  const [phase, setPhase] = useState<Phase>('recording')
  const [seconds, setSeconds] = useState(0)
  const [charCount, setCharCount] = useState(0)
  const transcriptRef = useRef<HTMLDivElement>(null)
  const charRef = useRef(0)

  // Reset when opened
  useEffect(() => {
    if (!open) return
    setPhase('recording')
    setSeconds(0)
    setCharCount(0)
    charRef.current = 0
  }, [open])

  // Timer — runs during recording and completing
  useEffect(() => {
    if (!open || phase === 'done') return
    const id = setInterval(() => setSeconds(s => s + 1), 1000)
    return () => clearInterval(id)
  }, [open, phase])

  // Transcript streaming
  useEffect(() => {
    if (!open) return
    const msPerChar = phase === 'recording' ? 9 : phase === 'completing' ? 1 : null
    if (msPerChar === null) return

    const id = setInterval(() => {
      charRef.current = Math.min(charRef.current + (phase === 'completing' ? 6 : 1), TRANSCRIPT.length)
      setCharCount(charRef.current)
      if (charRef.current >= TRANSCRIPT.length) {
        clearInterval(id)
        setPhase('done')
      }
    }, msPerChar)
    return () => clearInterval(id)
  }, [open, phase])

  // Auto-scroll transcript
  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight
    }
  }, [charCount])

  const fmt = (s: number) =>
    `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

  const isActive = phase === 'recording'

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

      {/* Backdrop */}
      <div
        onClick={phase === 'recording' ? onCancel : undefined}
        style={{
          position: 'absolute',
          inset: 0,
          background: 'rgba(10,12,26,0.60)',
          opacity: open ? 1 : 0,
          pointerEvents: open ? 'auto' : 'none',
          transition: 'opacity 0.3s ease',
          zIndex: 50,
        }}
      />

      {/* Panel */}
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
      }}>

        {/* Drag handle */}
        <div style={{ paddingTop: spacing.md, paddingBottom: spacing.sm, display: 'flex', justifyContent: 'center', flexShrink: 0 }}>
          <div style={{ width: 36, height: 4, borderRadius: radius.full, background: colors.divider }} />
        </div>

        {/* Status bar */}
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
              background: isActive ? colors.statusUrgent : phase === 'completing' ? colors.accent : colors.statusDone,
              animation: isActive ? 'recPulse 1.1s ease-in-out infinite' : 'none',
              transition: 'background 0.4s ease',
              flexShrink: 0,
            }} />
            <span style={{
              fontSize: font.size.sm,
              fontWeight: font.weight.bold,
              color: isActive ? colors.statusUrgent : phase === 'completing' ? colors.accent : colors.statusDone,
              letterSpacing: '0.8px',
              transition: 'color 0.4s ease',
            }}>
              {isActive ? 'REC' : phase === 'completing' ? 'TRANSCRIBING' : 'DONE'}
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

        {/* Waveform */}
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
              animation: isActive ? `w${i % 5} ${0.65 + (i % 4) * 0.10}s ease-in-out infinite` : 'none',
              animationDelay: `${(i * 0.048).toFixed(2)}s`,
              transformOrigin: 'center',
              transition: 'background 0.5s ease, opacity 0.5s ease',
            }} />
          ))}
        </div>

        {/* Live transcript box */}
        <div style={{
          flex: 1,
          minHeight: 0,
          marginLeft: spacing.lg,
          marginRight: spacing.lg,
          marginBottom: spacing.md,
          borderRadius: radius.md,
          background: colors.surface,
          border: `1.5px solid ${isActive ? colors.statusUrgent + '40' : colors.divider}`,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          transition: 'border-color 0.4s ease',
          position: 'relative',
        }}>
          {/* Label */}
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
            {phase === 'done' && (
              <span style={{
                fontSize: font.size.xs,
                fontWeight: font.weight.medium,
                color: colors.statusDone,
              }}>
                ✓ Review before saving
              </span>
            )}
          </div>

          {/* Text */}
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
              color: charCount > 0 ? colors.textPrimary : colors.textDisabled,
              lineHeight: '1.75',
              fontWeight: font.weight.regular,
              whiteSpace: 'pre-wrap',
            }}>
              {charCount > 0 ? TRANSCRIPT.slice(0, charCount) : 'Listening…'}
              {charCount > 0 && phase !== 'done' && (
                <span style={{
                  display: 'inline-block',
                  width: 2,
                  height: '1em',
                  background: isActive ? colors.statusUrgent : colors.primary,
                  marginLeft: 3,
                  verticalAlign: 'text-bottom',
                  borderRadius: 1,
                  animation: 'cur 0.85s step-end infinite',
                }} />
              )}
            </p>
          </div>

          {/* Bottom fade */}
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

        {/* Action button */}
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
              onClick={onCancel}
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
              ×
            </button>
          )}

          {phase === 'recording' && (
            <button
              onClick={() => setPhase('completing')}
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
              Transcribing…
            </button>
          )}

          {phase === 'done' && (
            <button
              onClick={onComplete}
              style={{
                flex: 1,
                height: 56,
                borderRadius: radius.md,
                background: colors.primary,
                border: 'none',
                cursor: 'pointer',
                fontFamily: font.family,
                fontSize: font.size.base,
                fontWeight: font.weight.semibold,
                color: 'white',
                boxShadow: '0 4px 20px rgba(27,45,107,0.30)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: spacing.sm,
              }}
            >
              Review extracted plan
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M3 8h10M9 4l4 4-4 4" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
          )}
        </div>
      </div>
    </>
  )
}
