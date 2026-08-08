import React, { useState, useEffect } from 'react'
import {
  fetchDJConfigs, createDJConfigEntry, updateDJConfigEntry, deleteDJConfigEntry,
  setDefaultDJConfig, previewDJBreak, fetchVoices, fetchVoiceProviders,
} from '../api'
import useVoiceSample from '../hooks/useVoiceSample'
import VoiceSelect from '../components/VoiceSelect'

const EXAMPLE_PERSONALITY = `You're a warm, friendly DJ with a laid-back vibe. You love discovering new music and sharing fun facts. You speak casually like you're talking to a friend — never stiff or formal. You occasionally make gentle jokes and always keep the energy positive. You like to comment on the mood of the music and what time of day it is.`

const EMPTY_CONFIG = {
  name: '',
  station_name: '',
  dj_name: '',
  personality_prompt: '',
  voice_provider: 'fish_audio',
  voice_id: '',
  voice_settings: '',
  break_frequency: 4,
  break_frequency_variance: 1,
  max_break_duration: 60,
  content_policy: 'clean_vocals',
  content_policy_suffix: '',
  mention_time: false,
}

function formatDuration(seconds) {
  if (seconds < 60) return `${seconds}s`
  const mins = Math.floor(seconds / 60)
  const rem = seconds % 60
  return rem ? `${mins}m ${rem}s` : `${mins}m`
}

