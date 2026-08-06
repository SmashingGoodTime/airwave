import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { completeSetup } from '../api'

const TIMEZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Anchorage',
  'America/Phoenix',
  'Pacific/Honolulu',
  'America/Toronto',
  'America/Vancouver',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Europe/Moscow',
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Asia/Kolkata',
  'Asia/Dubai',
  'Asia/Singapore',
  'Australia/Sydney',
  'Australia/Melbourne',
  'Pacific/Auckland',
  'America/Sao_Paulo',
  'Africa/Cairo',
  'Africa/Johannesburg',
  'UTC',
]

const STYLE_PRESETS = [
  {
    name: 'Lo-fi Chill',
    prompt: 'Relaxing lo-fi hip hop beats with mellow piano melodies, vinyl crackle, soft drums, and a cozy late-night study vibe',
  },
  {
    name: 'Classic Rock',
    prompt: 'Classic rock with driving electric guitars, powerful drums, catchy riffs, and anthemic energy inspired by the 70s and 80s',
  },
  {
    name: 'Jazz Lounge',
    prompt: 'Smooth jazz with warm saxophone, gentle piano, upright bass, and brushed drums, perfect for a late-night lounge atmosphere',
  },
  {
    name: 'Electronic Dance',
    prompt: 'Upbeat electronic dance music with pulsing synths, four-on-the-floor beats, energetic drops, and festival energy',
  },
  {
    name: 'Acoustic Cafe',
    prompt: 'Warm acoustic guitar with gentle fingerpicking, soft vocals, light percussion, and a cozy coffee shop feel',
  },
  {
    name: 'Ambient Focus',
    prompt: 'Ethereal ambient soundscapes with lush pads, subtle textures, gentle drones, and calming atmosphere for deep focus',
  },
]

const EXAMPLE_PERSONALITY = `You're a warm, friendly DJ with a laid-back vibe. You love discovering new music and sharing fun facts. You speak casually like you're talking to a friend — never stiff or formal. You occasionally make gentle jokes and always keep the energy positive. You like to comment on the mood of the music and what time of day it is.`

const TOTAL_STEPS = 5
const STEP_LABELS = ['Station', 'API Key', 'DJ Persona', 'Music', 'Launch']

