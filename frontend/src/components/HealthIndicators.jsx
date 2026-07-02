import React from 'react'

const FRIENDLY_NAMES = {
  music: 'Music Generation (Suno)',
  scriptwriter: 'DJ Script Writer (Claude)',
  voice: 'DJ Voice (ElevenLabs)',
  script_writer: 'DJ Script Writer (Claude)',
  music_provider: 'Music Generation (Suno)',
  voice_provider: 'DJ Voice (ElevenLabs)',
}

function friendlyName(name) {
  return FRIENDLY_NAMES[name] || name.replace(/_/g, ' ')
}

function HealthIndicators({ health }) {
  if (!health || typeof health !== 'object') {
    return (
      <div style={{ padding: 16, color: '#555', fontStyle: 'italic' }}>
        No health data available
      </div>
    )
  }

  const providers = Object.entries(health)

  if (providers.length === 0) {
    return (
      <div style={{ padding: 16, color: '#555', fontStyle: 'italic' }}>
        No providers configured yet. Add API keys in DJ Config to get started.
      </div>
    )
  }

  function statusLabel(status) {
    switch (status) {
      case 'ok': return 'Connected'
      case 'degraded': return 'Slow / Retrying'
      case 'error': return 'Error'
      case 'unconfigured': return 'Needs API key'
      default: return status || 'Unknown'
    }
  }

  return (
    <div style={{ padding: 16 }}>
      {providers.map(([name, status]) => {
        const statusValue = typeof status === 'object' ? status.status : status
        return (
          <div className="health-item" key={name}>
            <span className={`health-dot ${statusValue || 'unconfigured'}`} />
            <span style={{ fontWeight: 500, color: '#e0e0e0' }}>
              {friendlyName(name)}
            </span>
            <span style={{ fontSize: 12, color: '#a0a0b8', marginLeft: 'auto' }}>
              {statusLabel(statusValue)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

export default HealthIndicators
