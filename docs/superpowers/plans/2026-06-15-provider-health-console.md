# Provider Health Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Providers page into an ongoing maintenance console where operators can diagnose provider readiness, test saved keys, test unsaved candidate keys, and understand feature impact.

**Architecture:** Keep concrete provider knowledge inside `server/providers/registry.py` by adding a capability-level health-test helper. Extend the existing provider test endpoint with an optional candidate key body while keeping no-body saved-key tests backward-compatible. Update the React Providers page around metadata-driven provider cards with per-card test state, persistent results, and clear impact text.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLAlchemy test harness, pytest async tests, React 18, Vite.

---

## File Structure

- Modify `server/providers/registry.py`: add a public async helper for testing a provider capability against a supplied config object without mutating the registry.
- Modify `server/routers/providers.py`: add request/response fields for candidate-key tests and route candidate checks through the registry helper.
- Modify `tests/test_providers.py`: add registry helper tests with mock provider definitions.
- Modify `tests/test_routers.py`: add provider endpoint tests for saved tests, candidate tests, unknown providers, and unconfigured providers.
- Modify `frontend/src/api.js`: allow `testProvider(providerName, data)` to send an optional JSON body.
- Modify `frontend/src/pages/Providers.jsx`: replace repetitive cards with metadata-driven provider maintenance cards.
- Modify `frontend/src/App.css`: add responsive styling for provider maintenance cards and status pills.

---

### Task 1: Add Registry Candidate Health Tests

**Files:**
- Modify: `tests/test_providers.py`
- Modify later: `server/providers/registry.py`

- [ ] **Step 1: Add focused test providers and registry helper tests**

Append these classes and tests near the existing `TestProviderRegistry` tests in `tests/test_providers.py`:

```python
class CandidateHealthyMusicProvider(MusicProvider):
    """Music provider that records the API key used for health checks."""

    seen_keys: list[str] = []

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.seen_keys.append(api_key)

    async def generate(self, prompt: str, duration: int = 180) -> dict:
        return {}

    async def check_status(self) -> bool:
        return self.api_key == "candidate-key"


class CandidateFailingMusicProvider(MusicProvider):
    """Music provider whose health check raises an exception."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def generate(self, prompt: str, duration: int = 180) -> dict:
        return {}

    async def check_status(self) -> bool:
        raise RuntimeError("candidate exploded")
```

Add these test methods inside `class TestProviderRegistry`:

```python
    @pytest.mark.asyncio
    async def test_check_capability_health_uses_candidate_config_without_registering(self):
        CandidateHealthyMusicProvider.seen_keys.clear()
        definitions = (
            ProviderDefinition(
                key="candidate_music",
                capability="music",
                display_name="Candidate Music",
                module_path="tests.test_providers",
                class_name="CandidateHealthyMusicProvider",
                required_env=("SUNO_API_KEY",),
                factory=lambda ctx: ctx.provider_cls(api_key=ctx.value("SUNO_API_KEY")),
            ),
        )
        registry = ProviderRegistry(definitions=definitions)

        class CandidateConfig:
            SUNO_API_KEY = "candidate-key"

        result = await registry.check_capability_health("music", CandidateConfig())

        assert result == {
            "provider": "candidate_music",
            "healthy": True,
            "status": "healthy",
            "error": None,
        }
        assert CandidateHealthyMusicProvider.seen_keys == ["candidate-key"]
        assert registry.get_music_provider() is None

    @pytest.mark.asyncio
    async def test_check_capability_health_reports_unconfigured_candidate(self):
        definitions = (
            ProviderDefinition(
                key="candidate_music",
                capability="music",
                display_name="Candidate Music",
                module_path="tests.test_providers",
                class_name="CandidateHealthyMusicProvider",
                required_env=("SUNO_API_KEY",),
                factory=lambda ctx: ctx.provider_cls(api_key=ctx.value("SUNO_API_KEY")),
            ),
        )
        registry = ProviderRegistry(definitions=definitions)

        class EmptyConfig:
            SUNO_API_KEY = ""

        result = await registry.check_capability_health("music", EmptyConfig())

        assert result == {
            "provider": None,
            "healthy": False,
            "status": "unconfigured",
            "error": "Provider is not configured",
        }

    @pytest.mark.asyncio
    async def test_check_capability_health_reports_unknown_capability(self):
        registry = ProviderRegistry()

        result = await registry.check_capability_health("weather", object())

        assert result == {
            "provider": "weather",
            "healthy": False,
            "status": "unknown_provider",
            "error": "Unknown provider type: weather",
        }

    @pytest.mark.asyncio
    async def test_check_capability_health_reports_exceptions(self):
        definitions = (
            ProviderDefinition(
                key="candidate_music",
                capability="music",
                display_name="Candidate Music",
                module_path="tests.test_providers",
                class_name="CandidateFailingMusicProvider",
                required_env=("SUNO_API_KEY",),
                factory=lambda ctx: ctx.provider_cls(api_key=ctx.value("SUNO_API_KEY")),
            ),
        )
        registry = ProviderRegistry(definitions=definitions)

        class CandidateConfig:
            SUNO_API_KEY = "candidate-key"

        result = await registry.check_capability_health("music", CandidateConfig())

        assert result == {
            "provider": "candidate_music",
            "healthy": False,
            "status": "error",
            "error": "candidate exploded",
        }
```

