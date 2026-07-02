import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { getProviderDisplayStatus } from './providerStatus.js'

describe('getProviderDisplayStatus', () => {
  it('shows a successful unsaved candidate test as connected', () => {
    const status = getProviderDisplayStatus({
      savedKey: { is_configured: false },
      savedHealth: { status: 'unconfigured', healthy: false },
      typedKey: 'candidate-key',
      testResult: { healthy: true, status: 'healthy', testedCandidate: true },
    })

    assert.deepEqual(status, {
      tone: 'ok',
      label: 'Unsaved key connected',
    })
  })

  it('lets a manual saved-key test override stale saved health', () => {
    const status = getProviderDisplayStatus({
      savedKey: { is_configured: true },
      savedHealth: { status: 'error', healthy: false },
      typedKey: '',
      testResult: { healthy: true, status: 'healthy', testedCandidate: false },
    })

    assert.deepEqual(status, {
      tone: 'ok',
      label: 'Connected',
    })
  })

  it('keeps an untested typed key distinct from a connected key', () => {
    const status = getProviderDisplayStatus({
      savedKey: { is_configured: false },
      savedHealth: { status: 'unconfigured', healthy: false },
      typedKey: 'candidate-key',
      testResult: null,
    })

    assert.deepEqual(status, {
      tone: 'untested',
      label: 'Unsaved key ready to test',
    })
  })
})
