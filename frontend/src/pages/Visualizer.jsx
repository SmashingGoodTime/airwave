import React, { useRef, useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchStreamUrl, fetchDJConfig, fetchDashboardStatus, fetchTrackLyrics, fetchBreakScript } from '../api'
import { formatClock } from '../utils/format'

const VIZ_MODES = ['bars', 'circular', 'waveform']
const MODE_CYCLE_MS = 30000
const FFT_SIZE = 256
const SMOOTHING = 0.82

var DEMO_LYRICS = [
  'Neon lights are shining bright tonight',
  'The city hums a digital melody',
  'Waveforms dancing through the air',
  'Every beat a story waiting to be told',
  '',
  'Turn it up and let the signal flow',
  'Through the wires and the stereo',
  'This frequency is all we need',
  'A radio dream in the machine',
  '',
  'Signals crossing through the night',
  'Every station has a voice',
  'Broadcast love across the sky',
  'This is our sound, this is our choice',
].join('\n')

var DEMO_SCRIPT = "Hey there, beautiful people! You\'re locked in with Airwave, your nonstop source for fresh AI-generated beats. That last track was something special, wasn\'t it? We\'ve got plenty more coming your way. Stay tuned, stay groovy, and remember — the future sounds amazing."

const COLORS = {
  primary: '#e94560',
  accentAlt: '#8b5cf6',
  accent: '#6366f1',
  bg: '#0a0a1a',
}

function useAudioAnalyser(streamUrl) {
  const audioRef = useRef(null)
  const ctxRef = useRef(null)
  const analyserRef = useRef(null)
  const sourceRef = useRef(null)
  const [connected, setConnected] = useState(false)
  const [playing, setPlaying] = useState(false)

  const connect = useCallback(async () => {
    if (!streamUrl || connected) return

    // Never allocate a new AudioContext while a previous one is still open.
    if (ctxRef.current && ctxRef.current.state !== 'closed') {
      ctxRef.current.close().catch(() => {})
      ctxRef.current = null
      analyserRef.current = null
      sourceRef.current = null
    }

    try {
      const audio = new Audio()
      audio.crossOrigin = 'anonymous'
      audio.src = streamUrl
      audioRef.current = audio

      const ctx = new (window.AudioContext || window.webkitAudioContext)()
      ctxRef.current = ctx

      const analyser = ctx.createAnalyser()
      analyser.fftSize = FFT_SIZE
      analyser.smoothingTimeConstant = SMOOTHING
      analyserRef.current = analyser

      const source = ctx.createMediaElementSource(audio)
      source.connect(analyser)
      analyser.connect(ctx.destination)
      sourceRef.current = source

      await audio.play()
      setConnected(true)
      setPlaying(true)
    } catch (err) {
      console.warn('Audio analyser connection failed:', err.message)
      // Release the AudioContext created above before falling back.
      if (ctxRef.current && ctxRef.current.state !== 'closed') {
        ctxRef.current.close().catch(() => {})
      }
      ctxRef.current = null
      analyserRef.current = null
      sourceRef.current = null
      try {
        const audio = audioRef.current || new Audio()
        if (!audioRef.current) {
          audio.src = streamUrl
          audioRef.current = audio
        }
        await audio.play()
        setPlaying(true)
      } catch (e) {
        console.warn('Audio playback failed:', e.message)
      }
    }
  }, [streamUrl, connected])

  const disconnect = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.removeAttribute('src')
      audioRef.current.load()
      audioRef.current = null
    }
    if (ctxRef.current && ctxRef.current.state !== 'closed') {
      ctxRef.current.close().catch(() => {})
      ctxRef.current = null
    }
    analyserRef.current = null
    sourceRef.current = null
    setConnected(false)
    setPlaying(false)
  }, [])

  const getFrequencyData = useCallback(() => {
    if (!analyserRef.current) return null
    const data = new Uint8Array(analyserRef.current.frequencyBinCount)
    analyserRef.current.getByteFrequencyData(data)
    return data
  }, [])

  const getTimeDomainData = useCallback(() => {
    if (!analyserRef.current) return null
    const data = new Uint8Array(analyserRef.current.frequencyBinCount)
    analyserRef.current.getByteTimeDomainData(data)
    return data
  }, [])

  useEffect(() => {
    return () => disconnect()
  }, [disconnect])

  return { connect, disconnect, getFrequencyData, getTimeDomainData, connected, playing }
}

