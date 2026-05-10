# GTM Deployment Costs

Verified: 2026-05-10.

## Repo State

- No live deployment manifest was found in repo. No `Dockerfile`, `docker-compose.yml`, `fly.toml`, `render.yaml`, Railway, Heroku, Terraform, or Cloud Run config.
- Current runnable shape: FastAPI backend via `uvicorn`; `MemoryGraphStore` when `DATABASE_URL` is unset; Postgres when `DATABASE_URL` is set.
- Current CI shape: GitHub Actions backend CI only.
- Verification run: `102 passed, 11 skipped`.
- CI gap: `.github/workflows/backend-ci.yml` validates `data/condition_trajectories.json`, but that file is absent locally.

Primary repo refs:

- `backend/app/main.py`: app setup, store selection, routes, scheduler startup.
- `backend/app/config.py`: env, vendor keys, OpenAI defaults, Google Calendar settings, scheduler defaults.
- `backend/app/store.py`: memory/Postgres graph store.
- `backend/app/transcription.py`: OpenAI/Groq/local transcription providers.
- `backend/app/research.py`: ad hoc research pipeline.
- `backend/app/scheduler.py`: next-day daily task/calendar conflict check.
- `backend/app/approvals.py`: Google Calendar write approval.

## Cost Drivers

| Driver | Current repo usage | Pricing source |
|---|---|---|
| OpenAI text | Default `OPENAI_MODEL=gpt-5.5` for higher-quality extraction/research paths | `https://developers.openai.com/api/docs/models/gpt-5.5` |
| OpenAI transcription | Default `OPENAI_TRANSCRIPTION_MODEL=gpt-4o-transcribe` | `https://developers.openai.com/api/docs/models/gpt-4o-transcribe` |
| Hosting | FastAPI API and optional scheduler loop | `https://cloud.google.com/run/pricing` |
| Database | Postgres graph store required for real deploy | `https://cloud.google.com/sql/pricing` |
| Scheduler | Next-day check should be externalized for serverless deploys | `https://cloud.google.com/scheduler/pricing` |
| Secrets | API keys, encryption key, Google Calendar token | `https://cloud.google.com/secret-manager/pricing` |
| Google Calendar | Reads next-day events; writes only after user approval | `https://developers.google.com/workspace/calendar/api/guides/quota` |

Current official pricing points checked:

- GPT-5.5: `$5.00 / 1M input tokens`, `$30.00 / 1M output tokens`.
- GPT-4o Transcribe: `$2.50 / 1M input audio/text tokens`, `$10.00 / 1M output tokens`.
- Cloud Scheduler: 3 free jobs per billing account, then `$0.10/job/month`.
- Secret Manager: 6 free active versions, then `$0.06/version/location/month`; `$0.03/10k access ops`.
- Google Calendar API: quota-gated at `10,000 req/min/project` and `600 req/min/user/project`; billing changes are announced for later in 2026.

## Deployment Tiers

| Tier | Target | Recommended stack | Base monthly cost | Notes |
|---|---:|---|---:|---|
| Local/demo | 1 dev | Local `uvicorn`, memory store | `$0` | Not persistent; no production safety. |
| Hackathon public | 0-50 users | Cloud Run min=0, Neon/Supabase free or Cloud SQL dev, Cloud Scheduler, Secret Manager | `[Inference] $0-$40` | Cheapest public demo. Persistent DB required. |
| Pilot | 50-1k users | Cloud Run in `asia-southeast1`, Cloud SQL Postgres, Cloud Scheduler, Secret Manager, Cloud Logging | `[Inference] $50-$250` | Recommended first serious deploy. |
| Growth | 1k-10k users | Cloud Run API, separate worker, Cloud SQL HA/read replica, queue, stronger rate limits | `[Inference] $300-$1.5k+` | AI/search usage likely dominates. |
| Enterprise | 10k+ or regulated | Cloud Run or GKE, VPC, Cloud SQL Enterprise Plus or AlloyDB, KMS, SIEM, SSO/RBAC | `[Inference] $2k+` | Compliance and reliability drive cost. |

## Recommended Service Choices

### Demo

- Use Cloud Run for the FastAPI backend.
- Use managed Postgres; do not deploy with `MemoryGraphStore`.
- Use Secret Manager for `OPENAI_API_KEY`, `APP_API_READ_KEY`, `APP_API_WRITE_KEY`, `GRAPH_ENCRYPTION_KEY`, and Google Calendar token.
- Use Cloud Scheduler for `/scheduler/next-day-check`.
- Set `SCHEDULER_ENABLED=false` if Cloud Scheduler owns the job.

### Pilot

- Keep one Cloud Run service for API.
- Add one scheduled Cloud Scheduler HTTP job at 22:00 Asia/Singapore.
- Use Cloud SQL Postgres, not shared-memory local store.
- Add budget caps/alerts for OpenAI and live search vendors.
- Use structured logs for transcription, extraction, research, calendar writes, and notification generation.

### Growth

- Split research into a worker because page fetching and LLM extraction are slow and vendor-rate-limited.
- Add a queue for ad hoc research tasks.
- Add PgBouncer or connection pooling before increasing Cloud Run concurrency aggressively.
- Add per-user and per-patient rate limits.
- Consider `gpt-4o-mini-transcribe` or local Whisper for lower-cost transcription where quality is acceptable. `[Inference]`

### Enterprise

- Add real tenant/user/patient isolation; current defaults are single-patient oriented.
- Add refresh-token OAuth flow for Google Calendar.
- Add KMS-managed encryption and key rotation.
- Add immutable audit export.
- Add data retention controls per tenant.
- Consider regional processing endpoints or self-hosted transcription if data residency requires it. `[Inference]`

## Current Risks Before GTM

- No production deploy artifact.
- Auth is fail-open unless API keys are configured.
- `DATABASE_URL` is optional, but production needs it.
- Scheduler is in-process by default; this is not reliable for scale-to-zero serverless deploys. `[Inference]`
- Static Google token config is not enough for multi-user calendar access.
- CI references a missing JSON file.
- `.env.example` scheduler names do not fully match code names.
- Top-level `.env.example` has a malformed `SEALION_API_KEY=XXXDATABASE_URL=` line.

## Unit Cost Model

Use this for GTM modeling:

```text
monthly_cost =
  infra_base
  + transcription_minutes * transcription_price_per_min_equivalent
  + text_input_tokens / 1_000_000 * model_input_price
  + text_output_tokens / 1_000_000 * model_output_price
  + search_vendor_cost
  + database_storage
  + network_egress
```

`[Inference]` For early caregiver usage, infra is predictable and AI/search usage dominates once ad hoc research is used frequently.
