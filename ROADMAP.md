# Caregiver Companion Backend Roadmap

## Product Direction

Caregiver Companion is pivoting to a transcription-first backend. The primary source of truth is no longer NEHR or synthetic medical-record ingestion. The system now starts from caregiver speech, converts it into a transcript, extracts structured care information, redacts direct PII before model processing, triages the transcript into task buckets, and produces auditable care actions for review.

This roadmap is backend-only. Frontend implementation details are intentionally excluded except where an API or notification contract is required.

## Hard Product Decisions

- Remove NEHR as a source of truth.
- Remove demo-first flows and scripted demo reasoning from the target architecture.
- Treat the backend as production-oriented, not hackathon-only.
- Use OpenAI's hosted transcription API at `https://api.openai.com/v1/audio/transcriptions`.
- Use the existing OpenAI API key environment configuration for transcription and downstream LLM calls.
- Store raw transcript, redacted transcript, extracted entities, and generated task artifacts locally.
- Send raw audio to OpenAI transcription, but send only locally redacted text to downstream triage, research, guardrail, and synthesis models.
- Redact direct identifiers only. Do not redact quasi-identifiers such as age, clinic names, dates, or caregiver relationship unless they contain direct PII.
- Rehydrate PII placeholders locally before returning user-facing task outputs.
- Daily task scheduling uses next-day-only Google Calendar reads to minimize data access.
- At 10pm Singapore time daily, the backend checks the next day's possible scheduling conflicts and surfaces push-notification candidates.
- Daily tasks remain inside Caregiver Companion and should not be written to Google Calendar.
- Fixed-date ad hoc appointments are created as pending items first and require explicit user approval before Google Calendar write.

## Existing Graph Architecture

The current backend uses a graph-shaped data model:

- `nodes` are persisted objects.
- `edges` explain relationships between objects.
- `reasoning_logs` record model/tool decisions for auditability.

In the old architecture, a typical chain looked like:

```text
nehr_record
  -> inferred_condition
  -> scheduled_action
  -> caregiver_feedback
```

Edges such as `derived_from`, `triggers`, `applies_to`, and `feedback_on` made each scheduled action traceable back to evidence. `reasoning_logs` stored the steps the agent took, including tool calls, intermediate observations, and final conclusions.

This architecture is worth keeping, but the source nodes must change. Instead of NEHR records, the new graph should anchor on transcription sessions.

Target graph shape:

```text
transcription_session
  -> transcript
  -> pii_redaction
  -> extracted_entities
  -> triage_decision
      -> daily_task
      -> ad_hoc_research_task
      -> appointment_candidate
      -> research_plan
      -> synthesized_recommendation
      -> user_decision
```

The graph remains useful because it gives auditability for research agents, guardrail agents, synthesis agents, scheduling decisions, Google Calendar reads/writes, and user approvals.

## Target Backend Flow

```text
Frontend audio capture
        |
        v
OpenAI audio transcription
        |
        v
Local transcript storage
        |
        v
Local direct-PII redaction with placeholder map
        |
        v
Entity extraction over redacted transcript
        |
        v
Triage model
        |
        v
Daily task bucket       Ad hoc research bucket
        |               |
        v               v
Scheduling agent        Research planner
        |               |
        v               v
Next-day calendar read  Guardrail auditor
        |               |
        v               v
Conflict detection      Research tools
        |               |
        v               v
Push notification plan  Synthesis model
        |               |
        v               v
User review/edit        User-facing recommendation schema
```

## Transcription Service

The backend receives raw audio from the frontend and calls:

```text
POST https://api.openai.com/v1/audio/transcriptions
```

Default model:

```text
gpt-4o-transcribe
```

The model should remain configurable through environment settings so the backend can move to a smaller or newer transcription model without changing API contracts.

Expected storage:

- audio metadata, not necessarily the full audio file unless explicitly required
- transcription provider
- transcription model
- raw transcript
- transcript confidence metadata if available
- request timestamp
- processing status

## Direct PII Redaction and Rehydration

The repository already has `PiiRedactor` in `backend/app/privacy.py`. The new pipeline should adapt it for transcript-first processing.

Direct PII categories:

- person names
- patient names
- caregiver names
- phone numbers
- email addresses
- NRIC/FIN-like identifiers
- direct address fragments
- date of birth

