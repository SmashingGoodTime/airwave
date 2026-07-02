const BASE_URL = '/api'

async function apiFetch(path, options = {}) {
  const url = `${BASE_URL}${path}`
  const config = {
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  }

  if (config.body && typeof config.body === 'object' && !(config.body instanceof Blob)) {
    config.body = JSON.stringify(config.body)
  }

  const response = await fetch(url, config)

  if (!response.ok) {
    const errorBody = await response.text()
    let message
    try {
      const parsed = JSON.parse(errorBody)
      message = parsed.detail || parsed.message || errorBody
    } catch {
      message = errorBody
    }
    throw new Error(`API Error ${response.status}: ${message}`)
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
  return apiFetch('/setup/complete', { method: 'POST', body: data })
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

export function reorderStyles(data) {
  return apiFetch('/styles/reorder', { method: 'POST', body: data })
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

export function updateDJConfig(data) {
  return apiFetch('/dj/config', { method: 'PUT', body: data })
}

export function previewDJBreak(data) {
  return apiFetch('/dj/preview', { method: 'POST', body: data })
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

export function fetchActiveShow() {
  return apiFetch('/shows/active')
}

// Talk Show Configs
export function fetchTalkConfigs() {
  return apiFetch('/talk/configs')
}

export function createTalkConfig(data) {
  return apiFetch('/talk/configs', { method: 'POST', body: data })
}

export function updateTalkConfig(id, data) {
  return apiFetch(`/talk/configs/${id}`, { method: 'PUT', body: data })
}

export function deleteTalkConfig(id) {
  return apiFetch(`/talk/configs/${id}`, { method: 'DELETE' })
}

// Talk Topics
export function fetchTopics(configId) {
  return apiFetch(`/talk/configs/${configId}/topics`)
}

export function createTopic(data) {
  return apiFetch('/talk/topics', { method: 'POST', body: data })
}

export function updateTopic(id, data) {
  return apiFetch(`/talk/topics/${id}`, { method: 'PUT', body: data })
}

export function deleteTopic(id) {
  return apiFetch(`/talk/topics/${id}`, { method: 'DELETE' })
}

export function fetchTalkSegments() {
  return apiFetch('/talk/segments')
}

export function previewTalkSegment(data) {
  return apiFetch('/talk/preview', { method: 'POST', body: data })
}

// Providers
export function fetchProviders() {
  return apiFetch('/providers')
}

export function updateProviders(data) {
  return apiFetch('/providers', { method: 'PUT', body: data })
}

export function testProvider(providerName, data) {
  const options = { method: 'POST' }
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
