import React, { useRef, useState, useEffect, useCallback } from 'react'

function AudioPlayer({ streamUrl, compact }) {
  const audioRef = useRef(null)
  const [status, setStatus] = useState('idle') // idle | loading | playing | error
  const statusRef = useRef('idle')
  const timeoutRef = useRef(null)

  const updateStatus = (val) => {
    statusRef.current = val
    setStatus(val)
  }

  const cleanup = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
  }, [])

  const handlePlay = useCallback(async () => {
    const audio = audioRef.current
    if (!audio) return

    cleanup()
    updateStatus('loading')

    // Timeout fallback for streams that hang without erroring
    timeoutRef.current = setTimeout(() => {
      if (statusRef.current === 'loading') {
        audio.pause()
        audio.removeAttribute('src')
        audio.load()
        updateStatus('error')
      }
    }, 8000)

    try {
      audio.src = streamUrl
      audio.load()
      await audio.play()
      cleanup()
      updateStatus('playing')

      // Monitor for stream dropping mid-playback
      audio.onended = () => updateStatus('error')
      audio.onerror = () => {
        if (statusRef.current === 'playing') {
          updateStatus('error')
        }
      }
    } catch (e) {
      cleanup()
      updateStatus('error')
    }
  }, [streamUrl, cleanup])

  const handleStop = useCallback(() => {
    cleanup()
    const audio = audioRef.current
    if (!audio) return
    audio.onended = null
    audio.onerror = null
    audio.pause()
    audio.removeAttribute('src')
    audio.load()
    updateStatus('idle')
  }, [cleanup])

  useEffect(() => {
    return () => {
      cleanup()
      if (audioRef.current) {
        audioRef.current.pause()
      }
    }
  }, [cleanup])

  if (!streamUrl) {
    return (
      <div className="audio-player">
        <div className="audio-player-empty">No stream configured</div>
      </div>
    )
  }

  const isPlaying = status === 'playing'
  const isLoading = status === 'loading'
  const isError = status === 'error'

  const btnStyle = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    width: '100%',
    padding: compact ? '8px 12px' : '10px 16px',
    border: isPlaying ? '1px solid rgba(239, 68, 68, 0.3)' : 'none',
    borderRadius: 8,
    cursor: isLoading ? 'wait' : 'pointer',
    fontSize: compact ? 12 : 14,
    fontWeight: 600,
    transition: 'background 0.2s',
    background: isPlaying
      ? 'rgba(239, 68, 68, 0.15)'
      : 'linear-gradient(135deg, #6366f1, #8b5cf6)',
    color: isPlaying ? '#ef4444' : '#fff',
    opacity: isLoading ? 0.8 : 1,
  }

  return (
    <div className="audio-player">
      {compact && (
        <div style={{ fontSize: 11, color: '#a0a0b8', marginBottom: 6, fontWeight: 500 }}>Listen Live</div>
      )}
      <audio ref={audioRef} preload="none" />
      {isError && (
        <div style={{
          fontSize: compact ? 11 : 12,
          color: '#f59e0b',
          marginBottom: 8,
          padding: '6px 10px',
          background: 'rgba(245, 158, 11, 0.1)',
          borderRadius: 6,
          textAlign: 'center',
        }}>
          Stream unavailable — is a broadcast running?
        </div>
      )}
      <button
        onClick={isPlaying ? handleStop : handlePlay}
        disabled={isLoading}
        style={btnStyle}
      >
        {isLoading ? (
          <>
            <span style={{ display: 'inline-block', width: 14, height: 14, border: '2px solid rgba(255,255,255,0.3)', borderTopColor: '#fff', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
            Connecting...
          </>
        ) : isPlaying ? (
          <>&#9632; Stop</>
        ) : (
          <>&#9654; Play</>
        )}
      </button>
      {!compact && (
        <div style={{ marginTop: 8, fontSize: 12, color: '#a0a0b8', wordBreak: 'break-all' }}>
          Stream: {streamUrl}
        </div>
      )}
      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}

export default AudioPlayer
