import React from 'react'

function BufferStatus({ depth = 0, target = 5, warning = 2 }) {
  const maxDisplay = Math.max(target * 1.5, depth + 1)
  const percentage = Math.min((depth / maxDisplay) * 100, 100)

  let color
  let statusText
  if (depth >= target) {
    color = '#27ae60'
    statusText = 'Healthy'
  } else if (depth >= warning) {
    color = '#f39c12'
    statusText = 'Getting low'
  } else if (depth > 0) {
    color = '#e74c3c'
    statusText = 'Running low'
  } else {
    color = '#e74c3c'
    statusText = 'Empty'
  }

  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontSize: 13 }}>
        <span style={{ color: '#a0a0b8' }}>Songs Ready</span>
        <span style={{ fontWeight: 600, color }}>{depth} {depth === 1 ? 'track' : 'tracks'} &middot; {statusText}</span>
      </div>
      <div className="buffer-bar-container">
        <div
          className="buffer-bar-fill"
          style={{ width: `${percentage}%`, backgroundColor: color }}
        />
        <span className="buffer-bar-label">{depth} / {target}</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 11, color: '#555' }}>
        <span>0</span>
        <span>Target: {target}</span>
      </div>
    </div>
  )
}

export default BufferStatus
