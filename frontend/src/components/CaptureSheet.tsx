import { colors, font, radius, spacing } from '../tokens'

interface Props {
  open: boolean
  onClose: () => void
  onStartRecording: () => void
}

const options = [
  {
    id: 'record',
    label: 'Start voice recording',
    sub: 'Record a consultation live',
    primary: true,
    icon: (white: boolean) => (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <rect x="6.5" y="1" width="7" height="10" rx="3.5" stroke={white ? 'white' : colors.primary} strokeWidth="1.5" fill={white ? 'rgba(255,255,255,0.18)' : 'none'} />
        <path d="M3.5 9C3.5 12.6 6.4 15.5 10 15.5C13.6 15.5 16.5 12.6 16.5 9" stroke={white ? 'white' : colors.primary} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="10" y1="15.5" x2="10" y2="18.5" stroke={white ? 'white' : colors.primary} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="7" y1="18.5" x2="13" y2="18.5" stroke={white ? 'white' : colors.primary} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: 'import',
    label: 'Import voice recording',
    sub: 'From Files or Voice Memos',
    primary: false,
    icon: (_: boolean) => (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <path d="M10 2V13M6 9L10 13L14 9" stroke={colors.textSecondary} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M3 14V16.5C3 17.3 3.7 18 4.5 18H15.5C16.3 18 17 17.3 17 16.5V14" stroke={colors.textSecondary} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: 'photo',
    label: 'Take a photo of doctor notes',
    sub: 'Capture handwritten notes',
    primary: false,
    icon: (_: boolean) => (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <rect x="1.5" y="5.5" width="17" height="12" rx="2" stroke={colors.textSecondary} strokeWidth="1.5" />
        <circle cx="10" cy="11.5" r="3" stroke={colors.textSecondary} strokeWidth="1.5" />
        <path d="M7.5 5.5L8.8 2.5H11.2L12.5 5.5" stroke={colors.textSecondary} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    id: 'scan',
    label: 'Scan doctor notes',
    sub: 'Extract text from printed documents',
    primary: false,
    icon: (_: boolean) => (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <path d="M2 6.5V3.5H5M15 3.5H18V6.5M18 13.5V16.5H15M5 16.5H2V13.5" stroke={colors.textSecondary} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        <line x1="1" y1="10" x2="19" y2="10" stroke={colors.textSecondary} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
  },
]

export default function CaptureSheet({ open, onClose, onStartRecording }: Props) {
  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: 'absolute',
          inset: 0,
          background: 'rgba(17,17,17,0.45)',
          opacity: open ? 1 : 0,
          pointerEvents: open ? 'auto' : 'none',
          transition: 'opacity 0.25s ease',
          zIndex: 40,
        }}
      />
      <div style={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: 0,
        background: colors.white,
        borderRadius: `20px 20px 0 0`,
        zIndex: 41,
        transform: open ? 'translateY(0)' : 'translateY(100%)',
        transition: 'transform 0.32s cubic-bezier(0.4, 0, 0.2, 1)',
      }}>
        {/* Handle */}
        <div style={{ paddingTop: spacing.md, paddingBottom: spacing.md, display: 'flex', justifyContent: 'center' }}>
          <div style={{ width: 36, height: 4, borderRadius: radius.full, background: colors.divider }} />
        </div>

        {/* Label */}
        <div style={{ paddingLeft: spacing.xl, paddingRight: spacing.xl, paddingBottom: spacing.sm }}>
          <span style={{ fontSize: font.size.xs, fontWeight: font.weight.semibold, color: colors.textSecondary, textTransform: 'uppercase', letterSpacing: '0.7px' }}>
            Capture
          </span>
        </div>

        {/* Options */}
        {options.map((opt, i) => (
          <div
            key={opt.id}
            onClick={opt.id === 'record' ? () => { onClose(); onStartRecording() } : undefined}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: spacing.md,
              paddingTop: '14px',
              paddingBottom: '14px',
              paddingLeft: spacing.xl,
              paddingRight: spacing.xl,
              cursor: opt.id === 'record' ? 'pointer' : 'default',
              borderBottom: i < options.length - 1 ? `1px solid ${colors.divider}` : 'none',
              background: opt.primary ? colors.primaryLight : 'transparent',
              opacity: opt.primary ? 1 : 0.55,
            }}
          >
            <div style={{
              width: 42,
              height: 42,
              borderRadius: radius.md,
              background: opt.primary ? colors.primary : colors.surface,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}>
              {opt.icon(opt.primary)}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{ margin: 0, fontSize: font.size.base, fontWeight: opt.primary ? font.weight.semibold : font.weight.medium, color: opt.primary ? colors.primary : colors.textPrimary }}>
                {opt.label}
              </p>
              <p style={{ margin: '2px 0 0', fontSize: font.size.sm, color: colors.textSecondary, lineHeight: '1.35' }}>
                {opt.sub}
              </p>
            </div>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M6 4L10 8L6 12" stroke={opt.primary ? colors.primary : colors.textDisabled} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
        ))}

        <div style={{ height: spacing.xl }} />
      </div>
    </>
  )
}
