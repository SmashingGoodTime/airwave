import React, { useState, useEffect } from 'react'
import { fetchTalkConfigs, createTalkConfig, updateTalkConfig, deleteTalkConfig, fetchTopics, createTopic, updateTopic, deleteTopic, fetchTalkSegments, previewTalkSegment, fetchVoices, startStreaming, fetchStreamingStatus, previewDJBreak } from '../api'

const STEP_LABELS = ['Basics', 'Voices', 'Style']

const DEFAULT_CONFIG = {
  name: '', host_voice_id: '', host_personality_prompt: '', cohost_voices: '[]',
  segment_min_duration: 120, segment_max_duration: 600, topic_rotation: 'weighted',
  max_speakers: 3, intro_style: '', outro_style: '', conversation_style: '',
}

const DEFAULT_COHOST = { name: '', voice_id: '', personality_prompt: '' }

const EXAMPLE_HOST_PERSONALITY = `You're the main host — confident, curious, and great at drawing out interesting points from your co-hosts. You keep the conversation moving and always bring it back when things go off-track. Warm but sharp.`

function TalkShowConfig() {
  const [configs, setConfigs] = useState([])
  const [selectedConfig, setSelectedConfig] = useState(null)
  const [topics, setTopics] = useState([])
  const [segments, setSegments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [voices, setVoices] = useState([])
  const [showTopicModal, setShowTopicModal] = useState(false)
  const [showScriptModal, setShowScriptModal] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [editingTopic, setEditingTopic] = useState(null)
  const [activeTab, setActiveTab] = useState('topics')

  // Creation/editing wizard state
  const [wizardOpen, setWizardOpen] = useState(false)
  const [wizardStep, setWizardStep] = useState(0)
  const [editingConfig, setEditingConfig] = useState(null)
  const [configForm, setConfigForm] = useState({ ...DEFAULT_CONFIG })
  const [cohosts, setCohosts] = useState([])

  const [streamingStatus, setStreamingStatus] = useState(null)
  const [startingBroadcast, setStartingBroadcast] = useState(false)

  const [topicForm, setTopicForm] = useState({
    title: '', prompt: '', topic_type: 'conversation', weight: 1, max_plays: '', notes: '',
  })

  // Load data
  async function loadConfigs() {
    try {
      const data = await fetchTalkConfigs()
      setConfigs(Array.isArray(data) ? data : [])
      setError(null)
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }

  async function loadTopics(configId) {
    try {
      const data = await fetchTopics(configId)
      setTopics(Array.isArray(data) ? data : [])
    } catch (err) { setError(err.message) }
  }

  async function loadSegments() {
    try {
      const data = await fetchTalkSegments()
      setSegments(Array.isArray(data) ? data : [])
    } catch (err) { /* non-critical */ }
  }

  async function loadVoices() {
    try {
      const data = await fetchVoices('fish_audio')
      setVoices(Array.isArray(data) ? data : data?.voices || [])
    } catch (err) { /* voices may not be available yet */ }
  }

  async function loadStreamingStatus() {
    try {
      const data = await fetchStreamingStatus()
      setStreamingStatus(data)
    } catch { /* ignore */ }
  }

  async function handleStartBroadcast() {
    setStartingBroadcast(true)
    try {
      await startStreaming('talk')
      await loadStreamingStatus()
    } catch (err) { setError(err.message) }
    finally { setStartingBroadcast(false) }
  }

  useEffect(() => { loadConfigs(); loadSegments(); loadVoices(); loadStreamingStatus() }, [])
  useEffect(() => { if (selectedConfig) loadTopics(selectedConfig.id) }, [selectedConfig])

  // Voice helpers
  function voiceLabel(voiceId) {
    if (!voiceId) return 'None selected'
    const v = voices.find(v => v.voice_id === voiceId)
    return v ? v.name : voiceId
  }

  function VoiceSelect({ value, onChange, label }) {
    const [playingId, setPlayingId] = useState(null)
    const [audioElement, setAudioElement] = useState(null)
    const [loadingSample, setLoadingSample] = useState(false)

    useEffect(() => {
      return () => {
        if (audioElement) {
          audioElement.pause()
        }
      }
    }, [audioElement])

    const playSample = async (voiceId) => {
      if (!voiceId) return
      if (playingId === voiceId && audioElement) {
        audioElement.pause()
        setPlayingId(null)
        return
      }
      if (audioElement) {
        audioElement.pause()
      }
      const voice = voices.find(v => v.voice_id === voiceId)
      let url = voice?.sample_url

      if (!url) {
        setLoadingSample(true)
        try {
          const res = await previewDJBreak({ voice_id: voiceId, voice_provider: 'fish_audio' })
          url = res.audio_url
        } catch (err) {
          alert(`Failed to generate sample: ${err.message}`)
          setLoadingSample(false)
          return
        }
        setLoadingSample(false)
      }

      if (url) {
        const audio = new Audio(url)
        setAudioElement(audio)
        setPlayingId(voiceId)
        audio.play()
        audio.onended = () => setPlayingId(null)
        audio.onerror = () => {
          setPlayingId(null)
          alert("Error playing sample audio.")
        }
      }
    }

    const groups = {}
    for (const v of voices) {
      const cat = v.category || 'other'
      if (!groups[cat]) groups[cat] = []
      groups[cat].push(v)
    }
    const preferredOrder = ['bright', 'warm', 'deep', 'radio', 'vintage', 'specialty', 'other']
    const labels = { 
      bright: 'Bright & Energetic', 
      warm: 'Warm & Smooth', 
      deep: 'Deep & Rich', 
      radio: 'Radio Host', 
      vintage: 'Vintage Radio', 
      specialty: 'Specialty', 
      other: 'Other' 
    }
    const allCats = Object.keys(groups)
    const order = [...preferredOrder.filter(cat => groups[cat]), ...allCats.filter(cat => !preferredOrder.includes(cat))]

    return (
      <div className="form-group">
        {label && <label>{label}</label>}
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <select 
            value={value} 
            onChange={e => onChange(e.target.value)}
            style={{ flex: 1 }}
          >
            <option value="">Select a voice...</option>
            {order.map(cat => (
              <optgroup key={cat} label={labels[cat] || cat}>
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
            disabled={!value || loadingSample}
            onClick={() => playSample(value)}
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
        {voices.length === 0 && (
          <div className="help-text">No voices loaded. Check your API key configuration.</div>
        )}
      </div>
    )
  }

  // Wizard open/close
  function openCreateWizard() {
    setEditingConfig(null)
    setConfigForm({ ...DEFAULT_CONFIG })
    setCohosts([])
    setWizardStep(0)
    setWizardOpen(true)
  }

  function openEditWizard(config) {
    setEditingConfig(config)
    setConfigForm({
      name: config.name || '',
      host_voice_id: config.host_voice_id || '',
      host_personality_prompt: config.host_personality_prompt || '',
      cohost_voices: config.cohost_voices || '[]',
      segment_min_duration: config.segment_min_duration,
      segment_max_duration: config.segment_max_duration,
      topic_rotation: config.topic_rotation,
      max_speakers: config.max_speakers,
      intro_style: config.intro_style || '',
      outro_style: config.outro_style || '',
      conversation_style: config.conversation_style || '',
    })
    // Parse cohost_voices JSON into the array editor
    let parsed = []
    try {
      const raw = config.cohost_voices
      if (raw && typeof raw === 'string') parsed = JSON.parse(raw)
      else if (Array.isArray(raw)) parsed = raw
    } catch { /* ignore parse errors */ }
    setCohosts(Array.isArray(parsed) ? parsed : [])
    setWizardStep(0)
    setWizardOpen(true)
  }

  function closeWizard() {
    setWizardOpen(false)
    setEditingConfig(null)
  }

  // Cohost management
  function addCohost() {
    setCohosts([...cohosts, { ...DEFAULT_COHOST }])
  }

  function updateCohost(index, field, value) {
    const updated = [...cohosts]
    updated[index] = { ...updated[index], [field]: value }
    setCohosts(updated)
  }

  function removeCohost(index) {
    setCohosts(cohosts.filter((_, i) => i !== index))
  }

  // Form field updater
  function updateField(field, value) {
    setConfigForm(prev => ({ ...prev, [field]: value }))
  }

  function validateConfigForm() {
    const minDuration = Number(configForm.segment_min_duration)
    const maxDuration = Number(configForm.segment_max_duration)
    const maxSpeakers = Number(configForm.max_speakers)

    if (!configForm.name.trim()) return 'Talk show name is required.'
    if (!Number.isFinite(minDuration) || minDuration < 1 || minDuration > 7200) {
      return 'Minimum segment duration must be between 1 second and 2 hours.'
    }
    if (!Number.isFinite(maxDuration) || maxDuration < 1 || maxDuration > 7200) {
      return 'Maximum segment duration must be between 1 second and 2 hours.'
    }
    if (minDuration > maxDuration) {
      return 'Minimum segment duration cannot be longer than maximum segment duration.'
    }
    if (!Number.isFinite(maxSpeakers) || maxSpeakers < 1 || maxSpeakers > 8) {
      return 'Max speakers must be between 1 and 8.'
    }
    return null
  }

  function validateTopicForm() {
    const weight = Number(topicForm.weight)
    const maxPlays = topicForm.max_plays === '' ? null : Number(topicForm.max_plays)

    if (!topicForm.title.trim()) return 'Topic title is required.'
    if (!topicForm.prompt.trim()) return 'Topic prompt is required.'
    if (!Number.isFinite(weight) || weight <= 0) return 'Topic weight must be greater than 0.'
    if (maxPlays !== null && (!Number.isInteger(maxPlays) || maxPlays < 1)) {
      return 'Max plays must be a whole number greater than 0.'
    }
    return null
  }

  // Submit
  async function handleConfigSubmit() {
    const validationError = validateConfigForm()
    if (validationError) {
      setError(validationError)
      return
    }

    const payload = {
      ...configForm,
      segment_min_duration: parseInt(configForm.segment_min_duration),
      segment_max_duration: parseInt(configForm.segment_max_duration),
      max_speakers: parseInt(configForm.max_speakers),
      cohost_voices: JSON.stringify(cohosts.filter(c => c.name.trim())),
      intro_style: configForm.intro_style || null,
      outro_style: configForm.outro_style || null,
      conversation_style: configForm.conversation_style || null,
    }
    try {
      if (editingConfig) {
        await updateTalkConfig(editingConfig.id, payload)
      } else {
        await createTalkConfig(payload)
      }
      closeWizard()
      loadConfigs()
    } catch (err) { setError(err.message) }
  }

  // Topic handlers
  function openAddTopic() {
    setEditingTopic(null)
    setTopicForm({ title: '', prompt: '', topic_type: 'conversation', weight: 1, max_plays: '', notes: '' })
    setShowTopicModal(true)
  }

  function openEditTopic(topic) {
    setEditingTopic(topic)
    setTopicForm({ title: topic.title, prompt: topic.prompt, topic_type: topic.topic_type, weight: topic.weight, max_plays: topic.max_plays || '', notes: topic.notes || '' })
    setShowTopicModal(true)
  }

  async function handleTopicSubmit(e) {
    e.preventDefault()
    const validationError = validateTopicForm()
    if (validationError) {
      setError(validationError)
      return
    }

    const payload = { ...topicForm, talk_config_id: selectedConfig.id, weight: parseFloat(topicForm.weight), max_plays: topicForm.max_plays ? parseInt(topicForm.max_plays) : null }
    try {
      if (editingTopic) { await updateTopic(editingTopic.id, payload) }
      else { await createTopic(payload) }
      setShowTopicModal(false)
      loadTopics(selectedConfig.id)
    } catch (err) { setError(err.message) }
  }

  async function handleDeleteTopic(id) {
    if (!confirm('Delete this topic?')) return
    try { await deleteTopic(id); loadTopics(selectedConfig.id) } catch (err) { setError(err.message) }
  }

  async function handlePreview(topicId) {
    if (!selectedConfig) return
    setPreviewLoading(true)
    try {
      const result = await previewTalkSegment({ config_id: selectedConfig.id, topic_id: topicId || null })
      setShowScriptModal(result)
      loadSegments()
    } catch (err) { setError(`Preview failed: ${err.message}`) }
    finally { setPreviewLoading(false) }
  }

  function formatScript(scriptText, segmentType) {
    if (segmentType === 'monologue') return scriptText
    try {
      const lines = JSON.parse(scriptText)
      if (!Array.isArray(lines)) return scriptText
      return lines.map(l => {
        const pace = l.pace ? ` [${l.pace}]` : ''
        return `${l.speaker}${pace}: ${l.text}`
      }).join('\n\n')
    } catch { return scriptText }
  }

  function formatDuration(seconds) {
    if (!seconds) return '--'
    const m = Math.floor(seconds / 60)
    const s = Math.round(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  const typeBadge = (type) => {
    const colors = { monologue: '#4a9eff', conversation: '#66bb6a', debate: '#ff6b6b', interview: '#ffa94d' }
    return <span style={{ background: colors[type] || '#888', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 500 }}>{type}</span>
  }

  const statusBadge = (status) => {
    const colors = { ready: '#66bb6a', generating: '#ffa94d', played: '#888', playing: '#4a9eff', failed: '#ff6b6b' }
    return <span style={{ background: colors[status] || '#888', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>{status}</span>
  }

  if (loading) return <div className="loading-screen"><div className="loading-spinner" /><p>Loading talk show configs...</p></div>

  // ---- WIZARD VIEW ----
  if (wizardOpen) {
    return (
      <div className="page" style={{ maxWidth: 700 }}>
        <div className="page-header">
          <h2>{editingConfig ? `Edit: ${editingConfig.name}` : 'Create Talk Show'}</h2>
          <button className="btn" onClick={closeWizard}>Cancel</button>
        </div>

        {error && <div className="alert alert-error">{error}<button className="btn btn-sm" onClick={() => setError(null)} style={{ marginLeft: '1rem' }}>Dismiss</button></div>}

        {/* Step Indicator */}
        <div className="step-indicator" style={{ marginBottom: 28 }}>
          {STEP_LABELS.map((label, i) => (
            <React.Fragment key={i}>
              {i > 0 && <div className={`step-connector ${i <= wizardStep ? 'completed' : ''}`} />}
              <div
                className={`step-dot ${i === wizardStep ? 'active' : i < wizardStep ? 'completed' : ''}`}
                onClick={() => setWizardStep(i)}
                style={{ cursor: 'pointer' }}
                title={label}
              >
                {i < wizardStep ? '\u2713' : i + 1}
              </div>
            </React.Fragment>
          ))}
        </div>
        <div style={{ textAlign: 'center', marginBottom: 24, color: '#a0a0b8', fontSize: 13 }}>
          Step {wizardStep + 1}: {STEP_LABELS[wizardStep]}
        </div>

        <div className="card" style={{ padding: 28 }}>
          {/* STEP 0: Basics */}
          {wizardStep === 0 && (
            <>
              <div className="form-section">
                <h3>Show Identity</h3>
                <p className="section-help">Give your talk show a name and set how long segments should be.</p>
                <div className="form-group">
                  <label>Show Name</label>
                  <input
                    type="text"
                    value={configForm.name}
                    onChange={e => updateField('name', e.target.value)}
                    placeholder="Morning Hot Takes, Late Night Deep Dives..."
                  />
                  <div className="help-text">This is how the show appears in your schedule.</div>
                </div>
              </div>

              <div className="form-section">
                <h3>Segment Timing</h3>
                <p className="section-help">How long should each generated talk segment be?</p>
                <div className="form-row">
                  <div className="form-group">
                    <label>Minimum Duration</label>
                    <div className="range-group">
                      <input
                        type="range" min="1" max="7200" step="30"
                        value={configForm.segment_min_duration}
                        onChange={e => updateField('segment_min_duration', Number(e.target.value))}
                      />
                      <span className="range-value">{formatDuration(configForm.segment_min_duration)}</span>
                    </div>
                  </div>
                  <div className="form-group">
                    <label>Maximum Duration</label>
                    <div className="range-group">
                      <input
                        type="range" min="1" max="7200" step="30"
                        value={configForm.segment_max_duration}
                        onChange={e => updateField('segment_max_duration', Number(e.target.value))}
                      />
                      <span className="range-value">{formatDuration(configForm.segment_max_duration)}</span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="form-section" style={{ borderBottom: 'none' }}>
                <h3>Topic Rotation</h3>
                <p className="section-help">How should topics be picked when generating new segments?</p>
                <div className="policy-cards">
                  {[
                    { value: 'weighted', label: 'Weighted', desc: 'Topics with higher weight come up more often. Good for mixing frequent and rare topics.' },
                    { value: 'sequential', label: 'Sequential', desc: 'Cycle through topics in order. Predictable and evenly paced.' },
                    { value: 'random', label: 'Random', desc: 'Pure random selection. Every topic has equal chance each time.' },
                  ].map(opt => (
                    <label key={opt.value} className={`policy-card ${configForm.topic_rotation === opt.value ? 'selected' : ''}`}>
                      <input
                        type="radio" name="topic_rotation" value={opt.value}
                        checked={configForm.topic_rotation === opt.value}
                        onChange={e => updateField('topic_rotation', e.target.value)}
                      />
                      <div className="policy-card-content">
                        <div className="policy-card-label">{opt.label}</div>
                        <div className="policy-card-desc">{opt.desc}</div>
                      </div>
                    </label>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* STEP 1: Voices */}
          {wizardStep === 1 && (
            <>
              <div className="form-section">
                <h3>Host</h3>
                <p className="section-help">Your show's main voice. Every segment features the host.</p>
                <VoiceSelect
                  label="Host Voice"
                  value={configForm.host_voice_id}
                  onChange={v => updateField('host_voice_id', v)}
                />
                <div className="form-group">
                  <label>Host Personality</label>
                  <textarea
                    value={configForm.host_personality_prompt}
                    onChange={e => updateField('host_personality_prompt', e.target.value)}
                    placeholder="Describe the host's personality, speaking style, and tone..."
                    style={{ minHeight: 120 }}
                  />
                  <div className="help-text">
                    This shapes how the AI writes the host's dialogue.
                    {' '}
                    {!configForm.host_personality_prompt && (
                      <button
                        type="button"
                        className="example-link"
                        onClick={() => updateField('host_personality_prompt', EXAMPLE_HOST_PERSONALITY)}
                      >
                        Use an example &rarr;
                      </button>
                    )}
                  </div>
                </div>
              </div>

              <div className="form-section" style={{ borderBottom: 'none' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                  <div>
                    <h3 style={{ marginBottom: 4 }}>Co-hosts</h3>
                    <p className="section-help" style={{ margin: 0 }}>
                      Add voices for conversations, debates, and interviews. Leave empty for monologue-only shows.
                    </p>
                  </div>
                  <button type="button" className="btn btn-sm btn-primary" onClick={addCohost}>+ Add Co-host</button>
                </div>

                {cohosts.length === 0 && (
                  <div className="talk-empty-cohosts">
                    No co-hosts added. The show will use monologue-style segments only, or you can add co-hosts for conversations.
                  </div>
                )}

                {cohosts.map((cohost, i) => (
                  <div key={i} className="talk-cohost-card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: '#a0a0b8', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Co-host {i + 1}</span>
                      <button type="button" className="btn btn-sm btn-danger" onClick={() => removeCohost(i)}>Remove</button>
                    </div>
                    <div className="form-group">
                      <label>Name</label>
                      <input
                        type="text"
                        value={cohost.name}
                        onChange={e => updateCohost(i, 'name', e.target.value)}
                        placeholder="e.g. Roxy, Professor Dave..."
                      />
                    </div>
                    <VoiceSelect
                      label="Voice"
                      value={cohost.voice_id}
                      onChange={v => updateCohost(i, 'voice_id', v)}
                    />
                    <div className="form-group">
                      <label>Personality</label>
                      <textarea
                        value={cohost.personality_prompt}
                        onChange={e => updateCohost(i, 'personality_prompt', e.target.value)}
                        placeholder="Sarcastic, plays devil's advocate... or warm and supportive..."
                        style={{ minHeight: 80 }}
                      />
                    </div>
                  </div>
                ))}

                {cohosts.length > 0 && (
                  <div className="form-group" style={{ marginTop: 16 }}>
                    <label>Max Speakers per Segment</label>
                    <div className="range-group">
                      <input
                        type="range" min="2" max={Math.max(2, cohosts.length + 1)}
                        value={Math.min(configForm.max_speakers, cohosts.length + 1)}
                        onChange={e => updateField('max_speakers', Number(e.target.value))}
                      />
                      <span className="range-value">{Math.min(configForm.max_speakers, cohosts.length + 1)}</span>
                    </div>
                    <div className="help-text">
                      How many voices can appear in a single segment (including the host).
                    </div>
                  </div>
                )}
              </div>
            </>
          )}

          {/* STEP 2: Style */}
          {wizardStep === 2 && (
            <>
              <div className="form-section">
                <h3>Conversation Style</h3>
                <p className="section-help">Set the overall tone for how your hosts interact.</p>
                <div className="policy-cards">
                  {[
                    { value: '', label: 'Default', desc: 'Natural and balanced. The AI picks the best tone for each topic.' },
                    { value: 'comedic', label: 'Comedic', desc: 'Lighthearted, funny, lots of banter and jokes between hosts.' },
                    { value: 'intellectual', label: 'Intellectual', desc: 'Thoughtful analysis and deep dives. NPR/podcast vibes.' },
                    { value: 'casual', label: 'Casual', desc: 'Friends hanging out. Relaxed, tangents welcome, low-key energy.' },
                  ].map(opt => (
                    <label key={opt.value} className={`policy-card ${configForm.conversation_style === opt.value ? 'selected' : ''}`}>
                      <input
                        type="radio" name="conversation_style" value={opt.value}
                        checked={configForm.conversation_style === opt.value}
                        onChange={e => updateField('conversation_style', e.target.value)}
                      />
                      <div className="policy-card-content">
                        <div className="policy-card-label">{opt.label}</div>
                        <div className="policy-card-desc">{opt.desc}</div>
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              <div className="form-section" style={{ borderBottom: 'none' }}>
                <h3>Segment Flow</h3>
                <p className="section-help">How should segments open and close?</p>
                <div className="form-row">
                  <div className="form-group">
                    <label>Intro Style</label>
                    <select value={configForm.intro_style} onChange={e => updateField('intro_style', e.target.value)}>
                      <option value="">Default</option>
                      <option value="energetic">Energetic hook</option>
                      <option value="casual">Casual greeting</option>
                      <option value="dramatic">Dramatic teaser</option>
                      <option value="question">Provocative question</option>
                    </select>
                    <div className="help-text">How the AI kicks off each segment.</div>
                  </div>
                  <div className="form-group">
                    <label>Outro Style</label>
                    <select value={configForm.outro_style} onChange={e => updateField('outro_style', e.target.value)}>
                      <option value="">Default</option>
                      <option value="tease_next">Tease next topic</option>
                      <option value="recap">Quick recap</option>
                      <option value="cliffhanger">Cliffhanger</option>
                      <option value="callback">Callback to opening</option>
                    </select>
                    <div className="help-text">How each segment wraps up.</div>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Navigation buttons */}
        <div className="btn-group" style={{ marginTop: 20, justifyContent: 'space-between' }}>
          <button
            type="button"
            className="btn"
            onClick={() => setWizardStep(s => s - 1)}
            disabled={wizardStep === 0}
          >
            Back
          </button>
          <div style={{ display: 'flex', gap: 8 }}>
            {wizardStep < STEP_LABELS.length - 1 ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => setWizardStep(s => s + 1)}
                disabled={wizardStep === 0 && !configForm.name.trim()}
              >
                Next
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleConfigSubmit}
                disabled={!configForm.name.trim()}
              >
                {editingConfig ? 'Save Changes' : 'Create Show'}
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  // ---- MAIN LIST VIEW ----
  return (
    <div className="page">
      <div className="page-header">
        <h2>Talk Shows</h2>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {configs.length > 0 && (!streamingStatus?.streaming ? (
            <button
              className="btn"
              style={{ background: '#ff6b6b', color: '#fff', border: 'none' }}
              onClick={handleStartBroadcast}
              disabled={startingBroadcast}
            >
              {startingBroadcast ? 'Starting...' : 'Start Talk Broadcast'}
            </button>
          ) : streamingStatus?.show_type === 'talk' ? (
            <span style={{ padding: '0.5rem 1rem', background: 'rgba(255, 107, 107, 0.15)', color: '#ff6b6b', borderRadius: '6px', fontSize: '0.875rem', fontWeight: 500, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#ff6b6b', display: 'inline-block', animation: 'pulse 1.5s infinite' }} />
              Live
            </span>
          ) : null)}
          <button className="btn btn-primary" onClick={openCreateWizard}>New Talk Show</button>
        </div>
      </div>
      <p className="section-help" style={{ marginTop: -16, marginBottom: 20 }}>
        Configure AI-hosted talk shows with distinct hosts, co-hosts, and conversation styles.
      </p>
      {error && <div className="alert alert-error">{error}<button className="btn btn-sm" onClick={() => setError(null)} style={{ marginLeft: '1rem' }}>Dismiss</button></div>}

      {/* Config Cards */}
      <div className="card-grid">
        {configs.map(config => {
          const isSelected = selectedConfig?.id === config.id
          let cohostCount = 0
          try {
            const parsed = typeof config.cohost_voices === 'string' ? JSON.parse(config.cohost_voices) : config.cohost_voices
            cohostCount = Array.isArray(parsed) ? parsed.length : 0
          } catch { /* ignore */ }

          return (
            <div key={config.id} className={`card ${isSelected ? 'card-selected' : ''}`} onClick={() => setSelectedConfig(config)} style={{ cursor: 'pointer' }}>
              <div className="card-header"><h3>{config.name}</h3></div>
              <div className="card-body">
                <p><strong>Host voice:</strong> {voiceLabel(config.host_voice_id)}</p>
                <p><strong>Co-hosts:</strong> {cohostCount === 0 ? 'None (monologue)' : `${cohostCount} voice${cohostCount > 1 ? 's' : ''}`}</p>
                <p><strong>Duration:</strong> {formatDuration(config.segment_min_duration)} \u2013 {formatDuration(config.segment_max_duration)}</p>
                {config.conversation_style && <p><strong>Style:</strong> {config.conversation_style}</p>}
              </div>
              <div className="card-actions">
                <button className="btn btn-sm" onClick={(e) => { e.stopPropagation(); openEditWizard(config) }}>Edit</button>
                <button className="btn btn-sm btn-danger" onClick={async (e) => { e.stopPropagation(); if (confirm('Delete this talk show config?')) { await deleteTalkConfig(config.id); loadConfigs(); if (isSelected) setSelectedConfig(null) } }}>Delete</button>
              </div>
            </div>
          )
        })}
        {configs.length === 0 && <p className="empty-state">No talk shows configured yet. Create one to get started.</p>}
      </div>

      {/* Detail tabs for selected config */}
      {selectedConfig && (
        <div style={{ marginTop: '2rem' }}>
          <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', borderBottom: '2px solid #333' }}>
            <button
              className={`btn btn-sm ${activeTab === 'topics' ? 'btn-primary' : ''}`}
              onClick={() => setActiveTab('topics')}
              style={{ borderRadius: '4px 4px 0 0' }}
            >Topics</button>
            <button
              className={`btn btn-sm ${activeTab === 'segments' ? 'btn-primary' : ''}`}
              onClick={() => { setActiveTab('segments'); loadSegments() }}
              style={{ borderRadius: '4px 4px 0 0' }}
            >Recent Segments</button>
          </div>

          {/* Topics Tab */}
          {activeTab === 'topics' && (
            <>
              <div className="page-header">
                <h3>Topics for "{selectedConfig.name}"</h3>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <button className="btn btn-primary" onClick={openAddTopic}>Add Topic</button>
                  <button className="btn" onClick={() => handlePreview(null)} disabled={previewLoading}>
                    {previewLoading ? 'Generating...' : 'Preview Random'}
                  </button>
                </div>
              </div>
              <div className="card-grid">
                {topics.map(topic => (
                  <div key={topic.id} className={`card ${!topic.active ? 'card-inactive' : ''}`}>
                    <div className="card-header">
                      <h4>{topic.title}</h4>
                      {typeBadge(topic.topic_type)}
                    </div>
                    <div className="card-body">
                      <p className="text-muted" style={{ whiteSpace: 'pre-wrap' }}>{topic.prompt.length > 150 ? topic.prompt.substring(0, 150) + '...' : topic.prompt}</p>
                      <p><strong>Weight:</strong> {topic.weight} | <strong>Plays:</strong> {topic.play_count}{topic.max_plays ? `/${topic.max_plays}` : ''}</p>
                      {topic.notes && <p style={{ fontSize: '0.85rem', color: '#999' }}>{topic.notes}</p>}
                    </div>
                    <div className="card-actions">
                      <button className="btn btn-sm" onClick={() => handlePreview(topic.id)} disabled={previewLoading}>Preview</button>
                      <button className="btn btn-sm" onClick={() => openEditTopic(topic)}>Edit</button>
                      <button className="btn btn-sm btn-danger" onClick={() => handleDeleteTopic(topic.id)}>Delete</button>
                    </div>
                  </div>
                ))}
                {topics.length === 0 && <p className="empty-state">No topics yet. Add topics for the AI to discuss.</p>}
              </div>
            </>
          )}

          {/* Segments Tab */}
          {activeTab === 'segments' && (
            <>
              <div className="page-header">
                <h3>Recent Segments</h3>
                <button className="btn btn-sm" onClick={loadSegments}>Refresh</button>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {segments.map(seg => (
                  <div key={seg.id} className="card" style={{ cursor: 'pointer' }} onClick={() => seg.script_text && setShowScriptModal(seg)}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', padding: '0.75rem 1rem' }}>
                      {typeBadge(seg.segment_type)}
                      {statusBadge(seg.status)}
                      <span style={{ flex: 1 }}>{seg.speakers ? (Array.isArray(seg.speakers) ? seg.speakers : (() => { try { return JSON.parse(seg.speakers) } catch { return [seg.speakers] } })()).join(', ') : '--'}</span>
                      <span>{formatDuration(seg.duration)}</span>
                      <span style={{ fontSize: '0.85rem', color: '#999' }}>{new Date(seg.created_at).toLocaleString()}</span>
                    </div>
                  </div>
                ))}
                {segments.length === 0 && <p className="empty-state">No segments generated yet.</p>}
              </div>
            </>
          )}
        </div>
      )}

      {/* Topic Modal */}
      {showTopicModal && (
        <div className="modal-overlay" onClick={() => setShowTopicModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>{editingTopic ? 'Edit Topic' : 'Add Topic'}</h3>
            <form onSubmit={handleTopicSubmit}>
              <div className="form-group">
                <label>Title</label>
                <input value={topicForm.title} onChange={e => setTopicForm({...topicForm, title: e.target.value})} required />
              </div>
              <div className="form-group">
                <label>Prompt</label>
                <textarea value={topicForm.prompt} onChange={e => setTopicForm({...topicForm, prompt: e.target.value})} rows={4} required placeholder="What should the AI discuss? Be specific about angles, opinions, or key points to hit." />
              </div>
              <div className="form-group">
                <label>Type</label>
                <select value={topicForm.topic_type} onChange={e => setTopicForm({...topicForm, topic_type: e.target.value})}>
                  <option value="monologue">Monologue</option>
                  <option value="conversation">Conversation</option>
                  <option value="debate">Debate</option>
                  <option value="interview">Interview</option>
                </select>
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label>Weight</label>
                  <input type="number" min="0.1" step="0.1" value={topicForm.weight} onChange={e => setTopicForm({...topicForm, weight: e.target.value})} />
                </div>
                <div className="form-group">
                  <label>Max Plays</label>
                  <input type="number" min="1" step="1" value={topicForm.max_plays} onChange={e => setTopicForm({...topicForm, max_plays: e.target.value})} placeholder="Unlimited" />
                </div>
              </div>
              <div className="form-group">
                <label>Notes</label>
                <textarea value={topicForm.notes} onChange={e => setTopicForm({...topicForm, notes: e.target.value})} rows={2} placeholder="Key angles, context, or facts to weave in naturally" />
              </div>
              <div className="modal-actions">
                <button type="button" className="btn" onClick={() => setShowTopicModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary">{editingTopic ? 'Save' : 'Create'}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Script Viewer Modal */}
      {showScriptModal && (
        <div className="modal-overlay" onClick={() => setShowScriptModal(null)}>
          <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: '700px', maxHeight: '80vh' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3>
                {showScriptModal.segment_type ? typeBadge(showScriptModal.segment_type) : null}
                {' '}Segment Script
              </h3>
              <span style={{ color: '#999', fontSize: '0.9rem' }}>
                {formatDuration(showScriptModal.duration)}
                {showScriptModal.has_audio !== undefined && (showScriptModal.has_audio ? ' (audio ready)' : ' (text only)')}
              </span>
            </div>
            <pre style={{
              background: '#1a1a2e', padding: '1rem', borderRadius: '6px',
              whiteSpace: 'pre-wrap', wordWrap: 'break-word', maxHeight: '60vh',
              overflowY: 'auto', fontSize: '0.9rem', lineHeight: 1.6,
            }}>
              {formatScript(showScriptModal.script_text, showScriptModal.segment_type)}
            </pre>
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowScriptModal(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default TalkShowConfig
