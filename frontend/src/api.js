const BASE_URL = '/api'
const DEFAULT_TIMEOUT_MS = 15000

async function apiFetch(path, options = {}) {
  const url = `${BASE_URL}${path}`
  const { timeout = DEFAULT_TIMEOUT_MS, ...rest } = options
  const config = {
    headers: {
      'Content-Type': 'application/json',
    },
    ...rest,
  }

  if (!config.signal && timeout > 0 && typeof AbortSignal.timeout === 'function') {
    config.signal = AbortSignal.timeout(timeout)
  }

  if (
    config.body !== undefined &&
    config.body !== null &&
    typeof config.body !== 'string' &&
    !(config.body instanceof Blob) &&
    !(config.body instanceof FormData)
  ) {
    config.body = JSON.stringify(config.body)
  }

  let response
  try {
    response = await fetch(url, config)
  } catch (err) {
    if (err.name === 'TimeoutError' || err.name === 'AbortError') {
      throw new Error(`Request timed out: ${path}`)
    }
    throw err
  }

  if (!response.ok) {
    const errorBody = await response.text()
    let message
    try {
      const parsed = JSON.parse(errorBody)
      message = parsed.detail || parsed.message || errorBody
    } catch {
      message = errorBody
    }
    const error = new Error(`API Error ${response.status}: ${message}`)
    error.status = response.status
    throw error
  }

  const contentType = response.headers.get('content-type')
  if (contentType && contentType.includes('application/json')) {
    return response.json()
  }
  return response
}

// Setup
export function fetchSetupStatus() {
  return apiFetch('/setup/status')
}

export function completeSetup(data) {
  return apiFetch('/setup/complete', { method: 'POST', body: data, timeout: 60000 })
}

// Styles
export function fetchStyles() {
  return apiFetch('/styles')
}

export function createStyle(data) {
  return apiFetch('/styles', { method: 'POST', body: data })
}

export function updateStyle(id, data) {
  return apiFetch(`/styles/${id}`, { method: 'PUT', body: data })
}

export function deleteStyle(id) {
  return apiFetch(`/styles/${id}`, { method: 'DELETE' })
}

export function toggleStyle(id) {
  return apiFetch(`/styles/${id}/toggle`, { method: 'POST' })
}

// Announcements
export function fetchAnnouncements(active) {
  const params = active !== undefined ? `?active=${active}` : ''
  return apiFetch(`/announcements${params}`)
}

export function createAnnouncement(data) {
  return apiFetch('/announcements', { method: 'POST', body: data })
}

export function updateAnnouncement(id, data) {
  return apiFetch(`/announcements/${id}`, { method: 'PUT', body: data })
}

export function deleteAnnouncement(id) {
  return apiFetch(`/announcements/${id}`, { method: 'DELETE' })
}

// DJ Config
export function fetchDJConfig() {
  return apiFetch('/dj/config')
}

export function previewDJBreak(data) {
  return apiFetch('/dj/preview', { method: 'POST', body: data, timeout: 120000 })
}

export function fetchVoices(provider) {
  const params = provider ? `?provider=${provider}` : ''
  return apiFetch(`/dj/voices${params}`)
}

export function fetchVoiceProviders() {
  return apiFetch('/dj/voice-providers')
}

// DJ Configs (multi-config CRUD)
export function fetchDJConfigs() {
  return apiFetch('/dj/configs')
}

export function createDJConfigEntry(data) {
  return apiFetch('/dj/configs', { method: 'POST', body: data })
}

export function updateDJConfigEntry(id, data) {
  return apiFetch(`/dj/configs/${id}`, { method: 'PUT', body: data })
}

export function deleteDJConfigEntry(id) {
  return apiFetch(`/dj/configs/${id}`, { method: 'DELETE' })
}

export function setDefaultDJConfig(id) {
  return apiFetch(`/dj/configs/${id}/set-default`, { method: 'POST' })
}

// Dashboard
export function fetchDashboardStatus() {
  return apiFetch('/dashboard/status')
}

export function fetchRecentPlays() {
  return apiFetch('/dashboard/recent')
}

export function fetchTimelineItems() {
  return apiFetch('/dashboard/timeline')
}

export function fetchTimelineHealth() {
  return apiFetch('/dashboard/timeline/health')
}

export function fetchGenerationJobs() {
  return apiFetch('/dashboard/jobs')
}

export function fetchHealth() {
  return apiFetch('/dashboard/health')
}

export function fetchTrackLyrics(trackId) {
  return apiFetch(`/dashboard/track/${trackId}/lyrics`)
}

export function fetchBreakScript(breakId) {
  return apiFetch(`/dashboard/break/${breakId}/script`)
}

// Play Log
export function fetchPlayLog(page = 1, perPage = 20, startDate, endDate) {
  let params = `?page=${page}&per_page=${perPage}`
  if (startDate) params += `&start_date=${startDate}`
  if (endDate) params += `&end_date=${endDate}`
  return apiFetch(`/playlog${params}`)
}

export async function exportPlayLog() {
  const response = await fetch(`${BASE_URL}/playlog/export`)
  if (!response.ok) {
    throw new Error(`Export failed: ${response.status}`)
  }
  return response.blob()
}

// Stream
export function fetchStreamUrl() {
  return apiFetch('/stream/url')
}

// Shows
export function fetchShows() {
  return apiFetch('/shows')
}

export function createShow(data) {
  return apiFetch('/shows', { method: 'POST', body: data })
}

export function updateShow(id, data) {
  return apiFetch(`/shows/${id}`, { method: 'PUT', body: data })
}

export function deleteShow(id) {
  return apiFetch(`/shows/${id}`, { method: 'DELETE' })
}

export function toggleShow(id) {
  return apiFetch(`/shows/${id}/toggle`, { method: 'POST' })
}

// Providers
export function fetchProviders() {
  return apiFetch('/providers')
}

export function updateProviders(data) {
  return apiFetch('/providers', { method: 'PUT', body: data })
}

export function testProvider(providerName, data) {
  const options = { method: 'POST', timeout: 60000 }
  if (data) options.body = data
  return apiFetch(`/providers/test/${providerName}`, options)
}

// Streaming Control
export function fetchStreamingStatus() {
  return apiFetch('/streaming/status')
}

export function startStreaming(data = {}) {
  return apiFetch('/streaming/start', { method: 'POST', body: data })
}

export function stopStreaming() {
  return apiFetch('/streaming/stop', { method: 'POST' })
}

export function switchStreamingMode(data = {}) {
  return apiFetch('/streaming/switch', { method: 'POST', body: data })
}

// Reorder Shows
export function reorderShows(showIds) {
  return apiFetch('/shows/reorder', { method: 'POST', body: { show_ids: showIds } })
}

// Recording
export function fetchRecordingStatus() {
  return apiFetch('/recording/status')
}

export function toggleRecording(enabled) {
  return apiFetch('/recording/toggle', { method: 'POST', body: { enabled } })
}

export function updateRecordingSettings(data) {
  return apiFetch('/recording/settings', { method: 'PUT', body: data })
}

export function fetchRecordings() {
  return apiFetch('/recording/list')
}

export function deleteRecording(filename) {
  return apiFetch(`/recording/${encodeURIComponent(filename)}`, { method: 'DELETE' })
}

export function getRecordingDownloadUrl(filename) {
  return `/api/recording/download/${encodeURIComponent(filename)}`
}
