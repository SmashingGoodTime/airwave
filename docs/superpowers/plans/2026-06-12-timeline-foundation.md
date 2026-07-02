# Timeline Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first additive foundation for the first-principles redesign: immutable audio assets, one program timeline table, and durable generation jobs.

**Architecture:** Keep the existing scheduler, buffers, and API behavior intact. Add new ORM models and migrations that future work can migrate toward without breaking current routes.

**Tech Stack:** Python, SQLAlchemy ORM, Alembic, SQLite, pytest.

---

### Task 1: Add Timeline Foundation Models

**Files:**
- Create: `server/models/audio_asset.py`
- Create: `server/models/program_item.py`
- Create: `server/models/generation_job.py`
- Modify: `server/models/__init__.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing model tests**

Add tests that create `AudioAsset`, `ProgramItem`, and `GenerationJob` records and assert their defaults.

- [ ] **Step 2: Run model tests to verify failure**

Run: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_models.py`

Expected: imports fail because the new models do not exist yet.

- [ ] **Step 3: Implement models**

Create the three model files with focused columns:
- `AudioAsset`: immutable normalized audio metadata.
- `ProgramItem`: central planned/queued/played timeline item.
- `GenerationJob`: durable provider work item with retry metadata.

- [ ] **Step 4: Export models**

Import the models in `server/models/__init__.py` and add them to `__all__`.

- [ ] **Step 5: Run model tests**

Run: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_models.py`

Expected: all model tests pass.

### Task 2: Add Alembic Migration

**Files:**
- Create: `migrations/versions/0002_timeline_foundation.py`
- Modify: `tests/test_migrations.py`

- [ ] **Step 1: Write failing migration test**

Update migration tests to assert fresh databases include `audio_assets`, `program_items`, and `generation_jobs`, with Alembic version `0002_timeline_foundation`.

- [ ] **Step 2: Run migration tests to verify failure**

Run: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_migrations.py`

Expected: migration tests fail because the new revision does not exist.

- [ ] **Step 3: Implement migration**

Add a revision whose `upgrade()` creates missing tables from loaded model metadata and whose `downgrade()` drops only the three new tables.

- [ ] **Step 4: Run migration tests**

Run: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_migrations.py`

Expected: migration tests pass.

### Task 3: Verify Whole App

**Files:**
- No source changes expected.

- [ ] **Step 1: Run backend test suite**

Run: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1`

Expected: all tests pass.

- [ ] **Step 2: Run frontend build**

Run: `npm run build` from `frontend`.

Expected: Vite production build exits 0.
