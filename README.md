<p align="center">
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

<p align="center">
<b>English</b>
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

The current repository implements the v1 hackathon MVP described in [ROADMAP.md](ROADMAP.md): one caregiver-patient pair, synthetic NEHR-style records, a Postgres knowledge graph, an OpenAI Responses API tool loop, and a responsive Next.js interface.

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
  * Feedback stored as graph state for future roadmap work
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
* v2: memory from caregiver feedback, scheduled re-reasoning, deeper evaluation
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
CORS_ORIGINS=http://localhost:3000
DEMO_AGENT_MODE=auto
```