function generateSimulatedData(time, binCount) {
  binCount = binCount || 128
  const data = new Uint8Array(binCount)
  for (let i = 0; i < binCount; i++) {
    const freq = i / binCount
    const base = Math.sin(time * 0.002 + i * 0.1) * 40 + 60
    const pulse = Math.sin(time * 0.004) * 20
    const high = Math.max(0, 1 - freq * 2) * 80
    const mid = Math.exp(-Math.pow(freq - 0.3, 2) * 20) * 60
    data[i] = Math.max(0, Math.min(255, base + pulse + high + mid + Math.random() * 15))
  }
  return data
}

function drawBars(ctx, w, h, freqData) {
  const barCount = 64
  const gap = 3
  const barWidth = (w - gap * (barCount - 1)) / barCount
  const maxHeight = h * 0.75

  for (let i = 0; i < barCount; i++) {
    const dataIndex = Math.floor(Math.pow(i / barCount, 1.5) * freqData.length)
    const value = freqData[Math.min(dataIndex, freqData.length - 1)] / 255

    const barHeight = value * maxHeight + 2
    const x = i * (barWidth + gap)
    const y = h - barHeight

    const gradient = ctx.createLinearGradient(x, h, x, y)
    const t = i / barCount
    const r = Math.round(233 + (99 - 233) * t)
    const g = Math.round(69 + (102 - 69) * t)
    const b = Math.round(96 + (241 - 96) * t)
    gradient.addColorStop(0, 'rgba(' + r + ',' + g + ',' + b + ',0.9)')
    gradient.addColorStop(1, 'rgba(' + r + ',' + g + ',' + b + ',0.4)')

    ctx.fillStyle = gradient
    const radius = Math.min(barWidth / 2, 4)
    ctx.beginPath()
    ctx.moveTo(x + radius, y)
    ctx.lineTo(x + barWidth - radius, y)
    ctx.arcTo(x + barWidth, y, x + barWidth, y + radius, radius)
    ctx.lineTo(x + barWidth, h)
    ctx.lineTo(x, h)
    ctx.lineTo(x, y + radius)
    ctx.arcTo(x, y, x + radius, y, radius)
    ctx.closePath()
    ctx.fill()

    const reflGradient = ctx.createLinearGradient(x, h, x, h + barHeight * 0.3)
    reflGradient.addColorStop(0, 'rgba(' + r + ',' + g + ',' + b + ',0.15)')
    reflGradient.addColorStop(1, 'rgba(' + r + ',' + g + ',' + b + ',0)')
    ctx.fillStyle = reflGradient
    ctx.fillRect(x, h + 2, barWidth, barHeight * 0.3)
  }
}

