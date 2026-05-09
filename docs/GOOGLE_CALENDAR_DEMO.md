# Google Calendar Demo Runbook

This backend already integrates with Google Calendar in two places:

- Read: `POST /scheduler/next-day-check` reads tomorrow's Google Calendar events and compares them against stored daily tasks.
- Write: `POST /appointments/{appointment_id}/approve-calendar-write` writes an approved appointment candidate into Google Calendar.

For the demo on May 10, 2026, no code change is required if we provide a valid Google OAuth access token through `.env`. The current implementation does not include a browser OAuth login or refresh-token flow, so the demo token is short-lived and should be generated shortly before the demo.

Important date rule: `POST /scheduler/next-day-check` always checks tomorrow relative to the backend clock in `Asia/Singapore`.

- If rehearsing today, May 9, 2026, use May 10, 2026 calendar events.
- If running the live demo tomorrow, May 10, 2026, use May 11, 2026 calendar events.

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

### 2. Create A Transcript With A Daily Task And Appointment

Create a demo audio file. For the live demo on May 10, 2026, use May 11, 2026 so the appointment date matches the scheduler target date:

```bash
say -o /tmp/care-demo.aiff "John needs Panadol before lunch every day. John has a doctor appointment on May eleventh twenty twenty six at ten AM."
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

Copy:

```text
appointment_candidates[0].id
daily_tasks[0].id
```

### 3. Show Next-Day Calendar Conflict Detection

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

### 4. Approve Calendar Write

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
