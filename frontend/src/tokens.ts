export const colors = {
  primary: '#1B2D6B',
  primaryDark: '#111E4A',
  primaryLight: '#E8EDF8',
  accent: '#E07A20',
  accentLight: '#FEF3E8',

  surface: '#F6F2EB',
  white: '#FAFAF7',
  divider: '#E0D8CE',

  textPrimary: '#1A1209',
  textSecondary: '#7A6E64',
  textDisabled: '#B8AFA4',

  statusDone: '#3D7A5C',
  statusDoneLight: '#E8F3ED',
  statusUrgent: '#C4341C',
  statusUrgentLight: '#FCEAE7',

  recordingActive: '#C4341C',
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
  card: '0 2px 16px rgba(20,30,70,0.08)',
  fab: '0 6px 24px rgba(27,45,107,0.32)',
  sheet: '0 -4px 32px rgba(0,0,0,0.10)',
} as const