function DJConfig() {
  const [configs, setConfigs] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [form, setForm] = useState({ ...EMPTY_CONFIG })
  const [voices, setVoices] = useState([])
  const [voiceProviders, setVoiceProviders] = useState([])
  const [loading, setLoading] = useState(true)
  const [voicesLoading, setVoicesLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)
  const [preview, setPreview] = useState(null)
  const [previewing, setPreviewing] = useState(false)
  const [showPolicySuffix, setShowPolicySuffix] = useState(false)
  const [isNew, setIsNew] = useState(false)
  const [activeVoiceProvider, setActiveVoiceProvider] = useState('fish_audio')

  const { playingId, loadingSample, playSample } = useVoiceSample({
    voices,
    provider: activeVoiceProvider,
    onError: (msg) => setError(msg),
  })

  async function loadVoices(provider = 'fish_audio') {
    setVoicesLoading(true)
    try {
      const data = await fetchVoices(provider)
      setVoices(Array.isArray(data) ? data : data?.voices || [])
    } catch {
      setVoices([])
    } finally {
      setVoicesLoading(false)
    }
  }

  async function load() {
    try {
      const [cfgs, providersData] = await Promise.allSettled([
        fetchDJConfigs(),
        fetchVoiceProviders(),
      ])
      let activeProvider = 'fish_audio'
      if (providersData.status === 'fulfilled') {
        const providers = providersData.value || []
        setVoiceProviders(providers)
        const active = providers.find(p => p.active)
        if (active) activeProvider = active.key
      }
      setActiveVoiceProvider(activeProvider)
      if (cfgs.status === 'fulfilled') {
        const list = cfgs.value || []
        setConfigs(list)
        // Select the default or first config
        if (list.length > 0 && selectedId === null) {
          const def = list.find(c => c.is_default) || list[0]
          selectConfig(def, activeProvider)
        }
      }
      await loadVoices(activeProvider)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  function selectConfig(cfg, defaultProvider) {
    setSelectedId(cfg.id)
    setIsNew(false)
    setForm({
      name: cfg.name || 'Default',
      station_name: cfg.station_name || '',
      dj_name: cfg.dj_name || '',
      personality_prompt: cfg.personality_prompt || '',
      voice_provider: cfg.voice_provider || defaultProvider || activeVoiceProvider,
      voice_id: cfg.voice_id || '',
      voice_settings: cfg.voice_settings || '',
      break_frequency: cfg.break_frequency ?? 4,
      break_frequency_variance: cfg.break_frequency_variance ?? 1,
      max_break_duration: cfg.max_break_duration ?? 60,
      content_policy: cfg.content_policy || 'clean_vocals',
      content_policy_suffix: cfg.content_policy_suffix || '',
      mention_time: cfg.mention_time ?? false,
    })
    setShowPolicySuffix(!!cfg.content_policy_suffix)
    setPreview(null)
    setError(null)
    setSuccess(null)
  }

  function handleNew() {
    setSelectedId(null)
    setIsNew(true)
    setForm({ ...EMPTY_CONFIG, voice_provider: activeVoiceProvider })
    setShowPolicySuffix(false)
    setPreview(null)
  }

  useEffect(() => { load() }, [])

  async function handleSave(e) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setSuccess(null)
    try {
      if (isNew) {
        const created = await createDJConfigEntry(form)
        setIsNew(false)
        setSelectedId(created.id)
        setSuccess('DJ config created.')
      } else {
        await updateDJConfigEntry(selectedId, form)
        setSuccess('DJ config saved.')
      }
      // Reload the list
      const list = await fetchDJConfigs()
      setConfigs(list)
      setTimeout(() => setSuccess(null), 3000)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!selectedId) return
    const cfg = configs.find(c => c.id === selectedId)
    if (cfg?.is_default) { setError('Cannot delete the default config.'); return }
    if (!confirm('Delete this DJ config?')) return
    try {
      await deleteDJConfigEntry(selectedId)
      const list = await fetchDJConfigs()
      setConfigs(list)
      if (list.length > 0) {
        selectConfig(list.find(c => c.is_default) || list[0])
      } else {
        handleNew()
      }
      setSuccess('Config deleted.')
      setTimeout(() => setSuccess(null), 3000)
    } catch (err) { setError(err.message) }
  }

  async function handleSetDefault() {
    if (!selectedId) return
    try {
      await setDefaultDJConfig(selectedId)
      const list = await fetchDJConfigs()
      setConfigs(list)
      setSuccess('Set as default.')
      setTimeout(() => setSuccess(null), 3000)
    } catch (err) { setError(err.message) }
  }

  async function handlePreview() {
    setPreviewing(true)
    setPreview(null)
    try {
      const data = await previewDJBreak()
      setPreview(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setPreviewing(false)
    }
  }

  function updateField(field, value) {
    setForm(prev => ({ ...prev, [field]: value }))
  }

  if (loading) {
    return <div className="loading-screen"><div className="loading-spinner" /><p>Loading DJ config...</p></div>
  }

  const currentIsDefault = configs.find(c => c.id === selectedId)?.is_default

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>DJ Configurations</h2>
          <p className="page-subtitle">
            Create multiple DJ personalities for different shows. The default config is used when no show-specific config is set.
          </p>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}<button className="error-dismiss" onClick={() => setError(null)}>&times;</button></div>}
      {success && <div className="alert alert-success">{success}</div>}

      <div className="dj-config-layout">
        {/* Sidebar */}
        <div className="dj-config-sidebar">
          <button className="btn btn-primary btn-block" onClick={handleNew} style={{ marginBottom: 12 }}>
            + New DJ Config
          </button>
          {configs.map(cfg => (
            <div
              key={cfg.id}
              className={`dj-config-item ${cfg.id === selectedId ? 'active' : ''}`}
              onClick={() => selectConfig(cfg)}
            >
              <div className="dj-config-item-name">
                {cfg.name || 'Unnamed'}
                {cfg.is_default && <span className="dj-default-badge">Default</span>}
              </div>
              <div className="dj-config-item-sub">{cfg.dj_name || 'No DJ name'}</div>
            </div>
          ))}
          {configs.length === 0 && !isNew && (
            <div className="dj-config-empty">No configs yet. Create one to get started.</div>
          )}
        </div>

        {/* Editor */}
        <div className="dj-config-editor">
          {(selectedId || isNew) ? (
            <form onSubmit={handleSave}>
              <div className="card" style={{ marginBottom: 20 }}>
                <div className="form-section">
                  <h3>{isNew ? 'New DJ Config' : 'Edit DJ Config'}</h3>
                  <div className="form-group">
                    <label>Config Name</label>
                    <input
                      type="text"
                      value={form.name}
                      onChange={e => updateField('name', e.target.value)}
                      placeholder="e.g. Morning DJ, Night Owl"
                      required
                    />
                    <div className="help-text">A label to identify this config (shown in Show Schedule dropdowns).</div>
                  </div>
                </div>

                <div className="form-section">
                  <h3>Station Identity</h3>
                  <div className="form-row">
                    <div className="form-group">
                      <label>Station Name</label>
                      <input
                        type="text"
                        value={form.station_name}
                        onChange={e => updateField('station_name', e.target.value)}
                        placeholder="My AI Radio Station"
                      />
                    </div>
                    <div className="form-group">
                      <label>DJ Name</label>
                      <input
                        type="text"
                        value={form.dj_name}
                        onChange={e => updateField('dj_name', e.target.value)}
                        placeholder="DJ Nova"
                      />
                    </div>
                  </div>
                </div>

                <div className="form-section">
                  <h3>DJ Personality</h3>
                  <div className="form-group">
                    <label>Personality Prompt</label>
                    <textarea
                      value={form.personality_prompt}
                      onChange={e => updateField('personality_prompt', e.target.value)}
                      placeholder="Describe your DJ's personality, speaking style, and tone..."
                      style={{ minHeight: 140 }}
                    />
                    <div className="help-text">
                      The more detail you give, the more unique your DJ will sound.
                      {' '}
                      {!form.personality_prompt && (
                        <button
                          type="button"
                          className="example-link"
                          onClick={() => updateField('personality_prompt', EXAMPLE_PERSONALITY)}
                        >
                          Use an example &rarr;
                        </button>
                      )}
                    </div>
                  </div>
                </div>

                <div className="form-section">
                  <h3>Voice</h3>

                  <VoiceSelect
                    label="DJ Voice"
                    value={form.voice_id}
                    onChange={value => updateField('voice_id', value)}
                    voices={voices}
                    loading={voicesLoading}
                    playingId={playingId}
                    loadingSample={loadingSample}
                    onPlaySample={playSample}
                  />
                </div>

                <div className="form-section">
                  <h3>Break Settings</h3>
                  <div className="form-row">
                    <div className="form-group">
                      <label>Break Frequency</label>
                      <div className="range-group">
                        <input
                          type="range"
                          min="1"
                          max="10"
                          value={form.break_frequency}
                          onChange={e => updateField('break_frequency', Number(e.target.value))}
                        />
                        <span className="range-value">{form.break_frequency}</span>
                      </div>
                      <div className="help-text">
                        DJ talks every {form.break_frequency} song{form.break_frequency !== 1 ? 's' : ''}.
                      </div>
                    </div>
                    <div className="form-group">
                      <label>Randomness</label>
                      <div className="range-group">
                        <input
                          type="range"
                          min="0"
                          max="3"
                          step="0.5"
                          value={form.break_frequency_variance}
                          onChange={e => updateField('break_frequency_variance', Number(e.target.value))}
                        />
                        <span className="range-value">{form.break_frequency_variance}</span>
                      </div>
                    </div>
                  </div>
                  <div className="form-group">
                    <label>Break Length</label>
                    <div className="range-group">
                      <input
                        type="range"
                        min="10"
                        max="180"
                        step="5"
                        value={form.max_break_duration}
                        onChange={e => updateField('max_break_duration', Number(e.target.value))}
                      />
                      <span className="range-value">{formatDuration(form.max_break_duration)}</span>
                    </div>
                    <div className="help-text">
                      How long the DJ talks for. Scripts target about{' '}
                      {Math.round(form.max_break_duration * 1.5)} words &mdash; roughly{' '}
                      {Math.round(form.max_break_duration * 0.6)}s of speech &mdash; and the writer is
                      told to stay under {formatDuration(form.max_break_duration)}.
                    </div>
                  </div>
                </div>

                <div className="form-section">
                  <h3>Content Policy</h3>
                  <div className="policy-cards">
                    {['instrumental_only', 'clean_vocals', 'no_restrictions'].map(p => (
                      <label key={p} className={`policy-card ${form.content_policy === p ? 'selected' : ''}`}>
                        <input
                          type="radio"
                          name="content_policy"
                          value={p}
                          checked={form.content_policy === p}
                          onChange={e => updateField('content_policy', e.target.value)}
                        />
                        <div className="policy-card-content">
                          <div className="policy-card-label">
                            {p === 'instrumental_only' ? 'Instrumental Only' : p === 'clean_vocals' ? 'Clean Vocals' : 'No Restrictions'}
                          </div>
                        </div>
                      </label>
                    ))}
                  </div>
                  <div style={{ marginTop: 12 }}>
                    <button
                      type="button"
                      className="collapsible-toggle"
                      onClick={() => setShowPolicySuffix(!showPolicySuffix)}
                    >
                      {showPolicySuffix ? '- Hide' : '+ Show'} advanced: custom policy text
                    </button>
                    {showPolicySuffix && (
                      <div className="form-group" style={{ marginTop: 8 }}>
                        <textarea
                          value={form.content_policy_suffix}
                          onChange={e => updateField('content_policy_suffix', e.target.value)}
                          placeholder="Custom instructions appended to every music generation prompt..."
                          style={{ minHeight: 80 }}
                        />
                      </div>
                    )}
                  </div>
                </div>

                <div className="form-section">
                  <h3>Options</h3>
                  <label className="checkbox-group">
                    <input
                      type="checkbox"
                      checked={form.mention_time}
                      onChange={e => updateField('mention_time', e.target.checked)}
                    />
                    DJ mentions the current time during breaks
                  </label>
                </div>
              </div>

              <div className="btn-group">
                <button type="submit" className="btn btn-primary" disabled={saving}>
                  {saving ? 'Saving...' : isNew ? 'Create Config' : 'Save Changes'}
                </button>
                {!isNew && (
                  <button type="button" className="btn btn-secondary" onClick={handlePreview} disabled={previewing}>
                    {previewing ? 'Generating...' : 'Preview DJ Break'}
                  </button>
                )}
                {!isNew && !currentIsDefault && (
                  <button type="button" className="btn btn-secondary" onClick={handleSetDefault}>
                    Set as Default
                  </button>
                )}
                {!isNew && !currentIsDefault && (
                  <button type="button" className="btn btn-danger" onClick={handleDelete}>
                    Delete
                  </button>
                )}
              </div>
            </form>
          ) : (
            <div className="dj-config-placeholder">
              <p>Select a config from the sidebar or create a new one.</p>
            </div>
          )}

          {preview && (
            <div className="card" style={{ marginTop: 20 }}>
              <div className="card-header">
                <h3>DJ Break Preview</h3>
              </div>
              <p className="section-help">This is a sample of what your DJ would say. It won't be broadcast.</p>
              <div className="preview-box">
                {preview.script || preview.text || JSON.stringify(preview, null, 2)}
              </div>
              {preview.audio_url && (
                <audio controls src={preview.audio_url} style={{ width: '100%', marginTop: 12 }} />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default DJConfig
