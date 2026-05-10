# Backend API Verification

This repository is now backend-first. The active product flow starts with audio transcription, stores the transcript locally, redacts direct PII before downstream processing, triages the result into daily tasks and ad hoc artifacts, and keeps graph nodes/edges for auditability.

Transcription language defaults to auto-detect. First-class request values are `auto`, `en`, `ms`, `ta`, `zh`, and `th`. Non-English transcripts preserve the original text and store English-normalized text for downstream extraction.

## Start The Backend

From the repository root:

```bash
make backend
```

The backend runs at:

```text
http://127.0.0.1:8000
```

Settings are loaded from the repository root `.env` first and `backend/.env` second. `backend/.env` can override root values for local backend-only work.

## Required Environment

For real transcription:

```bash
OPENAI_API_KEY=...
```

Optional API protection and privacy controls:

```bash
APP_ENV=development
API_READ_KEY=...
API_WRITE_KEY=...
CLINICIAN_REVIEW_KEY=...
DATA_ENCRYPTION_KEY=...
RAW_TRANSCRIPT_RETENTION_DAYS=30
PLACEHOLDER_MAP_RETENTION_DAYS=30
```

When any API key is set, patient/caregiver read endpoints require an accepted `X-API-Key` or `X-Clinician-Key`, and mutating endpoints require the write key. In `APP_ENV=pilot` or `APP_ENV=production`, the backend requires `API_READ_KEY`, `API_WRITE_KEY`, and `DATA_ENCRYPTION_KEY` at startup.

```bash
X-API-Key: ...
```

Normal API responses redact raw transcripts, normalized transcript text, placeholder maps, calendar event payloads, and provider error details. When `DATA_ENCRYPTION_KEY` is configured, those sensitive fields are also encrypted at rest.

For Google Calendar writes:

```bash
GOOGLE_CALENDAR_ACCESS_TOKEN=...
GOOGLE_CALENDAR_ID=primary
```

Without a Google token, appointment approval still creates an audited `calendar_write_request` with `status: "write_failed"`.

Google Calendar OAuth routes exist for production account linking, but are disabled unless `GOOGLE_CALENDAR_OAUTH_ENABLED=true`. Demo mode still uses `GOOGLE_CALENDAR_ACCESS_TOKEN` and `GOOGLE_CALENDAR_ID`.

Optional SEA-LION transcript review:

```bash
SEALION_API_KEY=...
SEALION_BASE_URL=https://api.sea-lion.ai/v1
SEALION_MODEL=aisingapore/Gemma-SEA-LION-v4-27B-IT
SEALION_TRANSCRIPT_REVIEW_ENABLED=true
```

When enabled, SEA-LION receives only redacted transcript text and redacted artifact summaries. The backend stores transcript QA, extraction sanity, and localization outputs as `transcript_review` nodes linked with `reviewed_from`. SEA-Guard may also create a flag-only secondary `guardrail_review` during research; it does not override the deterministic local guardrail.

## Smoke Checks

Health check:

```bash
curl -s http://127.0.0.1:8000/health | jq
```

Expected:

```json
{"ok": true, "service": "Caregiver Companion API"}
```

Legacy NEHR/demo runtime paths should be physically absent:

```bash
curl -i -X POST http://127.0.0.1:8000/demo/reset
```

Expected status:

```text
404 Not Found
```

## End-To-End Transcription Flow

Create a small audio file on macOS:

```bash
say -o /tmp/care.aiff "John needs Panadol before lunch every day. John has a doctor appointment on June first twenty twenty six at ten AM."
afconvert -f WAVE -d LEI16 /tmp/care.aiff /tmp/care.wav
```

Send audio for transcription:

```bash
curl -s -X POST http://127.0.0.1:8000/transcriptions \
  -H "Content-Type: audio/wav" \
  --data-binary @/tmp/care.wav | jq
```

To force a supported Singapore language instead of auto-detection:

```bash
curl -s -X POST "http://127.0.0.1:8000/transcriptions?language=ms" \
  -H "Content-Type: audio/wav" \
  --data-binary @/tmp/care.wav | jq
```

If `API_WRITE_KEY` is set, add:

```bash
-H "X-API-Key: $API_WRITE_KEY"
```

Copy `transcription_session.id`, then process:

```bash
curl -s -X POST http://127.0.0.1:8000/transcriptions/SESSION_ID/process | jq
```

Expected behavior:

- `pii_redaction` is created internally before extraction.
- for Malay/Bahasa, Tamil, or Mandarin, stored transcript nodes keep original and English-normalized text internally, but normal API responses redact both fields.
- if enabled, SEA-LION transcript QA, extraction sanity checks, non-English localization, and flag-only SEA-Guard research review run on redacted inputs and create graph review nodes.
- `daily_tasks[0].payload.description` is rehydrated for the user, for example `John needs Panadol before lunch every day`.
- `daily_tasks[0].payload.original_instruction_redacted` keeps the redacted form, for example `PERSON_1 needs Panadol before lunch every day`.
- simple medication instructions create a daily task and do not create speculative research.
- fixed-date appointments become `appointment_candidate` nodes with `requires_calendar_write: true`.

