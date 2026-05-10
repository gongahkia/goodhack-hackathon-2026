# Caregiver Companion Backend

## Purpose
- Backend-first, transcription-driven care workflow.
- Source of truth: caregiver audio/transcript input.
- Removed: previous frontend, legacy NEHR/demo runtime, raw NEHR storage.
- Runtime flow starts from caregiver transcripts, not demo records.

## Core Flow
- Accept raw audio via OpenAI transcription.
- Support language hints: `auto`, `en`, `ms`, `ta`, `zh`, `th`.
- Store transcription sessions, original transcripts, and English-normalized text.
- Redact direct PII before extraction, triage, research, guardrail, and synthesis work.
- Rehydrate local placeholders before returning user-facing task artifacts.
- Triage transcripts into daily tasks, appointment candidates, and guarded ad hoc research tasks.
- Check next-day Google Calendar conflicts for daily tasks.
- Require explicit user approval before Google Calendar writes.
- Persist graph nodes, edges, and reasoning logs for auditability.

## Repository Layout
- `backend/`: FastAPI backend, graph store, transcription pipeline, tests.
- `backend/sql/schema.sql`: Postgres schema for graph nodes, edges, logs, and state.
- `backend/scripts/ralph_loop.py`: Bounded robustness loop.
- `data/`: Curated fallback catalogs for grants, resources, and trajectories.
- `docs/ARCHITECTURE.md`: Mermaid architecture diagrams and roadmap validation.
- `docs/API_VERIFICATION.md`: Manual curl verification and API test coverage.
- `docs/CI_CD.md`: Backend CI workflow and testing conventions.
- `docs/DEMO.md`: Full demo and live E2E runbook.
- `docs/LEARNING_HARNESS.md`: Context engineering, evals, and prompt candidate workflow.
- `docs/ROADMAP.md`: Backend architecture and implementation phases.

## Architecture
- Client/API caller talks to FastAPI.
- FastAPI uses `GraphStore` backed by memory or Postgres.
- Transcription feeds redaction, extraction, triage, scheduling, research, recommendations, and audit state.
- Daily tasks may create schedule conflict notifications.
- Appointment candidates require approval before calendar write requests.
- Ad hoc research tasks synthesize recommendations from curated and live research tools.
- Full diagrams: `open docs/ARCHITECTURE.md`.

## Setup
- Install `uv`.
- Install backend deps: `make install`.
- Run API: `make backend`.
- API base URL: `http://127.0.0.1:8000`.
- Health check: `curl -s http://127.0.0.1:8000/health | jq`.

## Environment
- Config load order: repo root `.env`, then `backend/.env`.
- Minimum real transcription env: `OPENAI_API_KEY`.
- In-memory graph store is used when `DATABASE_URL` is empty.
- Server reloads clear in-memory sessions.
- Transcription language override: `POST /transcriptions?language=ms` or `POST /transcribe?language=zh`.
- First-class language hints: `auto`, `en`, `ms`, `ta`, `zh`, `th`; locale/name aliases such as `en-SG`, `bahasa melayu`, `தமிழ்`, `zh-Hans`, `普通话`, and `ภาษาไทย` normalize to those codes.
- Non-English transcripts preserve original text and add English-normalized text.
- Optional external keys: `TINYFISH_API_KEY`, `EXA_API_KEY`, `SEALION_API_KEY`, `JINA_API_KEY`, `OPENALEX_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY`.
- Optional Google Calendar: `GOOGLE_CALENDAR_ACCESS_TOKEN`, `GOOGLE_CALENDAR_ID=primary`.
- Optional auth: `API_READ_KEY`, `API_WRITE_KEY`, `CLINICIAN_REVIEW_KEY`.
- Optional encryption: `DATA_ENCRYPTION_KEY`.
- Pilot/prod requires `API_READ_KEY`, `API_WRITE_KEY`, and `DATA_ENCRYPTION_KEY`.
- `GET /health` stays public and returns minimal service status.

## Security & Privacy
- Read endpoints require `X-API-Key` or `X-Clinician-Key` when any API key is configured.
- Mutating endpoints require the write key when API keys are configured.
- `DATA_ENCRYPTION_KEY` encrypts sensitive persisted fields at rest.
- Encrypted fields include raw transcripts, normalized transcripts, placeholder maps, calendar payloads, and provider errors.
- Normal API responses redact raw transcript fields and placeholder maps.
- SEA-LION review sends only redacted text/artifacts when enabled.
- SEA-LION outputs are stored as review nodes/localized display payloads.
- SEA-LION flags do not overwrite canonical transcript, extraction, or research data.

## Commands
- `make help`: List supported targets.
- `make install`: Create backend venv and install deps.
- `make backend`: Run FastAPI on `127.0.0.1:8000`.
- `make test`: Run backend tests with `pytest -q`.
- `make live-external-e2e`: Run opt-in live external-provider E2E.
- `make robustness-loop`: Run bounded frontend-readiness robustness checks.
- `make clean`: Remove backend cache artifacts.
- Full backend suite: `TINYFISH_API_KEY= SEALION_API_KEY= backend/.venv/bin/python -m pytest backend/tests`.

## API Surface
- `POST /transcriptions`
- `WS /transcriptions/live`
- `POST /transcriptions/{session_id}/process`
- `POST /transcripts/{transcript_id}/redact`
- `POST /transcripts/{transcript_id}/process`
- `GET /tasks/daily`
- `PATCH /tasks/daily/{task_id}`
- `POST /scheduler/next-day-check`
- `GET /research/tasks`
- `POST /research/tasks/{task_id}/run`
- `GET /recommendations`
- `POST /appointments/{appointment_id}/approve-calendar-write`
- `GET /notifications`
- `GET /audit`
- `POST /privacy/consents`
- `POST /privacy/requests`
- `POST /privacy/incidents`
- `POST /privacy/retention/purge`

## Live Caption Contract
- Frontend should show browser speech-recognition captions immediately.
- Optionally connect to `WS /transcriptions/live?language=en&content_type=audio/webm`.
- Browser clients may pass the write key as `api_key` query param because native WebSocket cannot set `X-API-Key`.
- Send binary audio chunks, then `{"type":"commit"}`.
- Backend returns `ready`, per-chunk `ack`, then `final` with the same stored transcript shape as `POST /transcriptions`.
- Current backend WS is batch-on-commit and does not emit partial words; browser captions stay the live fallback.

## Verification
- Unit/API tests: `make test`.
- Robustness loop: `make robustness-loop`.
- Manual API checks: `open docs/API_VERIFICATION.md`.
- CI/CD notes: `open docs/CI_CD.md`.
- Learning harness notes: `open docs/LEARNING_HARNESS.md`.
- Full demo/live E2E: `open docs/DEMO.md`.