- [ ] **Step 2: Run the new registry tests and verify they fail**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_providers.py::TestProviderRegistry::test_check_capability_health_uses_candidate_config_without_registering tests\test_providers.py::TestProviderRegistry::test_check_capability_health_reports_unconfigured_candidate tests\test_providers.py::TestProviderRegistry::test_check_capability_health_reports_unknown_capability tests\test_providers.py::TestProviderRegistry::test_check_capability_health_reports_exceptions
```

Expected: FAIL with `AttributeError: 'ProviderRegistry' object has no attribute 'check_capability_health'`.

- [ ] **Step 3: Add the registry helper**

In `server/providers/registry.py`, add this public method to `class ProviderRegistry` after `initialize` and before `_reset_providers`:

```python
    async def check_capability_health(self, capability: str, config: object) -> dict:
        """Check one provider capability against a supplied config object.

        This constructs a temporary provider from the matching provider
        definition and does not register it on the singleton. It is used for
        testing candidate credentials before they are saved.
        """
        if capability not in CAPABILITIES:
            return {
                "provider": capability,
                "healthy": False,
                "status": "unknown_provider",
                "error": f"Unknown provider type: {capability}",
            }

        for definition in self._definitions:
            if definition.capability != capability:
                continue
            if not definition.is_configured(config):
                continue

            try:
                provider = definition.create(config)
                healthy = await provider.check_status()
            except Exception as exc:
                logger.warning(
                    "Candidate health check failed for %s provider %s: %s",
                    capability,
                    definition.display_name,
                    exc,
                )
                return {
                    "provider": definition.key,
                    "healthy": False,
                    "status": "error",
                    "error": str(exc),
                }

            return {
                "provider": definition.key,
                "healthy": healthy,
                "status": "healthy" if healthy else "unhealthy",
                "error": None if healthy else "Provider reported unhealthy",
            }

        return {
            "provider": None,
            "healthy": False,
            "status": "unconfigured",
            "error": "Provider is not configured",
        }
```

- [ ] **Step 4: Run the registry tests and verify they pass**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_providers.py::TestProviderRegistry::test_check_capability_health_uses_candidate_config_without_registering tests\test_providers.py::TestProviderRegistry::test_check_capability_health_reports_unconfigured_candidate tests\test_providers.py::TestProviderRegistry::test_check_capability_health_reports_unknown_capability tests\test_providers.py::TestProviderRegistry::test_check_capability_health_reports_exceptions
```

Expected: all selected tests PASS.

- [ ] **Step 5: Commit registry helper**

If this directory is a Git worktree, run:

```bash
git add server/providers/registry.py tests/test_providers.py
git commit -m "feat: add provider candidate health helper"
```

If `git status` reports this directory is not a repository, record that in the final handoff instead of committing.

---

### Task 2: Extend Provider Test Endpoint

**Files:**
- Modify: `server/routers/providers.py`
- Modify: `tests/test_routers.py`

