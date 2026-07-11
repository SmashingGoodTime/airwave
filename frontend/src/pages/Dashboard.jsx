import React, { useState, useEffect, useRef, useCallback } from 'react'
import {
  fetchDashboardStatus,
  fetchRecentPlays,
  fetchTimelineItems,
  fetchTimelineHealth,
  fetchGenerationJobs,
  fetchHealth,
  fetchRecordingStatus,
  startStreaming,
  stopStreaming,
  switchStreamingMode,
  fetchStreamUrl,
  fetchShows,
  fetchDJConfigs,
  fetchTalkConfigs,
  fetchStyles,
  fetchStreamingStatus,
  createShow,
  updateShow
} from '../api'
import NowPlaying from '../components/NowPlaying'
import BufferStatus from '../components/BufferStatus'
import HealthIndicators from '../components/HealthIndicators'
import AudioPlayer from '../components/AudioPlayer'
import { formatDuration, formatTimeOfDay } from '../utils/format'

const panelStyle = {
  background: '#111126',
  border: '1px solid #1e1e3a',
  borderRadius: 8,
  padding: '1rem',
}

const mutedText = {
  color: '#a0a0b8',
  fontSize: '0.85rem',
}

const compactInput = {
  width: '100%',
  padding: '0.6rem',
  background: '#090915',
  border: '1px solid #1e1e3a',
  borderRadius: 6,
  color: '#e0e0e0',
}

