# Backend API Verification

This repository is now backend-first. The active product flow starts with audio transcription, stores the transcript locally, redacts direct PII before downstream processing, triages the result into daily tasks and ad hoc artifacts, and keeps graph nodes/edges for auditability.

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

Optional write protection:

```bash
API_WRITE_KEY=...
```

When `API_WRITE_KEY` is set, mutating endpoints require:

```bash
X-API-Key: ...
```

For Google Calendar writes:

```bash
GOOGLE_CALENDAR_ACCESS_TOKEN=...
GOOGLE_CALENDAR_ID=primary
```

Without a Google token, appointment approval still creates an audited `calendar_write_request` with `status: "write_failed"`.

Optional SEA-LION transcript review:

```bash
SEALION_API_KEY=...
SEALION_BASE_URL=https://api.sea-lion.ai/v1
SEALION_MODEL=aisingapore/Gemma-SEA-LION-v4-27B-IT
SEALION_TRANSCRIPT_REVIEW_ENABLED=true
```

When enabled, SEA-LION receives the redacted transcript only. The backend stores its output as a `transcript_review` node linked to the `pii_redaction` node with `reviewed_from`.

## Smoke Checks

Health check:

```bash
curl -s http://127.0.0.1:8000/health | jq
```

Legacy NEHR/demo runtime paths should be disabled by default:

```bash
curl -i -X POST http://127.0.0.1:8000/demo/reset
```

Expected status:

```text
410 Gone
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
- if enabled, SEA-LION transcript review runs on the redacted transcript and creates a `transcript_review` graph node.
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

## Automated Verification

Run the complete backend suite:

```bash
TINYFISH_API_KEY= SEALION_API_KEY= backend/.venv/bin/python -m pytest backend/tests
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
