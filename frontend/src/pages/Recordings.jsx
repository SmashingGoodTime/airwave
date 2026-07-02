import React, { useState, useEffect, useCallback } from 'react'
import {
  fetchRecordingStatus,
  toggleRecording,
  updateRecordingSettings,
  fetchRecordings,
  deleteRecording,
  getRecordingDownloadUrl,
} from '../api'

function Recordings() {
  const [status, setStatus] = useState(null)
  const [recordings, setRecordings] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [toggling, setToggling] = useState(false)
  const [retentionDays, setRetentionDays] = useState(7)
  const [savingSettings, setSavingSettings] = useState(false)

  const loadData = useCallback(async () => {
    try {
      const [statusData, recordingList] = await Promise.allSettled([
        fetchRecordingStatus(),
        fetchRecordings(),
      ])
      if (statusData.status === 'fulfilled') {
        setStatus(statusData.value)
        setRetentionDays(statusData.value.retention_days)
      }
      if (recordingList.status === 'fulfilled') setRecordings(recordingList.value)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  async function handleToggle() {
    setToggling(true)
    try {
      const result = await toggleRecording(!status?.enabled)
      setStatus(prev => ({ ...prev, enabled: result.enabled, active: result.active }))
      // Refresh list after a short delay to pick up new file
      setTimeout(loadData, 2000)
    } catch (err) {
      setError(err.message)
    } finally {
      setToggling(false)
    }
  }

  async function handleSaveSettings() {
    setSavingSettings(true)
    try {
      await updateRecordingSettings({ retention_days: retentionDays })
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setSavingSettings(false)
    }
  }

  async function handleDelete(filename) {
    if (!confirm(`Delete recording ${filename}?`)) return
    try {
      await deleteRecording(filename)
      setRecordings(prev => prev.filter(r => r.filename !== filename))
    } catch (err) {
      setError(err.message)
    }
  }

  if (loading) {
    return <div className="loading-screen"><div className="loading-spinner" /><p>Loading recordings...</p></div>
  }

  return (
    <div>
      <div className="page-header">
        <h2>Stream Recording</h2>
        <button className="btn btn-sm" onClick={loadData}>Refresh</button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="card-row">
        <div className="card">
          <div className="card-header">
            <h3>Recording Control</h3>
            <span className={`badge ${status?.active ? 'badge-active' : 'badge-inactive'}`}>
              {status?.active ? 'Recording' : 'Stopped'}
            </span>
          </div>
          <p className="section-help">
            Save a local copy of your broadcast stream. Recordings are saved as hourly MP3 files.
          </p>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginTop: '1rem' }}>
            <button
              className={`btn ${status?.enabled ? 'btn-danger' : 'btn-primary'}`}
              onClick={handleToggle}
              disabled={toggling}
            >
              {toggling ? 'Working...' : status?.enabled ? 'Stop Recording' : 'Start Recording'}
            </button>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h3>Storage</h3>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Files:</span>
              <strong>{status?.file_count ?? 0}</strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Disk usage:</span>
              <strong>{status?.disk_usage_mb ?? 0} MB</strong>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.5rem' }}>
              <label htmlFor="retention">Auto-delete after</label>
              <input
                id="retention"
                type="number"
                min="1"
                max="365"
                value={retentionDays}
                onChange={e => setRetentionDays(parseInt(e.target.value) || 7)}
                style={{ width: '60px' }}
                className="input"
              />
              <span>days</span>
              <button
                className="btn btn-sm"
                onClick={handleSaveSettings}
                disabled={savingSettings}
              >
                {savingSettings ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-header">
          <h3>Recordings</h3>
        </div>
        {recordings.length === 0 ? (
          <p style={{ color: '#555', fontStyle: 'italic', padding: '12px 0' }}>
            No recordings yet. Enable recording to start saving your broadcast.
          </p>
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>Date / Hour</th>
                  <th>Filename</th>
                  <th>Size</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {recordings.map(rec => (
                  <tr key={rec.filename}>
                    <td>{rec.duration_hint || rec.filename}</td>
                    <td>{rec.filename}</td>
                    <td>{rec.size_mb} MB</td>
                    <td style={{ display: 'flex', gap: '0.5rem' }}>
                      <a
                        href={getRecordingDownloadUrl(rec.filename)}
                        className="btn btn-sm"
                        download
                      >
                        Download
                      </a>
                      <button
                        className="btn btn-sm btn-danger"
                        onClick={() => handleDelete(rec.filename)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

export default Recordings
