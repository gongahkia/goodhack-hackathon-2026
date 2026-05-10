# Backend Architecture

This repository is a backend-first, transcript-driven caregiver workflow. The API accepts caregiver audio, stores transcript artifacts, redacts direct PII before downstream processing, triages each transcript into care buckets, and persists every artifact as graph nodes and edges for auditability.

## System Context

```mermaid
flowchart LR
    Frontend["Frontend / API Client"]
    Backend["FastAPI backend\nbackend/app/main.py"]
    Store["GraphStore\nMemory or Postgres"]
    OpenAI["OpenAI\ntranscription + normalization"]
    SeaLion["SEA-LION optional review"]
    Search["Curated corpus + Exa/TinyFish/Jina/OpenAlex/Semantic Scholar"]
    Google["Google Calendar API"]

    Frontend -->|"audio, edits, approvals"| Backend
    Backend -->|"nodes, edges, reasoning logs"| Store
    Backend -->|"raw audio"| OpenAI
    Backend -->|"redacted text/artifacts"| SeaLion
    Backend -->|"redacted/allowlisted research queries"| Search
    Backend -->|"next-day event read + approved appointment write"| Google
    Backend -->|"sanitized JSON responses"| Frontend
```

## End-To-End Flow

```mermaid
flowchart TD
    A["POST /transcriptions\nRaw caregiver audio"] --> B["Transcription session"]
    B --> C["Transcript\nraw + normalized text stored locally"]
    C --> D["PII redaction\nredacted_text + placeholder_map"]
    D --> E["Entity extraction\npeople, meds, time, appointments, actionables"]
    E --> F["Triage decision"]

    F --> G["Daily task bucket"]
    F --> H["Appointment candidate bucket"]
    F --> I["Ad hoc research bucket"]

    G --> J["PATCH /tasks/daily/{id}\nuser timing overrides"]
    G --> K["POST /scheduler/next-day-check\nGoogle Calendar read"]
    K --> L["schedule_conflict"]
    L --> M["notification_candidate"]

    H --> N["POST /appointments/{id}/approve-calendar-write"]
    N --> O["calendar_write_request"]
    O --> P["Google Calendar event"]

    I --> Q["POST /research/tasks/{id}/run"]
    Q --> R["research_plan"]
    R --> S["guardrail_review"]
    S --> T["research_result"]
    T --> U["synthesized_recommendation"]

    M --> V["GET /notifications"]
    U --> V
    J --> V
```

## Graph Lineage

```mermaid
flowchart TD
    TS["transcription_session"] -- transcribed_to --> T["transcript"]
    T -- redacted_as --> PII["pii_redaction"]
    PII -- extracted_from --> EE["extracted_entities"]
    EE -- triaged_from --> TD["triage_decision"]

    TD -- classified_as --> DT["daily_task"]
    TD -- classified_as --> AC["appointment_candidate"]
    TD -- classified_as --> RT["ad_hoc_research_task"]

    DT -- conflicts_with --> SC["schedule_conflict"]
    SC -- notifies_about --> NC["notification_candidate"]

    AC -- requires_approval --> CWR["calendar_write_request"]
    CWR -- approved_by_user --> UD["user_decision"]
    CWR -- written_to_calendar --> AC

    RT -- researches --> RP["research_plan"]
    RP -- guarded_by --> GR["guardrail_review"]
    GR -- approved_research --> RP
    GR -- blocked_research --> RP
    RR["research_result"] -- researches --> RP
    SR["synthesized_recommendation"] -- synthesized_from --> RR

    FB["caregiver_feedback"] -- feedback_on --> DT
    FB -- feedback_on --> AC
```

## Module Map

```mermaid
flowchart LR
    Main["main.py\nroutes, auth dependencies, response sanitization"]
    Config["config.py\nsettings + env"]
    Store["store.py\nGraphStore implementations"]
    Models["models.py\nnode/edge/API models"]
    Security["security.py\nAPI keys, sanitization, rate limit, vendor gates"]
    Crypto["storage_security.py\nfield encryption"]
    Compliance["compliance.py\nconsent, DSAR, incidents, retention"]

    Transcription["transcription.py\nprovider clients"]
    Pipeline["transcript_pipeline.py\ningestion + redaction orchestration"]
    Privacy["privacy.py\nPII redaction + rehydration"]
    Extraction["extraction.py\nentity extraction + triage"]
    Identity["identity.py\npatient aliases + known people"]
    Scheduler["scheduler.py\nnext-day conflict detection"]
    Approvals["approvals.py\ndaily edits + calendar writes"]
    Research["research.py\nguarded research pipeline"]
    V2["v2.py\ncare-plan helpers, memory, resources"]
    Notifications["notifications.py\npolling-friendly notification view"]
    Learning["learning.py\nhuman eval + prompt candidates"]
    Quality["quality.py and sealion_reviews.py\noptional regional quality checks"]

    Main --> Config
    Main --> Store
    Main --> Models
    Main --> Security
    Main --> Compliance
    Store --> Crypto
    Main --> Pipeline
    Pipeline --> Transcription
    Pipeline --> Privacy
    Main --> Extraction
    Extraction --> Privacy
    Main --> Identity
    Main --> Scheduler
    Main --> Approvals
    Main --> Research
    Main --> V2
    Main --> Notifications
    Main --> Learning
    Pipeline --> Quality
    Extraction --> Quality
```

## Data Protection Boundary

