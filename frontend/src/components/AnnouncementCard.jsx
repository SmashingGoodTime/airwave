import React from 'react'

function AnnouncementCard({ announcement, onEdit, onDelete, onToggle }) {
  const priority = announcement.priority || 'normal'
  const isExpired = announcement.expires_at && new Date(announcement.expires_at) < new Date()
  const isActive = announcement.active !== false

  function formatExpiry(dateStr) {
    if (!dateStr) return null
    const d = new Date(dateStr)
    return d.toLocaleString()
  }

  return (
    <div className={`card announcement-card ${priority} ${isExpired || !isActive ? 'expired' : ''}`}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <span className={`badge badge-${priority}`}>{priority}</span>
        <span style={{ display: 'flex', gap: 6 }}>
          {isExpired && <span className="badge badge-inactive">Expired</span>}
          <span className={`badge ${isActive ? 'badge-active' : 'badge-inactive'}`}>
            {isActive ? 'Active' : 'Inactive'}
          </span>
        </span>
      </div>
      <div className="announcement-text">{announcement.text}</div>
      <div className="announcement-meta">
        {announcement.play_count !== undefined && (
          <span>Played: {announcement.play_count}{announcement.max_plays ? ` / ${announcement.max_plays}` : ''}</span>
        )}
        {announcement.expires_at && (
          <span>{isExpired ? 'Expired' : 'Expires'}: {formatExpiry(announcement.expires_at)}</span>
        )}
      </div>
      <div className="announcement-actions">
        <button className="btn btn-sm btn-secondary" onClick={onToggle}>
          {isActive ? 'Deactivate' : 'Activate'}
        </button>
        <button className="btn btn-sm btn-secondary" onClick={onEdit}>Edit</button>
        <button className="btn btn-sm btn-danger" onClick={onDelete}>Delete</button>
      </div>
    </div>
  )
}

export default AnnouncementCard