function Setup({ onComplete }) {
  const navigate = useNavigate()
  const [step, setStep] = useState(1)
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [showKey, setShowKey] = useState(false)

  const [data, setData] = useState({
    station_name: '',
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/New_York',
    google_api_key: '',
    suno_api_key: '',
    fish_audio_api_key: '',
    dj_name: '',
    personality_prompt: '',
    content_policy: 'clean_vocals',
    styles: [{ name: '', prompt: '' }],
  })

  function updateField(field, value) {
    setData(prev => ({ ...prev, [field]: value }))
  }

  function updateStyle(index, field, value) {
    setData(prev => {
      const styles = [...prev.styles]
      styles[index] = { ...styles[index], [field]: value }
      return { ...prev, styles }
    })
  }

  function addStyle() {
    setData(prev => ({ ...prev, styles: [...prev.styles, { name: '', prompt: '' }] }))
  }

  function removeStyle(index) {
    if (data.styles.length <= 1) return
    setData(prev => ({ ...prev, styles: prev.styles.filter((_, i) => i !== index) }))
  }

  function addPreset(preset) {
    // Check if already added
    if (data.styles.some(s => s.name === preset.name)) return
    // Replace empty first slot or add new
    if (data.styles.length === 1 && !data.styles[0].name && !data.styles[0].prompt) {
      setData(prev => ({ ...prev, styles: [{ ...preset }] }))
    } else {
      setData(prev => ({ ...prev, styles: [...prev.styles, { ...preset }] }))
    }
  }

  function useExamplePersonality() {
    updateField('personality_prompt', EXAMPLE_PERSONALITY)
  }

  async function handleFinish() {
    setSubmitting(true)
    setError(null)
    const payload = {
      ...data,
      styles: data.styles.filter(s => s.name.trim() && s.prompt.trim()),
    }
    try {
      await completeSetup(payload)
      onComplete()
      navigate('/dashboard')
    } catch (err) {
      if (err.status === 409) {
        // Setup already completed elsewhere — treat as done.
        onComplete()
        navigate('/dashboard')
        return
      }
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  function canProceed() {
    switch (step) {
      case 1: return data.station_name.trim().length > 0
      case 2: return true
      case 3: return data.dj_name.trim().length > 0
      case 4: return data.styles.some(s => s.name.trim() && s.prompt.trim())
      case 5: return true
      default: return true
    }
  }

  function renderStepIndicator() {
    const items = []
    for (let i = 1; i <= TOTAL_STEPS; i++) {
      if (i > 1) {
        items.push(
          <div key={`c${i}`} className={`step-connector ${i <= step ? 'completed' : ''}`} />
        )
      }
      items.push(
        <div
          key={i}
          className={`step-dot ${i === step ? 'active' : i < step ? 'completed' : ''}`}
          title={STEP_LABELS[i - 1]}
        >
          {i < step ? '\u2713' : i}
        </div>
      )
    }
    return (
      <div style={{ marginBottom: 32 }}>
        <div className="step-indicator">{items}</div>
        <div style={{ textAlign: 'center', marginTop: 8, fontSize: 12, color: '#777' }}>
          Step {step} of {TOTAL_STEPS}: {STEP_LABELS[step - 1]}
        </div>
      </div>
    )
  }

  function renderStep() {
    switch (step) {
      case 1:
        return (
          <div>
            <h2>Welcome! Let's set up your radio station.</h2>
            <p className="step-description">
              Airwave creates an entire radio station powered by artificial intelligence.
              It generates original music, writes DJ scripts, and broadcasts everything
              as a continuous live stream. Let's get yours started.
            </p>
            <div className="form-group">
              <label>Station Name</label>
              <input
                type="text"
                value={data.station_name}
                onChange={e => updateField('station_name', e.target.value)}
                placeholder="e.g. Sunset Radio, The Chill Zone, KAIX FM"
                autoFocus
              />
              <div className="help-text">This is what listeners will see as your station's name.</div>
            </div>
            <div className="form-group">
              <label>Your Timezone</label>
              <select
                value={data.timezone}
                onChange={e => updateField('timezone', e.target.value)}
              >
                {(TIMEZONES.includes(data.timezone) ? TIMEZONES : [data.timezone, ...TIMEZONES]).map(tz => (
                  <option key={tz} value={tz}>{tz.replace(/_/g, ' ')}{tz === Intl.DateTimeFormat().resolvedOptions().timeZone ? ' (detected)' : ''}</option>
                ))}
              </select>
              <div className="help-text">
                Used for scheduling — so you can play different music at different times of day.
              </div>
            </div>
          </div>
        )

      case 2:
        return (
          <div>
            <h2>API Configuration</h2>
            <p className="step-description">
              Configure the API keys to power your automated radio station. You can enter them now or add them later in settings.
            </p>

            {/* Suno Key */}
            <div className="api-key-card" style={{ marginBottom: 16 }}>
              <div className="api-key-card-header">
                <label>Suno API Key (Music Generation)</label>
                <span className={`key-status ${data.suno_api_key ? 'configured' : 'skipped'}`}>
                  {data.suno_api_key ? '\u2713 Ready' : '\u2014 Not set'}
                </span>
              </div>
              <div className="api-key-description">
                Powers the AI music generator using Suno's V5 model.
              </div>
              <div className="api-key-input-row">
                <input
                  type={showKey ? 'text' : 'password'}
                  value={data.suno_api_key}
                  onChange={e => updateField('suno_api_key', e.target.value)}
                  placeholder="Paste your Suno API key here..."
                  autoFocus
                />
              </div>
              <a href="https://sunoapi.org/" target="_blank" rel="noopener noreferrer" className="api-key-link">
                Get a Suno API key &rarr;
              </a>
            </div>

            {/* Fish Audio Key */}
            <div className="api-key-card" style={{ marginBottom: 16 }}>
              <div className="api-key-card-header">
                <label>Fish Audio API Key (DJ Voice Synthesis)</label>
                <span className={`key-status ${data.fish_audio_api_key ? 'configured' : 'skipped'}`}>
                  {data.fish_audio_api_key ? '\u2713 Ready' : '\u2014 Not set'}
                </span>
              </div>
              <div className="api-key-description">
                Renders DJ breaks using premium, realistic voice models.
              </div>
              <div className="api-key-input-row">
                <input
                  type={showKey ? 'text' : 'password'}
                  value={data.fish_audio_api_key}
                  onChange={e => updateField('fish_audio_api_key', e.target.value)}
                  placeholder="Paste your Fish Audio API key here..."
                />
              </div>
              <a href="https://fish.audio/" target="_blank" rel="noopener noreferrer" className="api-key-link">
                Get a Fish Audio API key &rarr;
              </a>
            </div>

            {/* Google Gemini Key */}
            <div className="api-key-card" style={{ marginBottom: 16 }}>
              <div className="api-key-card-header">
                <label>Google Gemini API Key (DJ Scriptwriter)</label>
                <span className={`key-status ${data.google_api_key ? 'configured' : 'skipped'}`}>
                  {data.google_api_key ? '\u2713 Ready' : '\u2014 Not set'}
                </span>
              </div>
              <div className="api-key-description">
                Writes scripts and structures segments dynamically.
              </div>
              <div className="api-key-input-row">
                <input
                  type={showKey ? 'text' : 'password'}
                  value={data.google_api_key}
                  onChange={e => updateField('google_api_key', e.target.value)}
                  placeholder="Paste your Google AI API key here..."
                />
              </div>
              <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer" className="api-key-link">
                Get a Google AI API key &rarr;
              </a>
            </div>

            <button
              type="button"
              className="btn btn-secondary btn-sm"
              style={{ marginTop: 8 }}
              onClick={() => setShowKey(!showKey)}
            >
              {showKey ? 'Hide Keys' : 'Show Keys'}
            </button>
          </div>
        )

      case 3:
        return (
          <div>
            <h2>Create Your DJ Persona</h2>
            <p className="step-description">
              Your AI DJ has a name and personality that shapes how it talks to listeners.
              Have fun with this — you can always change it later!
            </p>
            <div className="form-group">
              <label>DJ Name</label>
              <input
                type="text"
                value={data.dj_name}
                onChange={e => updateField('dj_name', e.target.value)}
                placeholder="e.g. DJ Nova, Max Vibes, Luna Beats"
                autoFocus
              />
              <div className="help-text">The name your DJ will use on air.</div>
            </div>
            <div className="form-group">
              <label>Personality</label>
              <textarea
                value={data.personality_prompt}
                onChange={e => updateField('personality_prompt', e.target.value)}
                placeholder="Describe your DJ's personality: Are they energetic or chill? Funny or serious? Do they have catchphrases?"
                style={{ minHeight: 120 }}
              />
              <div className="help-text">
                This tells the AI how your DJ should talk. The more detail you give, the more unique your DJ will sound.
                {' '}
                <button type="button" className="example-link" onClick={useExamplePersonality}>
                  Use an example &rarr;
                </button>
              </div>
            </div>
            <div className="form-group">
              <label>Content Policy</label>
              <div className="policy-cards">
                <label className={`policy-card ${data.content_policy === 'instrumental_only' ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="setup_content_policy"
                    value="instrumental_only"
                    checked={data.content_policy === 'instrumental_only'}
                    onChange={e => updateField('content_policy', e.target.value)}
                  />
                  <div className="policy-card-content">
                    <div className="policy-card-label">Instrumental Only</div>
                    <div className="policy-card-desc">Music without any singing or lyrics. Great for focus, background music, or study streams.</div>
                  </div>
                </label>
                <label className={`policy-card ${data.content_policy === 'clean_vocals' ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="setup_content_policy"
                    value="clean_vocals"
                    checked={data.content_policy === 'clean_vocals'}
                    onChange={e => updateField('content_policy', e.target.value)}
                  />
                  <div className="policy-card-content">
                    <div className="policy-card-label">Clean Vocals</div>
                    <div className="policy-card-desc">Songs with singing, but nothing explicit. Safe for all audiences. This is the most popular option.</div>
                  </div>
                </label>
                <label className={`policy-card ${data.content_policy === 'no_restrictions' ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="setup_content_policy"
                    value="no_restrictions"
                    checked={data.content_policy === 'no_restrictions'}
                    onChange={e => updateField('content_policy', e.target.value)}
                  />
                  <div className="policy-card-content">
                    <div className="policy-card-label">No Restrictions</div>
                    <div className="policy-card-desc">No content filtering applied to music generation. May include explicit lyrics.</div>
                  </div>
                </label>
              </div>
            </div>
          </div>
        )

      case 4:
        return (
          <div>
            <h2>Choose Your Music Styles</h2>
            <p className="step-description">
              Styles tell the AI what kind of music to create. Your station will randomly pick
              from these when generating new songs. Add at least one — you can always add more later.
            </p>

            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 500, color: '#a0a0b8', marginBottom: 8 }}>
                Quick Add — click to add a preset:
              </div>
              <div className="preset-chips">
                {STYLE_PRESETS.map(preset => {
                  const isAdded = data.styles.some(s => s.name === preset.name)
                  return (
                    <button
                      key={preset.name}
                      type="button"
                      className="preset-chip"
                      style={isAdded ? { opacity: 0.4, cursor: 'default' } : {}}
                      onClick={() => !isAdded && addPreset(preset)}
                      disabled={isAdded}
                    >
                      {isAdded ? '\u2713 ' : '+ '}{preset.name}
                    </button>
                  )
                })}
              </div>
            </div>

            {data.styles.map((style, i) => (
              <div key={i} className="card" style={{ marginBottom: 12, padding: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#a0a0b8' }}>Style {i + 1}</span>
                  {data.styles.length > 1 && (
                    <button type="button" className="btn btn-sm btn-danger" onClick={() => removeStyle(i)}>Remove</button>
                  )}
                </div>
                <div className="form-group">
                  <label>Name</label>
                  <input
                    type="text"
                    value={style.name}
                    onChange={e => updateStyle(i, 'name', e.target.value)}
                    placeholder="e.g. Chill Vibes, Morning Energy, Late Night Jazz"
                  />
                </div>
                <div className="form-group">
                  <label>Description for the AI</label>
                  <textarea
                    value={style.prompt}
                    onChange={e => updateStyle(i, 'prompt', e.target.value)}
                    placeholder="Describe the music in detail: genre, instruments, mood, tempo, and vibe. The more specific you are, the better the results."
                    style={{ minHeight: 80 }}
                  />
                  <div className="help-text">
                    Tip: Be descriptive! Instead of "rock music", try "upbeat classic rock with driving guitar riffs, powerful drums, and anthemic energy".
                  </div>
                </div>
              </div>
            ))}
            <button type="button" className="btn btn-secondary" onClick={addStyle}>+ Add Another Style</button>
          </div>
        )

      case 5: {
        const validStyles = data.styles.filter(s => s.name.trim() && s.prompt.trim())
        return (
          <div>
            <h2>You're all set!</h2>
            <p className="step-description">
              Here's a summary of your station. Review everything below, then hit
              "Start Broadcasting" to launch.
            </p>

            <dl className="setup-review">
              <dt>Station Name</dt>
              <dd>{data.station_name || '(not set)'}</dd>
              <dt>Timezone</dt>
              <dd>{data.timezone.replace(/_/g, ' ')}</dd>
              <dt>DJ Name</dt>
              <dd>{data.dj_name || '(not set)'}</dd>
              <dt>Personality</dt>
              <dd style={{ maxHeight: 60, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {data.personality_prompt ? data.personality_prompt.substring(0, 150) + (data.personality_prompt.length > 150 ? '...' : '') : '(default)'}
              </dd>
              <dt>Content Policy</dt>
              <dd>{data.content_policy === 'instrumental_only' ? 'Instrumental Only' : data.content_policy === 'clean_vocals' ? 'Clean Vocals' : 'No Restrictions'}</dd>
              <dt>API Configurations</dt>
              <dd style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className={`key-status ${data.suno_api_key ? 'configured' : 'skipped'}`}>
                  {data.suno_api_key ? '\u2713 Suno (Music) configured' : '\u2014 Suno (Music) not set'}
                </span>
                <span className={`key-status ${data.fish_audio_api_key ? 'configured' : 'skipped'}`}>
                  {data.fish_audio_api_key ? '\u2713 Fish Audio (Voice) configured' : '\u2014 Fish Audio (Voice) not set'}
                </span>
                <span className={`key-status ${data.google_api_key ? 'configured' : 'skipped'}`}>
                  {data.google_api_key ? '\u2713 Google AI (Scripts) configured' : '\u2014 Google AI (Scripts) not set'}
                </span>
              </dd>
              <dt>Music Styles</dt>
              <dd>
                {validStyles.length > 0
                  ? validStyles.map(s => s.name).join(', ')
                  : '(none)'}
              </dd>
            </dl>

            {(!data.google_api_key || !data.suno_api_key || !data.fish_audio_api_key) && (
              <div className="info-callout" style={{ marginTop: 16 }}>
                <strong>Heads up:</strong> Some API keys are not set. The station will run, but missing features (music generation, scriptwriting, voice synthesis) will be unavailable until their keys are added in settings.
              </div>
            )}
          </div>
        )
      }

      default:
        return null
    }
  }

  return (
    <div className="setup-container">
      <div className="setup-header">
        <h1>Airwave</h1>
        <p>Your own AI-powered radio station in minutes.</p>
      </div>

      {renderStepIndicator()}

      {error && <div className="alert alert-error">{error}</div>}

      <div className="setup-card">
        {renderStep()}

        <div className="setup-nav">
          <div>
            {step > 1 && (
              <button className="btn" onClick={() => setStep(s => s - 1)}>Back</button>
            )}
          </div>
          <div>
            {step < TOTAL_STEPS ? (
              <button
                className="btn btn-primary"
                onClick={() => setStep(s => s + 1)}
                disabled={!canProceed()}
              >
                Next
              </button>
            ) : (
              <button
                className="btn btn-primary"
                onClick={handleFinish}
                disabled={submitting}
                style={{ padding: '10px 28px', fontSize: 15 }}
              >
                {submitting ? 'Starting...' : '\u{1F680} Start Broadcasting'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default Setup