function drawCircular(ctx, w, h, freqData, time) {
  const cx = w / 2
  const cy = h / 2
  const baseRadius = Math.min(w, h) * 0.2
  const maxBarLen = Math.min(w, h) * 0.22
  const barCount = 90
  const barWidth = 3

  const glowRadius = baseRadius + maxBarLen * 0.6
  const glow = ctx.createRadialGradient(cx, cy, baseRadius * 0.5, cx, cy, glowRadius)
  glow.addColorStop(0, 'rgba(233, 69, 96, 0.03)')
  glow.addColorStop(0.5, 'rgba(99, 102, 241, 0.02)')
  glow.addColorStop(1, 'rgba(99, 102, 241, 0)')
  ctx.fillStyle = glow
  ctx.fillRect(0, 0, w, h)

  ctx.beginPath()
  ctx.arc(cx, cy, baseRadius, 0, Math.PI * 2)
  ctx.strokeStyle = 'rgba(233, 69, 96, 0.2)'
  ctx.lineWidth = 1.5
  ctx.stroke()

  const rotation = time * 0.0003
  for (let i = 0; i < barCount; i++) {
    const dataIndex = Math.floor((i / barCount) * freqData.length)
    const value = freqData[Math.min(dataIndex, freqData.length - 1)] / 255
    const angle = (i / barCount) * Math.PI * 2 + rotation

    const barLen = value * maxBarLen + 4
    const x1 = cx + Math.cos(angle) * baseRadius
    const y1 = cy + Math.sin(angle) * baseRadius
    const x2 = cx + Math.cos(angle) * (baseRadius + barLen)
    const y2 = cy + Math.sin(angle) * (baseRadius + barLen)

    const t = i / barCount
    const r = Math.round(233 + (99 - 233) * t)
    const g = Math.round(69 + (102 - 69) * t)
    const b = Math.round(96 + (241 - 96) * t)

    ctx.beginPath()
    ctx.moveTo(x1, y1)
    ctx.lineTo(x2, y2)
    ctx.strokeStyle = 'rgba(' + r + ',' + g + ',' + b + ',' + (0.4 + value * 0.6) + ')'
    ctx.lineWidth = barWidth
    ctx.lineCap = 'round'
    ctx.stroke()
  }

  var sum = 0
  for (var k = 0; k < freqData.length; k++) sum += freqData[k]
  const avgLevel = sum / freqData.length / 255
  const pulseRadius = baseRadius * (0.85 + avgLevel * 0.15)
  const innerGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, pulseRadius)
  innerGlow.addColorStop(0, 'rgba(233, 69, 96, ' + (0.1 + avgLevel * 0.15) + ')')
  innerGlow.addColorStop(0.7, 'rgba(139, 92, 246, ' + (0.05 + avgLevel * 0.05) + ')')
  innerGlow.addColorStop(1, 'rgba(139, 92, 246, 0)')
  ctx.fillStyle = innerGlow
  ctx.beginPath()
  ctx.arc(cx, cy, pulseRadius, 0, Math.PI * 2)
  ctx.fill()
}

function drawWaveform(ctx, w, h, freqData, timeDomainData, time) {
  const midY = h / 2
  const amplitude = h * 0.3
  const points = timeDomainData || freqData
  const count = points.length

  ctx.beginPath()
  for (let i = 0; i < count; i++) {
    const x = (i / count) * w
    const val = timeDomainData
      ? (points[i] - 128) / 128
      : (points[i] / 255) * Math.sin(time * 0.002 + i * 0.05)
    const y = midY + val * amplitude
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  }
  const gradient = ctx.createLinearGradient(0, 0, w, 0)
  gradient.addColorStop(0, COLORS.primary)
  gradient.addColorStop(0.5, COLORS.accentAlt)
  gradient.addColorStop(1, COLORS.accent)
  ctx.strokeStyle = gradient
  ctx.lineWidth = 2.5
  ctx.stroke()

  ctx.beginPath()
  for (let i = 0; i < count; i++) {
    const x = (i / count) * w
    const val = timeDomainData
      ? (points[i] - 128) / 128
      : (points[i] / 255) * Math.sin(time * 0.002 + i * 0.05)
    const y = midY + val * amplitude
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  }
  ctx.strokeStyle = 'rgba(233, 69, 96, 0.15)'
  ctx.lineWidth = 8
  ctx.stroke()

  ctx.beginPath()
  ctx.moveTo(0, midY)
  for (let i = 0; i < count; i++) {
    const x = (i / count) * w
    const val = timeDomainData
      ? (points[i] - 128) / 128
      : (points[i] / 255) * Math.sin(time * 0.002 + i * 0.05)
    ctx.lineTo(x, midY + val * amplitude)
  }
  ctx.lineTo(w, midY)
  ctx.closePath()
  const fillGrad = ctx.createLinearGradient(0, midY - amplitude, 0, midY + amplitude)
  fillGrad.addColorStop(0, 'rgba(233, 69, 96, 0.08)')
  fillGrad.addColorStop(0.5, 'rgba(139, 92, 246, 0.03)')
  fillGrad.addColorStop(1, 'rgba(99, 102, 241, 0.08)')
  ctx.fillStyle = fillGrad
  ctx.fill()

  ctx.beginPath()
  ctx.moveTo(0, midY)
  ctx.lineTo(w, midY)
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)'
  ctx.lineWidth = 1
  ctx.stroke()
}