```mermaid
flowchart TD
    RawAudio["Raw audio"] -->|"sent to transcription provider"| OpenAI["OpenAI/Groq/local transcription"]
    RawAudio -->|"metadata only stored"| Session["transcription_session"]
    OpenAI --> RawTranscript["raw transcript stored locally"]
    RawTranscript --> Redactor["local PII redactor"]
    Redactor --> Redacted["redacted transcript"]
    Redactor --> Placeholder["placeholder_map stored locally"]

    Redacted --> Downstream["extraction, triage, research, SEA-LION review"]
    Placeholder --> Rehydrate["local rehydration for user-facing artifacts"]
    Rehydrate --> UserOutput["daily tasks, appointment candidates, recommendations"]

    RawTranscript --> Encrypt["optional field encryption with DATA_ENCRYPTION_KEY"]
    Placeholder --> Encrypt
    UserOutput --> Sanitize["normal API response sanitization"]
```

## External Integrations

| Integration | Current Use | Data Sent | Gate/Setting |
| --- | --- | --- | --- |
| OpenAI transcription | `POST /transcriptions` and `/transcribe` | Raw audio | `OPENAI_API_KEY`, `TRANSCRIPTION_PROVIDER=openai`, `VENDOR_OPENAI_ENABLED` |
| OpenAI normalization/search verification | Non-English normalization, optional live result verification | Transcript text for normalization; redacted query/results for verification | `OPENAI_API_KEY`, `LIVE_SEARCH_LLM_VERIFICATION` |
| SEA-LION | Optional transcript/artifact review and localization | Redacted transcript/artifact summaries | `SEALION_API_KEY`, `SEALION_TRANSCRIPT_REVIEW_ENABLED`, `VENDOR_SEALION_ENABLED` |
| Google Calendar read | Next-day conflict detection | Next-day time window only | `GOOGLE_CALENDAR_ACCESS_TOKEN`, `GOOGLE_CALENDAR_ID`, `VENDOR_GOOGLE_CALENDAR_ENABLED` |
| Google Calendar write | Approved appointment candidate insert | Appointment summary/date/time/location/description | Explicit `/appointments/{id}/approve-calendar-write` call |
| Exa/TinyFish/Jina/OpenAlex/Semantic Scholar | Guarded research | Redacted/allowlisted research queries and URLs | Vendor API keys and `VENDOR_*_ENABLED` |

## Roadmap Validation

Status as of May 10, 2026:

| Roadmap Area | Status | Evidence |
| --- | --- | --- |
| Product pivot to transcription-first backend | Done | README states backend-first transcript source of truth; frontend removed. |
| Phase 1 graph foundation | Done | `models.py` and `schema.sql` include transcript-first node/edge types. |
| Phase 2 NEHR/demo runtime removal | Done | Legacy demo routes, raw NEHR storage, scripted demo agent modules, and demo fixtures were physically removed. |
| Phase 3 transcription-first ingestion | Done | `transcription.py`, `transcript_pipeline.py`, `/transcriptions`, `/transcribe`, multilingual normalization, graph persistence. |
| Direct PII redaction and local rehydration | Done | `privacy.py`, `transcript_pipeline.py`, `extraction.py`; downstream work uses redacted text and user-facing artifacts are locally rehydrated. |
| Phase 4 extraction and triage | Done | `extraction.py` creates `extracted_entities`, `triage_decision`, `daily_task`, `appointment_candidate`, and `ad_hoc_research_task`; tests cover simple and multi-bucket transcripts. |
| Daily task scheduling semantics | Done | `approvals.py` supports timing/fixed/movable overrides; `scheduler.py` classifies fixed/movable/unsafe conflicts and medication spacing. |
| Google Calendar next-day read | Done | `scheduler.py` reads only the next-day window through `GoogleCalendarProvider`. |
| Daily 10pm Singapore job | Mostly done | The scheduler has an in-process loop and external cron endpoint with idempotent run state; deployed production still needs platform-level cron configuration. |
| Appointment approval before calendar write | Done | `approvals.py` creates `user_decision`, `calendar_write_request`, and writes only after `/appointments/{id}/approve-calendar-write`. |
| Push notification first step | Done for polling | `notification_candidate` nodes and `GET /notifications` exist. Real push provider/SSE/WebSocket are intentionally not implemented. |
| Phase 6 guarded research pipeline | Done | `research.py` plans, guardrails, runs curated/live adapters, classifies source tiers, and synthesizes recommendations. |
| Research source policy | Done | Official/high-trust/informal tiers and claim statuses are implemented in `research.py`; curated corpus is used before live tools. |
| Reasoning logs and auditability | Mostly done | Reasoning logs cover transcription, redaction, scheduling, research, and reviews. Some roadmap log ideals are not explicit because extraction/triage are deterministic rather than prompt-model calls. |
| API surface draft | Done and expanded | Draft endpoints exist; additional identity, privacy, learning, audit, and evaluation endpoints were added. |
| Evaluation plan | Mostly done | Unit/API/E2E tests cover all core eval cases; live Google Calendar full flow remains manual with real tokens. |
| Compliance/security hardening | Added beyond roadmap | Auth, response sanitization, encryption-at-rest option, consent/DSAR/incidents/retention, and vendor gates exist. |

Summary: the roadmap phases are implemented for demo and backend MVP purposes. The main remaining production gaps are enabling real Google OAuth in deployment, platform cron configuration, and broader conflict semantics beyond daily tasks and appointments.

## Test Entry Points

```bash
# Full deterministic demo flow through all three buckets.
backend/.venv/bin/python -m pytest backend/tests/test_full_backend_e2e.py -q

# Full default backend suite.
TINYFISH_API_KEY= SEALION_API_KEY= backend/.venv/bin/python -m pytest backend/tests -q
```
