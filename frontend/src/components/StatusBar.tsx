import { useState, useEffect } from 'react'
import { font } from '../tokens'

export default function StatusBar() {
  const [time, setTime] = useState(new Date())

  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 15000)
    return () => clearInterval(id)
  }, [])

  const formatted = time.toLocaleTimeString('en-SG', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: false,
  })

  return (
    <div style={{
      height: 44,
      flexShrink: 0,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 28px',
    }}>
      {/* Time */}
      <span style={{
        fontFamily: font.family,
        fontSize: '15px',
        fontWeight: 600,
        color: '#0D0D12',
        letterSpacing: '-0.3px',
      }}>
        {formatted}
      </span>

      {/* Right cluster */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
        {/* Signal bars */}
        <svg width="17" height="12" viewBox="0 0 17 12" fill="none">
          <rect x="0" y="8" width="3" height="4" rx="1" fill="#0D0D12" />
          <rect x="4.5" y="5.5" width="3" height="6.5" rx="1" fill="#0D0D12" />
          <rect x="9" y="3" width="3" height="9" rx="1" fill="#0D0D12" />
          <rect x="13.5" y="0" width="3" height="12" rx="1" fill="#0D0D12" />
        </svg>

        {/* WiFi */}
        <svg width="16" height="12" viewBox="0 0 16 12" fill="none">
          <path d="M8 9.5a1.25 1.25 0 1 1 0 2.5 1.25 1.25 0 0 1 0-2.5Z" fill="#0D0D12" />
          <path d="M4.5 6.8C5.5 5.7 6.7 5 8 5s2.5.7 3.5 1.8" stroke="#0D0D12" strokeWidth="1.5" strokeLinecap="round" />
          <path d="M1.5 3.8C3.2 2 5.5 1 8 1s4.8 1 6.5 2.8" stroke="#0D0D12" strokeWidth="1.5" strokeLinecap="round" />
        </svg>

        {/* Battery */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <div style={{
            width: 25,
            height: 12,
            borderRadius: 3,
            border: '1.5px solid #0D0D12',
            padding: '1.5px',
            display: 'flex',
            alignItems: 'center',
          }}>
            <div style={{ width: '76%', height: '100%', background: '#0D0D12', borderRadius: 1.5 }} />
          </div>
          <div style={{ width: 2, height: 5, background: '#0D0D12', borderRadius: 1, opacity: 0.6 }} />
        </div>
      </div>
    </div>
  )
}
