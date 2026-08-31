<p align="center">
<img alt="Caregiver Companion" src="asset/logo/hug.png" width="128">
<br>
<em>Transcript-first caregiver workflows</em>
<br><br>
<a title="Last Commit" target="_blank" href="https://github.com/gongahkia/goodhack-hackathon-2026/commits/main"><img src="https://img.shields.io/github/last-commit/gongahkia/goodhack-hackathon-2026.svg?style=flat-square&color=FF9900"></a>
<a title="GitHub Commits" target="_blank" href="https://github.com/gongahkia/goodhack-hackathon-2026/commits/main"><img src="https://img.shields.io/github/commit-activity/m/gongahkia/goodhack-hackathon-2026.svg?style=flat-square"></a>
<br>
<a title="Code Size" target="_blank" href="https://github.com/gongahkia/goodhack-hackathon-2026"><img src="https://img.shields.io/github/languages/code-size/gongahkia/goodhack-hackathon-2026.svg?style=flat-square&color=yellow"></a>
<a title="Repository Size" target="_blank" href="https://github.com/gongahkia/goodhack-hackathon-2026"><img src="https://img.shields.io/github/repo-size/gongahkia/goodhack-hackathon-2026.svg?style=flat-square&color=blueviolet"></a>
<a title="GitHub Pull Requests" target="_blank" href="https://github.com/gongahkia/goodhack-hackathon-2026/pulls"><img src="https://img.shields.io/github/issues-pr-closed/gongahkia/goodhack-hackathon-2026.svg?style=flat-square&color=FF9966"></a>
<br>
<a title="FastAPI" target="_blank" href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/backend-FastAPI-009688?style=flat-square"></a>
<a title="React and Vite" target="_blank" href="https://vite.dev/"><img src="https://img.shields.io/badge/frontend-React%20%2B%20Vite-61DAFB?style=flat-square"></a>
<a title="Python" target="_blank" href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12-3776AB?style=flat-square"></a>
<br>
<a title="Privacy" target="_blank" href="docs/ARCHITECTURE.md"><img src="https://img.shields.io/badge/privacy-PII%20redaction-8A2BE2?style=flat-square"></a>
<a title="Graph Store" target="_blank" href="backend/sql/schema.sql"><img src="https://img.shields.io/badge/storage-auditable%20graph-4B5563?style=flat-square"></a>
<a title="Calendar" target="_blank" href="docs/DEMO.md"><img src="https://img.shields.io/badge/calendar-explicit%20approval-22C55E?style=flat-square"></a>
</p>

<p align="center">
<b>README</b>
| <a href="docs/ARCHITECTURE.md">Architecture</a>
| <a href="docs/DEMO.md">Demo</a>
| <a href="docs/API_VERIFICATION.md">API Verification</a>
| <a href="docs/ROADMAP.md">Roadmap</a>
</p>

---

## Table of Contents

