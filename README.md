# Caregiver Companion Backend

Caregiver Companion is now a backend-first, transcription-driven care workflow. The active source of truth is caregiver audio/transcript input, not NEHR/demo records or a web frontend.

The backend:

- accepts raw audio and calls OpenAI audio transcription
- stores transcription sessions and raw transcripts locally
- redacts direct PII before downstream extraction, triage, research, guardrail, and synthesis work
- rehydrates local placeholders before returning user-facing task artifacts
- triages transcripts into daily tasks, appointment candidates, and guarded ad hoc research tasks
- checks next-day Google Calendar conflicts for daily tasks
- requires explicit user approval before writing appointments to Google Calendar
- persists graph nodes, edges, and reasoning logs for auditability

## Repository Layout

```text
backend/                 FastAPI backend, graph store, transcription pipeline, tests
backend/sql/schema.sql   Postgres schema for graph nodes, edges, logs, and state
data/                    Curated fallback catalogs for grants, resources, and trajectories
docs/API_VERIFICATION.md Manual curl verification and API test coverage
docs/CI_CD.md            Backend CI workflow and testing conventions
ROADMAP.md               Backend architecture and implementation phases
```

The previous frontend code has been removed. Current development and verification should target the backend API directly.

## Setup

Install backend dependencies:

```bash
make install
```

Start the backend:

```bash
make backend
```

The API runs at:

```text
http://127.0.0.1:8000
```

## Environment

Settings are read from the repository root `.env`, then `backend/.env` if present.

Minimum for real transcription:

```bash
OPENAI_API_KEY=...
```

Optional:

```bash
DATABASE_URL=...
API_WRITE_KEY=...
GOOGLE_CALENDAR_ACCESS_TOKEN=...
GOOGLE_CALENDAR_ID=primary
TINYFISH_API_KEY=...
EXA_API_KEY=...
SEALION_API_KEY=...
SEALION_TRANSCRIPT_REVIEW_ENABLED=true
```

Without `DATABASE_URL`, the backend uses an in-memory graph store. Server reloads clear in-memory sessions.

When `SEALION_TRANSCRIPT_REVIEW_ENABLED=true`, the backend sends only the redacted transcript, not the raw transcript, to SEA-LION and stores the result as a `transcript_review` graph node.

## Useful Commands

Run backend:

```bash
make backend
```

Run tests:

```bash
make test
```

Run the full explicit backend suite:

```bash
TINYFISH_API_KEY= SEALION_API_KEY= backend/.venv/bin/python -m pytest backend/tests
```

CI/CD notes:

```bash
open docs/CI_CD.md
```

Health check:

```bash
curl -s http://127.0.0.1:8000/health | jq
```

Manual API verification:

```bash
open docs/API_VERIFICATION.md
```

## Current API Surface

Core transcript-first endpoints:

- `POST /transcriptions`
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

Legacy NEHR/demo routes are disabled by default unless `LEGACY_DEMO_ENABLED=true`.