Do not redact:

- age
- appointment dates
- medication names
- dosage
- clinic or hospital names
- caregiver relationship
- medical conditions
- body parts
- calendar timing information

Recommended local representation:

```json
{
  "raw_text": "John needs to take medicine tomorrow morning.",
  "redacted_text": "PERSON_1 needs to take medicine tomorrow morning.",
  "placeholder_map": {
    "PERSON_1": "John"
  }
}
```

Downstream models should receive `redacted_text` and placeholder-aware entity payloads. User-facing outputs should be rehydrated locally:

```json
{
  "task": "Take medicine tomorrow morning",
  "assignee": "John"
}
```

Rehydration must happen after model output validation. The backend should reject or quarantine outputs that invent new placeholder IDs or produce malformed references.

## Entity Extraction Schema

First-version extractor output should be fixed schema JSON:

```json
{
  "people": [
    {
      "placeholder_id": "PERSON_1",
      "role": "patient | caregiver | clinician | unknown",
      "display_name_redacted": "PERSON_1"
    }
  ],
  "medications": [
    {
      "name": "Panadol",
      "dose": "500mg",
      "quantity": "one tablet",
      "route": "oral",
      "frequency": "daily",
      "timing_relation": "before lunch",
      "fixed_time_required": true,
      "safety_notes": []
    }
  ],
  "time_expressions": [
    {
      "raw_text": "tomorrow morning",
      "normalized_date": "YYYY-MM-DD",
      "normalized_time_window": "morning",
      "confidence": 0.0
    }
  ],
  "recurrences": [
    {
      "pattern": "daily",
      "start_date": "YYYY-MM-DD",
      "end_date": null
    }
  ],
  "appointments": [
    {
      "kind": "doctor | physio | lab | other",
      "date": "YYYY-MM-DD",
      "time": "HH:MM",
      "location": null,
      "requires_calendar_write": false
    }
  ],
  "actionables": [
    {
      "description": "Give PERSON_1 one Panadol tablet before lunch",
      "bucket_hint": "daily_task | ad_hoc_research | appointment | unclear",
      "urgency": "routine | clinical | financial | urgent",
      "confidence": 0.0
    }
  ],
  "medical_context": {
    "conditions": [],
    "body_parts": [],
    "risks": [],
    "clinician_warnings": []
  },
  "clarifications_needed": []
}
```

The extractor should not create final tasks. It only normalizes facts and uncertainties for triage.

## Triage Buckets

One transcript can produce both buckets if it contains multiple actionable ideas.

Bucket A: daily scheduled tasks.

- Low synthesis.
- Usually direct instructions.
- Examples: medication reminders, hydration, daily exercises, simple recurring care tasks.
- Should not trigger research merely because the task mentions a medication or condition.
- Medication-related daily tasks default to fixed-time unless the user later marks them movable.

Bucket B: ad hoc tasks requiring deeper synthesis and research.

- Higher synthesis.
- Usually inferred from risks, clinician warnings, future possibilities, grants, equipment needs, or policy questions.
- Examples: wheelchair grant research, amputation support planning, home modification schemes, medical subsidies, care-service options.
- Must pass guardrail review before research tools are called.

Guardrail rule:

```text
Do not allow research expansion from a simple direct daily instruction unless the transcript also contains an explicit future risk, uncertainty, grant question, equipment need, clinician warning, or user request for research.
```

Example:

```text
"Give Panadol daily before lunch."
```

Expected output:

```text
daily_task only
```

Forbidden output:

```text
research_task: investigate why Panadol is needed
```

## Daily Task Scheduling

Daily tasks are stored in Caregiver Companion and surfaced through the app plus push notifications. They are not written to Google Calendar.

Scheduling semantics:

- `fixed_clinical`: medication, clinician-directed fixed timing, safety-critical tasks
- `fixed_deadline`: must occur before a deadline
- `movable_routine`: low-risk task that can shift within a user-approved window
- `movable_preference`: household preference task
- `unclear`: requires user clarification

Medication defaults:

- medication tasks default to `fixed_clinical`
- user can later edit task timing and whether the task is movable
- backend must preserve the original instruction and the user's override separately

Scheduling agent responsibilities:

