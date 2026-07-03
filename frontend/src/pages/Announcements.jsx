import React, { useState, useEffect } from 'react'
import { fetchAnnouncements, createAnnouncement, updateAnnouncement, deleteAnnouncement } from '../api'
import AnnouncementCard from '../components/AnnouncementCard'

/** Convert a UTC ISO datetime string into a value for a datetime-local input (local wall time). */
function isoToLocalInputValue(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** Convert a datetime-local input value (local wall time) into a UTC ISO string. */
function localInputValueToIso(value) {
  if (!value) return null
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? null : d.toISOString()
}

function Announcements() {
  const [announcements, setAnnouncements] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [modalError, setModalError] = useState(null)
  const [showModal, setShowModal] = useState(false)
  const [editing, setEditing] = useState(null)
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [form, setForm] = useState({
    text: '',
    priority: 'normal',
    expires_at: '',
    max_plays: '',
  })

  async function loadAnnouncements() {
    try {
      const data = await fetchAnnouncements()
      setAnnouncements(Array.isArray(data) ? data : data.announcements || [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAnnouncements()
  }, [])

  function openAdd() {
    setEditing(null)
    setForm({ text: '', priority: 'normal', expires_at: '', max_plays: '' })
    setModalError(null)
    setShowModal(true)
  }

  function openEdit(ann) {
    setEditing(ann)
    setForm({
      text: ann.text || '',
      priority: ann.priority || 'normal',
      expires_at: isoToLocalInputValue(ann.expires_at),
      max_plays: ann.max_plays ?? '',
    })
    setModalError(null)
    setShowModal(true)
  }

  function validateForm() {
    const maxPlays = form.max_plays === '' ? null : Number(form.max_plays)

    if (!form.text.trim()) return 'Announcement text is required.'
    if (!['low', 'normal', 'high', 'urgent'].includes(form.priority)) {
      return 'Choose a valid announcement priority.'
    }
    if (maxPlays !== null && (!Number.isInteger(maxPlays) || maxPlays < 1)) {
      return 'Max plays must be a whole number greater than 0.'
    }
    return null
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const validationError = validateForm()
    if (validationError) {
      setModalError(validationError)
      return
    }

    const payload = {
      text: form.text,
      priority: form.priority,
      expires_at: localInputValueToIso(form.expires_at),
      max_plays: form.max_plays ? Number(form.max_plays) : null,
    }

    try {
      if (editing) {
        await updateAnnouncement(editing.id, payload)
      } else {
        await createAnnouncement(payload)
      }
      setShowModal(false)
      loadAnnouncements()
    } catch (err) {
      setModalError(err.message)
    }
  }

  async function handleDelete(id) {
    try {
      await deleteAnnouncement(id)
      setDeleteConfirm(null)
      loadAnnouncements()
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleToggle(ann) {
    try {
      await updateAnnouncement(ann.id, { active: !ann.active })
      loadAnnouncements()
    } catch (err) {
      setError(err.message)
    }
  }

  function isExpired(ann) {
    if (!ann.expires_at) return false
    return new Date(ann.expires_at) < new Date()
  }

  const activeAnnouncements = announcements.filter(a => !isExpired(a))
  const expiredAnnouncements = announcements.filter(a => isExpired(a))

  if (loading) {
    return <div className="loading-screen"><div className="loading-spinner" /><p>Loading announcements...</p></div>
  }

  return (
    <div>
      <div className="page-header">
        <h2>Announcements</h2>
        <button className="btn btn-primary" onClick={openAdd}>+ Add Announcement</button>
      </div>
      <p className="section-help" style={{ marginTop: -16, marginBottom: 20 }}>
        Announcements are messages your DJ will naturally work into their breaks — like upcoming events,
        shout-outs, promotions, or anything you want listeners to hear.
      </p>

      {error && <div className="alert alert-error">{error}</div>}

      {announcements.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: 40 }}>
          <p style={{ color: '#a0a0b8', marginBottom: 8 }}>No announcements yet.</p>
          <p style={{ color: '#666', fontSize: 13, marginBottom: 16 }}>
            Add an announcement and your DJ will mention it during their next break.
          </p>
          <button className="btn btn-primary" onClick={openAdd}>Add Your First Announcement</button>
        </div>
      ) : (
        <>
          <div className="card-grid">
            {activeAnnouncements.map(ann => (
              <AnnouncementCard
                key={ann.id}
                announcement={ann}
                onEdit={() => openEdit(ann)}
                onDelete={() => setDeleteConfirm(ann.id)}
                onToggle={() => handleToggle(ann)}
              />
            ))}
          </div>

          {expiredAnnouncements.length > 0 && (
            <>
              <h3 style={{ color: '#a0a0b8', margin: '24px 0 12px', fontSize: 14, textTransform: 'uppercase' }}>
                Expired
              </h3>
              <div className="card-grid">
                {expiredAnnouncements.map(ann => (
                  <AnnouncementCard
                    key={ann.id}
                    announcement={ann}
                    onEdit={() => openEdit(ann)}
                    onDelete={() => setDeleteConfirm(ann.id)}
                    onToggle={() => handleToggle(ann)}
                  />
                ))}
              </div>
            </>
          )}
        </>
      )}

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>{editing ? 'Edit Announcement' : 'Add Announcement'}</h3>
            {modalError && <div className="alert alert-error">{modalError}</div>}
            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label>Announcement Text</label>
                <textarea
                  value={form.text}
                  onChange={e => setForm({ ...form, text: e.target.value })}
                  placeholder="e.g. Don't forget our live event this Saturday at 8 PM! Tickets available at..."
                  required
                />
                <div className="help-text">Write what you want your DJ to mention. They'll weave it naturally into their break.</div>
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label>Priority</label>
                  <select
                    value={form.priority}
                    onChange={e => setForm({ ...form, priority: e.target.value })}
                  >
                    <option value="low">Low — mentioned occasionally</option>
                    <option value="normal">Normal — regular mentions</option>
                    <option value="high">High — mentioned frequently</option>
                    <option value="urgent">Urgent — mentioned every break</option>
                  </select>
                  <div className="help-text">Higher priority = mentioned more often.</div>
                </div>
                <div className="form-group">
                  <label>Max Plays (optional)</label>
                  <input
                    type="number"
                    min="1"
                    step="1"
                    value={form.max_plays}
                    onChange={e => setForm({ ...form, max_plays: e.target.value })}
                    placeholder="Unlimited"
                  />
                  <div className="help-text">Stop using this announcement after it's been mentioned this many times. Leave blank for unlimited.</div>
                </div>
              </div>
              <div className="form-group">
                <label>Expires At (optional)</label>
                <input
                  type="datetime-local"
                  value={form.expires_at}
                  onChange={e => setForm({ ...form, expires_at: e.target.value })}
                />
                <div className="help-text">Automatically stops this announcement after this date and time.</div>
              </div>
              <div className="modal-actions">
                <button type="button" className="btn" onClick={() => setShowModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary">{editing ? 'Save Changes' : 'Add Announcement'}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {deleteConfirm !== null && (
        <div className="modal-overlay" onClick={() => setDeleteConfirm(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Delete Announcement</h3>
            <p style={{ marginBottom: 16, color: '#a0a0b8' }}>
              Are you sure you want to delete this announcement?
            </p>
            <div className="modal-actions">
              <button className="btn" onClick={() => setDeleteConfirm(null)}>Cancel</button>
              <button className="btn btn-danger" onClick={() => handleDelete(deleteConfirm)}>Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Announcements
