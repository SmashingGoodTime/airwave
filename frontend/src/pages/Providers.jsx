import React, { useState, useEffect } from 'react'
import { fetchProviders, updateProviders, testProvider } from '../api'
import { getProviderDisplayStatus } from '../providerStatus.js'

const PROVIDERS = [
  {
    type: 'music',
    envVar: 'SUNO_API_KEY',
    title: 'Suno',
    role: 'Music Generation',
    healthKey: 'music',
    inputPlaceholder: 'Paste a Suno API key...',
    configuredText: 'Suno key saved',
    missingText: 'Suno key missing',
    impact: 'Required for generating new songs and replenishing the music buffer.',
    href: 'https://sunoapi.org/',
    linkLabel: 'Visit SunoAPI.org',
  },
  {
    type: 'voice',
    envVar: 'FISH_AUDIO_API_KEY',
    title: 'Fish Audio',
    role: 'DJ Voice Synthesis',
    healthKey: 'voice',
    inputPlaceholder: 'Paste a Fish Audio API key...',
    configuredText: 'Fish Audio key saved',
    missingText: 'Fish Audio key missing',
    impact: 'Required for rendering DJ breaks and spoken segments.',
    href: 'https://fish.audio/',
    linkLabel: 'Visit Fish.Audio',
  },
  {
    type: 'scriptwriter',
    envVar: 'GOOGLE_API_KEY',
    title: 'Google Gemini',
    role: 'DJ Scriptwriter',
    healthKey: 'scriptwriter',
    inputPlaceholder: 'Paste a Google AI API key...',
    configuredText: 'Google AI key saved',
    missingText: 'Google AI key missing',
    impact: 'Required for writing DJ breaks and transitions.',
    href: 'https://aistudio.google.com/apikey',
    linkLabel: 'Get a Google AI API key',
  },
]