- infer timing windows from medication instructions
- avoid compressing repeated medication doses too close together
- flag unsafe or suspicious timing instead of silently scheduling
- surface conflicts and ask for review when instructions are under-specified
- explain why a task is fixed or movable

Example conflict:

```text
Instruction: "three times a day before food"
Known meals: breakfast 10:00, lunch 11:30
```

The scheduler should not blindly schedule doses at 10:00 and 11:30. It should flag that the spacing is likely too close for a three-times-daily medication pattern and request user or clinician clarification.

## Google Calendar Integration

For MVP, use one demo Google account. This is an integration simplification, not a demo-quality product assumption.

Calendar read policy:

- read only the next day's events
- use the minimum Google Calendar scope needed for read-only conflict detection
- do not ingest broad historical calendar data
- do not use Google Calendar as the storage layer for daily tasks

Daily 10pm Singapore time job:

```text
At 22:00 Asia/Singapore:
  read tomorrow's Google Calendar events
  load tomorrow's active Caregiver Companion daily tasks
  detect conflicts
  classify conflicts as movable, fixed, or unsafe/unclear
  generate push notification candidates
  write an auditable scheduling log
```

Appointment write policy:

- ad hoc fixed-date appointments become pending appointment candidates
- user must approve before backend writes to Google Calendar
- backend should request create/update permission only when write is enabled
- backend must not request permission to delete existing calendar events

## Push Notifications and Event Emission

Daily task notifications should be app-owned.

Recommended backend contract:

- persist notification candidates
- expose REST endpoints for polling
- add SSE or WebSocket later only if real-time delivery becomes necessary
- keep push-provider integration behind an adapter

Notification categories:

- next-day conflict warning
- fixed clinical reminder
- movable routine reminder
- clarification required
- research result ready
- appointment approval required

For the product roadmap, REST polling plus persisted notification candidates is the simplest robust first step. It keeps backend state auditable and avoids coupling planning logic to a specific push vendor.

## Ad Hoc Research Pipeline

The ad hoc bucket should use a multi-stage agent pipeline:

```text
redacted transcript + extracted entities
        |
        v
research planner model
        |
        v
guardrail auditor model
        |
        v
approved research tool calls
        |
        v
research result bundle
        |
        v
synthesis model
        |
        v
frontend-ready recommendation schema
```

Research planner:

- identifies what might need research
- proposes search questions
- proposes required tools
- states why the research is relevant to the transcript
- must operate on redacted text

Guardrail auditor:

- approves, narrows, or blocks proposed research
- prevents research that is speculative, irrelevant, unsafe, or based only on a simple daily task
- enforces source trust tiers and makes sure informal sources are labeled correctly
- flags medical advice risk
- flags unsupported grant eligibility claims
- logs its decision before any external research tool is called

Research tools:

- prefer existing curated grant/resource data first
- use TinyFish and Exa for live research when freshness matters
- use official and high-trust Singapore sources for verified statutory-board, grant, subsidy, eligibility, and application facts
- allow broader discovery from news sites, Reddit, forums, blogs, and caregiver community posts when useful for surfacing lived-experience leads, practical tips, or questions worth checking
- never treat Reddit, forums, blogs, or uncited news as authoritative evidence for eligibility, medical advice, or application requirements
- record source URLs, snippets, retrieval time, source tier, and verification status

Synthesis model:

- takes the research bundle
- reduces it to caregiver-readable language
- avoids overclaiming eligibility
- produces a strict API schema
- links every recommendation to evidence
- separates verified facts from informal leads so users can make the final decision with clear source context

## Research Source Policy

Research should support agent-led discovery while making source quality visible to the user. The backend should not hide that different parts of a recommendation may come from different trust levels.

Tier 1: verified official sources.

- `gov.sg`
- `moh.gov.sg`
- `aic.sg`
- `healthhub.sg`
- `cpf.gov.sg`
- `msf.gov.sg`
- `sgenable.sg`
- other official Singapore public-sector or statutory-board domains if explicitly allowlisted

Tier 2: high-trust reference sources.

- recognized hospitals and healthcare institutions
- established charities and caregiver support organizations
- reputable clinical or public-health bodies
- major Singapore news outlets when reporting policy changes or official announcements

Tier 3: informal discovery sources.