- [ ] **Step 1: Add router tests for the new endpoint contract**

Add this test class in `tests/test_routers.py` before the Dashboard router section:

```python
# ---------------------------------------------------------------------------
# Providers router
# ---------------------------------------------------------------------------


class TestProvidersRouter:
    @pytest.mark.asyncio
    async def test_test_provider_unknown_provider(self, client: AsyncClient):
        resp = await client.post("/api/providers/test/weather")

        assert resp.status_code == 200
        assert resp.json() == {
            "provider": "weather",
            "healthy": False,
            "status": "unknown_provider",
            "tested_candidate": False,
            "error": "Unknown provider type: weather",
        }

    @pytest.mark.asyncio
    async def test_test_provider_unconfigured_saved_key(self, client: AsyncClient):
        resp = await client.post("/api/providers/test/music")

        assert resp.status_code == 200
        assert resp.json() == {
            "provider": "music",
            "healthy": False,
            "status": "unconfigured",
            "tested_candidate": False,
            "error": "Not configured",
        }

    @pytest.mark.asyncio
    async def test_test_provider_candidate_key_does_not_persist(
        self, client: AsyncClient, monkeypatch
    ):
        from server.providers.registry import ProviderRegistry
        import server.routers.providers as providers_router

        calls = []

        async def fake_check_capability_health(self, capability, config):
            calls.append((capability, config.SUNO_API_KEY))
            return {
                "provider": "suno",
                "healthy": True,
                "status": "healthy",
                "error": None,
            }

        monkeypatch.delenv("SUNO_API_KEY", raising=False)
        monkeypatch.setattr(
            ProviderRegistry,
            "check_capability_health",
            fake_check_capability_health,
        )
        monkeypatch.setattr(providers_router, "update_env_file", lambda values: calls.append(("persisted", values)))

        resp = await client.post(
            "/api/providers/test/music",
            json={"api_key": "candidate-key"},
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "provider": "suno",
            "healthy": True,
            "status": "healthy",
            "tested_candidate": True,
            "error": None,
        }
        assert calls == [("music", "candidate-key")]
        assert "SUNO_API_KEY" not in os.environ

    @pytest.mark.asyncio
    async def test_test_provider_saved_key_healthy(self, client: AsyncClient):
        from server.providers.registry import ProviderRegistry

        registry = ProviderRegistry.get_instance()
        registry._music = MockMusicProvider()
        registry._provider_keys["music"] = "mock_music"

        resp = await client.post("/api/providers/test/music")

        assert resp.status_code == 200
        assert resp.json() == {
            "provider": "music",
            "healthy": True,
            "status": "healthy",
            "tested_candidate": False,
            "error": None,
        }
```

Also add these imports at the top of `tests/test_routers.py`:

```python
import os

from tests.conftest import MockMusicProvider
```

- [ ] **Step 2: Run router provider tests and verify they fail**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_routers.py::TestProvidersRouter
```

Expected: tests fail because the response does not include `status` and `tested_candidate`, and the endpoint does not accept candidate-key bodies yet.

- [ ] **Step 3: Update provider router schemas and helper mappings**

In `server/routers/providers.py`, add this mapping after `router = APIRouter(...)`:

```python
PROVIDER_KEY_ENV = {
    "music": "SUNO_API_KEY",
    "scriptwriter": "GOOGLE_API_KEY",
    "voice": "FISH_AUDIO_API_KEY",
}
```

Replace `ProviderTestResult` with:

```python
class ProviderTestRequest(BaseModel):
    """Optional payload for testing an unsaved candidate API key."""

    api_key: Optional[str] = None


class ProviderTestResult(BaseModel):
    """Result of testing a single provider's connection."""

    provider: str
    healthy: bool
    status: str
    tested_candidate: bool = False
    error: Optional[str] = None
