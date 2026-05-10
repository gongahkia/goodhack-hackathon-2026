import { useRef } from 'react'
import { colors, font, radius, spacing } from '../tokens'

interface Props {
  open: boolean
  onClose: () => void
  onImport: (type: 'photo' | 'voice') => void
}

export default function ImportSheet({ open, onClose, onImport }: Props) {
  const backdropRef = useRef<HTMLDivElement>(null)

  if (!open) return null

  return (
    <div
      ref={backdropRef}
      onClick={e => { if (e.target === backdropRef.current) onClose() }}
      style={{
        position: 'absolute',
        inset: 0,
        background: 'rgba(17,17,17,0.45)',
        zIndex: 100,
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          background: colors.white,
          borderRadius: `${radius.card} ${radius.card} 0 0`,
          width: '100%',
          maxWidth: 480,
          padding: `${spacing.xl} ${spacing.xl} calc(${spacing.xl} + env(safe-area-inset-bottom))`,
        }}
      >
        {/* Handle */}
        <div style={{
          width: 36,
          height: 4,
          borderRadius: radius.full,
          background: colors.divider,
          margin: `0 auto ${spacing.xl}`,
        }} />

        <p style={{
          fontFamily: font.family,
          fontSize: font.size.lg,
          fontWeight: font.weight.semibold,
          color: colors.textPrimary,
          margin: `0 0 ${spacing.lg}`,
        }}>
          Import
        </p>

        {[
          { icon: '🖼️', label: 'Import photo of doctor notes', sub: 'JPG, PNG supported', action: () => onImport('photo') },
          { icon: '🎙️', label: 'Import voice recording', sub: 'M4A, MP3, WAV supported', action: () => onImport('voice') },
        ].map(item => (
          <button
            key={item.label}
            onClick={item.action}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              gap: spacing.lg,
              padding: spacing.lg,
              background: colors.surface,
              border: `1.5px solid ${colors.divider}`,
              borderRadius: radius.md,
              cursor: 'pointer',
              marginBottom: spacing.md,
              textAlign: 'left',
            }}
          >
            <span style={{ fontSize: 24 }}>{item.icon}</span>
            <div>
              <p style={{ fontFamily: font.family, fontSize: font.size.base, fontWeight: font.weight.medium, color: colors.textPrimary, margin: 0 }}>
                {item.label}
              </p>
              <p style={{ fontFamily: font.family, fontSize: font.size.sm, color: colors.textSecondary, margin: `${spacing.xs} 0 0` }}>
                {item.sub}
              </p>
            </div>
          </button>
        ))}

        <button
          onClick={onClose}
          style={{
            width: '100%',
            padding: spacing.lg,
            background: 'none',
            border: `1.5px solid ${colors.divider}`,
            borderRadius: radius.md,
            fontFamily: font.family,
            fontSize: font.size.base,
            fontWeight: font.weight.medium,
            color: colors.textSecondary,
            cursor: 'pointer',
            marginTop: spacing.xs,
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
