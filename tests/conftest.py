"""Shared test fixtures: async DB, mock providers, test client."""

import asyncio
import os
from collections.abc import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

# Force test database before any app imports
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"

from server.database import Base, get_session
from server.events.emitter import event_bus
from server.providers.base import MusicProvider, ScriptWriterProvider, VoiceProvider
from server.providers.registry import ProviderRegistry


# ---------------------------------------------------------------------------
# Mock providers
# ---------------------------------------------------------------------------


class MockMusicProvider(MusicProvider):
    """A mock music provider returning dummy results."""

    async def generate(self, prompt: str, duration: int = 180) -> dict:
        return {
            "filepath": "/tmp/test_track.wav",
            "title": f"Test Track: {prompt[:30]}",
            "duration": duration,
            "metadata": {"provider": "mock"},
        }

    async def check_status(self) -> bool:
        return True


class MockScriptWriterProvider(ScriptWriterProvider):
    """A mock scriptwriter provider returning canned scripts."""

    async def write_break(self, context: dict) -> dict:
        dj = context.get("dj_name", "DJ")
        return {
            "script_text": f"Hey listeners, this is {dj}! Great vibes tonight.",
            "metadata": {"provider": "mock"},
        }

    async def check_status(self) -> bool:
        return True


class MockVoiceProvider(VoiceProvider):
    """A mock voice provider returning a dummy audio path."""

    async def render(self, text: str, voice_config: dict) -> str:
        return "/tmp/test_break.wav"

    async def list_voices(self) -> list:
        return [
            {"voice_id": "voice_1", "name": "Alice"},
            {"voice_id": "voice_2", "name": "Bob"},
        ]

    async def check_status(self) -> bool:
        return True


class FailingMusicProvider(MusicProvider):
    """A music provider that always fails."""

    async def generate(self, prompt: str, duration: int = 180) -> dict:
        raise RuntimeError("Provider unavailable")

    async def check_status(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_global_runtime_state():
    """Reset process-wide singletons that can leak between tests."""
    ProviderRegistry._instance = None
    event_bus._handlers.clear()
    event_bus._ws_clients.clear()
    yield
    ProviderRegistry._instance = None
    event_bus._handlers.clear()
    event_bus._ws_clients.clear()


@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for the whole test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create a fresh in-memory SQLite engine per test.

    ``StaticPool`` makes every session share the one underlying connection,
    so all sessions see the same in-memory database. Without it aiosqlite
    hands out a fresh, empty ``:memory:`` database per connection, and the
    engine's separate-session timeline updates land in a database the test's
    own session can't see (a real file/WAL database shares across
    connections, so this only bites in-memory tests).
    """
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Provide an async session bound to the test engine."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Provider fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_music_provider() -> MockMusicProvider:
    return MockMusicProvider()


@pytest.fixture
def mock_scriptwriter_provider() -> MockScriptWriterProvider:
    return MockScriptWriterProvider()


@pytest.fixture
def mock_voice_provider() -> MockVoiceProvider:
    return MockVoiceProvider()


@pytest.fixture
def failing_music_provider() -> FailingMusicProvider:
    return FailingMusicProvider()


@pytest.fixture
def mock_registry(
    mock_music_provider, mock_scriptwriter_provider, mock_voice_provider
) -> ProviderRegistry:
    """Return a ProviderRegistry pre-loaded with mock providers."""
    registry = ProviderRegistry()
    registry._music = mock_music_provider
    registry._scriptwriter = mock_scriptwriter_provider
    registry._voice = mock_voice_provider
    return registry


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    """Provide an httpx AsyncClient wired to the FastAPI app with test DB."""
    from server.main import app

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
