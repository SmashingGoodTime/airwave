import React, { useState, useEffect, useRef } from 'react'
import { formatClock } from '../utils/format'

function NowPlaying({ track }) {
  const [elapsed, setElapsed] = useState(0)
  const intervalRef = useRef(null)

  useEffect(() => {
    if (!track) {
      setElapsed(0)
      return
    }

    if (track.started_at) {
      const startTime = new Date(track.started_at).getTime()
      const updateElapsed = () => {
        const now = Date.now()
        setElapsed(Math.floor((now - startTime) / 1000))
      }
      updateElapsed()
      intervalRef.current = setInterval(updateElapsed, 1000)
    } else if (track.elapsed !== undefined) {
      setElapsed(track.elapsed)
    }

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [track])

  if (!track) {
    return (
      <div className="now-playing">
        <div className="now-playing-empty">Nothing playing</div>
      </div>
    )
  }

  const duration = track.duration || 0
  const progress = duration > 0 ? Math.min((elapsed / duration) * 100, 100) : 0

  return (
    <div className="now-playing">
      <div className="now-playing-title">{track.title || 'Untitled'}</div>
      {track.style && <div className="now-playing-style">{track.style}</div>}
      <div className="progress-bar-container">
        <div className="progress-bar-fill" style={{ width: `${progress}%` }} />
      </div>
      <div className="progress-time">
        <span>{formatClock(elapsed)}</span>
        <span>{duration > 0 ? formatClock(duration) : '--:--'}</span>
      </div>
    </div>
  )
}

export default NowPlaying
