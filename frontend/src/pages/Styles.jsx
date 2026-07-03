import React, { useState, useEffect } from 'react'
import { fetchStyles, createStyle, updateStyle, deleteStyle, toggleStyle } from '../api'
import StyleCard from '../components/StyleCard'

function Styles() {
  const [styles, setStyles] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [modalError, setModalError] = useState(null)
  const [showModal, setShowModal] = useState(false)
  const [editingStyle, setEditingStyle] = useState(null)
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [form, setForm] = useState({
    name: '',
    prompt: '',
    weight: 1,
    tags: '',
    schedule_start: '',
    schedule_end: '',
  })

  async function loadStyles() {
    try {
      const data = await fetchStyles()
      setStyles(Array.isArray(data) ? data : data.styles || [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadStyles()
  }, [])

  function openAdd() {
    setEditingStyle(null)
    setForm({ name: '', prompt: '', weight: 1, tags: '', schedule_start: '', schedule_end: '' })
    setModalError(null)
    setShowModal(true)
  }

  function openEdit(style) {
    setEditingStyle(style)
    let scheduleStart = ''
    let scheduleEnd = ''
    if (style.schedule) {
      try {
        const s = JSON.parse(style.schedule)
        scheduleStart = s.start || ''
        scheduleEnd = s.end || ''
      } catch {
        // ignore malformed schedule
      }
    }
    setForm({
      name: style.name || '',
      prompt: style.prompt || '',
      weight: style.weight ?? 1,
      tags: style.tags || '',
      schedule_start: scheduleStart,
      schedule_end: scheduleEnd,
    })
    setModalError(null)
    setShowModal(true)
  }

  function validateForm() {
    const weight = Number(form.weight)

    if (!form.name.trim()) return 'Style name is required.'
    if (!form.prompt.trim()) return 'Style description is required.'
    if (!Number.isFinite(weight) || weight <= 0) return 'Style weight must be greater than 0.'
    return null
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const validationError = validateForm()
    if (validationError) {
      setModalError(validationError)
      return
    }

    const schedule = (form.schedule_start || form.schedule_end)
      ? JSON.stringify({ start: form.schedule_start || null, end: form.schedule_end || null })
      : null
    const payload = {
      name: form.name,
      prompt: form.prompt,
      weight: Number(form.weight),
      tags: form.tags || null,
      schedule,
    }

    try {
      if (editingStyle) {
        await updateStyle(editingStyle.id, payload)
      } else {
        await createStyle(payload)
      }
      setShowModal(false)
      loadStyles()
    } catch (err) {
      setModalError(err.message)
    }
  }

  async function handleDelete(id) {
    try {
      await deleteStyle(id)
      setDeleteConfirm(null)
      loadStyles()
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleToggle(id) {
    try {
      await toggleStyle(id)
      loadStyles()
    } catch (err) {
      setError(err.message)
    }
  }

  if (loading) {
    return <div className="loading-screen"><div className="loading-spinner" /><p>Loading styles...</p></div>
  }

  return (
    <div>
      <div className="page-header">
        <h2>Music Styles</h2>
        <button className="btn btn-primary" onClick={openAdd}>+ Add Style</button>
      </div>
      <p className="section-help" style={{ marginTop: -16, marginBottom: 20 }}>
        Music styles tell the AI what kind of music to create. Your station randomly picks from these
        when generating new songs. You can have as many styles as you want.
      </p>

      {error && <div className="alert alert-error">{error}</div>}

      {styles.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: 40 }}>
          <p style={{ color: '#a0a0b8', marginBottom: 16 }}>No styles configured yet.</p>
          <button className="btn btn-primary" onClick={openAdd}>Add Your First Style</button>
        </div>
      ) : (
        <div className="card-grid">
          {styles.map(style => (
            <StyleCard
              key={style.id}
              style={style}
              onEdit={() => openEdit(style)}
              onDelete={() => setDeleteConfirm(style.id)}
              onToggle={() => handleToggle(style.id)}
            />
          ))}
        </div>
      )}

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>{editingStyle ? 'Edit Style' : 'Add Style'}</h3>
            {modalError && <div className="alert alert-error">{modalError}</div>}
            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label>Name</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={e => setForm({ ...form, name: e.target.value })}
                  placeholder="e.g. Lo-fi Chill Beats"
                  required
                />
              </div>
              <div className="form-group">
                <label>Description for the AI</label>
                <textarea
                  value={form.prompt}
                  onChange={e => setForm({ ...form, prompt: e.target.value })}
                  placeholder="e.g. Relaxing lo-fi hip hop with mellow piano, soft drums, and a cozy late-night feel"
                  required
                />
                <div className="help-text">
                  Be descriptive! Include genre, instruments, mood, tempo, and vibe for best results.
                </div>
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label>Weight</label>
                  <input
                    type="number"
                    min="0.1"
                    step="0.1"
                    value={form.weight}
                    onChange={e => setForm({ ...form, weight: e.target.value })}
                    placeholder="1"
                  />
                  <div className="help-text">Higher weight = plays more often. Default is 1.</div>
                </div>
                <div className="form-group">
                  <label>Tags (comma-separated)</label>
                  <input
                    type="text"
                    value={form.tags}
                    onChange={e => setForm({ ...form, tags: e.target.value })}
                    placeholder="chill, ambient, focus"
                  />
                  <div className="help-text">Optional labels the DJ can reference when talking about the music.</div>
                </div>
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label>Schedule Start (optional)</label>
                  <input
                    type="time"
                    value={form.schedule_start}
                    onChange={e => setForm({ ...form, schedule_start: e.target.value })}
                  />
                </div>
                <div className="form-group">
                  <label>Schedule End (optional)</label>
                  <input
                    type="time"
                    value={form.schedule_end}
                    onChange={e => setForm({ ...form, schedule_end: e.target.value })}
                  />
                </div>
              </div>
              <div className="help-text" style={{ marginTop: -8 }}>
                Optional: Only play this style during certain hours. For example, jazz from 10 PM to 6 AM.
                Uses your station's timezone. Leave blank to play anytime.
              </div>
              <div className="modal-actions">
                <button type="button" className="btn" onClick={() => setShowModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary">{editingStyle ? 'Save Changes' : 'Add Style'}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {deleteConfirm !== null && (
        <div className="modal-overlay" onClick={() => setDeleteConfirm(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Delete Style</h3>
            <p style={{ marginBottom: 16, color: '#a0a0b8' }}>
              Are you sure you want to delete this style? This action cannot be undone.
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

export default Styles
