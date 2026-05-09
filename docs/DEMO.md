# Full Demo And Live E2E Runbook

This is the runbook for demonstrating the transcript-first caregiver workflow end to end. It assumes the frontend exists and is calling the backend API, but every step also includes the backend API shape so the flow can be tested directly with `curl`.

The demo should show one caregiver transcript producing all three buckets:

- Daily task: a routine medication/care instruction.
- Appointment candidate: a dated doctor/clinic appointment that can be written to Google Calendar after approval.
- Research task: a guarded subsidy/support lookup that produces a recommendation from verified sources.

Google Calendar is part of the same demo flow:

- Read: `POST /scheduler/next-day-check` reads tomorrow's Google Calendar events and compares them against stored daily tasks.
- Write: `POST /appointments/{appointment_id}/approve-calendar-write` writes an approved appointment candidate into Google Calendar.

For the demo on May 10, 2026, no code change is required if we provide a valid Google OAuth access token through `.env`. The current implementation does not include a browser OAuth login or refresh-token flow, so the demo token is short-lived and should be generated shortly before the demo.

Important date rule: `POST /scheduler/next-day-check` always checks tomorrow relative to the backend clock in `Asia/Singapore`.

- If rehearsing today, May 9, 2026, use May 10, 2026 calendar events.
- If running the live demo tomorrow, May 10, 2026, use May 11, 2026 calendar events.

## Frontend Demo Assumptions

The frontend does not need special Google Calendar logic for the current demo. It only needs to call the backend endpoints and render the returned artifacts.

Expected frontend screens or panels:

- Capture: upload/record caregiver audio and show transcription progress.
- Review: show extracted daily tasks, appointment candidates, and research tasks.
- Daily tasks: show pending care tasks and allow schedule edits.
- Appointment: show pending calendar-write approval and then written status.
- Research: run guarded research and show synthesized recommendation.
- Notifications: show daily task review, conflict warnings, and research readiness.

Frontend headers:

```text
X-API-Key: $API_WRITE_KEY
```

Use the write key for demo actions. A production frontend should separate read and write keys or move auth to a real user/session model.

## End-To-End Backend Flow

1. `POST /transcriptions`
   - Frontend uploads audio.
   - Backend calls the transcription provider.
   - Backend stores `transcription_session` and `transcript`.
2. `POST /transcriptions/{session_id}/process`
   - Backend redacts direct PII.
   - Backend extracts entities.
   - Backend triages into daily task, appointment, and research buckets.
3. `GET /tasks/daily`
   - Frontend shows routine care tasks.
4. `POST /scheduler/next-day-check`
   - Backend reads Google Calendar and creates `schedule_conflict` plus `notification_candidate` nodes if needed.
5. `POST /appointments/{appointment_id}/approve-calendar-write`
   - Backend writes the approved appointment into Google Calendar.
6. `POST /research/tasks/{task_id}/run`
   - Backend runs guarded research and creates a `synthesized_recommendation`.
7. `GET /notifications`
   - Frontend shows pending review, conflict, calendar, and research notifications.

The deterministic backend test for this flow is:

```bash
backend/.venv/bin/python -m pytest backend/tests/test_full_backend_e2e.py -q
```

That test uses mocked OpenAI and Google Calendar boundaries so CI stays deterministic.

## What The Code Does

### Calendar Read Flow

1. The backend calls `run_next_day_schedule_check(...)`.
2. `GoogleCalendarProvider` reads events from:

   ```text
   GET https://www.googleapis.com/calendar/v3/calendars/{GOOGLE_CALENDAR_ID}/events
   ```

3. It sends `Authorization: Bearer $GOOGLE_CALENDAR_ACCESS_TOKEN`.
4. It only reads the next-day window in `Asia/Singapore`.
5. It compares Google Calendar busy events with local `daily_task` nodes.
6. It creates:
   - `schedule_conflict` nodes
   - `notification_candidate` nodes
   - reasoning-log entries for auditability

If `GOOGLE_CALENDAR_ACCESS_TOKEN` is missing, the scheduler still runs, but it sees zero Google Calendar events.

### Calendar Write Flow