```

- [ ] **Step 4: Update the endpoint implementation**

Replace the existing `test_provider` function in `server/routers/providers.py` with:

```python
@router.post("/test/{provider_name}", response_model=ProviderTestResult)
async def test_provider(
    provider_name: str,
    body: Optional[ProviderTestRequest] = None,
) -> ProviderTestResult:
    """Test a single provider's health/connectivity.

    Args:
        provider_name: One of 'music', 'scriptwriter', or 'voice'.
        body: Optional candidate key payload. Candidate keys are tested
              without being persisted.

    Returns:
        Test result with health status and optional error message.
    """
    from server.config import Settings
    from server.providers.registry import ProviderRegistry

    registry = ProviderRegistry.get_instance()
    candidate_key = (body.api_key or "").strip() if body else ""

    if candidate_key:
        env_var = PROVIDER_KEY_ENV.get(provider_name)
        if env_var is None:
            return ProviderTestResult(
                provider=provider_name,
                healthy=False,
                status="unknown_provider",
                tested_candidate=True,
                error=f"Unknown provider type: {provider_name}",
            )

        candidate_config = Settings().model_copy(update={env_var: candidate_key})
        result = await registry.check_capability_health(provider_name, candidate_config)
        return ProviderTestResult(
            provider=result["provider"] or provider_name,
            healthy=result["healthy"],
            status=result["status"],
            tested_candidate=True,
            error=result["error"],
        )

    getter_map = {
        "music": registry.get_music_provider,
        "scriptwriter": registry.get_scriptwriter_provider,
        "voice": registry.get_voice_provider,
    }

    getter = getter_map.get(provider_name)
    if getter is None:
        return ProviderTestResult(
            provider=provider_name,
            healthy=False,
            status="unknown_provider",
            tested_candidate=False,
            error=f"Unknown provider type: {provider_name}",
        )

    provider = getter()
    if provider is None:
        return ProviderTestResult(
            provider=provider_name,
            healthy=False,
            status="unconfigured",
            tested_candidate=False,
            error="Not configured",
        )

    try:
        healthy = await provider.check_status()
        return ProviderTestResult(
            provider=provider_name,
            healthy=healthy,
            status="healthy" if healthy else "unhealthy",
            tested_candidate=False,
            error=None if healthy else "Provider reported unhealthy",
        )
    except Exception as exc:
        logger.warning("Provider test failed for %s: %s", provider_name, exc)
        return ProviderTestResult(
            provider=provider_name,
            healthy=False,
            status="error",
            tested_candidate=False,
            error=str(exc),
        )
```

- [ ] **Step 5: Run router provider tests and verify they pass**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_routers.py::TestProvidersRouter
```

Expected: all provider router tests PASS.

- [ ] **Step 6: Run provider-related backend tests**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_providers.py tests\test_routers.py
```

Expected: selected provider and router tests PASS.

- [ ] **Step 7: Commit endpoint contract**

If this directory is a Git worktree, run:

```bash
git add server/routers/providers.py tests/test_routers.py
git commit -m "feat: test unsaved provider keys"
```

If `git status` reports this directory is not a repository, record that in the final handoff instead of committing.

---

### Task 3: Update Frontend API Helper

**Files:**
- Modify: `frontend/src/api.js`

- [ ] **Step 1: Update `testProvider` to accept an optional body**

In `frontend/src/api.js`, replace:

```javascript
export function testProvider(providerName) {
  return apiFetch(`/providers/test/${providerName}`, { method: 'POST' })
}
```

with:

```javascript
export function testProvider(providerName, data) {
  const options = { method: 'POST' }
  if (data) options.body = data
  return apiFetch(`/providers/test/${providerName}`, options)
}
```

- [ ] **Step 2: Run frontend build**

Run:

```powershell
Set-Location frontend
npm run build
```

Expected: build succeeds with Vite output and no import errors.

- [ ] **Step 3: Commit API helper update**

If this directory is a Git worktree, run:

```bash
git add frontend/src/api.js
git commit -m "feat: allow provider candidate test payloads"
```

If `git status` reports this directory is not a repository, record that in the final handoff instead of committing.

---

### Task 4: Refactor Providers Page Into Maintenance Cards

**Files:**
- Modify: `frontend/src/pages/Providers.jsx`

- [ ] **Step 1: Add provider card metadata**

In `frontend/src/pages/Providers.jsx`, add this constant after the imports:

```javascript
const PROVIDERS = [
  {
    type: 'music',
    envVar: 'SUNO_API_KEY',
    title: 'Suno',
    role: 'Music Generation',
    keyState: 'sunoKey',
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
    keyState: 'fishKey',
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
    keyState: 'googleKey',
    healthKey: 'scriptwriter',
    inputPlaceholder: 'Paste a Google AI API key...',
    configuredText: 'Google AI key saved',
    missingText: 'Google AI key missing',
    impact: 'Required for writing DJ breaks, transitions, and talk content.',
    href: 'https://aistudio.google.com/apikey',
    linkLabel: 'Get a Google AI API key',
  },
]
```

- [ ] **Step 2: Replace separate key states with keyed state objects**

Replace:

```javascript
  const [googleKey, setGoogleKey] = useState('')
  const [sunoKey, setSunoKey] = useState('')
  const [fishKey, setFishKey] = useState('')

  const [maskedGoogle, setMaskedGoogle] = useState({})
  const [maskedSuno, setMaskedSuno] = useState({})
  const [maskedFish, setMaskedFish] = useState({})
