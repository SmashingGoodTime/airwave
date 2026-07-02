import React from 'react'

function StyleCard({ style, onEdit, onDelete, onToggle }) {
  const tags = style.tags ? style.tags.split(',').map(t => t.trim()).filter(Boolean) : []
  let scheduleStart = null
  let scheduleEnd = null
  if (style.schedule) {
    try {
      const s = JSON.parse(style.schedule)
      scheduleStart = s.start
      scheduleEnd = s.end
    } catch {
      // ignore
    }
  }

  return (
    <div className="card style-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
        <div className="style-card-name">{style.name}</div>
        <span className={`badge ${style.active !== false ? 'badge-active' : 'badge-inactive'}`}>
          {style.active !== false ? 'Active' : 'Inactive'}
        </span>
      </div>
      <div className="style-card-prompt">{style.prompt}</div>
      <div className="style-card-meta">
        <span className="style-card-weight">Weight: {style.weight ?? 1}</span>
        {tags.map(tag => (
          <span key={tag} className="style-card-tag">{tag}</span>
        ))}
      </div>
      {(scheduleStart || scheduleEnd) && (
        <div style={{ fontSize: 12, color: '#a0a0b8', marginBottom: 12 }}>
          Schedule: {scheduleStart || '...'} - {scheduleEnd || '...'}
        </div>
      )}
      <div className="style-card-actions">
        <button className="btn btn-sm btn-secondary" onClick={onEdit}>Edit</button>
        <button className="btn btn-sm" onClick={onToggle}>
          {style.active !== false ? 'Disable' : 'Enable'}
        </button>
        <button className="btn btn-sm btn-danger" onClick={onDelete}>Delete</button>
      </div>
    </div>
  )
}

export default StyleCard