1. Transcript processing creates an `appointment_candidate` when it detects a dated appointment.
2. The candidate must have:
   - `requires_calendar_write: true`
   - `calendar_write_status: "pending_user_approval"`
   - `date`
3. The demo operator calls:

   ```text
   POST /appointments/{appointment_id}/approve-calendar-write
   ```

4. The backend creates a `user_decision` node and a `calendar_write_request` node.
5. The backend calls:

   ```text
   POST https://www.googleapis.com/calendar/v3/calendars/{GOOGLE_CALENDAR_ID}/events
   ```

6. The Google event payload contains:
   - `summary`
   - `start.dateTime`
   - `start.timeZone = "Asia/Singapore"`
   - `end.dateTime`
   - `end.timeZone = "Asia/Singapore"`
   - optional `location`
   - optional `description`
7. On success, the appointment stores:
   - `calendar_write_status: "written"`
   - `google_event_id`
   - `calendar_write_request_id`
8. On failure, the backend records `calendar_write_request.payload.status = "write_failed"` and does not mark the appointment as written.

## Required Google Setup

Use a dedicated demo Google account and calendar. Do not use a personal production calendar with sensitive events.

1. Open Google Cloud Console.
2. Create or select a demo project.
3. Enable the Google Calendar API.
4. Configure the OAuth consent screen.
5. Add the demo Google account as a test user if the app is in testing mode.
6. Create OAuth client credentials.
7. Generate an access token shortly before the demo.

Official references:

- Google OAuth 2.0 overview: https://developers.google.com/identity/protocols/oauth2
- Calendar API scopes: https://developers.google.com/workspace/calendar/api/auth
- Events insert API: https://developers.google.com/workspace/calendar/api/v3/reference/events/insert

## OAuth Token For Demo

Use the narrowest practical scope for the demo:

```text
https://www.googleapis.com/auth/calendar.events
```

Google documents this scope as allowing the app to view and edit events on calendars the user can access. The event insert endpoint accepts this scope.

Fast path for demo token generation:

1. Open OAuth 2.0 Playground:

   ```text
   https://developers.google.com/oauthplayground
   ```

2. Click the gear icon.
3. Enable `Use your own OAuth credentials`.
4. Paste the OAuth client ID and secret from the Google Cloud demo project.
5. In the scope box, enter:

   ```text
   https://www.googleapis.com/auth/calendar.events
   ```

6. Authorize the API using the demo Google account.
7. Exchange the authorization code for tokens.
8. Copy the `access_token`.
9. Put it in `.env` as `GOOGLE_CALENDAR_ACCESS_TOKEN`.

Access tokens expire. Generate the token shortly before the demo and restart the backend after updating `.env`.

## Backend Environment

Minimum demo `.env` values:

```bash
APP_ENV=development
API_READ_KEY=demo-read-key
API_WRITE_KEY=demo-write-key
CLINICIAN_REVIEW_KEY=demo-clinician-key
DATA_ENCRYPTION_KEY=replace-with-long-random-demo-secret

GOOGLE_CALENDAR_ID=primary
GOOGLE_CALENDAR_ACCESS_TOKEN=ya29...
GOOGLE_CALENDAR_API_BASE_URL=https://www.googleapis.com/calendar/v3
VENDOR_GOOGLE_CALENDAR_ENABLED=true

OPENAI_API_KEY=sk-...
TRANSCRIPTION_PROVIDER=openai
OPENAI_TRANSCRIPTION_MODEL=gpt-4o-transcribe
```

If using a separate demo calendar, set `GOOGLE_CALENDAR_ID` to that calendar ID instead of `primary`. Calendar IDs are available in Google Calendar settings under the calendar's integration settings.

## Pre-Demo Verification

### Deterministic Backend E2E

Run this first to verify the repository's expected test format:

```bash
backend/.venv/bin/python -m pytest backend/tests/test_full_backend_e2e.py -q
```

Expected:

```text
1 passed
```

This proves the mocked full flow from first transcription through all three buckets, calendar write, scheduler conflict, research recommendation, and notifications.

Run the complete backend suite when time allows:

```bash
TINYFISH_API_KEY= SEALION_API_KEY= backend/.venv/bin/python -m pytest backend/tests -q
```

