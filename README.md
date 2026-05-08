# Caregiver Companion v1

Hackathon MVP for a Singapore family caregiver workflow. The app ingests synthetic NEHR records, writes a traceable knowledge graph, runs an Anthropic tool-use agent, and renders a mobile-first caregiving calendar.

## Structure

- `backend/` - FastAPI service, graph store, agent tools, demo seed flow.
- `frontend/` - Next.js 14 App Router UI with FullCalendar.
- `data/` - curated trajectories, grants, and educational resources.
- `backend/sql/schema.sql` - Supabase Postgres schema.

## Local Demo

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`, click `Reset demo`, then `Ingest new record`.

Without `DATABASE_URL` the backend uses an in-memory graph store for rehearsal. With `DATABASE_URL` it initializes the Supabase Postgres schema automatically.

## Deployment

- Deploy `backend/` to Render or Railway with `DATABASE_URL`, `ANTHROPIC_API_KEY`, optional `EXA_API_KEY`, and `CORS_ORIGINS`.
- Deploy `frontend/` to Vercel with `NEXT_PUBLIC_API_BASE_URL` set to the backend URL.

The scripted demo path runs when `ANTHROPIC_API_KEY` is absent. Set `DEMO_AGENT_MODE=anthropic` and provide the key/model to use Claude native tool use.