export default function Providers() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  const [keys, setKeys] = useState({ music: '', scriptwriter: '', voice: '' })
  const [maskedKeys, setMaskedKeys] = useState({})

  const [health, setHealth] = useState({})
  const [showKey, setShowKey] = useState(false)
  const [testingStatus, setTestingStatus] = useState({})
  const [testResults, setTestResults] = useState({})

  useEffect(() => {
    loadProviders()
  }, [])

  function setProviderKey(type, value) {
    setKeys(prev => ({ ...prev, [type]: value }))
    setTestResults(prev => {
      if (!prev[type]) return prev
      const copy = { ...prev }
      delete copy[type]
      return copy
    })
  }

  function providerStatus(provider) {
    return getProviderDisplayStatus({
      savedKey: maskedFor(provider),
      savedHealth: health[provider.healthKey] || { status: 'unconfigured', healthy: false },
      typedKey: keys[provider.type],
      testResult: testResults[provider.type] || null,
    })
  }

  function maskedFor(provider) {
    return maskedKeys[provider.envVar] || {}
  }

  function testButtonLabel(provider) {
    if (testingStatus[provider.type]) return 'Testing...'
    return keys[provider.type] ? 'Test Unsaved Key' : 'Test Saved Key'
  }

  async function loadProviders() {
    try {
      const data = await fetchProviders()
      setHealth(data.health || {})

      const loadedKeys = data.keys || []
      setMaskedKeys(Object.fromEntries(loadedKeys.map(k => [k.env_var, k])))
      setKeys({ music: '', scriptwriter: '', voice: '' })
      setTestResults({})
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleTest(provider) {
    const providerType = provider.type
    const candidateKey = keys[providerType].trim()
    setTestingStatus(prev => ({ ...prev, [providerType]: true }))
    setTestResults(prev => {
      const copy = { ...prev }
      delete copy[providerType]
      return copy
    })

    try {
      const result = await testProvider(
        providerType,
        candidateKey ? { api_key: candidateKey } : undefined
      )
      setTestResults(prev => ({
        ...prev,
        [providerType]: {
          healthy: result.healthy,
          status: result.status,
          testedCandidate: result.tested_candidate,
          error: result.healthy ? null : result.error || 'Connection failed',
        },
      }))
    } catch (err) {
      setTestResults(prev => ({
        ...prev,
        [providerType]: {
          healthy: false,
          status: 'error',
          testedCandidate: Boolean(candidateKey),
          error: err.message,
        },
      }))
    } finally {
      setTestingStatus(prev => ({ ...prev, [providerType]: false }))
    }
  }

  async function handleSave(e) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setSuccess(null)

    try {
      const payload = {}
      if (keys.scriptwriter.trim()) payload.google_api_key = keys.scriptwriter.trim()
      if (keys.music.trim()) payload.suno_api_key = keys.music.trim()
      if (keys.voice.trim()) payload.fish_audio_api_key = keys.voice.trim()

      await updateProviders(payload)
      setSuccess('API settings saved and providers reloaded.')
      setTimeout(() => setSuccess(null), 3000)
      await loadProviders()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  function renderProviderCard(provider) {
    const savedKey = maskedFor(provider)
    const status = providerStatus(provider)
    const result = testResults[provider.type]
    const typedKey = keys[provider.type]
    const canTest = Boolean(savedKey.is_configured || typedKey.trim())

    return (
      <div className="card provider-maintenance-card" key={provider.type}>
        <div className="card-header provider-card-header">
          <div>
            <h3>{provider.title}</h3>
            <p className="section-help">{provider.role}</p>
          </div>
          <div className="provider-status-stack">
            <span className={`health-dot ${status.tone}`} title={status.label} />
            <span className={`key-status ${savedKey.is_configured ? 'configured' : 'skipped'}`}>
              {savedKey.is_configured ? provider.configuredText : provider.missingText}
            </span>
            <span className={`provider-state provider-state-${status.tone}`}>
              {status.label}
            </span>
          </div>
        </div>

        <div className="provider-card-body">
          <p className="provider-impact">{provider.impact}</p>
          <div className="api-key-input-row">
            <input
              aria-label={`${provider.title} API key`}
              type={showKey ? 'text' : 'password'}
              value={typedKey}
              disabled={testingStatus[provider.type]}
              onChange={e => setProviderKey(provider.type, e.target.value)}
              placeholder={savedKey.masked_value
                ? `Current: ${savedKey.masked_value} - paste new key to replace`
                : provider.inputPlaceholder}
            />
            <button
              type="button"
              className="btn btn-secondary"
              disabled={testingStatus[provider.type] || !canTest}
              onClick={() => handleTest(provider)}
            >
              {testButtonLabel(provider)}
            </button>
          </div>

          {result && (
            <div className={`test-result ${result.healthy ? 'test-ok' : 'test-error'}`}>
              {result.healthy
                ? `${result.testedCandidate ? 'Unsaved key' : 'Saved key'} connected successfully`
                : `${result.testedCandidate ? 'Unsaved key' : 'Saved key'} failed: ${result.error}`}
            </div>
          )}

          <a href={provider.href} target="_blank" rel="noopener noreferrer" className="api-key-link">
            {provider.linkLabel} &rarr;
          </a>
        </div>
      </div>
    )
  }

  const isTestingAnyProvider = Object.values(testingStatus).some(Boolean)

  if (loading) {
    return (
      <div className="page-loading">
        <div className="loading-spinner" />
        <p>Loading API settings...</p>
      </div>
    )
  }

  return (
    <div className="providers-page">
      <div className="page-header">
        <h2>API Configurations</h2>
        <p className="section-help">
          Configure API credentials for Suno (Music), Fish Audio (Voice), and Google Gemini (Scripts). Leave input fields blank to preserve existing keys.
        </p>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {success && <div className="alert alert-success">{success}</div>}

      <form onSubmit={handleSave}>
        <div className="provider-card-list">
          {PROVIDERS.map(provider => renderProviderCard(provider))}
        </div>

        <div style={{ marginTop: 24, display: 'flex', gap: 12, alignItems: 'center' }}>
          <button type="submit" className="btn btn-primary" disabled={saving || isTestingAnyProvider}>
            {saving ? 'Saving...' : 'Save Configurations'}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setShowKey(!showKey)}
          >
            {showKey ? 'Hide Raw Keys' : 'Show Raw Keys'}
          </button>
        </div>

        <div className="info-callout" style={{ marginTop: 20 }}>
          Saving will update your .env file and reinitialize providers. The station broadcast stream will continue running during reinitialization.
        </div>
      </form>
    </div>
  )
}