- Reddit discussions
- caregiver forums
- Facebook-style community posts if accessible through approved tooling
- blogs and personal writeups
- general news commentary
- product reviews or marketplace discussions

Existing repository grant/resource data should remain useful, but it should become curated fallback or seed data rather than the primary source of truth for time-sensitive policy facts.

Recommended order:

```text
curated local data for known schemes
        +
verified official/high-trust live research for factual claims
        +
informal discovery sources for leads and lived-experience context
        |
        v
synthesis with source tier, freshness, and verification labels
```

User-facing research output should group claims by source status:

- `verified_fact`: sourced from official or high-trust references
- `needs_verification`: plausible but not yet confirmed by official sources
- `community_tip`: surfaced from Reddit, forums, blogs, or informal posts
- `rejected_or_unsafe`: blocked by the guardrail auditor

Example user-facing phrasing:

```text
Verified: AIC lists mobility-aid support under the Seniors' Mobility and Enabling Fund.
Community tip: Reddit/forum caregivers often suggest asking the hospital medical social worker about paperwork before buying equipment. This is not an official eligibility rule.
```

## Proposed Graph Node Types

Replace NEHR-centered nodes with transcript-centered nodes:

- `transcription_session`
- `transcript`
- `pii_redaction`
- `extracted_entities`
- `triage_decision`
- `daily_task`
- `schedule_conflict`
- `notification_candidate`
- `ad_hoc_research_task`
- `research_plan`
- `guardrail_review`
- `research_result`
- `synthesized_recommendation`
- `appointment_candidate`
- `calendar_write_request`
- `user_decision`
- `caregiver_feedback`

Proposed edge types:

- `transcribed_to`
- `redacted_as`
- `extracted_from`
- `triaged_from`
- `classified_as`
- `scheduled_from`
- `conflicts_with`
- `notifies_about`
- `researches`
- `guarded_by`
- `approved_research`
- `blocked_research`
- `synthesized_from`
- `requires_approval`
- `approved_by_user`
- `written_to_calendar`
- `feedback_on`

The exact names can change during implementation, but the graph should preserve provenance from transcript to final user-facing output.

## Reasoning Logs and Auditability

Every model or tool step should have a log entry.

Log events:

- audio transcription requested
- transcription response received
- PII redaction summary
- entity extraction prompt version and output
- triage prompt version and output
- scheduling decision
- Google Calendar read window and event count
- conflict detection result
- research planner proposal
- guardrail approval/block decision
- research tool call and source result
- synthesis model output
- rehydration validation
- user approval/edit/dismissal
- Google Calendar write result

Logs should avoid storing raw direct PII in model-facing records, but local audit storage may retain raw transcript and placeholder map under access-controlled storage.

## API Surface Draft

Initial backend endpoints:

- `POST /transcriptions`
  - accepts audio
  - calls OpenAI transcription
  - stores raw transcript
  - returns transcript session ID

- `POST /transcriptions/{id}/process`
  - redacts direct PII
  - extracts entities
  - runs triage
  - creates daily/ad hoc pending artifacts

- `GET /tasks/daily`
  - returns active daily tasks

- `PATCH /tasks/daily/{id}`
  - lets user edit timing, fixed/movable semantics, and task fields

- `POST /scheduler/next-day-check`
  - manually triggers the next-day conflict job

- `GET /notifications`
  - returns persisted notification candidates

- `GET /research/tasks`
  - returns pending and completed ad hoc research tasks

- `POST /research/tasks/{id}/run`
  - runs guarded research pipeline

- `GET /recommendations`
  - returns synthesized recommendation cards

- `POST /appointments/{id}/approve-calendar-write`
  - writes an approved fixed-date appointment to Google Calendar

## Migration Plan

Phase 1: roadmap and schema planning.

- overwrite old NEHR/demo roadmap
- define transcript-first graph types
- define redaction and rehydration policy
- define daily/ad hoc triage rules
- define next-day calendar deconfliction behavior

Phase 2: remove NEHR-centered runtime paths.

- remove or quarantine demo reset/ingest endpoints
- remove `nehr_record` as primary source node
- remove scripted Parkinson demo reasoner
- keep graph store and reasoning logs
- update tests away from demo NEHR fixtures

Phase 3: implement transcription-first ingestion.