function Dashboard() {
  const [status, setStatus] = useState(null)
  const [recentPlays, setRecentPlays] = useState([])
  const [timelineItems, setTimelineItems] = useState([])
  const [timelineHealth, setTimelineHealth] = useState(null)
  const [generationJobs, setGenerationJobs] = useState([])
  const [health, setHealth] = useState(null)
  const [recordingStatus, setRecordingStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [wsConnected, setWsConnected] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [streamingShowType, setStreamingShowType] = useState(null)
  const [streamingAction, setStreamingAction] = useState(false)
  const [streamUrl, setStreamUrl] = useState(null)

  const [shows, setShows] = useState([])
  const [djConfigs, setDJConfigs] = useState([])
  const [talkConfigs, setTalkConfigs] = useState([])
  const [styles, setStyles] = useState([])
  const [broadcastMode, setBroadcastMode] = useState('manual')
  const [currentShowId, setCurrentShowId] = useState(null)
  const [activeShowName, setActiveShowName] = useState(null)
  const [currentShowStartedAt, setCurrentShowStartedAt] = useState(null)
  const [durationMinutes, setDurationMinutes] = useState(30)
  const [timeLeft, setTimeLeft] = useState(null)

  const [selectedDjConfigId, setSelectedDjConfigId] = useState('')
  const [selectedShowType, setSelectedShowType] = useState('music')
  const [selectedStyleIds, setSelectedStyleIds] = useState([])
  const [selectedTalkConfigId, setSelectedTalkConfigId] = useState('')
  const [selectedPresetShowId, setSelectedPresetShowId] = useState('')

  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const fallbackInterval = useRef(null)
  const wsClosedRef = useRef(false)
  // Timestamp until which a manual-action error must not be cleared by background refreshes.
  const actionErrorUntilRef = useRef(0)
  const countdownReloadedRef = useRef(false)

  function setActionError(message) {
    actionErrorUntilRef.current = Date.now() + 8000
    setError(message)
  }

  async function loadData() {
    try {
      const [
        statusData,
        recentData,
        timelineData,
        timelineHealthData,
        jobsData,
        healthData,
        recData,
        showsData,
        djsData,
        talkData,
        stylesData,
        streamStatusData
      ] = await Promise.allSettled([
        fetchDashboardStatus(),
        fetchRecentPlays(),
        fetchTimelineItems(),
        fetchTimelineHealth(),
        fetchGenerationJobs(),
        fetchHealth(),
        fetchRecordingStatus(),
        fetchShows(),
        fetchDJConfigs(),
        fetchTalkConfigs(),
        fetchStyles(),
        fetchStreamingStatus()
      ])

      const loadedShows = showsData.status === 'fulfilled' ? showsData.value : []

      if (statusData.status === 'fulfilled') setStatus(statusData.value)
      if (recentData.status === 'fulfilled') setRecentPlays(recentData.value)
      if (timelineData.status === 'fulfilled') setTimelineItems(timelineData.value)
      if (timelineHealthData.status === 'fulfilled') setTimelineHealth(timelineHealthData.value)
      if (jobsData.status === 'fulfilled') setGenerationJobs(jobsData.value)
      if (healthData.status === 'fulfilled') setHealth(healthData.value)
      if (recData.status === 'fulfilled') setRecordingStatus(recData.value)
      if (showsData.status === 'fulfilled') setShows(loadedShows)
      if (djsData.status === 'fulfilled') setDJConfigs(djsData.value)
      if (talkData.status === 'fulfilled') setTalkConfigs(talkData.value)
      if (stylesData.status === 'fulfilled') setStyles(stylesData.value)

      if (streamStatusData.status === 'fulfilled') {
        const streamData = streamStatusData.value
        setStreaming(streamData.streaming)
        setStreamingShowType(streamData.show_type)
        setBroadcastMode(streamData.broadcast_mode || 'manual')
        setCurrentShowId(streamData.current_show_id)
        setActiveShowName(streamData.active_show_name)
        setCurrentShowStartedAt(streamData.current_show_started_at)
        setDurationMinutes(streamData.duration_minutes || 30)

        if (streamData.streaming && streamData.broadcast_mode === 'manual' && streamData.current_show_id) {
          const currentShowObj = loadedShows.find(s => s.id === streamData.current_show_id)
          if (currentShowObj) {
            setSelectedDjConfigId(currentShowObj.dj_config_id || '')
            setSelectedShowType(currentShowObj.show_type)
            setSelectedStyleIds(currentShowObj.style_ids || [])
            setSelectedTalkConfigId(currentShowObj.talk_config_id || '')
          }
        }
      }

      // The dashboard is effectively down when its core fetches fail together.
      const criticalResults = [statusData, streamStatusData]
      const criticalFailures = criticalResults.filter(r => r.status === 'rejected')
      if (criticalFailures.length === criticalResults.length) {
        setError(`Dashboard unavailable: ${criticalFailures[0].reason?.message || 'request failed'}`)
      } else if (Date.now() >= actionErrorUntilRef.current) {
        // Keep recent manual-action errors visible for a few seconds.
        setError(null)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const loadDataRef = useRef(loadData)
  loadDataRef.current = loadData

  const connectWebSocket = useCallback(() => {
    if (wsClosedRef.current) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/api/dashboard/ws`

    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setWsConnected(true)
        if (fallbackInterval.current) {
          clearInterval(fallbackInterval.current)
          fallbackInterval.current = null
        }
      }

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'status.snapshot' && msg.data) {
            setStatus(prev => ({ ...prev, ...msg.data }))
            if (msg.data.streaming !== undefined) {
              setStreaming(msg.data.streaming)
              setStreamingShowType(msg.data.streaming_show_type ?? null)
            }
          } else if (msg.type === 'stream.started' && msg.data) {
            setStreaming(true)
            setStreamingShowType(msg.data.show_type ?? null)
            loadDataRef.current()
          } else if (msg.type === 'stream.stopped') {
            setStreaming(false)
            setStreamingShowType(null)
            setBroadcastMode('manual')
            setCurrentShowId(null)
            setActiveShowName(null)
            setCurrentShowStartedAt(null)
          } else if (msg.type === 'stream.mode_changed' || msg.type === 'show.started') {
            loadDataRef.current()
          } else if (msg.type === 'track.started' && msg.data) {
            setStatus(prev => ({ ...prev, now_playing: msg.data }))
          } else if (msg.type === 'track.ended' || msg.type === 'break.generated' || msg.type === 'provider.error') {
            loadDataRef.current()
          } else if (msg.type === 'buffer.low' || msg.type === 'buffer.critical') {
            setStatus(prev => ({
              ...prev,
              buffer_depth: msg.data?.buffer_depth ?? msg.data?.ready ?? prev?.buffer_depth
            }))
          }
        } catch {
          // Ignore malformed socket messages.
        }
      }

      ws.onclose = () => {
        if (wsClosedRef.current) return
        setWsConnected(false)
        wsRef.current = null
        if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
        reconnectTimer.current = setTimeout(connectWebSocket, 5000)
        if (!fallbackInterval.current) {
          fallbackInterval.current = setInterval(() => loadDataRef.current(), 15000)
        }
      }

      ws.onerror = () => { ws.close() }
    } catch {
      if (!fallbackInterval.current) {
        fallbackInterval.current = setInterval(() => loadDataRef.current(), 10000)
      }
    }
  }, [])

  useEffect(() => {
    wsClosedRef.current = false
    loadData()
    connectWebSocket()
    fetchStreamUrl().then(data => setStreamUrl(data?.url || null)).catch(() => {})
    return () => {
      wsClosedRef.current = true
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current)
        reconnectTimer.current = null
      }
      if (fallbackInterval.current) {
        clearInterval(fallbackInterval.current)
        fallbackInterval.current = null
      }
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.onerror = null
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connectWebSocket])

  useEffect(() => {
    // New show start (or countdown restart) re-arms the expiry reload latch.
    countdownReloadedRef.current = false

    if (broadcastMode !== 'scheduled' || !streaming || !currentShowStartedAt) {
      setTimeLeft(null)
      return
    }

    const tick = () => {
      const started = new Date(currentShowStartedAt).getTime()
      const durationMs = durationMinutes * 60 * 1000
      const remaining = Math.max(0, durationMs - (Date.now() - started))
      const totalSecs = Math.floor(remaining / 1000)
      const minutes = Math.floor(totalSecs / 60)
      const seconds = totalSecs % 60
      setTimeLeft(`${minutes}:${String(seconds).padStart(2, '0')}`)
      if (remaining <= 0 && !countdownReloadedRef.current) {
        countdownReloadedRef.current = true
        loadDataRef.current()
      }
    }

    tick()
    const interval = setInterval(tick, 1000)
    return () => clearInterval(interval)
  }, [broadcastMode, streaming, currentShowStartedAt, durationMinutes])

  async function handleGoLive() {
    setStreamingAction(true)
    try {
      let liveShow = shows.find(s => s.name === 'Live Broadcast')
      const showData = {
        name: 'Live Broadcast',
        show_type: selectedShowType,
        dj_config_id: selectedDjConfigId ? parseInt(selectedDjConfigId) : null,
        talk_config_id: selectedTalkConfigId ? parseInt(selectedTalkConfigId) : null,
        style_ids: selectedStyleIds,
        active: true,
        duration_minutes: 60,
        queue_order: 0,
      }

      let showId
      if (liveShow) {
        const updated = await updateShow(liveShow.id, showData)
        showId = updated.id
      } else {
        const created = await createShow(showData)
        showId = created.id
      }

      await startStreaming({ show_id: showId, broadcast_mode: 'manual' })
      setStreaming(true)
      setBroadcastMode('manual')
      setCurrentShowId(showId)
      setActiveShowName('Live Broadcast')
      setStreamingShowType(selectedShowType)
      setError(null)
      loadData()
    } catch (err) {
      setActionError(err.message)
    } finally {
      setStreamingAction(false)
    }
  }

  async function handleGoLivePreset() {
    if (!selectedPresetShowId) return
    setStreamingAction(true)
    try {
      const showId = parseInt(selectedPresetShowId)
      await startStreaming({ show_id: showId, broadcast_mode: 'manual' })
      const selectedShow = shows.find(s => s.id === showId)
      setStreaming(true)
      setBroadcastMode('manual')
      setCurrentShowId(showId)
      setActiveShowName(selectedShow?.name || 'Live Broadcast')
      setStreamingShowType(selectedShow?.show_type || 'music')
      setError(null)
      loadData()
    } catch (err) {
      setActionError(err.message)
    } finally {
      setStreamingAction(false)
    }
  }

  async function handleActivateScheduler() {
    setStreamingAction(true)
    try {
      const activeShows = shows.filter(s => s.active && s.name !== 'Live Broadcast')
      if (activeShows.length === 0) {
        throw new Error('No active program blocks found.')
      }

      if (streaming) {
        await switchStreamingMode({ broadcast_mode: 'scheduled', show_id: activeShows[0].id })
      } else {
        await startStreaming({ broadcast_mode: 'scheduled', show_id: activeShows[0].id })
      }
      setStreaming(true)
      setBroadcastMode('scheduled')
      setError(null)
      loadData()
    } catch (err) {
      setActionError(err.message)
    } finally {
      setStreamingAction(false)
    }
  }

  async function handleSkipBlock() {
    if (broadcastMode !== 'scheduled' || streamingAction) return
    setStreamingAction(true)
    try {
      const activeShows = shows.filter(s => s.active && s.name !== 'Live Broadcast')
      if (activeShows.length <= 1) {
        throw new Error('Need more than one active program block.')
      }

      const currentIdx = activeShows.findIndex(s => s.id === currentShowId)
      const nextIdx = (currentIdx + 1) % activeShows.length
      const nextShow = activeShows[nextIdx]
      await switchStreamingMode({ broadcast_mode: 'scheduled', show_id: nextShow.id })
      setError(null)
      loadData()
    } catch (err) {
      setActionError(err.message)
    } finally {
      setStreamingAction(false)
    }
  }

  async function handleStopStreaming() {
    setStreamingAction(true)
    try {
      await stopStreaming()
      setStreaming(false)
      setStreamingShowType(null)
      setBroadcastMode('manual')
      setCurrentShowId(null)
      setActiveShowName(null)
      setError(null)
      loadData()
    } catch (err) {
      setActionError(err.message)
    } finally {
      setStreamingAction(false)
    }
  }

  function handleStyleToggle(styleId) {
    setSelectedStyleIds(prev =>
      prev.includes(styleId) ? prev.filter(id => id !== styleId) : [...prev, styleId]
    )
  }

  const programBlocks = shows.filter(s => s.name !== 'Live Broadcast')
  const activeProgramBlocks = programBlocks.filter(s => s.active)
  const timelineIssues = timelineHealth?.issues || []
  const failedJobs = generationJobs.filter(job => job.status === 'failed')
  const runningJobs = generationJobs.filter(job => job.status === 'running')
  const problemJobs = [...runningJobs, ...failedJobs].slice(0, 6)
  const bufferDepth = status?.buffer_depth ?? 0
  const bufferTarget = status?.buffer_target ?? 3
  const bufferWarning = status?.buffer_warning ?? 2
  const streamModeLabel = broadcastMode === 'scheduled' ? 'Scheduled' : 'Manual'
  const currentShowLabel = activeShowName || (streaming ? `${streamingShowType || 'music'} stream` : 'Not broadcasting')
  const hasAttention = timelineIssues.length > 0 || failedJobs.length > 0 || bufferDepth <= bufferWarning

  if (loading) {
    return (
      <div style={{ maxWidth: 1180, margin: '0 auto' }}>
        <div className="card">Loading dashboard...</div>
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 1180, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div className="page-header" style={{ marginBottom: 0 }}>
        <div>
          <h2>Dashboard</h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 6 }}>
            <StatusPill tone={streaming ? 'good' : 'idle'} label={streaming ? 'On Air' : 'Idle'} />
            <StatusPill tone={wsConnected ? 'good' : 'warn'} label={wsConnected ? 'Live' : 'Polling'} />
            {recordingStatus?.active && <StatusPill tone="bad" label="REC" />}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <button className="btn btn-sm" onClick={loadData}>Refresh</button>
          {streaming && (
            <button className="btn btn-sm btn-danger" onClick={handleStopStreaming} disabled={streamingAction}>
              {streamingAction ? 'Stopping...' : 'Stop'}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="alert alert-error">
          <strong>Error:</strong> {error}
        </div>
      )}

      <section style={{
        ...panelStyle,
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
        gap: '1rem',
        alignItems: 'center',
      }}>
        <div>
          <div style={{ ...mutedText, marginBottom: 6 }}>{streamModeLabel}</div>
          <div style={{ fontSize: '1.35rem', fontWeight: 700, color: '#f5f7fb' }}>
            {currentShowLabel}
          </div>
          <div style={{ ...mutedText, marginTop: 8, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <span>{streamingShowType || selectedShowType}</span>
            {broadcastMode === 'scheduled' && timeLeft && <span>{timeLeft} left</span>}
            {recordingStatus?.active && <span>{recordingStatus.disk_usage_mb} MB recorded</span>}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          {broadcastMode === 'scheduled' && streaming && (
            <button className="btn btn-sm btn-secondary" onClick={handleSkipBlock} disabled={streamingAction}>
              Skip Block
            </button>
          )}
          {!streaming && (
            <button className="btn btn-sm btn-primary" onClick={handleGoLive} disabled={streamingAction}>
              Go Live
            </button>
          )}
        </div>
      </section>

      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem' }}>
        <div className="card" style={{ margin: 0 }}>
          <div className="card-header">
            <h3>Now Playing</h3>
            <span className={`badge ${status?.stream_status === 'online' ? 'badge-active' : 'badge-inactive'}`}>
              {status?.stream_status === 'online' ? 'Online' : 'Offline'}
            </span>
          </div>
          <NowPlaying track={status?.now_playing || null} />
        </div>

        <div className="card" style={{ margin: 0 }}>
          <div className="card-header">
            <h3>Monitor</h3>
          </div>
          <AudioPlayer streamUrl={streamUrl} compact />
        </div>
      </section>

      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '1rem' }}>
        <div className="card" style={{ margin: 0 }}>
          <div className="card-header">
            <h3>Music Queue</h3>
          </div>
          <BufferStatus depth={bufferDepth} target={bufferTarget} warning={bufferWarning} />
        </div>

        <div className="card" style={{ margin: 0 }}>
          <div className="card-header">
            <h3>AI Services</h3>
          </div>
          <HealthIndicators health={health} />
        </div>

        <div className="card" style={{ margin: 0 }}>
          <div className="card-header">
            <h3>Attention</h3>
            <span className={`badge ${hasAttention ? 'badge-inactive' : 'badge-active'}`}>
              {hasAttention ? 'Review' : 'Clear'}
            </span>
          </div>
          <AttentionList
            bufferDepth={bufferDepth}
            bufferWarning={bufferWarning}
            timelineIssues={timelineIssues}
            failedJobs={failedJobs}
            runningJobs={runningJobs}
          />
        </div>
      </section>

      <section className="card" style={{ margin: 0 }}>
        <div className="card-header">
          <h3>Broadcast Control</h3>
          <span className="badge badge-track">{streamModeLabel}</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1rem' }}>
          <div style={panelStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', marginBottom: 12 }}>
              <h4 style={{ margin: 0, color: '#f5f7fb', fontSize: '0.95rem' }}>Manual Live</h4>
              <StatusPill tone={broadcastMode === 'manual' && streaming ? 'good' : 'idle'} label={broadcastMode === 'manual' && streaming ? 'Active' : 'Ready'} />
            </div>

            <div style={{ display: 'grid', gap: 12 }}>
              <SegmentedControl
                value={selectedShowType}
                options={[
                  ['music', 'Music'],
                  ['talk', 'Talk'],
                  ['hybrid', 'Hybrid'],
                ]}
                onChange={setSelectedShowType}
              />

              <label style={{ display: 'grid', gap: 6 }}>
                <span style={mutedText}>DJ</span>
                <select value={selectedDjConfigId} onChange={e => setSelectedDjConfigId(e.target.value)} style={compactInput}>
                  <option value="">Default DJ</option>
                  {djConfigs.map(config => (
                    <option key={config.id} value={config.id}>
                      {config.dj_name || config.station_name || `DJ ${config.id}`}
                    </option>
                  ))}
                </select>
              </label>

              {(selectedShowType === 'music' || selectedShowType === 'hybrid') && (
                <div>
                  <div style={{ ...mutedText, marginBottom: 6 }}>Styles</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    {styles.length === 0 ? (
                      <span style={mutedText}>No active styles</span>
                    ) : styles.map(style => {
                      const isSelected = selectedStyleIds.includes(style.id)
                      return (
                        <button
                          key={style.id}
                          type="button"
                          onClick={() => handleStyleToggle(style.id)}
                          className={`btn btn-sm ${isSelected ? 'btn-primary' : 'btn-secondary'}`}
                          style={{ fontSize: '0.75rem' }}
                        >
                          {style.name}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}

              {(selectedShowType === 'talk' || selectedShowType === 'hybrid') && (
                <label style={{ display: 'grid', gap: 6 }}>
                  <span style={mutedText}>Talk Config</span>
                  <select value={selectedTalkConfigId} onChange={e => setSelectedTalkConfigId(e.target.value)} style={compactInput}>
                    <option value="">Select config</option>
                    {talkConfigs.map(config => (
                      <option key={config.id} value={config.id}>
                        {config.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}

              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button className="btn btn-primary" onClick={handleGoLive} disabled={streamingAction}>
                  {streamingAction ? 'Working...' : streaming && broadcastMode === 'manual' ? 'Update Live' : 'Go Live'}
                </button>
                {programBlocks.length > 0 && (
                  <>
                    <select value={selectedPresetShowId} onChange={e => setSelectedPresetShowId(e.target.value)} style={{ ...compactInput, maxWidth: 220 }}>
                      <option value="">Show block</option>
                      {programBlocks.map(block => (
                        <option key={block.id} value={block.id}>
                          {block.name}
                        </option>
                      ))}
                    </select>
                    <button className="btn btn-secondary" onClick={handleGoLivePreset} disabled={!selectedPresetShowId || streamingAction}>
                      Load
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>

          <div style={panelStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', marginBottom: 12 }}>
              <h4 style={{ margin: 0, color: '#f5f7fb', fontSize: '0.95rem' }}>Schedule</h4>
              <StatusPill tone={broadcastMode === 'scheduled' && streaming ? 'good' : 'idle'} label={broadcastMode === 'scheduled' && streaming ? 'Active' : `${activeProgramBlocks.length} blocks`} />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 4 }}>
                {programBlocks.length === 0 ? (
                  <span style={mutedText}>No blocks</span>
                ) : programBlocks.map(block => {
                  const isActive = broadcastMode === 'scheduled' && currentShowId === block.id
                  return (
                    <div
                      key={block.id}
                      style={{
                        minWidth: 150,
                        padding: '0.7rem',
                        borderRadius: 6,
                        border: isActive ? '1px solid #2ec4b6' : '1px solid #1e1e3a',
                        background: isActive ? '#102a2b' : '#090915',
                      }}
                    >
                      <div style={{ color: '#f5f7fb', fontWeight: 700, fontSize: '0.85rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {block.name}
                      </div>
                      <div style={{ ...mutedText, display: 'flex', justifyContent: 'space-between', marginTop: 5 }}>
                        <span>{block.show_type}</span>
                        <span>{block.duration_minutes}m</span>
                      </div>
                    </div>
                  )
                })}
              </div>

              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button className="btn btn-primary" onClick={handleActivateScheduler} disabled={streamingAction || activeProgramBlocks.length === 0}>
                  {broadcastMode === 'scheduled' && streaming ? 'Restart Schedule' : 'Start Schedule'}
                </button>
                {broadcastMode === 'scheduled' && streaming && (
                  <button className="btn btn-secondary" onClick={handleSkipBlock} disabled={streamingAction || activeProgramBlocks.length <= 1}>
                    Skip Block
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1rem' }}>
        <div className="card" style={{ margin: 0 }}>
          <div className="card-header">
            <h3>Recent Activity</h3>
            <button className="btn btn-sm" onClick={() => fetchRecentPlays().then(setRecentPlays).catch(() => {})}>
              Refresh
            </button>
          </div>
          <RecentPlayTable plays={recentPlays.slice(0, 8)} />
        </div>

        <div className="card" style={{ margin: 0 }}>
          <div className="card-header">
            <h3>Generation</h3>
            <span className={`badge ${failedJobs.length ? 'badge-inactive' : 'badge-active'}`}>
              {runningJobs.length} running
            </span>
          </div>
          <JobList jobs={problemJobs} />
        </div>
      </section>

      <details className="card" style={{ margin: 0 }}>
        <summary style={{ cursor: 'pointer', color: '#f5f7fb', fontWeight: 700 }}>
          Diagnostics
        </summary>
        <Diagnostics
          timelineHealth={timelineHealth}
          timelineItems={timelineItems}
          generationJobs={generationJobs}
        />
      </details>
    </div>
  )
}

function StatusPill({ tone, label }) {
  const colors = {
    good: ['#143624', '#66bb6a'],
    warn: ['#3a2c10', '#ffc857'],
    bad: ['#3a1414', '#ff6b6b'],
    idle: ['#15172b', '#a0a0b8'],
  }
  const [bg, fg] = colors[tone] || colors.idle
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      background: bg,
      color: fg,
      border: `1px solid ${fg}33`,
      borderRadius: 999,
      padding: '0.25rem 0.55rem',
      fontSize: '0.75rem',
      fontWeight: 700,
    }}>
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: fg }} />
      {label}
    </span>
  )
}

function SegmentedControl({ value, options, onChange }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${options.length}, 1fr)`, gap: 6 }}>
      {options.map(([optionValue, label]) => (
        <button
          key={optionValue}
          type="button"
          className={`btn btn-sm ${value === optionValue ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => onChange(optionValue)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

function AttentionList({ bufferDepth, bufferWarning, timelineIssues, failedJobs, runningJobs }) {
  const items = []
  if (bufferDepth <= bufferWarning) {
    items.push(`Queue low: ${bufferDepth} ready`)
  }
  timelineIssues.slice(0, 3).forEach(issue => {
    items.push(`${issue.count} ${issue.message}`)
  })
  if (failedJobs.length > 0) {
    items.push(`${failedJobs.length} failed generation job${failedJobs.length === 1 ? '' : 's'}`)
  }
  if (runningJobs.length > 0) {
    items.push(`${runningJobs.length} generation job${runningJobs.length === 1 ? '' : 's'} running`)
  }

  if (items.length === 0) {
    return <p style={{ ...mutedText, margin: 0 }}>No current issues</p>
  }

  return (
    <ul style={{ margin: 0, paddingLeft: '1rem', color: '#d5d7ef', display: 'grid', gap: 6 }}>
      {items.map((item, index) => (
        <li key={`${item}-${index}`} style={{ fontSize: '0.85rem' }}>{item}</li>
      ))}
    </ul>
  )
}

function RecentPlayTable({ plays }) {
  if (plays.length === 0) {
    return <p style={{ ...mutedText, margin: 0 }}>No recent plays</p>
  }

  return (
    <div className="table-container">
      <table className="table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Type</th>
            <th>Title</th>
            <th>Duration</th>
          </tr>
        </thead>
        <tbody>
          {plays.map((play, index) => (
            <tr key={play.id || index}>
              <td>{formatTimeOfDay(play.played_at || play.started_at || play.timestamp)}</td>
              <td>
                <span className={`badge badge-${play.type === 'track' || play.item_type === 'track' ? 'track' : 'break'}`}>
                  {play.type || play.item_type}
                </span>
              </td>
              <td>{play.title || 'Untitled'}</td>
              <td>{formatDuration(play.duration)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function JobList({ jobs }) {
  if (jobs.length === 0) {
    return <p style={{ ...mutedText, margin: 0 }}>No active problems</p>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {jobs.map(job => (
        <div key={job.id} style={{ border: '1px solid #1e1e3a', borderRadius: 6, padding: '0.7rem', background: '#090915' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <strong style={{ color: '#f5f7fb', fontSize: '0.85rem' }}>{job.job_type}</strong>
            <span style={{ color: job.status === 'failed' ? '#ff6b6b' : '#4a9eff', fontSize: '0.8rem', fontWeight: 700 }}>
              {job.status}
            </span>
          </div>
          <div style={{ ...mutedText, marginTop: 4 }}>
            {job.provider || job.capability || 'Provider'}
          </div>
          {job.error_message && (
            <div style={{ color: '#ffb3b3', fontSize: '0.78rem', marginTop: 6 }}>
              {job.error_message}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function Diagnostics({ timelineHealth, timelineItems, generationJobs }) {
  const issues = timelineHealth?.issues || []
  return (
    <div style={{ display: 'grid', gap: 14, marginTop: 14 }}>
      <div>
        <h4 style={{ margin: '0 0 8px', color: '#f5f7fb' }}>Timeline</h4>
        {issues.length === 0 ? (
          <p style={{ ...mutedText, margin: 0 }}>Timeline healthy</p>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {issues.map(issue => (
              <span key={issue.code} className="badge badge-inactive">
                {issue.count} {issue.message}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="table-container">
        <table className="table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Status</th>
              <th>Title</th>
              <th>Asset</th>
            </tr>
          </thead>
          <tbody>
            {timelineItems.slice(0, 8).map(item => (
              <tr key={item.id}>
                <td>{item.item_type}</td>
                <td>{item.status}</td>
                <td>{item.title || 'Untitled'}</td>
                <td>{item.asset?.normalized_filepath || '--'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="table-container">
        <table className="table">
          <thead>
            <tr>
              <th>Job</th>
              <th>Provider</th>
              <th>Status</th>
              <th>Output</th>
            </tr>
          </thead>
          <tbody>
            {generationJobs.slice(0, 8).map(job => (
              <tr key={job.id}>
                <td>{job.job_type}</td>
                <td>{job.provider || job.capability || '--'}</td>
                <td>{job.status}</td>
                <td>{job.output?.title || (job.output_asset_id ? `Asset ${job.output_asset_id}` : '--')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default Dashboard