```

with:

```javascript
  const [keys, setKeys] = useState({ music: '', scriptwriter: '', voice: '' })
  const [maskedKeys, setMaskedKeys] = useState({})
```

- [ ] **Step 3: Add helper functions for card state**

Add these functions inside `Providers`, after `useEffect(() => { loadProviders() }, [])`:

```javascript
  function setProviderKey(type, value) {
    setKeys(prev => ({ ...prev, [type]: value }))
  }

  function maskedFor(provider) {
    return maskedKeys[provider.envVar] || {}
  }

  function providerHealth(provider) {
    const manual = testResults[provider.type]
    if (manual) return manual
    return health[provider.healthKey] || { status: 'unconfigured', healthy: false }
  }

  function providerStatus(provider) {
    const savedKey = maskedFor(provider)
    const h = providerHealth(provider)
    if (!savedKey.is_configured && !keys[provider.type]) {
      return { tone: 'unconfigured', label: 'Not configured' }
    }
    if (h.healthy || h.status === 'healthy') {
      return { tone: 'ok', label: 'Connected' }
    }
    if (h.status === 'error' || h.status === 'unhealthy' || h.status === 'circuit_open') {
      return { tone: 'error', label: h.status === 'circuit_open' ? 'Circuit open' : 'Needs attention' }
    }
    if (keys[provider.type]) {
      return { tone: 'untested', label: 'Unsaved key ready to test' }
    }
    return { tone: 'unconfigured', label: 'Untested' }
  }

  function testButtonLabel(provider) {
    if (testingStatus[provider.type]) return 'Testing...'
    return keys[provider.type] ? 'Test Unsaved Key' : 'Test Saved Key'
  }
```

- [ ] **Step 4: Update `loadProviders` to build masked key map**

Replace the key handling portion of `loadProviders`:

```javascript
      const keys = data.keys || []
      setMaskedGoogle(keys.find(k => k.env_var === 'GOOGLE_API_KEY') || {})
      setMaskedSuno(keys.find(k => k.env_var === 'SUNO_API_KEY') || {})
      setMaskedFish(keys.find(k => k.env_var === 'FISH_AUDIO_API_KEY') || {})

      setGoogleKey('')
      setSunoKey('')
      setFishKey('')
```

with:

```javascript
      const loadedKeys = data.keys || []
      setMaskedKeys(Object.fromEntries(loadedKeys.map(k => [k.env_var, k])))
      setKeys({ music: '', scriptwriter: '', voice: '' })
```

- [ ] **Step 5: Update `handleTest` to send candidate keys**

Replace `handleTest` with:

```javascript
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
```

- [ ] **Step 6: Update `handleSave` to read keyed state**

Replace the payload construction in `handleSave`:

```javascript
      const payload = {}
      if (googleKey) payload.google_api_key = googleKey
      if (sunoKey) payload.suno_api_key = sunoKey
      if (fishKey) payload.fish_audio_api_key = fishKey
```

with:

```javascript
      const payload = {}
      if (keys.scriptwriter.trim()) payload.google_api_key = keys.scriptwriter.trim()
      if (keys.music.trim()) payload.suno_api_key = keys.music.trim()
      if (keys.voice.trim()) payload.fish_audio_api_key = keys.voice.trim()
