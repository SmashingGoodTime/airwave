import { useState, useEffect, useRef, useCallback } from 'react'
import { previewDJBreak } from '../api'

/**
 * Shared voice sample playback logic for voice pickers.
 *
 * Handles play/stop toggling, generating a sample via the DJ preview
 * endpoint when the voice has no sample_url, and safe cleanup on unmount.
 * Playing state is only set once playback actually starts.
 */
export default function useVoiceSample({ voices, provider = 'fish_audio', onError }) {
  const [playingId, setPlayingId] = useState(null)
  const [loadingSample, setLoadingSample] = useState(false)
  const audioRef = useRef(null)
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    setPlayingId(null)
  }, [])

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current = null
      }
    }
  }, [])

  const playSample = useCallback(async (voiceId) => {
    if (!voiceId) return
    if (playingId === voiceId && audioRef.current) {
      stop()
      return
    }
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }

    const voice = voices.find(v => v.voice_id === voiceId)
    let url = voice?.sample_url

    if (!url) {
      setLoadingSample(true)
      try {
        const res = await previewDJBreak({ voice_id: voiceId, voice_provider: provider })
        url = res.audio_url
      } catch (err) {
        if (onErrorRef.current) onErrorRef.current(`Failed to generate sample: ${err.message}`)
        return
      } finally {
        setLoadingSample(false)
      }
    }
    if (!url) return

    const audio = new Audio(url)
    audioRef.current = audio
    audio.onended = () => setPlayingId(null)
    audio.onerror = () => {
      setPlayingId(null)
      if (onErrorRef.current) onErrorRef.current('Error playing sample audio.')
    }
    try {
      await audio.play()
      setPlayingId(voiceId)
    } catch (err) {
      setPlayingId(null)
      if (onErrorRef.current) onErrorRef.current(`Could not play sample: ${err.message}`)
    }
  }, [voices, provider, playingId, stop])

  return { playingId, loadingSample, playSample, stopSample: stop }
}