Fetch daily tasks:

```bash
curl -s http://127.0.0.1:8000/tasks/daily | jq
```

## Appointment Approval

Copy an appointment candidate id from the process response, then approve:

```bash
curl -s -X POST http://127.0.0.1:8000/appointments/APPOINTMENT_ID/approve-calendar-write | jq
```

### Cron and Conflict Resolution

External scheduler trigger:

```bash
curl -s -X POST http://127.0.0.1:8000/scheduler/cron/next-day-check \
  -H "X-Cron-Key: $SCHEDULER_CRON_KEY" | jq
```

List active conflicts:

```bash
curl -s http://127.0.0.1:8000/schedule-conflicts \
  -H "X-API-Key: $API_READ_KEY" | jq
```

Resolve with a safe custom time:

```bash
curl -s -X POST http://127.0.0.1:8000/schedule-conflicts/CONFLICT_ID/resolve \
  -H "X-API-Key: $API_WRITE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"action":"custom_time","scheduled_time":"11:00","reason":"Caregiver selected a clear slot."}' | jq
```

Expected without a Google token:

```json
{
  "calendar_write_request": {
    "payload": {
      "status": "write_failed"
    },
    "status": "clarification_required"
  },
  "calendar_event": null
}
```

Expected with a valid Google token:

- `calendar_write_request.payload.status` becomes `written`.
- the appointment candidate stores `calendar_write_status: "written"`.
- the response includes the Google event id/link returned by Google Calendar.

## Daily Task Edits

Patch a daily task with validated user overrides:

```bash
curl -s -X PATCH http://127.0.0.1:8000/tasks/daily/TASK_ID \
  -H "Content-Type: application/json" \
  -d '{
    "scheduling_semantics": "movable_routine",
    "scheduled_time": "11:00",
    "meal_times": {"breakfast": "08:00", "lunch": "12:30"},
    "reason": "Caregiver manually adjusted this timing."
  }' | jq
```

The backend preserves the original instruction and stores user edits under `payload.user_override`. It also creates a `caregiver_feedback` node linked with `feedback_on`.

## Notifications

Fetch polling-friendly backend notifications:

```bash
curl -s http://127.0.0.1:8000/notifications | jq
```

Notifications include:

- pending daily task review
- next-day schedule conflict warnings
- calendar write failures
- research result readiness
- dismiss/edit feedback visibility

## Privacy Controls

Record explicit consent/purpose evidence:

```bash
curl -s -X POST http://127.0.0.1:8000/privacy/consents \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_WRITE_KEY" \
  -d '{"purpose":"audio_transcription","notice_version":"pilot.v1"}' | jq
```

Create a data subject request:

```bash
curl -s -X POST http://127.0.0.1:8000/privacy/requests \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_WRITE_KEY" \
  -d '{"request_type":"access","requester":"caregiver"}' | jq
```

Clinician-only incident and retention controls:

```bash
curl -s -X POST http://127.0.0.1:8000/privacy/incidents \
  -H "Content-Type: application/json" \
  -H "X-Clinician-Key: $CLINICIAN_REVIEW_KEY" \
  -d '{"summary":"Possible transcript exposure","affected_data_categories":["transcript"]}' | jq

curl -s -X POST http://127.0.0.1:8000/privacy/retention/purge \
  -H "X-Clinician-Key: $CLINICIAN_REVIEW_KEY" | jq
```

## Automated Verification

Run the deterministic full backend E2E for the demo flow:

```bash
backend/.venv/bin/python -m pytest backend/tests/test_full_backend_e2e.py -q
```

This covers first transcription through all three buckets (`daily_tasks`, `appointment_candidates`, `ad_hoc_research_tasks`), mocked Google Calendar write, mocked next-day conflict detection, guarded research, recommendations, and notifications.

Run the complete backend suite:

```bash
TINYFISH_API_KEY= SEALION_API_KEY= backend/.venv/bin/python -m pytest backend/tests
```

Live-token testing is intentionally manual. Once real `OPENAI_API_KEY` and `GOOGLE_CALENDAR_ACCESS_TOKEN` values are available, use the format in:

```bash
open docs/DEMO.md
```

The API contract tests cover:

- write-key enforcement
- full mocked transcription route flow
- empty audio rejection before provider dispatch
- idempotent processing
- long transcript processing with daily, appointment, and research artifacts
- negative contracts for missing sessions, wrong node types, malformed edits, and unsupported fields
- direct PII redaction with local rehydration
- daily task edit validation and feedback nodes
- appointment approval and audited calendar write failure
- notification visibility for transcript-first graph nodes
- research evidence merging, where local corpus evidence is kept alongside mocked live web-search evidence
- learning context, model evaluation records, and prompt candidates that require human review
- read protection, response redaction, encrypted sensitive fields, consent/DSAR/incident records, and retention purge behavior
