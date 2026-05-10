# Project Architecture And Data Flow

Verified: 2026-05-10.

## Scope

This document covers the current backend repository. No production frontend is present in repo. The source of truth is caregiver audio or transcript input, converted into three output buckets:

- Google Calendar appointment candidates.
- Daily task scheduling/review and next-day conflict checks.
- Ad hoc research tasks and recommendations.

## Architecture

![Project architecture and data flow](./project-architecture-data-flow-diagram.svg)

```mermaid
flowchart LR
  Client[Caregiver/API client] --> API[FastAPI app]
  API --> Auth[API key auth, CORS, rate limits]
  API --> Store[(GraphStore: memory or Postgres)]

  API --> TP[transcript pipeline]
  TP --> STT[transcription provider]
  STT --> OAI[OpenAI gpt-4o-transcribe]
  STT --> Groq[Groq optional]
  STT --> Local[local MLX/faster-whisper optional]

  TP --> Redact[PII redaction]
  Redact --> Extract[entity extraction]
  Extract --> Triage[triage decision]

  Triage --> Daily[daily_task]
  Triage --> Appt[appointment_candidate]
  Triage --> Research[ad_hoc_research_task]

  Daily --> Scheduler[next-day scheduler]
  Scheduler --> GCalRead[Google Calendar events.list]
  Scheduler --> Conflict[schedule_conflict]

  Appt --> Approval[user decision]
  Approval --> CalendarWrite[calendar_write_request]
  CalendarWrite --> GCalWrite[Google Calendar events.insert]

  Research --> Guard[guardrail review]
  Guard --> Search[curated corpus and live search]
  Search --> Result[research_result]
  Result --> Synth[synthesized_recommendation]

  Conflict --> Notify[notifications]
  Daily --> Notify
  CalendarWrite --> Notify
  Synth --> Notify

  Store --> Audit[reasoning logs, consent, processing activity, retention]
```

## Core Components

| Component | File | Role |
|---|---|---|
| API app | `backend/app/main.py` | Routes, startup, auth dependency wiring, scheduler startup. |
| Config | `backend/app/config.py` | Env-driven vendor keys, model defaults, scheduler, Google Calendar settings. |
| Store | `backend/app/store.py` | Graph abstraction with memory and Postgres implementations. |
| Schema | `backend/sql/schema.sql` | Nodes, edges, reasoning logs, provenance, indexes. |
| Transcription | `backend/app/transcription.py` | OpenAI/Groq/local transcription and normalization. |
| Transcript pipeline | `backend/app/transcript_pipeline.py` | Session node creation, transcript node creation, redaction node creation. |
| Privacy | `backend/app/privacy.py` | PII placeholder mapping and local rehydration. |
| Extraction | `backend/app/extraction.py` | Entity extraction, triage, task/candidate node creation. |
| Scheduler | `backend/app/scheduler.py` | Next-day calendar read, conflict detection, notification candidate creation. |
| Approvals | `backend/app/approvals.py` | Daily patching and approved Google Calendar writes. |
| Research | `backend/app/research.py` | Planning, guardrails, search/fetch/extract/synthesis. |
| Notifications | `backend/app/notifications.py` | User-facing notification aggregation. |
| Compliance | `backend/app/compliance.py` | Consent, processing activity, retention purge. |

## Graph Model

Key node types:

- `transcription_session`
- `transcript`
- `pii_redaction`
- `extracted_entities`
- `triage_decision`
- `daily_task`
- `appointment_candidate`
- `ad_hoc_research_task`
- `research_plan`
- `guardrail_review`
- `research_result`
- `synthesized_recommendation`
- `schedule_conflict`
- `notification_candidate`
- `calendar_write_request`
- `user_decision`

Key edge types:

- `transcribed_to`
- `redacted_as`
- `classified_as`
- `scheduled_from`
- `generated`
- `requires_approval`
- `approved_as`
- `wrote_to_calendar`

## End-To-End Data Flow

