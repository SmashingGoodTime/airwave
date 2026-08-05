# Contributing to AI Radio DJ

Thanks for your interest in contributing! This guide covers everything you need to get started.

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- FFmpeg (for audio processing)
- Docker & Docker Compose (optional, for full stack testing)

### Local Development

1. **Clone and install Python dependencies:**

   ```bash
   git clone https://github.com/SmashingGoodTime/ai-radio-dj.git
   cd ai-radio-dj
   pip install -r requirements-dev.txt
   ```

   `requirements-dev.txt` pulls in the runtime dependencies plus the test
   tooling. Use `requirements.txt` alone only for a non-development install.

2. **Set up environment variables:**

   ```bash
   cp .env.example .env
   # Edit .env with your API keys (all optional for development)
   ```

3. **Run the backend:**

   ```bash
   python -m server.main
   ```

   The API starts at `http://localhost:8000`. The setup wizard runs on first launch.

4. **Install and run the frontend (dev mode):**

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

   Vite dev server starts at `http://localhost:5173` with hot reload. API requests proxy to port 8000.

5. **Build the frontend for production serving:**

   ```bash
   cd frontend
   npm run build
   ```

   FastAPI serves the built files from `frontend/dist/` at `/`.

### Full Stack (Docker)

```bash
docker-compose up --build
```

This starts the app, Liquidsoap, and Icecast together. The UI is at `http://localhost:8000`, the stream at `http://localhost:8080/stream`.

## Project Structure

```
server/           Python backend (FastAPI)
  models/         SQLAlchemy ORM models (Track, Style, Show, DJConfig, etc.)
  routers/        API route handlers (shows, styles, dj_config, dashboard, etc.)
  providers/      Provider abstraction layer (music, voice, scriptwriter, telephony, conversation)
  engine/         Core station logic (scheduler, buffer, DJ brain, playout)
  events/         Event bus and handlers
  utils/          Shared utilities (rate limiter, audio helpers)
frontend/src/     React frontend (Vite)
  pages/          Page components (Dashboard, Shows, Styles, DJConfig, etc.)
  components/     Reusable UI components
liquidsoap/       Liquidsoap playout configuration (includes harbor input for live calls)
icecast/          Icecast streaming server configuration
audio/            Audio file storage (tracks, breaks, calls, fallback, archive)
docs/             Documentation
```

## Code Style

### Python

- **Type hints on all function signatures and return types.** Use `Optional`, `list`, `dict`, etc.
- **Docstrings on all public methods and classes** in Google style:
  ```python
  async def generate(self, prompt: str, duration: int = 180) -> dict:
      """Generate a music track from a text prompt.

      Args:
          prompt: Text description of the desired music style.
          duration: Target duration in seconds.

      Returns:
          A dict with keys: task_id, filepath, title, duration, metadata.

      Raises:
          RuntimeError: If generation fails after retries.
      """
  ```
- **Async by default** for all provider calls, database operations, and engine methods.
- **Pydantic models** for all API request/response schemas (separate from SQLAlchemy models).
- **Logging** via Python's `logging` module. Use `logger = logging.getLogger(__name__)` at module level.
- **No hardcoded values.** Configuration goes in the database (managed via UI) or environment variables.

### JavaScript / React

- Functional components with hooks.
- Keep pages in `frontend/src/pages/`, reusable components in `frontend/src/components/`.
- Use the API client in `frontend/src/api.js` for all backend calls.

### General

- No trailing whitespace.
- Files end with a newline.
- Keep imports sorted: stdlib, third-party, local.

## Database Migrations

Schema changes are managed with Alembic. Do not add ad hoc `CREATE TABLE`
or `ALTER TABLE` patches to application startup code.

```bash
# Create a new migration after changing SQLAlchemy models
alembic revision --autogenerate -m "describe schema change"

# Apply migrations locally
alembic upgrade head

# Verify migration tests and the rest of the suite
python -m pytest tests/test_migrations.py
python -m pytest
```

The app also runs `alembic upgrade head` during backend startup, so Docker
and local runs keep the SQLite database current automatically.

## Architecture Rules

These are non-negotiable design principles. PRs that violate them will be asked to refactor.

### Provider Abstraction

**Never import a specific provider in engine or router code.** Always go through the provider registry.

```python
# WRONG
from server.providers.music.suno import SunoProvider

# RIGHT
from server.providers.registry import get_music_provider
provider = get_music_provider()
```

New providers are added by:
1. Creating a file in the appropriate `providers/` subdirectory
2. Subclassing the abstract base from `providers/base.py`
3. Registering in `providers/registry.py`
4. No other code changes needed

See `docs/adding-providers.md` for a full walkthrough.

### Graceful Degradation

The UI must load and be fully navigable even with zero providers configured. Provider failures log warnings but never crash the engine.

### Audio Normalization

All audio entering any queue must pass through the audio pipeline (48kHz stereo WAV, -14 LUFS). No exceptions.

### Dead Air Prevention

Always maintain fallback audio. Buffer alerts must surface before dead air is possible.

## Running Tests

```bash
# Install the same dependencies CI expects
python -m pip install -r requirements-dev.txt

# Run all tests
python -m pytest

# Run with verbose output
python -m pytest -v

# Run a specific test file
python -m pytest tests/test_scheduler_reliability.py

# Run async tests
python -m pytest tests/ -k "async"
```

Provider tests should use mocks (never call real APIs in tests). Engine tests should use mock providers or fakes that return dummy audio files. Scheduler tests should prove the station keeps queueing audio when providers, files, or Liquidsoap are unavailable.

## Pull Request Process

1. **Fork the repo** and create a feature branch from `main`:
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make your changes.** Follow the code style and architecture rules above.

3. **Test your changes.** Add or update tests as appropriate.

4. **Commit with a clear message:**
   ```
   Add OpenAI music provider

   Implements MusicProvider interface using the OpenAI API.
   Includes rate limiting, retry logic, and health checks.
   ```

5. **Push and open a PR** against `main`. Include:
   - A summary of what changed and why
   - Any new dependencies added
   - How to test the changes
   - Screenshots for UI changes

6. **Address review feedback.** Maintainers may request changes before merging.

## What to Contribute

Here are some areas where contributions are welcome:

- **New providers** — Music generation, TTS voices, scriptwriter backends, telephony services, conversation AI
- **Event handlers** — Discord bots, webhook integrations, now-playing widgets
- **Call-in improvements** — Additional telephony providers, call queue management, moderation tools
- **UI improvements** — Better visualizations, mobile responsiveness, accessibility
- **Tests** — Unit and integration tests for any module
- **Documentation** — Tutorials, examples, translations
- **Bug fixes** — Check the issue tracker for open bugs

## Reporting Issues

When filing a bug report, please include:

- Steps to reproduce
- Expected vs. actual behavior
- Log output (set `LOG_LEVEL=DEBUG` in `.env` for detailed logs)
- Your environment (OS, Python version, Docker version if applicable)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
