import React from 'react'

export const VOICE_CATEGORY_ORDER = ['bright', 'warm', 'deep', 'radio', 'vintage', 'specialty', 'other']
export const VOICE_CATEGORY_LABELS = {
  bright: 'Bright & Energetic',
  warm: 'Warm & Smooth',
  deep: 'Deep & Rich',
  radio: 'Radio Host',
  vintage: 'Vintage Radio',
  specialty: 'Specialty',
  other: 'Other',
}

// Category-grouped voice dropdown with a sample play/stop button.
// Shared by DJConfig and TalkShowConfig so voice pickers look and
// behave identically everywhere.
function VoiceSelect({ value, onChange, label, voices, playingId, loadingSample, onPlaySample, loading = false }) {
  const groups = {}
  for (const v of voices) {
    const cat = v.category || 'other'
    if (!groups[cat]) groups[cat] = []
    groups[cat].push(v)
  }
  const allCats = Object.keys(groups)
  const order = [
    ...VOICE_CATEGORY_ORDER.filter(cat => groups[cat]),
    ...allCats.filter(cat => !VOICE_CATEGORY_ORDER.includes(cat)),
  ]

  return (
    <div className="form-group">
      {label && <label>{label}</label>}
      <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
        <select
          value={value}
          onChange={e => onChange(e.target.value)}
          disabled={loading}
          style={{ flex: 1 }}
        >
          <option value="">{loading ? 'Loading voices...' : 'Select a voice...'}</option>
          {order.map(cat => (
            <optgroup key={cat} label={VOICE_CATEGORY_LABELS[cat] || cat}>
              {groups[cat].map(v => (
                <option key={v.voice_id} value={v.voice_id}>{v.name}</option>
              ))}
            </optgroup>
          ))}
        </select>
        <button
          type="button"
          className="btn btn-secondary"
          style={{ padding: '0 16px', height: '40px', minWidth: '95px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}
          disabled={!value || loadingSample || loading}
          onClick={() => onPlaySample(value)}
        >
          {loadingSample ? (
            <span>Loading...</span>
          ) : playingId === value ? (
            <>
              <span style={{ fontSize: '10px' }}>■</span> Stop
            </>
          ) : (
            <>
              <span style={{ fontSize: '12px' }}>▶</span> Play
            </>
          )}
        </button>
      </div>
      {voices.length === 0 && !loading && (
        <div className="help-text">No voices loaded. Check your API key configuration.</div>
      )}
    </div>
  )
}

export default VoiceSelect
