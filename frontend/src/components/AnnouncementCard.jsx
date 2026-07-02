import React from 'react'

function AnnouncementCard({ announcement, onEdit, onDelete, onToggle }) {
  const priority = announcement.priority || 'normal'
  const isExpired = announcement.expires_at && new Date(announcement.expires_at) < new Date()

  function formatExpiry(dateStr) {
    if (!dateStr) return null
    const d = new Date(dateStr)
    return d.toLocaleString()
  }

  return (
    <div className={`card announcement-card ${priority} ${isExpired ? 'expired' : ''}`}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <span className={`badge badge-${priority}`}>{priority}</span>
        {isExpired && <span className="badge badge-inactive">Expired</span>}
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
        <button className="btn btn-sm btn-secondary" onClick={onEdit}>Edit</button>
        <button className="btn btn-sm btn-danger" onClick={onDelete}>Delete</button>
      </div>
    </div>
  )
}

export default AnnouncementCard