### Live Token Smoke Test Format

Use this exact format once real tokens are available. This is the discovery anchor for future agents: live E2E testing with real tokens is manual curl-based, while CI uses mocked integration tests.

Required live env:

```bash
export API_WRITE_KEY=demo-write-key
export API_READ_KEY=demo-read-key
export OPENAI_API_KEY=sk-...
export GOOGLE_CALENDAR_ACCESS_TOKEN=ya29...
export GOOGLE_CALENDAR_ID=primary
```

Start the backend:

```bash
make backend
```

Health check:

```bash
curl -s http://127.0.0.1:8000/health | jq
```

Expected:

```json
{
  "ok": true,
  "service": "Caregiver Companion API"
}
```

Verify Google Calendar read access through the backend:

```bash
curl -s -X POST http://127.0.0.1:8000/scheduler/next-day-check \
  -H "X-API-Key: $API_WRITE_KEY" | jq
```

Expected:

- `calendar_event_count` is `0` or more.
- No `write_failed` notification appears just from this read check.
- If the demo calendar has a busy event tomorrow, the count should reflect it.

Optional direct Google token check:

```bash
curl -s "https://www.googleapis.com/calendar/v3/calendars/$GOOGLE_CALENDAR_ID/events?maxResults=1" \
  -H "Authorization: Bearer $GOOGLE_CALENDAR_ACCESS_TOKEN" | jq
```

If this fails with `401`, regenerate the access token.

## Demo Script

This path assumes the frontend exists. Use the curl commands only as fallback if a frontend view is missing or if you need to debug the backend during rehearsal.

### Presenter Setup

Open two browser tabs:

- The frontend on the Capture screen.
- The demo Google Calendar on the scheduler target date.

Suggested opening:

```text
This is the caregiver's day-to-day workflow. They do not need to fill out a structured medical form. They can speak naturally, and the system turns that note into care tasks, calendar actions, and support research for review.
```

### 1. Prepare A Calendar Conflict

Before the demo, add a busy event on the demo Google Calendar for the scheduler target date.

Use:

- May 10, 2026 if rehearsing on May 9, 2026.
- May 11, 2026 if running the demo on May 10, 2026.

Example:

```text
Title: Clinic prep call
Time: 11:30 AM - 12:30 PM on the scheduler target date
Calendar: demo calendar / primary
```

Presenter line:

```text
I have also placed an existing calendar event tomorrow so we can show conflict detection instead of just generating tasks in isolation.
```

### 2. Capture A Realistic Caregiver Note

In the frontend Capture screen, click Record and say this as one natural caregiver note:

```text
I'm recording this for my dad John. He needs Panadol before lunch every day. He also has a doctor appointment on May eleventh twenty twenty six at ten AM. The doctor said he may need wheelchair support soon, so please help me find Singapore wheelchair grants or subsidies.
```

Why this note works for the demo:

- "Panadol before lunch every day" becomes the daily task bucket.
- "doctor appointment on May eleventh twenty twenty six at ten AM" becomes the appointment candidate bucket.
- "wheelchair grants or subsidies" plus "doctor said he may need" becomes the guarded research bucket.

Presenter line while recording:

```text
This is intentionally a normal caregiver note: a medication reminder, an appointment, and a support question all mixed together.
```

After recording:

1. Click the frontend action that uploads/submits the audio.
2. Wait for transcription to complete.
3. Click Process, Generate plan, or the equivalent frontend action.
4. The review screen should show all three buckets.

Expected frontend result:

- Daily task: `Give Panadol before lunch`.
- Appointment: doctor appointment on May 11, 2026 at 10:00.
- Research task: wheelchair grant/support lookup pending guardrail review.

Presenter line after the review appears:

```text
The system has separated one messy note into three different workstreams: daily care execution, a calendar approval, and guarded support research.
```

Backend fallback for creating the same demo audio:

Create a demo audio file. For the live demo on May 10, 2026, use May 11, 2026 so the appointment date matches the scheduler target date:

