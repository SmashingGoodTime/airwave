"""Tests for FastAPI router endpoints."""

import json
import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.models.announcement import Announcement
from server.models.audio_asset import AudioAsset
from server.models.dj_break import DJBreak
from server.models.dj_config import DJConfig
from server.models.generation_job import GenerationJob
from server.models.playlog import PlayLog
from server.models.program_item import ProgramItem
from server.models.station import Station
from server.models.style import Style
from server.models.talk_segment import TalkSegment
from server.models.track import Track
from tests.conftest import MockMusicProvider


# ---------------------------------------------------------------------------
# Setup router
# ---------------------------------------------------------------------------


class TestSetupRouter:
    @pytest.mark.asyncio
    async def test_setup_status_not_complete(self, client: AsyncClient):
        resp = await client.get("/api/setup/status")
        assert resp.status_code == 200
        assert resp.json()["setup_complete"] is False

    @pytest.mark.asyncio
    async def test_setup_complete(self, client: AsyncClient):
        resp = await client.post(
            "/api/setup/complete",
            json={
                "station_name": "Test Radio",
                "timezone": "US/Eastern",
                "dj_name": "DJ Test",
                "content_policy": "instrumental_only",
                "styles": [
                    {"name": "Ambient", "prompt": "ambient electronic"},
                    {"name": "Jazz", "prompt": "smooth jazz"},
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Verify setup is now complete
        resp = await client.get("/api/setup/status")
        assert resp.json()["setup_complete"] is True


# ---------------------------------------------------------------------------
# Styles router
# ---------------------------------------------------------------------------


class TestStylesRouter:
    @pytest.mark.asyncio
    async def test_list_styles_empty(self, client: AsyncClient):
        resp = await client.get("/api/styles")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_create_style(self, client: AsyncClient):
        resp = await client.post(
            "/api/styles",
            json={"name": "Lo-fi", "prompt": "lo-fi hip hop beats"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Lo-fi"
        assert data["prompt"] == "lo-fi hip hop beats"
        assert data["active"] is True
        assert data["weight"] == 1.0
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_and_list(self, client: AsyncClient):
        await client.post("/api/styles", json={"name": "A", "prompt": "p1"})
        await client.post("/api/styles", json={"name": "B", "prompt": "p2"})
        resp = await client.get("/api/styles")
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_update_style(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/styles", json={"name": "Old", "prompt": "old prompt"}
        )
        style_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/styles/{style_id}",
            json={"name": "New", "prompt": "new prompt"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New"
        assert resp.json()["prompt"] == "new prompt"

    @pytest.mark.asyncio
    async def test_update_style_not_found(self, client: AsyncClient):
        resp = await client.put(
            "/api/styles/9999", json={"name": "X"}
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_style(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/styles", json={"name": "Del", "prompt": "p"}
        )
        style_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/styles/{style_id}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Verify deleted
        resp = await client.get("/api/styles")
        ids = [s["id"] for s in resp.json()]
        assert style_id not in ids

    @pytest.mark.asyncio
    async def test_delete_style_not_found(self, client: AsyncClient):
        resp = await client.delete("/api/styles/9999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_toggle_style(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/styles", json={"name": "Toggle", "prompt": "p"}
        )
        style_id = create_resp.json()["id"]
        assert create_resp.json()["active"] is True

        resp = await client.post(f"/api/styles/{style_id}/toggle")
        assert resp.status_code == 200
        assert resp.json()["active"] is False

        resp = await client.post(f"/api/styles/{style_id}/toggle")
        assert resp.json()["active"] is True

    @pytest.mark.asyncio
    async def test_toggle_not_found(self, client: AsyncClient):
        resp = await client.post("/api/styles/9999/toggle")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_reorder_styles(self, client: AsyncClient):
        r1 = await client.post("/api/styles", json={"name": "A", "prompt": "p1", "weight": 1.0})
        r2 = await client.post("/api/styles", json={"name": "B", "prompt": "p2", "weight": 2.0})
        id1 = r1.json()["id"]
        id2 = r2.json()["id"]

        resp = await client.post(
            "/api/styles/reorder",
            json=[{"id": id1, "weight": 5.0}, {"id": id2, "weight": 3.0}],
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Verify weights
        resp = await client.get("/api/styles")
        styles = {s["id"]: s for s in resp.json()}
        assert styles[id1]["weight"] == 5.0
        assert styles[id2]["weight"] == 3.0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"name": "", "prompt": "ambient"},
            {"name": "Ambient", "prompt": ""},
            {"name": "Ambient", "prompt": "ambient", "weight": 0},
            {"name": "Ambient", "prompt": "ambient", "weight": -1},
        ],
    )
    async def test_create_rejects_invalid_style_fields(
        self, client: AsyncClient, payload: dict
    ):
        resp = await client.post("/api/styles", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", [{"weight": 0}, {"weight": -1}])
    async def test_update_rejects_invalid_style_weight(
        self, client: AsyncClient, payload: dict
    ):
        create_resp = await client.post(
            "/api/styles", json={"name": "Ambient", "prompt": "ambient"}
        )
        assert create_resp.status_code == 201

        resp = await client.put(
            f"/api/styles/{create_resp.json()['id']}",
            json=payload,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_reorder_rejects_invalid_style_weight(self, client: AsyncClient):
        resp = await client.post("/api/styles/reorder", json=[{"id": 1, "weight": 0}])
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_accepts_valid_schedule(self, client: AsyncClient):
        resp = await client.post(
            "/api/styles",
            json={
                "name": "Night",
                "prompt": "ambient",
                "schedule": '{"start": "22:00", "end": "06:00"}',
            },
        )
        assert resp.status_code == 201
        assert resp.json()["schedule"] == '{"start": "22:00", "end": "06:00"}'

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "schedule",
        [
            "not json",
            '"just a string"',
            "[1, 2]",
            '{"start": "22:00"}',
            '{"start": "22:00", "end": "06:00", "extra": 1}',
            '{"start": "25:00", "end": "06:00"}',
            '{"start": "22:00", "end": "6pm"}',
            '{"start": 22, "end": "06:00"}',
        ],
    )
    async def test_create_rejects_malformed_schedule(
        self, client: AsyncClient, schedule: str
    ):
        resp = await client.post(
            "/api/styles",
            json={"name": "Bad", "prompt": "p", "schedule": schedule},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_update_rejects_malformed_schedule(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/styles", json={"name": "S", "prompt": "p"}
        )
        resp = await client.put(
            f"/api/styles/{create_resp.json()['id']}",
            json={"schedule": '{"start": "nope", "end": "06:00"}'},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_style_removes_show_junction_rows(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from sqlalchemy import select as sa_select

        from server.models.show_style import show_styles

        style_resp = await client.post(
            "/api/styles", json={"name": "Linked", "prompt": "p"}
        )
        style_id = style_resp.json()["id"]
        show_resp = await client.post(
            "/api/shows",
            json={"name": "Block", "show_type": "music", "style_ids": [style_id]},
        )
        assert show_resp.status_code == 201

        resp = await client.delete(f"/api/styles/{style_id}")
        assert resp.status_code == 200

        result = await db_session.execute(
            sa_select(show_styles.c.style_id).where(
                show_styles.c.style_id == style_id
            )
        )
        assert result.all() == []


# ---------------------------------------------------------------------------
# Announcements router
# ---------------------------------------------------------------------------


class TestAnnouncementsRouter:
    @pytest.mark.asyncio
    async def test_list_empty(self, client: AsyncClient):
        resp = await client.get("/api/announcements")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_create_announcement(self, client: AsyncClient):
        resp = await client.post(
            "/api/announcements",
            json={"text": "Big concert this Friday!", "priority": "high"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["text"] == "Big concert this Friday!"
        assert data["priority"] == "high"
        assert data["active"] is True
        assert data["play_count"] == 0

    @pytest.mark.asyncio
    async def test_update_announcement(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/announcements", json={"text": "Original", "priority": "normal"}
        )
        ann_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/announcements/{ann_id}",
            json={"text": "Updated text", "priority": "urgent"},
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "Updated text"
        assert resp.json()["priority"] == "urgent"

    @pytest.mark.asyncio
    async def test_update_not_found(self, client: AsyncClient):
        resp = await client.put(
            "/api/announcements/9999", json={"text": "X"}
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_announcement(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/announcements", json={"text": "Del me"}
        )
        ann_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/announcements/{ann_id}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_delete_not_found(self, client: AsyncClient):
        resp = await client.delete("/api/announcements/9999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_filter_by_active(self, client: AsyncClient):
        await client.post(
            "/api/announcements", json={"text": "Active", "active": True}
        )
        await client.post(
            "/api/announcements", json={"text": "Inactive", "active": False}
        )

        resp = await client.get("/api/announcements?active=true")
        texts = [a["text"] for a in resp.json()]
        assert "Active" in texts
        assert "Inactive" not in texts

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"text": ""},
            {"text": "Station ID", "priority": "extreme"},
            {"text": "Station ID", "max_plays": 0},
            {"text": "Station ID", "max_plays": -1},
        ],
    )
    async def test_create_rejects_invalid_announcement_fields(
        self, client: AsyncClient, payload: dict
    ):
        resp = await client.post("/api/announcements", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [{"priority": "extreme"}, {"max_plays": 0}, {"max_plays": -1}],
    )
    async def test_update_rejects_invalid_announcement_fields(
        self, client: AsyncClient, payload: dict
    ):
        create_resp = await client.post(
            "/api/announcements", json={"text": "Station ID"}
        )
        assert create_resp.status_code == 201

        resp = await client.put(
            f"/api/announcements/{create_resp.json()['id']}",
            json=payload,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_orders_by_active_then_priority(self, client: AsyncClient):
        await client.post(
            "/api/announcements",
            json={"text": "Low active", "priority": "low", "active": True},
        )
        await client.post(
            "/api/announcements",
            json={"text": "High inactive", "priority": "high", "active": False},
        )
        await client.post(
            "/api/announcements",
            json={"text": "Urgent active", "priority": "urgent", "active": True},
        )

        resp = await client.get("/api/announcements")
        texts = [a["text"] for a in resp.json()]
        assert texts == ["Urgent active", "Low active", "High inactive"]

    @pytest.mark.asyncio
    async def test_toggle_active_via_put(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/announcements", json={"text": "Toggle me", "active": True}
        )
        ann_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/announcements/{ann_id}", json={"active": False}
        )
        assert resp.status_code == 200
        assert resp.json()["active"] is False

        resp = await client.put(
            f"/api/announcements/{ann_id}", json={"active": True}
        )
        assert resp.json()["active"] is True

    @pytest.mark.asyncio
    async def test_expires_at_normalized_to_utc(self, client: AsyncClient):
        resp = await client.post(
            "/api/announcements",
            json={"text": "Zulu", "expires_at": "2099-01-01T00:00:00Z"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["expires_at"] == "2099-01-01T00:00:00+00:00"
        assert data["expired"] is False

    @pytest.mark.asyncio
    async def test_auto_deactivation_state_visible(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        expired = Announcement(
            text="Old news",
            expires_at=datetime(2020, 1, 1, 0, 0),
            active=True,
        )
        exhausted = Announcement(
            text="Played out", max_plays=2, play_count=2, active=True
        )
        db_session.add_all([expired, exhausted])
        await db_session.commit()

        resp = await client.get("/api/announcements")
        by_text = {a["text"]: a for a in resp.json()}
        assert by_text["Old news"]["expired"] is True
        assert by_text["Old news"]["plays_exhausted"] is False
        assert by_text["Played out"]["plays_exhausted"] is True
        assert by_text["Played out"]["expired"] is False


# ---------------------------------------------------------------------------
# DJ Config router
# ---------------------------------------------------------------------------


class TestDJConfigRouter:
    @pytest.mark.asyncio
    async def test_get_default_config(self, client: AsyncClient):
        resp = await client.get("/api/dj/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["station_name"] == "AI Radio"
        assert data["dj_name"] == "DJ Claude"
        assert data["break_frequency"] == 3

    @pytest.mark.asyncio
    async def test_update_config(self, client: AsyncClient):
        resp = await client.put(
            "/api/dj/config",
            json={
                "station_name": "Cool FM",
                "dj_name": "DJ Cool",
                "break_frequency": 5,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["station_name"] == "Cool FM"
        assert data["dj_name"] == "DJ Cool"
        assert data["break_frequency"] == 5

    @pytest.mark.asyncio
    async def test_update_config_partial(self, client: AsyncClient):
        # Create initial config
        await client.put("/api/dj/config", json={"station_name": "FM1"})
        # Update only dj_name
        resp = await client.put("/api/dj/config", json={"dj_name": "NewDJ"})
        data = resp.json()
        assert data["station_name"] == "FM1"
        assert data["dj_name"] == "NewDJ"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"break_frequency": 0},
            {"break_frequency_variance": -1},
            {"content_policy": "anything_goes"},
            {"max_break_duration": 0},
        ],
    )
    async def test_update_config_rejects_invalid_timing_fields(
        self, client: AsyncClient, payload: dict
    ):
        resp = await client.put("/api/dj/config", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_voices_empty_no_provider(self, client: AsyncClient):
        resp = await client.get("/api/dj/voices")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_preview_no_provider(self, client: AsyncClient):
        resp = await client.post("/api/dj/preview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["script"] is None
        assert "error" in data


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
        monkeypatch.setattr(
            providers_router,
            "update_env_file",
            lambda values: calls.append(("persisted", values)),
        )

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


# ---------------------------------------------------------------------------
# Dashboard router
# ---------------------------------------------------------------------------


class TestDashboardRouter:
    @pytest.mark.asyncio
    async def test_status_idle(self, client: AsyncClient):
        resp = await client.get("/api/dashboard/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["now_playing"] is None
        assert data["buffer_depth"] == 0
        assert data["stream_status"] == "idle"
        assert "provider_health" in data

    @pytest.mark.asyncio
    async def test_status_online_when_scheduler_is_streaming(
        self, client: AsyncClient
    ):
        from server.main import app

        class FakeScheduler:
            is_streaming = True
            streaming_show_type = "music"

        previous_scheduler = getattr(app.state, "scheduler", None)
        app.state.scheduler = FakeScheduler()
        try:
            resp = await client.get("/api/dashboard/status")
        finally:
            app.state.scheduler = previous_scheduler

        assert resp.status_code == 200
        data = resp.json()
        assert data["now_playing"] is None
        assert data["streaming"] is True
        assert data["stream_status"] == "online"

    @pytest.mark.asyncio
    async def test_recent_empty(self, client: AsyncClient):
        resp = await client.get("/api/dashboard/recent")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("limit", [0, -1, 101])
    async def test_recent_rejects_invalid_limit(
        self, client: AsyncClient, limit: int
    ):
        resp = await client.get(f"/api/dashboard/recent?limit={limit}")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_timeline_returns_program_items(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        asset = AudioAsset(
            asset_type="music_track",
            normalized_filepath="audio/tracks/song.wav",
            duration=180.0,
            loudness_lufs=-14.0,
            status="ready",
        )
        db_session.add(asset)
        await db_session.flush()
        item = ProgramItem(
            item_type="music_track",
            status="ready",
            audio_asset_id=asset.id,
            source_table="tracks",
            source_id=42,
            title="Timeline Song",
            duration=180.0,
        )
        db_session.add(item)
        await db_session.commit()

        resp = await client.get("/api/dashboard/timeline")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["item_type"] == "music_track"
        assert data[0]["status"] == "ready"
        assert data[0]["title"] == "Timeline Song"
        assert data[0]["source_table"] == "tracks"
        assert data[0]["source_id"] == 42
        assert data[0]["asset"]["asset_type"] == "music_track"
        assert data[0]["asset"]["normalized_filepath"] == "audio/tracks/song.wav"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("limit", [0, -1, 101])
    async def test_timeline_rejects_invalid_limit(
        self, client: AsyncClient, limit: int
    ):
        resp = await client.get(f"/api/dashboard/timeline?limit={limit}")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_jobs_returns_generation_jobs(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        job = GenerationJob(
            job_type="generate_track",
            capability="generate_music",
            provider="MockMusicProvider",
            status="failed",
            attempts=1,
            error_message="provider down",
            input_json='{"prompt": "ambient"}',
        )
        db_session.add(job)
        await db_session.commit()

        resp = await client.get("/api/dashboard/jobs")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["job_type"] == "generate_track"
        assert data[0]["capability"] == "generate_music"
        assert data[0]["provider"] == "MockMusicProvider"
        assert data[0]["status"] == "failed"
        assert data[0]["error_message"] == "provider down"
        assert data[0]["input"]["prompt"] == "ambient"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("limit", [0, -1, 101])
    async def test_jobs_rejects_invalid_limit(
        self, client: AsyncClient, limit: int
    ):
        resp = await client.get(f"/api/dashboard/jobs?limit={limit}")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_timeline_health_reports_diagnostics(
        self, client: AsyncClient, db_session: AsyncSession, tmp_path
    ):
        ready_file = tmp_path / "ready.wav"
        ready_file.write_bytes(b"audio")
        missing_file = tmp_path / "missing.wav"

        track = Track(filepath=str(ready_file), title="Ready Track", status="ready")
        dj_break = DJBreak(
            audio_filepath=str(ready_file),
            script_text="Break",
            status="ready",
        )
        talk_segment = TalkSegment(
            audio_filepath=str(ready_file),
            segment_type="monologue",
            status="ready",
        )
        asset_missing_file = AudioAsset(
            asset_type="music_track",
            normalized_filepath=str(missing_file),
            status="ready",
        )
        asset_for_orphan = AudioAsset(
            asset_type="dj_break",
            normalized_filepath=str(ready_file),
            status="ready",
        )
        db_session.add_all(
            [track, dj_break, talk_segment, asset_missing_file, asset_for_orphan]
        )
        await db_session.flush()
        db_session.add(
            ProgramItem(
                item_type="dj_break",
                status="ready",
                audio_asset_id=None,
                source_table="dj_breaks",
                source_id=99,
            )
        )
        db_session.add(
            ProgramItem(
                item_type="dj_break",
                status="ready",
                audio_asset_id=asset_for_orphan.id,
                source_table="dj_breaks",
                source_id=100,
            )
        )
        db_session.add(
            GenerationJob(
                job_type="generate_track",
                capability="generate_music",
                status="failed",
                error_message="boom",
            )
        )
        await db_session.commit()

        resp = await client.get("/api/dashboard/timeline/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["unmirrored_ready_tracks"] == 1
        assert data["summary"]["unmirrored_ready_breaks"] == 1
        assert data["summary"]["unmirrored_ready_talk_segments"] == 1
        assert data["summary"]["program_items_without_assets"] == 1
        assert data["summary"]["ready_assets_missing_files"] == 1
        assert data["summary"]["recent_failed_jobs"] == 1
        assert data["healthy"] is False
        codes = {issue["code"] for issue in data["issues"]}
        reconciliation_codes = {
            issue["code"] for issue in data["reconciliation"]["issues"]
        }
        assert "unmirrored_ready_tracks" in codes
        assert "program_items_without_assets" in codes
        assert "ready_assets_missing_files" in codes
        assert "recent_failed_jobs" in codes
        assert "legacy_ready_missing_timeline" not in codes
        assert "legacy_ready_missing_timeline" in reconciliation_codes

    @pytest.mark.asyncio
    async def test_timeline_health_includes_reconciliation_diagnostics(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        first = Track(
            filepath="audio/tracks/first.wav",
            title="First",
            status="ready",
            created_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
        )
        second = Track(
            filepath="audio/tracks/second.wav",
            title="Second",
            status="ready",
            created_at=datetime(2026, 1, 1, 2, tzinfo=timezone.utc),
        )
        db_session.add_all([first, second])
        await db_session.flush()
        db_session.add_all(
            [
                ProgramItem(
                    item_type="music_track",
                    status="ready",
                    source_table="tracks",
                    source_id=second.id,
                    title=second.title,
                    created_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
                ),
                ProgramItem(
                    item_type="music_track",
                    status="ready",
                    source_table="tracks",
                    source_id=first.id,
                    title=first.title,
                    created_at=datetime(2026, 1, 1, 3, tzinfo=timezone.utc),
                ),
            ]
        )
        await db_session.commit()

        resp = await client.get("/api/dashboard/timeline/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["healthy"] is False
        assert data["summary"]["music_candidate_mismatch"] == 1
        assert data["reconciliation"]["parity_status"] == "drifting"
        assert data["reconciliation"]["summary"]["music_candidate_mismatch"] == 1
        assert data["reconciliation"]["comparisons"][0]["aligned"] is False
        assert "music_candidate_mismatch" in {
            issue["code"] for issue in data["issues"]
        }

    @pytest.mark.asyncio
    async def test_timeline_health_empty_is_healthy(self, client: AsyncClient):
        resp = await client.get("/api/dashboard/timeline/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["healthy"] is True
        assert data["issues"] == []

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client: AsyncClient):
        resp = await client.get("/api/dashboard/health")
        assert resp.status_code == 200
        data = resp.json()
        # All should be unconfigured in test
        assert "music" in data
        assert "scriptwriter" in data
        assert "voice" in data

    @pytest.mark.asyncio
    async def test_track_lyrics_missing_returns_404(self, client: AsyncClient):
        resp = await client.get("/api/dashboard/track/9999/lyrics")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_break_script_missing_returns_404(self, client: AsyncClient):
        resp = await client.get("/api/dashboard/break/9999/script")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Recording router
# ---------------------------------------------------------------------------


class TestRecordingRouter:
    @pytest.mark.asyncio
    async def test_toggle_playout_failure_leaves_db_unchanged(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        from server.engine.playout import PlayoutInterface

        station = Station(recording_enabled=False)
        db_session.add(station)
        await db_session.commit()

        async def failing_start(self) -> bool:
            return False

        monkeypatch.setattr(PlayoutInterface, "start_recording", failing_start)

        resp = await client.post("/api/recording/toggle", json={"enabled": True})

        assert resp.status_code == 502
        db_session.expire_all()
        result = await db_session.execute(select(Station).limit(1))
        assert result.scalar_one().recording_enabled is False

    @pytest.mark.asyncio
    async def test_toggle_success_commits_and_reports_real_state(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        from server.engine.playout import PlayoutInterface

        station = Station(recording_enabled=False)
        db_session.add(station)
        await db_session.commit()

        async def ok_start(self) -> bool:
            return True

        async def recording_on(self) -> bool:
            return True

        monkeypatch.setattr(PlayoutInterface, "start_recording", ok_start)
        monkeypatch.setattr(PlayoutInterface, "is_recording", recording_on)

        resp = await client.post("/api/recording/toggle", json={"enabled": True})

        assert resp.status_code == 200
        assert resp.json() == {"enabled": True, "active": True}
        db_session.expire_all()
        result = await db_session.execute(select(Station).limit(1))
        assert result.scalar_one().recording_enabled is True


# ---------------------------------------------------------------------------
# API catch-all
# ---------------------------------------------------------------------------


class TestApiCatchAll:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def test_unknown_api_path_returns_json_404(
        self, client: AsyncClient, method: str
    ):
        resp = await client.request(method, "/api/nonexistent/endpoint")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Not found"}


# ---------------------------------------------------------------------------
# PlayLog router
# ---------------------------------------------------------------------------


class TestPlayLogRouter:
    @pytest.mark.asyncio
    async def test_list_empty(self, client: AsyncClient):
        resp = await client.get("/api/playlog")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "query",
        [
            "start_date=not-a-date",
            "end_date=2026-13-01",
            "start_date=2026-01-01T00:00:00&end_date=garbage",
        ],
    )
    async def test_invalid_date_filter_returns_422(
        self, client: AsyncClient, query: str
    ):
        resp = await client.get(f"/api/playlog?{query}")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_date_filter_accepts_z_suffix(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        db_session.add(
            PlayLog(
                item_type="track",
                item_id=1,
                started_at=datetime(2026, 1, 15, 12, 0),
                duration=180.0,
            )
        )
        await db_session.commit()

        resp = await client.get(
            "/api/playlog?start_date=2026-01-01T00:00:00Z&end_date=2026-02-01T00:00:00Z"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        # Stored naive UTC must serialize with an explicit UTC offset
        assert data["items"][0]["started_at"] == "2026-01-15T12:00:00+00:00"

    @pytest.mark.asyncio
    async def test_export_csv_empty(self, client: AsyncClient, engine, monkeypatch):
        self._patch_export_factory(engine, monkeypatch)
        resp = await client.get("/api/playlog/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        lines = resp.text.strip().split("\n")
        assert len(lines) == 1  # Header only

    @staticmethod
    def _patch_export_factory(engine, monkeypatch) -> None:
        """Point the export's own session factory at the test engine."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        import server.routers.playlog as playlog_router

        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        monkeypatch.setattr(playlog_router, "get_session_factory", lambda: factory)

    @pytest.mark.asyncio
    async def test_export_csv_guards_formula_injection(
        self, client: AsyncClient, db_session: AsyncSession, engine, monkeypatch
    ):
        self._patch_export_factory(engine, monkeypatch)
        db_session.add(
            PlayLog(
                item_type="track",
                item_id=1,
                started_at=datetime(2026, 1, 1, 12, 0),
                duration=180.0,
                metadata_json='=HYPERLINK("http://evil.example")',
            )
        )
        await db_session.commit()

        resp = await client.get("/api/playlog/export")

        assert resp.status_code == 200
        assert "'=HYPERLINK" in resp.text
        # Timestamps carry the explicit UTC offset
        assert "2026-01-01T12:00:00+00:00" in resp.text

    @pytest.mark.asyncio
    async def test_export_csv_streams_all_batches(
        self, client: AsyncClient, db_session: AsyncSession, engine, monkeypatch
    ):
        import server.routers.playlog as playlog_router

        self._patch_export_factory(engine, monkeypatch)
        monkeypatch.setattr(playlog_router, "EXPORT_BATCH_SIZE", 2)
        for i in range(5):
            db_session.add(
                PlayLog(
                    item_type="track",
                    item_id=i,
                    started_at=datetime(2026, 1, 1, i, 0),
                )
            )
        await db_session.commit()

        resp = await client.get("/api/playlog/export")

        lines = resp.text.strip().split("\n")
        assert len(lines) == 6  # header + 5 rows


# ---------------------------------------------------------------------------
# Stream router
# ---------------------------------------------------------------------------


class TestStreamRouter:
    @pytest.mark.asyncio
    async def test_get_stream_url(self, client: AsyncClient):
        resp = await client.get("/api/stream/url")
        assert resp.status_code == 200
        assert "url" in resp.json()


# ---------------------------------------------------------------------------
# Shows router
# ---------------------------------------------------------------------------


class TestShowsRouter:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"name": ""},
            {"name": "Bad Type", "show_type": "weather"},
            {"name": "Zero Duration", "duration_minutes": 0},
            {"name": "Negative Duration", "duration_minutes": -5},
        ],
    )
    async def test_create_rejects_invalid_show_fields(
        self, client: AsyncClient, payload: dict
    ):
        resp = await client.post("/api/shows", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"name": ""},
            {"show_type": "weather"},
            {"duration_minutes": 0},
            {"duration_minutes": -5},
        ],
    )
    async def test_update_rejects_invalid_show_fields(
        self, client: AsyncClient, payload: dict
    ):
        create_resp = await client.post(
            "/api/shows",
            json={"name": "Morning Block", "show_type": "music"},
        )
        assert create_resp.status_code == 201

        resp = await client.put(
            f"/api/shows/{create_resp.json()['id']}",
            json=payload,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Audio files
# ---------------------------------------------------------------------------


class TestAudioFiles:
    @pytest.mark.asyncio
    async def test_serves_generated_audio_files(
        self, client: AsyncClient, tmp_path, monkeypatch
    ):
        """Preview audio URLs should return audio bytes, not the SPA shell."""
        from server.config import settings

        audio_root = tmp_path / "audio"
        breaks_dir = audio_root / "breaks"
        breaks_dir.mkdir(parents=True)
        preview_file = breaks_dir / "preview.wav"
        preview_file.write_bytes(b"fake wav")
        monkeypatch.setattr(settings, "AUDIO_DIR", str(audio_root))

        resp = await client.get("/audio/breaks/preview.wav")

        assert resp.status_code == 200
        assert resp.content == b"fake wav"
        assert "text/html" not in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Talk show router
# ---------------------------------------------------------------------------


class TestTalkShowRouter:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"name": "", "segment_min_duration": 120},
            {"name": "Talk", "segment_min_duration": 0},
            {"name": "Talk", "segment_max_duration": 0},
            {"name": "Talk", "segment_gap": -1},
            {"name": "Talk", "topic_rotation": "chaos"},
            {"name": "Talk", "max_speakers": 0},
        ],
    )
    async def test_create_rejects_invalid_talk_config_fields(
        self, client: AsyncClient, payload: dict
    ):
        resp = await client.post("/api/talk/configs", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_accepts_sequential_topic_rotation(self, client: AsyncClient):
        resp = await client.post(
            "/api/talk/configs",
            json={"name": "Sequential Talk", "topic_rotation": "sequential"},
        )

        assert resp.status_code == 201
        assert resp.json()["topic_rotation"] == "sequential"

    @pytest.mark.asyncio
    async def test_create_rejects_segment_min_greater_than_max(
        self, client: AsyncClient
    ):
        resp = await client.post(
            "/api/talk/configs",
            json={
                "name": "Bad Timing",
                "segment_min_duration": 900,
                "segment_max_duration": 300,
            },
        )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_update_rejects_segment_min_greater_than_max(
        self, client: AsyncClient
    ):
        create_resp = await client.post(
            "/api/talk/configs",
            json={
                "name": "Timing",
                "segment_min_duration": 120,
                "segment_max_duration": 300,
            },
        )
        config_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/talk/configs/{config_id}",
            json={"segment_min_duration": 600, "segment_max_duration": 300},
        )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_update_rejects_min_above_existing_max(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/talk/configs",
            json={
                "name": "Timing",
                "segment_min_duration": 120,
                "segment_max_duration": 300,
            },
        )
        config_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/talk/configs/{config_id}",
            json={"segment_min_duration": 600},
        )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_update_rejects_max_below_existing_min(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/talk/configs",
            json={
                "name": "Timing",
                "segment_min_duration": 300,
                "segment_max_duration": 600,
            },
        )
        config_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/talk/configs/{config_id}",
            json={"segment_max_duration": 120},
        )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"title": "", "prompt": "Discuss.", "talk_config_id": 1},
            {"title": "Topic", "prompt": "", "talk_config_id": 1},
            {"title": "Topic", "prompt": "Discuss.", "talk_config_id": 1, "topic_type": "weather"},
            {"title": "Topic", "prompt": "Discuss.", "talk_config_id": 1, "weight": 0},
            {"title": "Topic", "prompt": "Discuss.", "talk_config_id": 1, "max_plays": 0},
        ],
    )
    async def test_create_rejects_invalid_topic_fields(
        self, client: AsyncClient, payload: dict
    ):
        resp = await client.post("/api/talk/topics", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.parametrize("limit", [0, -1, 101])
    async def test_segments_rejects_invalid_limit(
        self, client: AsyncClient, limit: int
    ):
        resp = await client.get(f"/api/talk/segments?limit={limit}")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_preview_accepts_json_body(self, client: AsyncClient, monkeypatch):
        """The React client posts preview parameters as JSON."""
        from server.engine.talk_show import TalkShowEngine

        expected_topic_id = None

        async def fake_generate_segment(
            self, session, show, config=None, topic_id=None, preview=False
        ):
            class Segment:
                id = 123
                segment_type = "conversation"
                script_text = '[{"speaker":"Host","text":"Hello"}]'
                duration = 4.0
                speakers = '["Host"]'
                audio_filepath = "audio/talks/preview.wav"

            assert topic_id == expected_topic_id
            # Router previews must never touch rotation/timeline state.
            assert preview is True
            return Segment()

        monkeypatch.setattr(TalkShowEngine, "generate_segment", fake_generate_segment)

        resp = await client.post("/api/talk/configs", json={"name": "Previewable"})
        config_id = resp.json()["id"]
        resp = await client.post(
            "/api/talk/topics",
            json={
                "talk_config_id": config_id,
                "title": "Test topic",
                "prompt": "Discuss the test.",
                "topic_type": "conversation",
            },
        )
        expected_topic_id = resp.json()["id"]

        resp = await client.post(
            "/api/talk/preview",
            json={"config_id": config_id, "topic_id": expected_topic_id},
        )

        assert resp.status_code == 200
        assert resp.json()["segment_id"] == 123
