import React, { useState, useEffect, useRef } from 'react'
import { fetchPlayLog, exportPlayLog } from '../api'
import { formatDuration, formatTimestamp } from '../utils/format'

function PlayLog() {
  const [entries, setEntries] = useState([])
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const requestIdRef = useRef(0)
  const perPage = 20

  async function loadLog(p, start, end) {
    const requestId = ++requestIdRef.current
    setLoading(true)
    try {
      const data = await fetchPlayLog(p, perPage, start || undefined, end || undefined)
      if (requestId !== requestIdRef.current) return // stale response
      setEntries(Array.isArray(data) ? data : data.items || data.entries || [])
      const totalCount = data.total || 0
      setTotal(totalCount)
      setTotalPages(data.total_pages || data.pages || Math.ceil(totalCount / perPage) || 1)
      setError(null)
    } catch (err) {
      if (requestId !== requestIdRef.current) return
      setError(err.message)
    } finally {
      if (requestId === requestIdRef.current) setLoading(false)
    }
  }

  useEffect(() => {
    loadLog(page, startDate, endDate)
  }, [page, startDate, endDate])

  function handleStartDateChange(value) {
    setStartDate(value)
    setPage(1)
  }

  function handleEndDateChange(value) {
    setEndDate(value)
    setPage(1)
  }

  function handleClearFilter() {
    setStartDate('')
    setEndDate('')
    setPage(1)
  }

  async function handleExport() {
    setExporting(true)
    try {
      const blob = await exportPlayLog()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `playlog-${new Date().toISOString().slice(0, 10)}.csv`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err.message)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div>
      <div className="page-header">
        <h2>Play Log</h2>
        <button className="btn btn-secondary" onClick={handleExport} disabled={exporting}>
          {exporting ? 'Exporting...' : 'Export CSV'}
        </button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="filter-row">
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>From</label>
            <input
              type="date"
              value={startDate}
              onChange={e => handleStartDateChange(e.target.value)}
            />
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>To</label>
            <input
              type="date"
              value={endDate}
              onChange={e => handleEndDateChange(e.target.value)}
            />
          </div>
          <div className="filter-actions">
            {(startDate || endDate) && (
              <button className="btn btn-sm" onClick={handleClearFilter}>
                Clear
              </button>
            )}
          </div>
        </div>
        {total > 0 && (
          <div style={{ fontSize: 12, color: '#a0a0b8', marginTop: 8 }}>
            {total} total entries
          </div>
        )}
      </div>

      <div className="card">
        {loading ? (
          <div style={{ textAlign: 'center', padding: 32 }}>
            <div className="loading-spinner" style={{ margin: '0 auto 12px' }} />
            <p style={{ color: '#a0a0b8' }}>Loading play log...</p>
          </div>
        ) : entries.length === 0 ? (
          <p style={{ color: '#555', fontStyle: 'italic', padding: 24, textAlign: 'center' }}>
            {(startDate || endDate) ? 'No entries match the selected date range.' : 'No play history yet.'}
          </p>
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Type</th>
                  <th>Title</th>
                  <th>Duration</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry, i) => (
                  <tr key={entry.id || `entry-${i}`}>
                    <td>{formatTimestamp(entry.started_at || entry.played_at || entry.timestamp)}</td>
                    <td>
                      <span className={`badge badge-${(entry.item_type || entry.type) === 'track' ? 'track' : 'break'}`}>
                        {entry.item_type || entry.type}
                      </span>
                    </td>
                    <td>{entry.title || 'Untitled'}</td>
                    <td>{formatDuration(entry.duration)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!loading && entries.length > 0 && (
          <div className="pagination">
            <button
              className="btn btn-sm"
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page <= 1}
            >
              Previous
            </button>
            <span className="pagination-info">
              Page {page} of {totalPages}
            </span>
            <button
              className="btn btn-sm"
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
            >
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default PlayLog
