# Provider Health Console Design

## Objective

Improve ongoing setup and configuration maintenance by making the Providers page the operator's central console for diagnosing and fixing AI service readiness.

Operators should be able to answer three questions quickly:

- Which providers are configured?
- Which providers are currently usable?
- What station capability is unavailable when a provider is missing or failing?

## Scope

- Improve the existing Providers page rather than adding a new page.
- Keep the three current provider roles: music, scriptwriter, and voice.
- Show clearer status, impact, and error details per provider.
- Allow testing a newly typed API key before saving it.
- Preserve the existing behavior where blank fields leave saved keys unchanged.
- Keep provider-specific code isolated inside the provider layer and registry.

## Non-Goals

- Do not change scheduler, playout, generation, or queueing behavior.
- Do not store API keys in the database.
- Do not expose raw saved keys in API responses.
- Do not add new provider types.
- Do not rework the first-run setup wizard in this phase.
- Do not make frontend code import provider implementations directly.

## Backend Behavior

Extend the existing provider test endpoint:

```http
POST /api/providers/test/{provider_name}
```

The endpoint should continue to work with no request body, testing the currently saved provider configuration.

It should also accept an optional JSON body with a candidate key:

```json
{
  "api_key": "candidate-key-value"
}
```

When `api_key` is provided, the backend tests that key without persisting it. The provider registry remains the normal path for saved-key health checks. Candidate-key checks should use provider-layer construction or a registry helper so engine and router code do not import concrete providers directly.

Response shape:

```json
{
  "provider": "music",
  "healthy": true,
  "status": "healthy",
  "tested_candidate": true,
  "error": null
}
```

Status values:

- `healthy`: provider responded successfully.
- `unhealthy`: provider was configured but did not pass its health check.
- `unconfigured`: no saved key was available and no candidate key was supplied.
- `error`: the test failed with an exception.
- `unknown_provider`: the requested provider role is not recognized.

The existing `/api/providers` response should remain compatible. It may include richer health data if already available from the registry, but the frontend must tolerate missing or partial health information.

## Frontend Behavior

Update `frontend/src/pages/Providers.jsx` so each provider card acts as a maintenance unit.

Each card shows:

- Provider name and role.
- Current key state using the masked saved key when present.
- Connection state derived from saved health and recent manual tests.
- A short impact line explaining what becomes unavailable if this provider is missing.
- A persistent latest test result area with success or error details.

Each card supports:

- Entering a replacement key.
- Testing the saved key when no replacement key is typed.
- Testing the typed key before saving.
- Saving replacement keys through the existing provider update API.

The global save button can remain, but the card should make it clear whether a test is using the saved key or the unsaved candidate key. Blank fields must still preserve existing keys.

Suggested impact text:

- Music: "Required for generating new songs and replenishing the music buffer."
- Scriptwriter: "Required for writing DJ breaks, transitions, and talk content."
- Voice: "Required for rendering DJ breaks and spoken segments."

## Error Handling

- Failed provider tests should not clear typed keys.
- Failed provider tests should not overwrite saved provider health.
- Candidate-key tests should never persist secrets.
- The UI should distinguish "not configured" from "configured but failing."
- If provider health checks throw, the user should see the error in the relevant card while the rest of the page stays usable.

## Data Flow

1. Providers page loads `/api/providers`.
2. Page renders masked key state and any saved health state.
3. Operator types a key in one card.
4. Operator clicks test.
5. Frontend sends `POST /api/providers/test/{provider_name}` with `{ "api_key": "..." }`.
6. Backend tests the candidate key without writing `.env` or mutating process environment.
7. UI stores the latest result on that card.
8. Operator saves keys through `PUT /api/providers`.
9. Backend writes `.env`, updates process environment, and reinitializes the registry.
10. Page reloads provider state.

## Testing

Backend tests should cover:

- Saved provider test still works with no body.
- Candidate key test does not persist the key.
- Candidate key test returns `tested_candidate: true`.
- Unknown provider returns an explicit non-healthy response.
- Missing saved key with no candidate returns `unconfigured`.

Frontend verification:

- `npm run build` in `frontend`.

Backend verification:

- `powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_providers.py tests\test_routers.py`
- `powershell -ExecutionPolicy Bypass -File scripts\test.ps1`

## Implementation Notes

- Keep the endpoint backward-compatible so existing callers of `testProvider(providerName)` keep working.
- Add an optional body parameter to the frontend API helper rather than creating a separate function.
- Prefer provider-registry helpers over concrete provider imports in routers.
- Keep copy concise and operational. This page is for fixing problems, not explaining the whole app.
