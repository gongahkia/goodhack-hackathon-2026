export const colors = {
  primary: '#3B5BFF',
  primaryDark: '#2440E0',
  primaryLight: '#EEF1FF',
  accent: '#E8A020',
  accentLight: '#FFF7E6',

  surface: '#F5F6FA',
  white: '#FFFFFF',
  divider: '#EBEBED',

  textPrimary: '#0D0D12',
  textSecondary: '#8A8FA8',
  textDisabled: '#C8CADB',

  statusDone: '#15B876',
  statusDoneLight: '#E8FAF3',
  statusUrgent: '#D63B3B',
  statusUrgentLight: '#FDECEA',

  recordingActive: '#D63B3B',
} as const

export const radius = {
  xs: '4px',
  sm: '6px',
  md: '10px',
  card: '18px',
  lg: '20px',
  pill: '100px',
  full: '9999px',
} as const

export const font = {
  family: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
  weight: {
    regular: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
  },
  size: {
    xs: '11px',
    sm: '13px',
    base: '15px',
    md: '16px',
    lg: '18px',
    xl: '22px',
    xxl: '28px',
  },
} as const

export const spacing = {
  xs: '4px',
  sm: '8px',
  md: '12px',
  lg: '16px',
  xl: '24px',
  xxl: '32px',
  xxxl: '48px',
} as const

export const shadow = {
  card: '0 2px 16px rgba(30,40,100,0.07)',
  fab: '0 4px 20px rgba(59,91,255,0.35)',
  sheet: '0 -4px 32px rgba(0,0,0,0.10)',
} as const
