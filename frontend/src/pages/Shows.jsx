import React, { useState, useEffect, useMemo } from 'react'
import {
  fetchShows,
  createShow,
  updateShow,
  deleteShow,
  toggleShow,
  fetchStyles,
  fetchDJConfigs,
  fetchTalkConfigs,
  reorderShows
} from '../api'

const TYPE_CONFIG = {
  music: { color: '#4a9eff', bg: 'rgba(74, 158, 255, 0.12)', icon: '\u266B', label: 'Music' },
  talk:  { color: '#ff6b6b', bg: 'rgba(255, 107, 107, 0.12)', icon: '\uD83C\uDF99', label: 'Talk' },
  hybrid:{ color: '#ffa94d', bg: 'rgba(255, 169, 77, 0.12)', icon: '\u2726', label: 'Hybrid' },
}

function Shows() {
  const [shows, setShows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [modalError, setModalError] = useState(null)
  const [showModal, setShowModal] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({
    name: '',
    show_type: 'music',
    duration_minutes: 30,
    queue_order: 0,
    talk_config_id: '',
    dj_config_id: '',
    style_ids: [],
  })
  const [allStyles, setAllStyles] = useState([])
  const [allDJConfigs, setAllDJConfigs] = useState([])
  const [allTalkConfigs, setAllTalkConfigs] = useState([])

  // Filter out the system-generated live override show block
  const programBlocks = useMemo(() => {
    return shows
      .filter(s => s.name !== 'Live Broadcast')
      .sort((a, b) => a.queue_order - b.queue_order)
  }, [shows])

  async function load() {
    try {
      const [showData, djData] = await Promise.allSettled([fetchShows(), fetchDJConfigs()])
      if (showData.status === 'fulfilled') setShows(Array.isArray(showData.value) ? showData.value : [])
      if (djData.status === 'fulfilled') setAllDJConfigs(Array.isArray(djData.value) ? djData.value : [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function loadModalData() {
    try {
      const [styles, djConfigs, talkConfigs] = await Promise.allSettled([
        fetchStyles(),
        fetchDJConfigs(),
        fetchTalkConfigs()
      ])
      if (styles.status === 'fulfilled') setAllStyles(Array.isArray(styles.value) ? styles.value : [])
      if (djConfigs.status === 'fulfilled') setAllDJConfigs(Array.isArray(djConfigs.value) ? djConfigs.value : [])
      if (talkConfigs.status === 'fulfilled') setAllTalkConfigs(Array.isArray(talkConfigs.value) ? talkConfigs.value : [])
    } catch { /* ignore */ }
  }

  function openAdd() {
    setEditing(null)
    setForm({
      name: '',
      show_type: 'music',
      duration_minutes: 30,
      queue_order: programBlocks.length,
      talk_config_id: '',
      dj_config_id: '',
      style_ids: []
    })
    setModalError(null)
    setShowModal(true)
    loadModalData()
  }

  function openEdit(show) {
    setEditing(show)
    setForm({
      name: show.name,
      show_type: show.show_type,
      duration_minutes: show.duration_minutes,
      queue_order: show.queue_order,
      talk_config_id: show.talk_config_id || '',
      dj_config_id: show.dj_config_id || '',
      style_ids: show.style_ids || []
    })
    setModalError(null)
    setShowModal(true)
    loadModalData()
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const payload = {
      ...form,
      duration_minutes: parseInt(form.duration_minutes) || 30,
      talk_config_id: form.talk_config_id ? parseInt(form.talk_config_id) : null,
      dj_config_id: form.dj_config_id ? parseInt(form.dj_config_id) : null,
      style_ids: form.style_ids.length > 0 ? form.style_ids : [],
    }
    try {
      if (editing) {
        await updateShow(editing.id, payload)
      } else {
        await createShow(payload)
      }
      setShowModal(false)
      load()
    } catch (err) {
      setModalError(err.message)
    }
  }

  async function handleDelete(id) {
    if (!confirm('Delete this program block?')) return
    try {
      await deleteShow(id)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleToggle(id) {
    try {
      await toggleShow(id)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  async function moveShow(index, direction) {
    const list = [...programBlocks]
    const targetIdx = index + direction
    if (targetIdx < 0 || targetIdx >= list.length) return

    // Swap
    const temp = list[index]
    list[index] = list[targetIdx]
    list[targetIdx] = temp

    // Save order
    const ids = list.map(s => s.id)
    try {
      await reorderShows(ids)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  function toggleStyleId(id) {
    setForm(prev => {
      const ids = prev.style_ids.includes(id)
        ? prev.style_ids.filter(s => s !== id)
        : [...prev.style_ids, id]
      return { ...prev, style_ids: ids }
    })
  }

  const activeCount = programBlocks.filter(s => s.active).length
  const totalMins = programBlocks.filter(s => s.active).reduce((sum, s) => sum + s.duration_minutes, 0)
  const totalHoursLabel = totalMins > 60
    ? `${Math.floor(totalMins / 60)}h ${totalMins % 60}m`
    : `${totalMins} mins`

  if (loading) return <div className="page"><div className="shows-loading"><div className="loading-spinner" /><p>Loading schedule...</p></div></div>

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h2>Program Blocks Schedule</h2>
          <p className="page-subtitle">
            {programBlocks.length === 0
              ? 'No program blocks configured'
              : `${activeCount} active block${activeCount !== 1 ? 's' : ''} \u00B7 ${totalHoursLabel} total duration in loop`}
          </p>
        </div>
        <button className="btn btn-primary" onClick={openAdd}>+ Add Program Block</button>
      </div>

      {error && (
        <div className="error-banner">
          {error}
          <button className="error-dismiss" onClick={() => setError(null)}>&times;</button>
        </div>
      )}

      {programBlocks.length === 0 ? (
        <div className="shows-empty">
          <div className="shows-empty-icon">{'\u23F1'}</div>
          <h3>No Automation Program Blocks</h3>
          <p>
            Add program blocks to establish a loop sequence for automated scheduled playout.
            Each block plays in order for its set duration.
          </p>
          <button className="btn btn-primary" onClick={openAdd}>Create Your First Block</button>
        </div>
      ) : (
        <div className="table-container card">
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: '80px', textAlign: 'center' }}>Order</th>
                <th>Program Block Name</th>
                <th>Type</th>
                <th>Duration</th>
                <th>Details</th>
                <th>Status</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {programBlocks.map((show, index) => {
                const cfg = TYPE_CONFIG[show.show_type] || TYPE_CONFIG.music
                const djc = allDJConfigs.find(c => c.id === show.dj_config_id)
                const tc = allTalkConfigs.find(c => c.id === show.talk_config_id)
                return (
                  <tr key={show.id} className={!show.active ? 'row-inactive' : ''}>
                    <td style={{ textAlign: 'center' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', alignItems: 'center' }}>
                        <button
                          className="btn-chevron"
                          onClick={() => moveShow(index, -1)}
                          disabled={index === 0}
                          title="Move Up"
                          style={{ border: 'none', background: 'transparent', cursor: index === 0 ? 'default' : 'pointer', color: index === 0 ? '#444' : '#888' }}
                        >
                          &#9650;
                        </button>
                        <span style={{ fontWeight: 'bold', fontSize: '0.85rem' }}>{index + 1}</span>
                        <button
                          className="btn-chevron"
                          onClick={() => moveShow(index, 1)}
                          disabled={index === programBlocks.length - 1}
                          title="Move Down"
                          style={{ border: 'none', background: 'transparent', cursor: index === programBlocks.length - 1 ? 'default' : 'pointer', color: index === programBlocks.length - 1 ? '#444' : '#888' }}
                        >
                          &#9660;
                        </button>
                      </div>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>{show.name}</div>
                    </td>
                    <td>
                      <span className="show-type-badge" style={{ background: cfg.bg, color: cfg.color, padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600 }}>
                        {cfg.icon} {cfg.label}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontWeight: 600 }}>{show.duration_minutes} mins</span>
                    </td>
                    <td>
                      <div style={{ fontSize: '0.75rem', color: '#888' }}>
                        {show.show_type !== 'talk' && (
                          <div>DJ: {djc ? djc.name : 'Default'}</div>
                        )}
                        {show.show_type !== 'music' && (
                          <div>Talk Show: {tc ? tc.name : 'None'}</div>
                        )}
                        {(show.show_type === 'music' || show.show_type === 'hybrid') && (
                          <div>Styles: {show.style_ids?.length || 0} selected</div>
                        )}
                      </div>
                    </td>
                    <td>
                      <span className={`badge ${show.active ? 'badge-active' : 'badge-inactive'}`}>
                        {show.active ? 'Active' : 'Disabled'}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <div style={{ display: 'inline-flex', gap: '0.35rem' }}>
                        <button className="btn btn-sm btn-secondary" onClick={() => handleToggle(show.id)}>
                          {show.active ? 'Disable' : 'Enable'}
                        </button>
                        <button className="btn btn-sm" onClick={() => openEdit(show)}>Edit</button>
                        <button className="btn btn-sm btn-danger" onClick={() => handleDelete(show.id)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal show-modal" onClick={e => e.stopPropagation()}>
            <div className="show-modal-header">
              <h3>{editing ? 'Edit Program Block' : 'New Program Block'}</h3>
              <button className="modal-close" onClick={() => setShowModal(false)}>&times;</button>
            </div>
            {modalError && <div className="alert alert-error">{modalError}</div>}
            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label className="form-label">Program Name</label>
                <input value={form.name} onChange={e => setForm({...form, name: e.target.value})} required placeholder="e.g. Morning Groove, Jazz hour, Tech Podcast" />
              </div>

              <div className="form-group">
                <label className="form-label">Content Type</label>
                <div className="show-type-selector" style={{ display: 'flex', gap: '0.5rem' }}>
                  {Object.entries(TYPE_CONFIG).map(([type, cfg]) => (
                    <button
                      key={type}
                      type="button"
                      className={`show-type-option ${form.show_type === type ? 'selected' : ''}`}
                      style={{
                        flex: 1,
                        padding: '0.75rem',
                        border: '1px solid #1e1e3a',
                        borderRadius: '6px',
                        borderColor: form.show_type === type ? cfg.color : '#1e1e3a',
                        background: form.show_type === type ? cfg.bg : 'transparent',
                        color: form.show_type === type ? cfg.color : '#888',
                        cursor: 'pointer',
                        fontWeight: 600
                      }}
                      onClick={() => setForm({...form, show_type: type})}
                    >
                      <span className="show-type-option-icon" style={{ marginRight: '6px' }}>{cfg.icon}</span>
                      <span className="show-type-option-label">{cfg.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">Play Duration (Minutes)</label>
                <input
                  type="number"
                  min="5"
                  max="1440"
                  value={form.duration_minutes}
                  onChange={e => setForm({...form, duration_minutes: e.target.value})}
                  required
                  placeholder="30"
                />
                <span className="form-hint">How long this block runs before transitioning to the next block in the queue.</span>
              </div>

              {(form.show_type === 'music' || form.show_type === 'hybrid') && allStyles.length > 0 && (
                <div className="form-group">
                  <label className="form-label">Music Styles</label>
                  <div className="style-picker" style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem', maxHeight: '120px', overflowY: 'auto', padding: '0.5rem', background: '#090915', border: '1px solid #1e1e3a', borderRadius: '6px' }}>
                    {allStyles.filter(s => s.active).map(s => {
                      const isSelected = form.style_ids.includes(s.id)
                      return (
                        <button
                          key={s.id}
                          type="button"
                          className={`style-pill ${isSelected ? 'selected' : ''}`}
                          style={{
                            padding: '4px 12px',
                            borderRadius: '20px',
                            border: isSelected ? '1px solid #4a9eff' : '1px solid #2a2a4a',
                            background: isSelected ? '#1b263b' : 'transparent',
                            color: isSelected ? '#4a9eff' : '#888',
                            cursor: 'pointer',
                            fontSize: '0.75rem',
                            display: 'flex',
                            alignItems: 'center'
                          }}
                          onClick={() => toggleStyleId(s.id)}
                        >
                          {isSelected && <span className="style-pill-check" style={{ marginRight: '4px' }}>&#10003;</span>}
                          {s.name}
                        </button>
                      )
                    })}
                  </div>
                  <span className="form-hint">Selected styles play only during this block. Leave empty to use all active styles.</span>
                </div>
              )}

              {(form.show_type === 'music' || form.show_type === 'hybrid') && (
                <div className="form-group">
                  <label className="form-label">DJ Personality Config</label>
                  <select value={form.dj_config_id} onChange={e => setForm({...form, dj_config_id: e.target.value})}>
                    <option value="">Use Station Default DJ</option>
                    {allDJConfigs.map(c => (
                      <option key={c.id} value={c.id}>
                        {c.name}{c.is_default ? ' (Default)' : ''} &mdash; {c.dj_name}
                      </option>
                    ))}
                  </select>
                  <span className="form-hint">Optionally override the DJ persona for this show block.</span>
                </div>
              )}

              {(form.show_type === 'talk' || form.show_type === 'hybrid') && (
                <div className="form-group">
                  <label className="form-label">Talk Show Config</label>
                  <select value={form.talk_config_id} onChange={e => setForm({...form, talk_config_id: e.target.value})}>
                    <option value="">None</option>
                    {allTalkConfigs.map(c => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                  <span className="form-hint">Select a talk config for dialogue segments.</span>
                </div>
              )}

              <div className="modal-actions" style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', marginTop: '1.5rem' }}>
                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary">{editing ? 'Save Changes' : 'Create Block'}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

export default Shows
