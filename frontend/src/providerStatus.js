const ERROR_STATUSES = new Set(['error', 'unhealthy', 'circuit_open'])

export function getProviderDisplayStatus({
  savedKey = {},
  savedHealth = {},
  typedKey = '',
  testResult = null,
}) {
  const hasTypedKey = Boolean(typedKey.trim())

  if (testResult) {
    if (testResult.healthy || testResult.status === 'healthy') {
      return {
        tone: 'ok',
        label: testResult.testedCandidate ? 'Unsaved key connected' : 'Connected',
      }
    }

    if (testResult.status === 'circuit_open') {
      return { tone: 'error', label: 'Circuit open' }
    }

    return {
      tone: 'error',
      label: testResult.testedCandidate ? 'Unsaved key failed' : 'Needs attention',
    }
  }

  if (!savedKey.is_configured && !hasTypedKey) {
    return { tone: 'unconfigured', label: 'Not configured' }
  }

  if (!savedKey.is_configured && hasTypedKey) {
    return { tone: 'untested', label: 'Unsaved key ready to test' }
  }

  if (savedHealth.healthy || savedHealth.status === 'healthy') {
    return { tone: 'ok', label: 'Connected' }
  }

  if (savedHealth.status === 'circuit_open') {
    return { tone: 'error', label: 'Circuit open' }
  }

  if (ERROR_STATUSES.has(savedHealth.status)) {
    return { tone: 'error', label: 'Needs attention' }
  }

  return { tone: 'unconfigured', label: 'Untested' }
}
