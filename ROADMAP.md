# Caregiver Companion — Product Roadmap

**Project name:** Caregiver Companion
**Context:** Build for Good Hackathon, Singapore
**Primary user:** Family caregivers of elderly Singaporeans (adult children caring for aging parents)
**Secondary user (v3+):** Domestic helpers acting as primary caregivers
**Tertiary user (v3+):** The elderly themselves

---

## Product Vision

A single, preemptive, fully-traceable care companion that turns Singapore's fragmented health, grant, and care-resource ecosystem into one actionable, dynamically-updating plan for the family caregiver. The system ingests medical records (NEHR), reasons over them, anticipates needs months in advance, and provides one-tap pathways to act — every recommendation auditable back to its source.

The North Star metric is **caregiver-hours saved per week** while maintaining or improving clinical adherence.

---

## Architecture Overview

- **Knowledge graph data spine:** `nodes`, `edges`, `reasoning_logs`, and raw NEHR-style records. Nodes represent `nehr_record`, `inferred_condition`, `scheduled_action`, `recommended_resource`, `grant_opportunity`, and `caregiver_feedback`. Edges encode `derived_from`, `triggers`, `recommends`, `applies_to`, and `feedback_on`.
- **OpenAI reasoning layer:** OpenAI Responses API function-tool loop reads records, checks graph context, searches curated Singapore grants/resources, reads condition trajectories, creates graph nodes, and logs tool calls/results.
- **Provenance guardrail:** every `scheduled_action` must be linked by a `derived_from` edge to a source `nehr_record` or `inferred_condition`; ungrounded care actions are rejected.
- **Care intelligence layer:** caregiver approvals, dismissals, edits, usefulness scores, and steering signals become graph feedback that conditions future low-risk recommendations while preserving high-priority medication, falls-risk, appointment, and grant-deadline actions.
- **Singapore resource layer:** curated condition trajectories, AIC/MOH/SG Enable/CHAS-style grant data, verified resources, and allowlisted live search are used to keep recommendations local, relevant, and auditable.
- **User experience layer:** mobile-first Next.js app with calendar, agenda, forecast, review, records, event detail, reasoning trail, settings, notifications, multilingual labels, calendar export, and subscription feed.
- **Deployment path:** Next.js frontend, FastAPI backend, Supabase Postgres for production persistence, with in-memory storage and scripted reasoning fallback for local demos when external services are absent.

---

## Version 1 — Hackathon MVP (completed)

**Goal:** A demo-perfect, single-patient flow that proves the bidirectional traceability + preemptive reasoning concept.

### In scope

