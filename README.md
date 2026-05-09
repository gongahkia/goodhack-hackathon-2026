<p align="center">
  <img src="./asset/logo/hug.png" width="25%">
<br>
<strong>Caregiver Companion</strong>
<br>
<em>Trace every care decision back to evidence</em>
<br><br>
<img alt="Next.js" src="https://img.shields.io/badge/Next.js-14-black?style=flat-square">
<img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-Python-009688?style=flat-square">
<img alt="OpenAI" src="https://img.shields.io/badge/OpenAI-Responses_API-412991?style=flat-square">
<img alt="Postgres" src="https://img.shields.io/badge/Postgres-Supabase-3ECF8E?style=flat-square">
<br>
<img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-5-blue?style=flat-square">
<img alt="Tailwind CSS" src="https://img.shields.io/badge/Tailwind-CSS-38BDF8?style=flat-square">
<img alt="Python" src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square">
<img alt="License" src="https://img.shields.io/badge/license-unset-lightgrey?style=flat-square">
</p>

---

## Table of Contents

* [💡 Introduction](#-introduction)
* [🔮 Features](#-features)
* [🏗️ Architecture and Ecosystem](#️-architecture-and-ecosystem)
* [🗺️ Roadmap](#️-roadmap)
* [🚀 Run Setup](#-run-setup)
  * [Local Development](#local-development)
  * [Environment Variables](#environment-variables)
  * [Deployment](#deployment)
* [🛠️ Development Guide](#️-development-guide)
* [❓ FAQ](#-faq)
  * [How does Caregiver Companion store data?](#how-does-caregiver-companion-store-data)
  * [Does the app require an OpenAI API key?](#does-the-app-require-an-openai-api-key)
  * [Are records manually ingested by the user?](#are-records-manually-ingested-by-the-user)
  * [How is provenance enforced?](#how-is-provenance-enforced)
  * [Is this production-ready for real patient data?](#is-this-production-ready-for-real-patient-data)
* [🙏 Acknowledgement](#-acknowledgement)

---

## 💡 Introduction

Caregiver Companion is a mobile-first web application for family caregivers of elderly Singaporeans. It turns connected health records into a traceable care calendar, links every action back to its source record, and surfaces preemptive care tasks such as grant applications before they become urgent.

The current repository implements the v1 hackathon MVP described in [ROADMAP.md](ROADMAP.md), plus an initial v2 foundation: caregiver-feedback memory, readable reasoning narratives, care-plan review summaries, and standards-based calendar export.

## 🔮 Features

* Knowledge graph spine
  * `nodes` and `edges` adjacency-list model
  * `nehr_record`, `inferred_condition`, `scheduled_action`, `recommended_resource`, `grant_opportunity`, and `caregiver_feedback` nodes
  * `derived_from`, `triggers`, `recommends`, `applies_to`, and `feedback_on` edges
* Traceable care calendar
  * FullCalendar month/week/day views
  * Pending review, approved, dismissed, and edited statuses
  * Click any calendar action to inspect evidence and reasoning
* Record provenance
  * Records list shows forward-trace to spawned actions
  * Event detail shows back-trace to source records
  * Scheduled actions are rejected if they lack provenance
* Reasoning trail
  * OpenAI Responses API function-tool loop
  * Tool calls and tool results persisted in `reasoning_logs`
  * Readable reasoning trail exposed through Settings and event detail
* Curated safety constraints
  * Condition trajectories in `data/condition_trajectories.json`
  * Singapore grants in `data/grants_singapore.json`
  * Educational resources in `data/educational_resources.json`
  * No live YouTube search for media
* Caregiver controls
  * Approve, dismiss, and edit pending actions
  * Feedback stored as graph state and summarized into learned caregiver memory signals
* v2 care intelligence foundations
  * `/memory` summarizes approve/dismiss/edit patterns by action type, recent feedback, edited fields, confidence, and safety policy
  * `/care-plan/review` provides a nightly-style care-plan review narrative
  * Event detail renders readable reasoning narratives, not only raw logs
  * `.ics` calendar export and subscription feed for external calendar apps
  * `/resources/search` and `/grants/search` return allowlisted, verified resources with curated fallback when live search is unavailable
  * Exa search, TinyFish rendered search, TinyFish fetch, and SEA-LION regional review/safety checks are exposed as first-class model tools with allowlist and redaction checks
  * Caregiver memory signals are passed back into future reasoning so low-risk suggestions can be down-ranked without suppressing high-priority care actions
* Language support
  * English, Bahasa Melayu, Chinese, and Tamil UI language packs
  * Persisted language selection in Settings
  * Static navigation, labels, statuses, and controls translated in the frontend
* Local-first rehearsal path
  * In-memory store when `DATABASE_URL` is absent
  * Scripted reasoning fallback when `OPENAI_API_KEY` is absent
  * Automatic care plan preparation on backend startup when the graph is empty

## 🏗️ Architecture and Ecosystem

| Project | Description |
|---|---|
| [`frontend/`](frontend) | Next.js 14 App Router, TypeScript, Tailwind, FullCalendar, mobile-first UI |
| [`backend/`](backend) | FastAPI service, graph store, API routes, OpenAI tool loop |
| [`backend/sql/schema.sql`](backend/sql/schema.sql) | Supabase Postgres schema, indexes, and deferred provenance trigger |
| [`data/`](data) | Curated condition trajectories, grant catalog, and educational resources |
| [`Makefile`](Makefile) | Root commands for install, dev, test, build, and care plan rebuild |
| [`ROADMAP.md`](ROADMAP.md) | Product roadmap from v1 through v4+ |

### Data Flow

```text
Connected record source
  -> nehr_records_raw
  -> nehr_record graph nodes
  -> OpenAI Responses API tool loop
  -> inferred_condition / scheduled_action / grant_opportunity / recommended_resource nodes
  -> edges with mandatory provenance
  -> Next.js calendar, records, event detail, and reasoning trail
```

## 🗺️ Roadmap

See [ROADMAP.md](ROADMAP.md).

In brief:

* v1: single-patient, traceable, reactive care planning MVP
* v2: memory from caregiver feedback, scheduled re-reasoning summaries, calendar export, allowlisted live content, deeper evaluation
* v3: continuous monitoring, multilingual voice, domestic-helper mode
* v4+: real NEHR partnerships, B2B2C distribution, regional expansion

## 🚀 Run Setup

### Local Development

Install dependencies from the repository root:

```bash
make install
```

Run backend and frontend together:

```bash
make dev
```

Open:

```text
http://127.0.0.1:3000
```

The backend prepares the initial care plan automatically on startup when no graph data exists.

Run services separately:

```bash
make backend
make frontend
```

Rebuild local care plan data while the backend is running:

```bash
make rebuild-care-plan
```

### Environment Variables

Backend variables live in [`backend/.env.example`](backend/.env.example):

```bash
DATABASE_URL=
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.5
EXA_API_KEY=
TINYFISH_API_KEY=
SEALION_API_KEY=
SEALION_MODEL=aisingapore/Gemma-SEA-LION-v4-27B-IT
SEALION_GUARD_MODEL=aisingapore/SEA-Guard
CORS_ORIGINS=http://localhost:3000
DEMO_AGENT_MODE=auto
LIVE_SEARCH_LLM_VERIFICATION=true
```

Frontend variables live in [`frontend/.env.example`](frontend/.env.example):

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Without `DATABASE_URL`, the backend uses an in-memory graph store. Without `OPENAI_API_KEY`, the backend uses the scripted v1 reasoning path so the local care flow remains testable.

### Deployment

Recommended deployment split:

* Frontend: Vercel
* Backend: Render or Railway
* Database: Supabase Postgres

Backend deployment needs:

```bash
DATABASE_URL=...
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.5
EXA_API_KEY=...
TINYFISH_API_KEY=...
SEALION_API_KEY=...
CORS_ORIGINS=https://your-frontend.example
```

Frontend deployment needs:

```bash
NEXT_PUBLIC_API_BASE_URL=https://your-backend.example
```

## 🛠️ Development Guide

Common commands:

```bash
make test
make build
make clean
```

Backend tests cover:

* v1 care plan generation
* scheduled-action provenance enforcement
* bidirectional trace helpers
* v2 memory summaries, memory-conditioned reasoning, first-class Exa/TinyFish tooling, care-plan review, verified search, and `.ics` export generation

Frontend build checks:

* TypeScript validity
* Next.js production build
* route generation for Calendar, Records, Settings, Reasoning Trail, and Event Detail

## ❓ FAQ

### How does Caregiver Companion store data?

The deployed store is Supabase Postgres using the schema in [`backend/sql/schema.sql`](backend/sql/schema.sql). Knowledge graph state is stored in:

* `nodes`
* `edges`
* `reasoning_logs`
* `nehr_records_raw`

For local development without `DATABASE_URL`, the backend uses an in-memory store.

### Does the app require an OpenAI API key?

No for local rehearsal, yes for the real agent path.

If `OPENAI_API_KEY` is absent, the backend uses a deterministic scripted reasoner that creates the same v1 care plan. If `OPENAI_API_KEY` is set, the backend uses the OpenAI Responses API function-tool loop.

### Are records manually ingested by the user?

No. The UI does not expose manual ingestion. On backend startup, if the graph is empty, the app prepares the current care plan automatically. Settings includes a rebuild control for local testing and recovery.

### How is provenance enforced?

The agent toolbox stages `scheduled_action` creation until a valid `derived_from` edge is created. The Postgres schema also includes a deferred constraint trigger that rejects persisted scheduled actions without a `derived_from` edge to a `nehr_record` or `inferred_condition`.

### Is this production-ready for real patient data?

No. v1 uses synthetic NEHR-style records and has no authentication. Before real patient data, the roadmap calls for authentication, PDPA review, clinician review workflows, stronger evaluation, and real integration agreements.

## 🙏 Acknowledgement

Built for the Build for Good hackathon in Singapore.

This project uses Next.js, FastAPI, Supabase Postgres, FullCalendar, Tailwind CSS, OpenAI APIs, and curated Singapore healthcare references.