* [💡 Introduction](#-introduction)
* [🔮 Features](#-features)
* [👥 Team Members](#-team-members)
* [🏗️ Architecture and Ecosystem](#️-architecture-and-ecosystem)
* [🌟 Star History](#-star-history)
* [🗺️ Roadmap](#️-roadmap)
* [🚀 Setup](#-setup)
  * [Install](#install)
  * [Run](#run)
  * [Environment](#environment)
  * [Verification](#verification)
* [📡 API Surface](#-api-surface)
* [🛠️ Development Guide](#️-development-guide)

---

## 💡 Introduction

Caregiver Companion converts caregiver audio or transcripts into auditable care actions.

The backend stores transcript sessions, redacts direct PII before downstream model/tool work, extracts care entities, triages them into daily tasks, appointment candidates, and guarded research tasks, then persists the lineage as graph nodes, edges, and reasoning logs.

## 🔮 Features

* Transcript-first workflow
  * Raw audio ingestion through OpenAI transcription
  * Language hints: `auto`, `en`, `ms`, `ta`, `zh`, `th`
  * Original transcript plus English-normalized text
  * Batch-on-commit WebSocket path for browser audio chunks
* Privacy boundary
  * Direct PII redaction before extraction, triage, research, guardrails, and synthesis
  * Local placeholder rehydration for user-facing artifacts
  * Optional sensitive-field encryption through `DATA_ENCRYPTION_KEY`
  * API response sanitization for raw transcript fields and placeholder maps
* Care triage
  * Daily tasks
  * Appointment candidates
  * Ad hoc research tasks
  * Notification candidates
* Calendar workflow
  * Next-day Google Calendar conflict checks
  * Explicit user approval before Google Calendar writes
  * Calendar OAuth scaffold and token-based demo mode
* Research workflow
  * Curated fallback catalogs
  * Optional Exa, TinyFish, Jina, OpenAlex, and Semantic Scholar integrations
  * Guardrail review before synthesis
* Auditability
  * Graph nodes
  * Graph edges
  * Reasoning logs
  * Human eval and prompt candidate harness
* Frontend
  * React + TypeScript + Vite
  * Capture/review/task/notification-oriented UI
  * Browser live-caption fallback contract

## 👥 Team members

<table>
	<tbody>
        <tr>
            <td align="center">
                <a href="https://github.com/gongahkia">
                    <img src="https://avatars.githubusercontent.com/u/117062305?v=4" width="100;" alt="gongahkia"/>
                    <br />
                    <sub><b>Gabriel Ong</b></sub>
                </a>
                <br />
            </td>
            <td align="center">
                <a href="https://github.com/kopicplusplus">
                    <img src="https://avatars.githubusercontent.com/u/262940233?v=4" width="100;" alt=""/>
                    <br />
                    <sub><b>Keith Tang</b></sub>
                </a>
                <br />
            </td>
            <td align="center">
                <a href="https://www.linkedin.com/in/leeziqikarin/">
                    <img src="https://media.licdn.com/dms/image/v2/D5603AQFa8pAQPkSi5g/profile-displayphoto-crop_800_800/B56ZmWS4x.J4AI-/0/1759163160813?e=1780531200&v=beta&t=7nx-On5k51LBiJ4r0j-1x50iQ9Q3_al8tYSxK__o4fI" width="100;" alt=""/>
                    <br />
                    <sub><b>Karin Lee</b></sub>
                </a>
                <br />
            </td>
            <td align="center">
                <a href="https://github.com/a-stint">
                    <img src="https://avatars.githubusercontent.com/u/149822619?v=4" width="100;" alt=""/>
                    <br />
                    <sub><b>Astin Tay</b></sub>
                </a>
                <br />
            </td> 
        </tr>
	</tbody>
</table>

## 🏗️ Architecture and Ecosystem

| Project | Description | Entry Point |
| --- | --- | --- |
| Backend API | FastAPI routes, auth dependencies, response sanitization | [`backend/app/main.py`](backend/app/main.py) |
| Transcript Pipeline | Ingestion, redaction, graph persistence orchestration | [`backend/app/transcript_pipeline.py`](backend/app/transcript_pipeline.py) |
| Privacy | Direct PII redaction and rehydration | [`backend/app/privacy.py`](backend/app/privacy.py) |
| Extraction | Entity extraction and triage buckets | [`backend/app/extraction.py`](backend/app/extraction.py) |
| Scheduler | Next-day calendar conflict detection | [`backend/app/scheduler.py`](backend/app/scheduler.py) |
| Research | Guarded external/curated research pipeline | [`backend/app/research.py`](backend/app/research.py) |
| Graph Store | Memory/Postgres-backed node, edge, and log persistence | [`backend/app/store.py`](backend/app/store.py) |
| SQL Schema | Postgres graph schema | [`backend/sql/schema.sql`](backend/sql/schema.sql) |
| Frontend | React app | [`frontend/src/App.tsx`](frontend/src/App.tsx) |
| Demo Runbook | Full demo and live E2E notes | [`docs/DEMO.md`](docs/DEMO.md) |

![Project Architecture](docs/project-architecture-diagram.svg)

![Project Data Flow](docs/project-data-flow-diagram.svg)

## 🗺️ Roadmap

* [Backend roadmap](docs/ROADMAP.md)
* [Architecture diagrams](docs/ARCHITECTURE.md)
* [Frontend notes](docs/FRONTEND.md)
* [Learning harness](docs/LEARNING_HARNESS.md)

## 🚀 Setup

### Install

```bash
make install
```

This installs backend dependencies through `uv` and frontend dependencies through `npm`.

### Run

```bash
make dev
```

Services:

* Backend: `http://127.0.0.1:8000`
* Frontend: `http://127.0.0.1:5173`
* Health check: `curl -s http://127.0.0.1:8000/health | jq`

Useful targets:

| Command | Description |
| --- | --- |
| `make backend` | Run FastAPI on `127.0.0.1:8000` |
| `make frontend` | Run Vite on `127.0.0.1:5173` |
| `make fresh-dev` | Stop existing dev servers, then run both |
| `make stop-dev` | Stop listeners on `:8000` and `:5173` |
| `make test` | Run backend tests |
| `make build-frontend` | Build frontend |
| `make robustness-loop` | Run bounded frontend-readiness robustness checks |
| `make clean` | Remove local build/cache artifacts |

### Environment

Config load order:

1. repo root `.env`
2. `backend/.env`

Minimum real transcription env:

```text
OPENAI_API_KEY=
```

Optional env:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Use Postgres instead of in-memory graph store |
| `DATA_ENCRYPTION_KEY` | Encrypt sensitive persisted fields |
| `API_READ_KEY`, `API_WRITE_KEY` | Gate read/write API routes |
| `CLINICIAN_REVIEW_KEY` | Gate clinician review routes |
| `GOOGLE_CALENDAR_ACCESS_TOKEN` | Demo Google Calendar access |
| `GOOGLE_CALENDAR_REFRESH_TOKEN` | OAuth scaffold refresh token |
| `GOOGLE_CALENDAR_ID` | Calendar ID, defaults to `primary` |
| `SCHEDULER_CRON_KEY` | Scheduler cron auth |
| `SEALION_API_KEY` | Optional SEA-LION review |
| `TINYFISH_API_KEY`, `EXA_API_KEY`, `JINA_API_KEY`, `OPENALEX_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY` | Optional research providers |

### Verification

```bash
make test
```

Additional checks:

* [API verification](docs/API_VERIFICATION.md)
* [CI/CD notes](docs/CI_CD.md)
* [Full demo and live E2E runbook](docs/DEMO.md)

## 📡 API Surface

| Method | Route |
| --- | --- |
| `POST` | `/transcriptions` |
| `WS` | `/transcriptions/live` |
| `POST` | `/transcriptions/{session_id}/process` |
| `POST` | `/transcripts/{transcript_id}/redact` |
| `POST` | `/transcripts/{transcript_id}/process` |
| `GET` | `/tasks/daily` |
| `PATCH` | `/tasks/daily/{task_id}` |
| `GET` | `/appointments` |
| `GET` | `/schedule/day` |
| `POST` | `/scheduler/next-day-check` |
| `POST` | `/scheduler/cron/next-day-check` |
| `GET` | `/schedule-conflicts` |
| `POST` | `/schedule-conflicts/{conflict_id}/resolve` |
| `GET` | `/research/tasks` |
| `POST` | `/research/tasks/{task_id}/run` |
| `GET` | `/recommendations` |
| `POST` | `/appointments/{appointment_id}/approve-calendar-write` |
| `GET` | `/calendar/google/connect` |
| `GET` | `/calendar/google/callback` |
| `GET` | `/calendar/google/status` |
| `DELETE` | `/calendar/google/disconnect` |
| `GET` | `/notifications` |
| `GET` | `/audit` |
| `POST` | `/privacy/consents` |
| `POST` | `/privacy/requests` |
| `POST` | `/privacy/incidents` |
| `POST` | `/privacy/retention/purge` |

## 🛠️ Development Guide

Read the source in this order:

1. [`Makefile`](Makefile)
2. [`backend/app/main.py`](backend/app/main.py)
3. [`backend/app/transcript_pipeline.py`](backend/app/transcript_pipeline.py)
4. [`backend/app/store.py`](backend/app/store.py)
5. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

Testing:

```bash
make test
```

Focused backend suite:

```bash
TINYFISH_API_KEY= SEALION_API_KEY= backend/.venv/bin/python -m pytest backend/tests
```