- Synthetic NEHR records (1–2 patients, modeled on public Synapxe / HealthHub documentation), one of which has a progressive condition (e.g., early-stage Parkinson's) to drive the preemption demo.
- **Reactive** processing only: when a new NEHR record is ingested, the agent re-reasons and updates the schedule.
- Knowledge graph stored in Postgres (Supabase), adjacency-list representation.
- Calendar UI (FullCalendar.js) showing medication schedule, therapy appointments, preemptive future tasks (e.g., "Apply for SMF grant" 6 months out).
- **Daily / weekly task agenda view** alongside the calendar: tasks are grouped into flexible time blocks rather than strict minute-by-minute ordering. For example, a 10am-12pm block can contain 3 required tasks that the caregiver may reorder within the block, followed by a protected 12pm-6pm rest block, then a 6pm-10pm block for the remaining tasks. The view should support daily mode first, with weekly aggregation as the maximum horizon for routine caregiving tasks.
- **Forecast view** for longer-horizon actions: segmented by grant, subsidy, equipment, and care-service applications the family may need to prepare for (e.g., hospice application, wheelchair grant, mobility aid subsidy, home modification support). Each forecast card opens into a timeline showing trigger, eligibility evidence, prep steps, documents needed, application window, and follow-up checkpoints.
- **Appointment preparation prompts**: every agenda item that represents an appointment generates caregiver-facing talking points, including immediate symptoms/questions, medication or therapy adherence notes, and long-term concerns inferred from the patient's condition trajectory. These prompts remain linked to the source records and forecast items that produced them.
- Click into any calendar event → see provenance chain back to the NEHR record(s) and the chain-of-thought that generated it.
- Embedded media for ~10–15 curated, vetted videos mapped to common conditions (no live YouTube search in v1).
- Curated grant database covering breadth of senior-relevant Singapore schemes (AIC SMF, Pioneer/Merdeka, MOH subsidies, SG Enable, CHAS, etc.) — shallow integration, deep enough for demo.
- Curated `condition_trajectory_database` (JSON, ~5 conditions) the agent reasons over for preemption, rather than inventing trajectories.
- **Human-in-the-loop v1**: AI-generated tasks marked with "Pending Review" badge. Caregiver can Approve / Dismiss / Edit. Dismiss/edit feed into `reasoning_logs` for later memory use.
- Audit log viewer showing the agent's chain of thought for any decision.

### Out of scope for v1 (deliberately)

- React Native / native mobile app → use mobile-responsive Next.js instead
- Real NEHR integration (assumed API)
- Voice / Sea-Lion multilingual
- Live web search for media (curated only)
- Continuous agentic monitoring
- Memory persistence across sessions for caregiver preferences (logged, but not yet conditioning reasoning)
- Admin / clinician review interface
- Real grant API submissions (UI shows "one-tap apply" but links out to real stat board pages)

### Implemented stack

- **Frontend:** Next.js 14, Tailwind, shadcn/ui, FullCalendar.js, mobile-responsive layout. Deployed to Vercel.
- **Backend:** Python FastAPI, single service.
- **Agent:** OpenAI Responses API with function-tool loop, plus scripted fallback for deterministic local demos.
- **Storage:** Supabase Postgres.
- **Search:** Exa (primary) + Tinyfish (fallback).
- **LLM provider:** OpenAI.

### Demo flow (3-minute pitch)

1. Show synthetic NEHR record for 78yo with early-stage Parkinson's just ingested.
2. Calendar and daily agenda populate: medication schedule, physio appointments with embedded exercise videos, follow-up bookings, and flexible time blocks that distinguish "do these tasks sometime in this window" from protected rest.
3. Open an appointment → generated talking points appear, combining today's questions with longer-term concerns such as fall risk, mobility decline, caregiver fatigue, and likely future equipment needs.
4. Switch to forecast view: grant and care-application cards appear for anticipated needs, such as wheelchair support or hospice planning.
5. Open the Seniors' Mobility and Enabling Fund forecast → timeline shown: NEHR diagnosis → condition trajectory → predicted mobility decline → eligibility evidence → document prep → application checkpoint.
6. Click "Apply" → pre-filled handoff to AIC.
7. Caregiver dismisses an unrelated suggestion → show that the dismissal is logged and will inform future suggestions (foreshadowing v2).

---

## Version 2 — Current hardening, ~4 weeks

**Goal:** Move from "demo-magic" to "actually usable for one real caregiver-patient pair."

- **Product naming stays Caregiver Companion** for the current hackathon and roadmap cycle.
- **True chain-of-thought reasoning surfaced to the user**: not just logged, but rendered as a readable narrative ("I noticed X in last week's record, which combined with Y from three months ago suggests Z…"). v1 logs the chain; v2 makes it a first-class UI artifact.
- **Live web search (Exa) for educational content and grants** with safety guardrails: source allowlist (gov.sg, healthhub.sg, AIC, recognized clinical bodies), recency checks, and a secondary LLM verification pass before content is shown.
- **Memory layer**: caregiver Approve/Dismiss/Edit signals now condition future reasoning. If a caregiver consistently dismisses dietary suggestions, the agent down-weights them. Stored as structured preferences + raw event log.
- **Scheduled re-reasoning**: nightly job re-examines the full record set per patient and surfaces "what's changed, what should I anticipate?" updates, not just record-triggered updates.
- **Calendar export and subscription integrations**: provide standards-based calendar export (`.ics`) and a stable subscription feed that external calendar apps can consume directly. Caregivers should be able to add the provisioned care schedule to Apple Calendar, Google Calendar, Outlook, and similar apps, with updates flowing from Caregiver Companion into their existing daily calendar workflow.
- **Agenda intelligence upgrades**: learn caregiver preferences for task ordering inside flexible blocks, protect rest blocks unless a task is clinically urgent, and explain why any task must happen at a specific time instead of being movable within the block.
- **Forecast intelligence upgrades**: keep grant, hospice, equipment, respite-care, and home-modification timelines updated as records change; flag missing documents early; and surface conflicts between forecast deadlines and the caregiver's weekly capacity.
- **Longitudinal appointment prep**: appointment talking points become a longitudinal brief that tracks recurring concerns, previously asked questions, unresolved clinician advice, and future risks that should be revisited at the next consultation.
- **Caregiver review intelligence**: expose human-in-the-loop decisions from notifications, action detail cards, and review surfaces rather than requiring a dedicated bottom-tab destination. Caregivers can approve/dismiss actions, rate usefulness, leave notes, and steer future suggestions toward "more", "less", or "simpler" recommendations. These signals feed memory and future reasoning.
- **Proper evaluation harness**:
  - Golden test set of synthetic patient records with expected schedules.
  - Per-decision eval: was the provenance correct? Was the reasoning sound? Was the action appropriate?
  - Hallucination detection: any task without a valid provenance edge fails eval.
  - Human eval workflow for clinician-graded sample.

---

## Version 3 — Multi-user and integration expansion, ~3 months

**Goal:** Scale to multiple caregivers, broaden languages, deepen integrations.

- **Continuous agentic monitoring**: agent watches for external triggers — new grants announced, updated clinical guidelines, seasonal factors (haze → respiratory patients, dengue clusters, flu season for elderly).
- **Configurable protected rest windows**: caregivers can define preferred rest blocks, work constraints, helper availability, and household routines. The agenda should make hidden rest opportunities explicit, label them as protected, and treat rest as a first-class care-plan constraint rather than an empty gap.
- **Fixed vs flexible task semantics**: every scheduled action should declare whether it is fixed-time, flexible-within-block, deadline-based, or movable. Medication, appointments, and grant deadlines should stay fixed unless edited; therapy, education, documentation, and low-risk reminders should be movable within caregiver-approved windows.
- **Rest-aware agenda validation**: the planner should flag low-risk flexible tasks that land inside protected rest, suggest alternate morning/evening blocks, and explain when an action must interrupt rest because it is clinically or financially urgent.
- **Caregiver capacity signals**: blocks should show load and overload state, including number of tasks, estimated effort, urgency mix, and whether the caregiver has a realistic rest opportunity that day.
- **Sea-Lion multilingual + voice**: voice readout of schedule and prognosis in English, Mandarin, Malay, Tamil, Bahasa Indonesia, Tagalog. Critical for elderly direct use and helper accessibility.
- **Domestic helper user mode**: distinct UX, language-first, with appropriate scoping of what they can approve vs. what escalates to family.
- **Real grant integration**: where APIs exist (or partnerships can be formed with AIC / SG Enable / town councils), move from handoff links to true one-tap apply.
- **Caregiver-to-caregiver knowledge sharing**: anonymized, opt-in patterns (e.g., "other caregivers of dementia patients found this resource useful").
- **Multiplayer and caregiver assignment**: multiple family members can share a patient care plan, assign tasks, track ownership, and see which caregiver approved or dismissed each recommendation.
- **Evaluation harness expansion**: broaden the current eval from provenance smoke tests into scenario-level quality gates across Parkinson's, dementia, post-stroke recovery, COPD, and congestive heart failure. Each fixture should define source records, expected action types, required actions, forbidden actions, required source links, expected grant/resource IDs, and acceptable timing windows.
- **Per-decision scoring**: evaluate every generated care action for provenance correctness, clinical plausibility, financial relevance, timing appropriateness, caregiver burden, reasoning presence, source specificity, and safe-to-show status.
- **Negative safety tests**: verify that the agent does not invent future needs for unknown trajectories, does not surface grants without eligibility evidence, rejects non-allowlisted resources, and applies caregiver dismissal memory only to low-risk suggestions without suppressing medication, falls-risk, appointment, or grant-deadline actions.
- **Evaluator architecture**: keep the live care-plan generator as a single OpenAI reasoning loop, then add deterministic validators and an optional OpenAI evaluator/critic for offline, CI, or nightly QA. Multi-agent critique should support evaluation and review, not make the live MVP flow harder to debug.

---

## Version 4 — Full MVP target, 6–12 months

**Goal:** Reach the eventual full MVP: a partner-ready care planning product that can support real integrations, real caregiver workflows, and a credible path toward deployment beyond synthetic demo data.

- **Real NEHR integration** via Synapxe partnership.
- **B2B2C distribution** through polyclinics, hospital discharge planning teams, and AIC.
- **Native mobile / Expo companion app** as a separate client against the existing FastAPI backend.
  - Current deployment fit: the v1 product remains a responsive Next.js 14 App Router web app for Vercel or a Node/Next host, backed by FastAPI on Render/Fly/Railway-style infrastructure and Supabase Postgres. The mobile UX is a phone-sized responsive web shell, but still browser-based.
  - Reusable pieces for Expo: API contracts in `frontend/lib/api.ts`, data types in `frontend/lib/types.ts`, i18n strings in `frontend/lib/i18n.tsx` after adapting storage/provider concerns, and the product flow/screen structure.
  - Expo replacement work: Next.js routing/pages, DOM/browser APIs such as `window.print`, file inputs, iframe embeds, and `localStorage`, FullCalendar's web component, Tailwind/shadcn web styling, HTML anchors/forms, and web-only attachment handling.
  - Recommended path: deploy the MVP as web first; if native mobile is needed, build a dedicated `mobile/` Expo app against the existing FastAPI backend rather than converting the Next.js frontend in place.
- **Adaptive rest-preserving scheduler**: move from static time blocks to a scheduling engine that learns caregiver capacity, protects rest by default, reschedules movable tasks around fixed commitments, and records why any rest interruption was necessary.
- **Caregiver burden evaluation**: include rest protection, block overload, avoidable interruptions, and task-movement quality in the evaluation harness so the system is measured not only on clinical correctness but also on whether it reduces mental clutter.
- **Expansion to chronic disease management** beyond elderly (diabetes, oncology survivorship, mental health).
- **Regional expansion** to Malaysia, Indonesia, Thailand — Sea-Lion's multilingual capability becomes a strategic moat.
- **Predictive health insights** at the population level (privacy-preserving, opt-in) — caregiving signal is a uniquely undertapped dataset.

---

## TAM / SAM / SOM

- **TAM:** Aging-population caregiving across ASEAN. ASEAN 65+ population projected at ~75M+ by 2030. Family caregivers conservatively 1.5–2x that figure.
- **SAM:** Singapore family caregivers of elderly with chronic or progressive conditions. ~1M Singaporeans aged 65+ today, projected ~1.5M by 2030. Roughly 210,000 family caregivers per AIC (figure varies by source — verify before pitch).
- **SOM (year 1):** Singapore family caregivers of patients recently discharged from polyclinics or hospitals with a new chronic diagnosis. Estimated ~30,000–50,000 caregivers in this acute-onset window annually, where the value of preemption is highest.

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Clinical incorrectness from LLM reasoning | Curated trajectory database in v1; clinician review layer in v2; hallucination eval in v2 |
| NEHR API never opens | Build the assumed-API abstraction so swapping in real integration is contained; pursue Synapxe partnership early |
| Caregiver doesn't trust AI recommendations | Bidirectional traceability and visible chain-of-thought from v1; HITL approval gate; memory that learns from dismissals |
| Grant landscape changes | Curated database in v1, live search with allowlist in v2, partnerships in v3 |
| Privacy / PDPA | Synthetic data only in v1; proper data handling architecture before any real patient data touches the system |

---

## Open Questions

- Whether to pursue Synapxe / AIC partnerships pre- or post-hackathon win.
- Whether monetization is B2C (caregiver subscription), B2B2C (hospital / polyclinic licensing), or grant-funded (MOH, Tote Board).