```mermaid
flowchart TD
  A[audio upload or live websocket] --> B[transcription_session]
  B --> C[STT provider]
  C --> D[normalized English transcript]
  D --> E[PII redaction]
  E --> F[extracted_entities]
  F --> G[triage_decision]

  G --> A1[appointment bucket]
  A1 --> A2[appointment_candidate]
  A2 --> A3[user approves calendar write]
  A3 --> A4[user_decision]
  A4 --> A5[calendar_write_request]
  A5 --> A6[Google Calendar events.insert]
  A6 --> A7[appointment written or write_failed]
  A7 --> N[notifications and audit graph]

  G --> D1[daily task bucket]
  D1 --> D2[daily_task pending review]
  D2 --> D3[user review or patch]
  D3 --> D4[22:00 Asia/Singapore next-day check]
  D4 --> D5[Google Calendar events.list]
  D5 --> D6[conflict detection]
  D6 --> D7[schedule_conflict and notification_candidate]
  D7 --> N

  G --> R1[ad hoc research bucket]
  R1 --> R2[ad_hoc_research_task]
  R2 --> R3[research_plan]
  R3 --> R4[guardrail_review]
  R4 --> R5[curated corpus plus live search]
  R5 --> R6[page fetch and extraction]
  R6 --> R7[research_result nodes]
  R7 --> R8[synthesized_recommendation]
  R8 --> N
```

## Appointment Flow

1. Transcript extraction identifies date/time/location intent.
2. `appointment_candidate` is created with `requires_calendar_write`.
3. User explicitly approves.
4. `user_decision` and `calendar_write_request` nodes are created.
5. Google Calendar `events.insert` is called.
6. Candidate status becomes written or failed.
7. Notification output reflects write status.

Important constraint: appointments write to Google Calendar only after user approval.

## Daily Task Flow

1. Extraction identifies actionable care instruction.
2. `daily_task` is created.
3. User can review/patch task state.
4. Scheduled check reads next-day Google Calendar events.
5. Conflict detector compares task timing to appointments.
6. `schedule_conflict` and `notification_candidate` are created when needed.

Important constraint: daily tasks are not written to Google Calendar in current code.

## Ad Hoc Research Flow

1. Extraction identifies explicit research intent.
2. `ad_hoc_research_task` is created.
3. Research pipeline creates `research_plan`.
4. Guardrail blocks simple daily instructions and low-basis medical queries.
5. Search uses curated local corpus and optional live providers.
6. Fetched pages are extracted with OpenAI when configured, otherwise local fallback.
7. `research_result` nodes feed `synthesized_recommendation`.
8. Recommendation is returned through `/recommendations` and `/notifications`.

Important constraint: live research depends on vendor keys and vendor allow-list settings.

## Output Surfaces

| Output | Endpoint | Backing nodes |
|---|---|---|
| Notifications | `GET /notifications` | `notification_candidate`, daily/research/calendar status nodes |
| Daily tasks | `GET /tasks/daily` | `daily_task` |
| Daily task patch | `PATCH /tasks/daily/{task_id}` | `daily_task` |
| Scheduler check | `POST /scheduler/next-day-check` | `daily_task`, `schedule_conflict`, `notification_candidate` |
| Research tasks | `GET /research/tasks` | `ad_hoc_research_task` |
| Run research | `POST /research/tasks/{task_id}/run` | `research_plan`, `guardrail_review`, `research_result`, `synthesized_recommendation` |
| Recommendations | `GET /recommendations` | `synthesized_recommendation` |
| Calendar approval | `POST /appointments/{appointment_id}/approve-calendar-write` | `appointment_candidate`, `user_decision`, `calendar_write_request` |

## Deployment-Relevant Architecture Notes

- Memory store is suitable only for local/demo use.
- Postgres is required for durable graph lineage.
- In-process scheduler is acceptable for local runs; use external Cloud Scheduler for serverless production. `[Inference]`
- Research should become an async worker at growth scale. `[Inference]`
- Google Calendar multi-user support needs proper OAuth refresh-token flow. `[Inference]`