// Parse lyrics string into timed lines (simple line-by-line with even distribution)
function parseLyrics(lyricsText, duration) {
  if (!lyricsText || !duration) return []
  var lines = lyricsText.split('\n').filter(function(l) { return l.trim().length > 0 })
  if (lines.length === 0) return []
  var timePerLine = duration / lines.length
  return lines.map(function(line, i) {
    return { text: line.trim(), startTime: i * timePerLine, endTime: (i + 1) * timePerLine }
  })
}

function LyricsOverlay({ lyrics, elapsed, duration, visible }) {
  if (!visible || !lyrics) return null

  var lines = parseLyrics(lyrics, duration)
  if (lines.length === 0) return null

  // Find current line index
  var currentIndex = -1
  for (var i = 0; i < lines.length; i++) {
    if (elapsed >= lines[i].startTime && elapsed < lines[i].endTime) {
      currentIndex = i
      break
    }
  }

  // Show a window of lines around the current one
  var windowSize = 5
  var startIdx = Math.max(0, currentIndex - 2)
  var endIdx = Math.min(lines.length, startIdx + windowSize)
  if (endIdx - startIdx < windowSize) {
    startIdx = Math.max(0, endIdx - windowSize)
  }
  var visibleLines = lines.slice(startIdx, endIdx)

  return (
    <div className="viz-lyrics">
      <div className="viz-lyrics-label">{'\u266B'} LYRICS</div>
      <div className="viz-lyrics-lines">
        {visibleLines.map(function(line, i) {
          var globalIdx = startIdx + i
          var isCurrent = globalIdx === currentIndex
          var isPast = globalIdx < currentIndex
          return (
            <div
              key={globalIdx}
              className={'viz-lyrics-line' + (isCurrent ? ' current' : '') + (isPast ? ' past' : '')}
            >
              {line.text}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function DJTranscriptOverlay({ scriptText, visible }) {
  if (!visible || !scriptText) return null

  return (
    <div className="viz-transcript">
      <div className="viz-transcript-label">{'\uD83C\uDFA4'} DJ SPEAKING</div>
      <div className="viz-transcript-text">{scriptText}</div>
    </div>
  )
}

function NowPlayingOverlay({ trackInfo }) {
  if (!trackInfo) return null

  var title = trackInfo.title
  var style_name = trackInfo.style_name
  var elapsed = trackInfo.elapsed
  var duration = trackInfo.duration
  var progress = duration > 0 ? Math.min(elapsed / duration, 1) : 0

  return (
    <div className="viz-now-playing">
      <div className="viz-np-label">NOW PLAYING</div>
      <div className="viz-np-title">{title || 'Unknown Track'}</div>
      {style_name && <div className="viz-np-style">{style_name}</div>}
      <div className="viz-np-progress-track">
        <div className="viz-np-progress-fill" style={{ width: (progress * 100) + '%' }} />
      </div>
      <div className="viz-np-time">
        {formatClock(elapsed)} / {formatClock(duration)}
      </div>
    </div>
  )
}

function StationBranding({ stationName, djName }) {
  return (
    <div className="viz-branding">
      <div className="viz-brand-name">{stationName || 'Airwave'}</div>
      {djName && <div className="viz-brand-dj">with {djName}</div>}
      <div className="viz-brand-live">
        <span className="viz-live-dot" />
        LIVE
      </div>
    </div>
  )
}

function Visualizer() {
  const navigate = useNavigate()
  const canvasRef = useRef(null)
  const animRef = useRef(null)
  const [streamUrl, setStreamUrl] = useState(null)
  const [stationName, setStationName] = useState('')
  const [djName, setDjName] = useState('')
  const [trackInfo, setTrackInfo] = useState({
    title: 'Digital Horizons',
    style_name: 'Synthwave',
    elapsed: 0,
    duration: 210,
  })
  const [vizMode, setVizMode] = useState(0)
  const [showControls, setShowControls] = useState(true)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const controlsTimerRef = useRef(null)
  const wsRef = useRef(null)
  const wsClosedRef = useRef(false)

  // Lyrics and transcript state
  const [lyrics, setLyrics] = useState(DEMO_LYRICS)
  const [djScript, setDjScript] = useState(DEMO_SCRIPT)
  const [contentMode, setContentMode] = useState('track') // 'track' or 'break'
  const [hasLiveData, setHasLiveData] = useState(false)

  const { connect, disconnect, getFrequencyData, getTimeDomainData, connected, playing } = useAudioAnalyser(streamUrl)

  // Fetch initial data
  useEffect(() => {
    fetchStreamUrl()
      .then(function(data) { setStreamUrl(data && data.url ? data.url : null) })
      .catch(function() {})

    fetchDJConfig()
      .then(function(data) {
        if (data) {
          setStationName(data.station_name || '')
          setDjName(data.dj_name || '')
        }
      })
      .catch(function() {})

    fetchDashboardStatus()
      .then(function(data) {
        if (data && data.now_playing) {
          setTrackInfo({
            title: data.now_playing.title,
            style_name: data.now_playing.style_name,
            elapsed: data.now_playing.elapsed || 0,
            duration: data.now_playing.duration || 0,
          })
          setContentMode('track')
          // Fetch lyrics for currently playing track
          if (data.now_playing.id) {
            fetchTrackLyrics(data.now_playing.id)
              .then(function(d) { setLyrics(d.lyrics || '') })
              .catch(function() {})
          }
        }
      })
      .catch(function() {})
  }, [])

  // WebSocket for real-time track/break updates
  useEffect(() => {
    wsClosedRef.current = false
    var reconnectTimer = null

    function connectWs() {
      if (wsClosedRef.current) return
      try {
        var proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        var wsUrl = proto + '//' + window.location.host + '/api/dashboard/ws'
        var ws = new WebSocket(wsUrl)
        wsRef.current = ws

        ws.onmessage = function(e) {
          try {
            var msg = JSON.parse(e.data)

            if (msg.type === 'status.snapshot' && msg.data && msg.data.now_playing) {
              setHasLiveData(true)
              setTrackInfo({
                title: msg.data.now_playing.title,
                style_name: msg.data.now_playing.style_name,
                elapsed: msg.data.now_playing.elapsed || 0,
                duration: msg.data.now_playing.duration || 0,
              })
              setContentMode('track')
            }

            if (msg.type === 'track.started' && msg.data) {
              setHasLiveData(true)
              setTrackInfo({
                title: msg.data.title,
                style_name: msg.data.style_name,
                elapsed: 0,
                duration: msg.data.duration || 0,
              })
              setContentMode('track')
              setDjScript('')

              // Use lyrics from the event if provided, otherwise fetch
              if (msg.data.lyrics) {
                setLyrics(msg.data.lyrics)
              } else if (msg.data.track_id) {
                fetchTrackLyrics(msg.data.track_id)
                  .then(function(d) { setLyrics(d.lyrics || '') })
                  .catch(function() { setLyrics('') })
              } else {
                setLyrics('')
              }
            }

            if (msg.type === 'break.started' && msg.data) {
              setHasLiveData(true)
              setContentMode('break')
              setLyrics('')

              // Use script_text from the event if provided, otherwise fetch
              if (msg.data.script_text) {
                setDjScript(msg.data.script_text)
              } else if (msg.data.break_id) {
                fetchBreakScript(msg.data.break_id)
                  .then(function(d) { setDjScript(d.script_text || '') })
                  .catch(function() { setDjScript('') })
              }
            }

            if (msg.type === 'break.ended') {
              setContentMode('track')
              setDjScript('')
            }
          } catch (ex) { /* ignore parse errors */ }
        }

        ws.onclose = function() {
          if (!wsClosedRef.current) {
            reconnectTimer = setTimeout(connectWs, 5000)
          }
        }

        ws.onerror = function() {
          // Will trigger onclose
        }
      } catch (ex) {
        if (!wsClosedRef.current) {
          reconnectTimer = setTimeout(connectWs, 5000)
        }
      }
    }

    connectWs()
    return function() {
      wsClosedRef.current = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.onerror = null
        wsRef.current.close()
      }
    }
  }, [])

  // Elapsed time counter
  useEffect(() => {
    if (!trackInfo) return
    var id = setInterval(function() {
      setTrackInfo(function(prev) {
        return prev ? { title: prev.title, style_name: prev.style_name, elapsed: prev.elapsed + 1, duration: prev.duration } : null
      })
    }, 1000)
    return function() { clearInterval(id) }
  }, [trackInfo && trackInfo.title])

  // Demo mode: cycle between lyrics and DJ transcript when no live data
  useEffect(() => {
    if (hasLiveData) return
    var id = setInterval(function() {
      setContentMode(function(m) { return m === 'track' ? 'break' : 'track' })
    }, 20000) // Switch every 20s in demo
    return function() { clearInterval(id) }
  }, [hasLiveData])

  // Demo mode: reset the demo track whenever the cycle returns to 'track'
  useEffect(() => {
    if (hasLiveData) return
    if (contentMode === 'track') {
      setTrackInfo({ title: 'Digital Horizons', style_name: 'Synthwave', elapsed: 0, duration: 210 })
    }
  }, [hasLiveData, contentMode])

  // Auto-cycle visualization modes
  useEffect(() => {
    var id = setInterval(function() {
      setVizMode(function(m) { return (m + 1) % VIZ_MODES.length })
    }, MODE_CYCLE_MS)
    return function() { clearInterval(id) }
  }, [])

  // Hide controls after inactivity
  var resetControlsTimer = useCallback(function() {
    setShowControls(true)
    if (controlsTimerRef.current) clearTimeout(controlsTimerRef.current)
    controlsTimerRef.current = setTimeout(function() { setShowControls(false) }, 4000)
  }, [])

  useEffect(() => {
    resetControlsTimer()
    return function() {
      if (controlsTimerRef.current) clearTimeout(controlsTimerRef.current)
    }
  }, [resetControlsTimer])

  // Canvas rendering loop
  useEffect(() => {
    var canvas = canvasRef.current
    if (!canvas) return

    var ctx = canvas.getContext('2d')
    var running = true

    function render() {
      if (!running) return

      var dpr = window.devicePixelRatio || 1
      var w = canvas.clientWidth
      var h = canvas.clientHeight

      if (w === 0 || h === 0) {
        animRef.current = requestAnimationFrame(render)
        return
      }

      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr
        canvas.height = h * dpr
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      }

      ctx.fillStyle = COLORS.bg
      ctx.fillRect(0, 0, w, h)

      ctx.strokeStyle = 'rgba(255, 255, 255, 0.02)'
      ctx.lineWidth = 1
      var gridSize = 60
      for (var gx = gridSize; gx < w; gx += gridSize) {
        ctx.beginPath()
        ctx.moveTo(gx, 0)
        ctx.lineTo(gx, h)
        ctx.stroke()
      }
      for (var gy = gridSize; gy < h; gy += gridSize) {
        ctx.beginPath()
        ctx.moveTo(0, gy)
        ctx.lineTo(w, gy)
        ctx.stroke()
      }

      var now = performance.now()
      var freqData = getFrequencyData()
      var timeDomainData = getTimeDomainData()

      if (!freqData) {
        freqData = generateSimulatedData(now)
      }

      var mode = VIZ_MODES[vizMode]
      if (mode === 'bars') {
        drawBars(ctx, w, h, freqData)
      } else if (mode === 'circular') {
        drawCircular(ctx, w, h, freqData, now)
      } else if (mode === 'waveform') {
        drawWaveform(ctx, w, h, freqData, timeDomainData, now)
      }

      animRef.current = requestAnimationFrame(render)
    }

    render()
    return function() {
      running = false
      if (animRef.current) cancelAnimationFrame(animRef.current)
    }
  }, [vizMode, getFrequencyData, getTimeDomainData])

  // Fullscreen handling
  var toggleFullscreen = useCallback(function() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(function() {})
    } else {
      document.exitFullscreen().catch(function() {})
    }
  }, [])

  useEffect(() => {
    var handler = function() { setIsFullscreen(!!document.fullscreenElement) }
    document.addEventListener('fullscreenchange', handler)
    return function() { document.removeEventListener('fullscreenchange', handler) }
  }, [])

  // Keyboard shortcuts
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') {
        if (document.fullscreenElement) {
          document.exitFullscreen()
        } else {
          navigate('/dashboard')
        }
      } else if (e.key === 'f' || e.key === 'F') {
        toggleFullscreen()
      } else if (e.key === 'm' || e.key === 'M') {
        setVizMode(function(m) { return (m + 1) % VIZ_MODES.length })
      } else if (e.key === ' ') {
        e.preventDefault()
        if (playing) disconnect()
        else connect()
      }
      resetControlsTimer()
    }
    window.addEventListener('keydown', onKey)
    return function() { window.removeEventListener('keydown', onKey) }
  }, [navigate, toggleFullscreen, playing, connect, disconnect, resetControlsTimer])

  var elapsed = trackInfo ? trackInfo.elapsed : 0
  var duration = trackInfo ? trackInfo.duration : 0

  return (
    <div
      className="visualizer-page"
      onMouseMove={resetControlsTimer}
      onClick={resetControlsTimer}
    >
      <canvas ref={canvasRef} className="viz-canvas" />

      <StationBranding stationName={stationName} djName={djName} />
      <NowPlayingOverlay trackInfo={trackInfo} />

      {/* Lyrics overlay — right side, during tracks */}
      <LyricsOverlay
        lyrics={lyrics}
        elapsed={elapsed}
        duration={duration}
        visible={contentMode === 'track' && !!lyrics}
      />

      {/* DJ transcript overlay — right side, during breaks */}
      <DJTranscriptOverlay
        scriptText={djScript}
        visible={contentMode === 'break' && !!djScript}
      />

      <div className="viz-mode-indicator">
        {VIZ_MODES.map(function(mode, i) {
          return (
            <button
              key={mode}
              className={'viz-mode-dot' + (i === vizMode ? ' active' : '')}
              onClick={function() { setVizMode(i) }}
              title={mode}
            />
          )
        })}
      </div>

      <div className={'viz-controls' + (showControls ? ' visible' : '')}>
        <button className="viz-ctrl-btn" onClick={function() { navigate('/dashboard') }} title="Back to Dashboard">
          {'\u2190'} Back
        </button>
        <button
          className="viz-ctrl-btn"
          onClick={function() { if (playing) disconnect(); else connect(); }}
          title={playing ? 'Stop Audio' : 'Play Audio'}
        >
          {playing ? '\u25A0 Stop' : '\u25B6 Play'}
        </button>
        <button
          className="viz-ctrl-btn"
          onClick={function() { setVizMode(function(m) { return (m + 1) % VIZ_MODES.length }) }}
          title="Next Visualization (M)"
        >
          Mode: {VIZ_MODES[vizMode]}
        </button>
        <button className="viz-ctrl-btn" onClick={toggleFullscreen} title="Fullscreen (F)">
          {isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
        </button>
      </div>

      <div className={'viz-keyboard-hint' + (showControls ? ' visible' : '')}>
        Space: play/stop &nbsp;&middot;&nbsp; M: switch mode &nbsp;&middot;&nbsp; F: fullscreen &nbsp;&middot;&nbsp; Esc: back
      </div>
    </div>
  )
}

export default Visualizer