```

- [ ] **Step 7: Add a metadata-driven card renderer**

Add this function inside `Providers`, before the `if (loading)` block:

```javascript
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
              type={showKey ? 'text' : 'password'}
              value={typedKey}
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
```

- [ ] **Step 8: Replace the repeated provider card JSX**

Inside the `<form onSubmit={handleSave}>`, replace the entire `<div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>` block that contains the three hardcoded Suno, Fish Audio, and Google Gemini cards with:

```javascript
        <div className="provider-card-list">
          {PROVIDERS.map(provider => renderProviderCard(provider))}
        </div>
```

- [ ] **Step 9: Run frontend build**

Run:

```powershell
Set-Location frontend
npm run build
```

Expected: build succeeds with Vite output and no React syntax errors.

- [ ] **Step 10: Commit Providers page refactor**

If this directory is a Git worktree, run:

```bash
git add frontend/src/pages/Providers.jsx
git commit -m "feat: improve provider maintenance cards"
```

If `git status` reports this directory is not a repository, record that in the final handoff instead of committing.

---

### Task 5: Add Provider Console Styling

**Files:**
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Add CSS for provider maintenance cards**

Append this CSS near existing provider/API key styles in `frontend/src/App.css`:

```css
.provider-card-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.provider-maintenance-card {
  overflow: hidden;
}

.provider-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.provider-card-header h3 {
  margin-bottom: 4px;
}

.provider-status-stack {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
  min-width: 220px;
}

.provider-card-body {
  padding: 16px;
}

.provider-impact {
  margin: 0 0 12px;
  color: #b8b8c8;
  font-size: 14px;
  line-height: 1.45;
}

.provider-state {
  border-radius: 999px;
  padding: 3px 8px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.provider-state-ok {
  color: #7ee787;
  background: rgba(126, 231, 135, 0.12);
}

.provider-state-error {
  color: #ff9b9b;
  background: rgba(255, 155, 155, 0.12);
}

.provider-state-unconfigured,
.provider-state-untested {
  color: #d8c47d;
  background: rgba(216, 196, 125, 0.12);
}

.health-dot.untested {
  background: #d8c47d;
}

@media (max-width: 720px) {
  .provider-card-header {
    flex-direction: column;
  }

  .provider-status-stack {
    justify-content: flex-start;
    min-width: 0;
  }

  .api-key-input-row {
    flex-direction: column;
  }

  .api-key-input-row .btn {
    width: 100%;
  }
}
```

- [ ] **Step 2: Run frontend build**

Run:

```powershell
Set-Location frontend
npm run build
```

Expected: build succeeds.

- [ ] **Step 3: Commit styling**

If this directory is a Git worktree, run:

```bash
git add frontend/src/App.css
git commit -m "style: polish provider health console"
```

If `git status` reports this directory is not a repository, record that in the final handoff instead of committing.

---

### Task 6: Final Verification

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run selected backend tests**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_providers.py tests\test_routers.py
```

Expected: selected backend tests PASS.

- [ ] **Step 2: Run full backend suite**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
```

Expected: full backend suite PASS.

- [ ] **Step 3: Run frontend production build**

Run:

```powershell
Set-Location frontend
npm run build
```

Expected: frontend build PASS.

- [ ] **Step 4: Review changed files**

Run:

```powershell
git diff -- server/providers/registry.py server/routers/providers.py tests/test_providers.py tests/test_routers.py frontend/src/api.js frontend/src/pages/Providers.jsx frontend/src/App.css
```

Expected: diff only contains provider health console changes. If `git diff` fails because this directory is not a Git worktree, use `Get-Content` on the changed files and report that Git verification was unavailable.

- [ ] **Step 5: Final commit**

If this directory is a Git worktree and prior task commits were skipped, run:

```bash
git add server/providers/registry.py server/routers/providers.py tests/test_providers.py tests/test_routers.py frontend/src/api.js frontend/src/pages/Providers.jsx frontend/src/App.css
git commit -m "feat: add provider health console"
```

If this directory is not a Git worktree, do not attempt a commit. Include that limitation in the final handoff.