```bash
say -o /tmp/care-demo.aiff "I'm recording this for my dad John. He needs Panadol before lunch every day. He also has a doctor appointment on May eleventh twenty twenty six at ten AM. The doctor said he may need wheelchair support soon, so please help me find Singapore wheelchair grants or subsidies."
afconvert -f WAVE -d LEI16 /tmp/care-demo.aiff /tmp/care-demo.wav
```

Upload it:

```bash
curl -s -X POST http://127.0.0.1:8000/transcriptions \
  -H "X-API-Key: $API_WRITE_KEY" \
  -H "Content-Type: audio/wav" \
  --data-binary @/tmp/care-demo.wav | jq
```

Copy:

```text
transcription_session.id
```

Process it:

```bash
curl -s -X POST http://127.0.0.1:8000/transcriptions/SESSION_ID/process \
  -H "X-API-Key: $API_WRITE_KEY" | jq
```

Expected backend output:

- `daily_tasks[0]` exists.
- `appointment_candidates[0]` exists.
- `ad_hoc_research_tasks[0]` exists.

Frontend should show three review surfaces:

- Daily task bucket: `Give Panadol before lunch`.
- Appointment bucket: doctor appointment on May 11, 2026 at 10:00.
- Research bucket: wheelchair grant/support lookup pending guardrail review.

Copy:

```text
appointment_candidates[0].id
daily_tasks[0].id
ad_hoc_research_tasks[0].id
```

### 3. Show Daily Task And Conflict Detection In The Frontend

In the frontend:

1. Open the Daily Tasks view.
2. Show the Panadol task and its timing.
3. Run or refresh the Schedule Check view/action.
4. Open Notifications.

Expected frontend result if the task overlaps the prepared Google Calendar event:

- A conflict warning appears.
- The notification references the existing calendar event title.
- The UI does not silently move the fixed clinical task.

Presenter line:

```text
Because this is a care task, the system does not silently move it around the calendar. It flags the conflict and keeps the review decision visible.
```

Backend fallback:

Run:

```bash
curl -s -X POST http://127.0.0.1:8000/scheduler/next-day-check \
  -H "X-API-Key: $API_WRITE_KEY" | jq
```

Expected if the task overlaps the prepared Google Calendar event:

- `calendar_event_count >= 1`
- `schedule_conflicts` includes the Google event title
- `notification_candidates` includes a next-day conflict warning

If there is no conflict, patch the daily task to a conflicting time:

```bash
curl -s -X PATCH http://127.0.0.1:8000/tasks/daily/DAILY_TASK_ID \
  -H "X-API-Key: $API_WRITE_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "scheduled_time": "12:00",
    "scheduling_semantics": "fixed_clinical",
    "reason": "Demo conflict timing"
  }' | jq
```

Then rerun `/scheduler/next-day-check`.

Fetch notifications directly:

```bash
curl -s http://127.0.0.1:8000/notifications \
  -H "X-API-Key: $API_READ_KEY" | jq
```

### 4. Approve Appointment Calendar Write In The Frontend

In the frontend:

1. Open the Appointment bucket or appointment detail.
2. Show that it is pending calendar-write approval.
3. Click Approve / Add to Google Calendar.
4. Switch to the Google Calendar tab.
5. Show the new doctor appointment event.

Expected frontend result:

- The appointment status changes to written.
- The UI can show the Google event link or written status.
- The event appears in the demo Google Calendar.

Presenter line:

```text
Calendar writes are explicit. The backend creates an approval record first, writes the event only after approval, and stores the Google event id back on the appointment.
```

Backend fallback:

Run:

```bash
curl -s -X POST http://127.0.0.1:8000/appointments/APPOINTMENT_ID/approve-calendar-write \
  -H "X-API-Key: $API_WRITE_KEY" | jq
```

Expected success:

- `calendar_event.id` is present.
- `calendar_event.htmlLink` is present.
- `appointment_candidate.payload.calendar_write_status` is `written`.
- A new event appears in Google Calendar.

Expected failure if the token is missing/expired:

- `calendar_event` is `null`.
- `calendar_write_request.payload.status` is `write_failed`.
- The appointment remains `pending_user_approval`.

### 5. Run Guarded Research In The Frontend

In the frontend:

1. Open the Research bucket.
2. Show the wheelchair grants/support task.
3. Click Run research or Review sources.
4. Show the resulting recommendation.