- add OpenAI transcription provider
- keep provider configurable
- store transcription sessions and transcripts
- adapt PII redactor for direct-identifier-only transcript redaction
- persist placeholder maps locally

Phase 4: implement extraction and triage.

- add strict entity extraction schema
- add triage model contract
- create daily task and ad hoc research task artifacts
- support multi-bucket transcripts
- reject speculative research expansion for simple daily instructions

Phase 5: implement daily scheduler.

- add fixed/movable scheduling semantics
- add medication spacing checks
- integrate single demo Google account read-only access
- implement 10pm Singapore next-day conflict job
- persist notification candidates

Phase 6: implement guarded research pipeline.

- research planner model
- guardrail auditor model
- TinyFish/Exa adapters with allowlist policy
- source freshness and citation capture
- synthesis model with strict frontend schema

Phase 7: implement approval workflows.

- pending appointment candidates
- explicit user approval before Google Calendar write
- user edits for daily timing and fixed/movable classification
- feedback nodes to support future personalization

## Evaluation Plan

Core eval cases:

- simple medication transcript creates only a daily task
- transcript with multiple instructions creates multiple artifacts
- transcript with direct PII is redacted before downstream LLM calls
- placeholders are correctly rehydrated in user-facing output
- daily medication task defaults to fixed clinical timing
- medication spacing conflict is flagged
- next-day calendar conflict is detected without reading wider history
- 10pm Singapore job creates notification candidates
- ad hoc research is blocked when based only on a simple medication reminder
- ad hoc research proceeds when transcript includes explicit future risk or grant/equipment need
- synthesis output has evidence links and does not overclaim grant eligibility
- fixed-date appointment requires user approval before calendar write

Production quality metrics:

- transcription accuracy for caregiver speech
- medication/entity extraction accuracy
- date and recurrence normalization accuracy
- direct PII redaction recall
- placeholder rehydration correctness
- daily/ad hoc triage precision
- guardrail false-positive and false-negative rate
- scheduling conflict detection accuracy
- research source validity
- recommendation approval/edit/dismissal rate

## Change Log

- 2026-05-09: Rewrote roadmap around transcription-first backend architecture.
- 2026-05-09: Declared NEHR and demo-first flows deprecated for the target product direction.
- 2026-05-09: Preserved graph and reasoning-log architecture as the auditability backbone.
- 2026-05-09: Added local direct-PII redaction and local rehydration requirements.
- 2026-05-09: Added daily scheduled task vs ad hoc research task triage design.
- 2026-05-09: Added next-day-only Google Calendar deconfliction and 10pm Singapore conflict notification job.
- 2026-05-09: Added guarded research pipeline with planner, auditor, tools, and synthesis stages.
- 2026-05-09: Implemented Phase 1 graph foundation by adding transcript-first node and edge types to backend models and Postgres schema while preserving existing graph store behavior.
- 2026-05-09: Started Phase 3 before destructive Phase 2 removal so the backend has a working transcript-first ingestion path before old NEHR/demo runtime paths are quarantined.
- 2026-05-09: Added OpenAI audio transcription provider support, transcription-session/transcript graph persistence, local direct-identifier transcript redaction, placeholder maps, and rehydration validation.
- 2026-05-09: Implemented Phase 2 runtime quarantine by disabling NEHR/demo bootstrapping, demo ingest/reset endpoints, NEHR record endpoints, and scheduled demo review unless `LEGACY_DEMO_ENABLED=true`.
- 2026-05-09: Implemented Phase 4 extraction and triage with strict entity schemas, conservative daily/ad hoc/appointment bucket classification, graph artifact creation, and guardrail logic blocking speculative research from simple medication reminders.
- 2026-05-09: Implemented Phase 5 daily scheduler with next-day-only Google Calendar read adapter, fixed/movable conflict classification, three-times-daily medication spacing checks, persisted schedule conflict nodes, notification candidates, and polling-friendly notification output.
- 2026-05-09: Implemented Phase 6 guarded research pipeline with redacted research planning, guardrail approval/blocking, TinyFish/Exa-capable source-tier adapters, citation freshness capture, strict synthesized recommendation schema, and recommendation polling.
- 2026-05-09: Implemented Phase 7 approval workflows with daily task edit overrides, caregiver feedback nodes, explicit appointment approval before Google Calendar insert, and audited calendar write success/failure states.