Expected frontend result:

- The research task has guardrail/provenance metadata.
- The result separates verified facts from items that need review.
- The recommendation avoids claiming eligibility unless the evidence supports it.

Presenter line:

```text
Research is guarded separately from daily care. The system should not turn every medical sentence into speculative research, but when the caregiver explicitly asks about support or grants, it creates a reviewable research task and labels evidence quality.
```

Backend fallback:

Run:

```bash
curl -s -X POST http://127.0.0.1:8000/research/tasks/RESEARCH_TASK_ID/run \
  -H "X-API-Key: $API_WRITE_KEY" | jq
```

Expected:

- `research_plan` is created.
- `guardrail_review` is created.
- `research_result` nodes are created if sources are available.
- `synthesized_recommendation` is created.

Then fetch recommendations:

```bash
curl -s http://127.0.0.1:8000/recommendations \
  -H "X-API-Key: $API_READ_KEY" | jq
```

### 6. End On Notifications And Auditability

In the frontend:

1. Open Notifications.
2. Show the daily task review, conflict warning, and research result readiness.
3. If there is an audit/provenance view, show the graph/reasoning trail for one artifact.

Presenter closing:

```text
The key point is that the assistant is not just producing text. It is building a graph of source transcript, redaction, triage decisions, care tasks, calendar approvals, research guardrails, and user-facing notifications.
```

Backend fallback:

Run:

```bash
curl -s http://127.0.0.1:8000/notifications \
  -H "X-API-Key: $API_READ_KEY" | jq
```

Expected notification kinds:

- `daily task review`
- `next-day conflict warning`
- `research result ready`

Optional audit check:

```bash
curl -s http://127.0.0.1:8000/audit \
  -H "X-API-Key: $API_READ_KEY" | jq
```

## Frontend Click Path

Use this if the frontend is available:

1. Open Capture.
2. Record or upload the demo audio.
3. Wait for transcription complete.
4. Click Process / Generate plan.
5. Show the three buckets:
   - Daily task
   - Appointment
   - Research task
6. Open Daily Tasks and show the Panadol task.
7. Run or refresh Schedule Check and show the conflict notification.
8. Open Appointment and approve Google Calendar write.
9. Open Google Calendar and show the new doctor appointment event.
10. Open Research and run the wheelchair grants task.
11. Open Notifications and show all pending items.

If any frontend view is missing, fall back to the matching curl command in the demo script.

## Do We Need Code Changes?

For tomorrow's demo: no. The backend already supports Google Calendar read and write using `GOOGLE_CALENDAR_ACCESS_TOKEN`.

For a real deployment: yes. We should add a proper OAuth flow that:

- redirects the user to Google for consent,
- stores a refresh token securely,
- refreshes access tokens automatically,
- stores token ownership per user/account,
- lets users disconnect Google Calendar,
- scopes read/write permissions separately where possible.

The current implementation is intentionally suitable for a controlled demo or pilot operator setup, not self-service production account linking.

## Troubleshooting

### `calendar_event_count` is always `0`

- Confirm `GOOGLE_CALENDAR_ACCESS_TOKEN` is set in the backend process.
- Confirm the backend was restarted after updating `.env`.
- Confirm `GOOGLE_CALENDAR_ID` points to the calendar with the busy event.
- Confirm the event is on the scheduler target date in Singapore time: May 10, 2026 for rehearsal on May 9, or May 11, 2026 for the live demo on May 10.
- Confirm `VENDOR_GOOGLE_CALENDAR_ENABLED=true`.

### Calendar write returns `write_failed`

- Regenerate the OAuth access token.
- Confirm the token includes `https://www.googleapis.com/auth/calendar.events`.
- Confirm the demo Google account has write access to the chosen calendar.
- Confirm `GOOGLE_CALENDAR_ID=primary` or the correct calendar ID.

### Event is written at the wrong time

- The backend writes events in `Asia/Singapore`.
- Check the transcript date/time extraction.
- If no time is extracted, appointment writes default to `09:00`.

### Duplicate write is rejected

This is expected. Once an appointment has `calendar_write_status: "written"` or a `google_event_id`, the backend rejects duplicate calendar inserts.
