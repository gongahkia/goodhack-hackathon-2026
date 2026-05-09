from __future__ import annotations

import asyncio
from contextlib import suppress
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .agent.loop import run_agent_for_trigger
from .config import get_settings
from .demo import PATIENT, PATIENT_ID, ingest_trigger_records, seed_baseline
from .eval import evaluate_care_plan
from .graph_queries import backtrace_sources, forward_actions
from .models import CaregiverNoteCreate, ClarificationUpdate, HumanEvaluationCreate, NodeEdit, StatusUpdate
from .notifications import build_notifications
from .privacy import PiiRedactor, sanitize_audit_payload
from .store import GraphStore, MemoryGraphStore, PostgresGraphStore
from .transcription import TranscriptionError, transcribe_audio
from .v2 import (
    build_appointment_prep,
    build_calendar_ics,
    build_care_plan_review,
    build_forecast,
    build_memory_profile,
    event_reasoning_narrative,
    create_human_evaluation,
    load_memory_profile,
    normalize_scheduling_payload,
    process_caregiver_note,
    refresh_memory_profile,
    resolve_caregiver_clarification,
    search_verified_grants,
    search_verified_resources,
    with_scheduling_metadata,
)

settings = get_settings()
store: GraphStore = (
    PostgresGraphStore(settings.database_url, settings.repo_root / "backend" / "sql" / "schema.sql")
    if settings.database_url
    else MemoryGraphStore()
)

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    await store.init()
    existing_nodes = await store.list_nodes(PATIENT_ID)
    if not existing_nodes:
        await rebuild_care_plan()
    if settings.scheduled_review_enabled:
        app.state.scheduled_review_task = asyncio.create_task(scheduled_review_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    task = getattr(app.state, "scheduled_review_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "store": "postgres" if settings.database_url else "memory"}


@app.post("/demo/reset")
async def reset_demo() -> dict:
    return await rebuild_care_plan()


@app.post("/demo/ingest")
async def ingest_demo() -> dict:
    result = await ingest_trigger_records(store)
    agent_result = await run_agent_for_trigger(store, settings, PATIENT_ID, result["node_ids"][0])
    return {**result, "agent": agent_result}


async def rebuild_care_plan() -> dict:
    baseline = await seed_baseline(store)
    trigger = await ingest_trigger_records(store)
    agent_result = await run_agent_for_trigger(store, settings, PATIENT_ID, trigger["node_ids"][0])
    return {**baseline, "trigger": trigger, "agent": agent_result}


async def scheduled_review_loop() -> None:
    while True:
        await asyncio.sleep(max(60, settings.scheduled_review_interval_seconds))
        with suppress(Exception):
            await run_scheduled_review()


async def run_scheduled_review() -> dict:
    graph = await store.graph_subset(PATIENT_ID)
    logs = await store.list_reasoning_logs()
    review = build_care_plan_review(graph, logs)
    log = await store.create_reasoning_log("scheduled_review")
    conclusion = " ".join(review["narrative"][:3])
    await store.append_reasoning_step(
        log.id,
        {
            "kind": "care_plan_review",
            "record_count": review["record_count"],
            "condition_count": review["condition_count"],
            "pending_review_count": review["pending_review_count"],
            "upcoming_30_day_count": review["upcoming_30_day_count"],
            "memory_instructions": review["memory_instructions"],
        },
    )
    await store.finish_reasoning_log(log.id, conclusion)
    return {"reasoning_log_id": str(log.id), "conclusion": conclusion, "review": review}


@app.get("/patient/summary")
async def patient_summary() -> dict:
    graph = await store.graph_subset(PATIENT_ID, ["inferred_condition"])
    conditions = [node.payload.get("display_name") for node in graph.nodes if node.payload.get("display_name")]
    patient = PATIENT.model_copy(update={"key_conditions": list(dict.fromkeys(PATIENT.key_conditions + conditions))})
    return patient.model_dump()


@app.get("/records")
async def records() -> list[dict]:
    graph = await store.graph_subset(PATIENT_ID)
    record_nodes = [node for node in graph.nodes if node.type == "nehr_record"]
    return [
        {**node.model_dump(mode="json"), "forward_actions": [action.model_dump(mode="json") for action in forward_actions(node, graph.nodes, graph.edges)]}
        for node in record_nodes
    ]


@app.get("/records/{record_id}")
async def record_detail(record_id: UUID) -> dict:
    graph = await store.graph_subset(PATIENT_ID)
    node = await store.get_node(record_id)
    if not node:
        raise HTTPException(404, "Record not found")
    return {
        **node.model_dump(mode="json"),
        "forward_actions": [action.model_dump(mode="json") for action in forward_actions(node, graph.nodes, graph.edges)],
    }


@app.get("/events")
async def events() -> list[dict]:
    nodes = await store.list_nodes(PATIENT_ID, ["scheduled_action"])
    return [with_scheduling_metadata(node).model_dump(mode="json") for node in nodes if node.status != "dismissed"]


@app.get("/events/{event_id}")
async def event_detail(event_id: UUID) -> dict:
    graph = await store.graph_subset(PATIENT_ID)
    node = await store.get_node(event_id)
    if not node:
        raise HTTPException(404, "Event not found")
    node = with_scheduling_metadata(node)
    related_edges = [edge for edge in graph.edges if edge.from_node == event_id or edge.to_node == event_id]
    related_ids = {edge.from_node for edge in related_edges} | {edge.to_node for edge in related_edges}
    related_nodes = [item for item in graph.nodes if item.id in related_ids and item.id != event_id]
    log = await store.get_reasoning_log(node.reasoning_log_id) if node.reasoning_log_id else None
    return {
        **node.model_dump(mode="json"),
        "source_records": [source.model_dump(mode="json") for source in backtrace_sources(node, graph.nodes, graph.edges)],
        "related_nodes": [item.model_dump(mode="json") for item in related_nodes],
        "related_edges": [edge.model_dump(mode="json") for edge in related_edges],
        "reasoning_log": log.model_dump(mode="json") if log else None,
        "reasoning_narrative": event_reasoning_narrative(node, graph, log),
        "appointment_prep": build_appointment_prep(node, graph),
    }


@app.get("/calendar.ics")
async def calendar_export() -> Response:
    nodes = await store.list_nodes(PATIENT_ID, ["scheduled_action"])
    active = [node for node in nodes if node.status != "dismissed"]
    return Response(
        build_calendar_ics(active, f"{PATIENT.name} Care Plan"),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="caregiver-companion-care-plan.ics"'},
    )


@app.get("/calendar/feed.ics")
async def calendar_feed() -> Response:
    nodes = await store.list_nodes(PATIENT_ID, ["scheduled_action"])
    active = [node for node in nodes if node.status != "dismissed"]
    return Response(
        build_calendar_ics(active, f"{PATIENT.name} Care Plan"),
        media_type="text/calendar; charset=utf-8",
    )


@app.get("/memory")
async def memory_profile() -> dict:
    return await load_memory_profile(store, PATIENT_ID)


@app.get("/care-plan/review")
async def care_plan_review() -> dict:
    graph = await store.graph_subset(PATIENT_ID)
    logs = await store.list_reasoning_logs()
    return build_care_plan_review(graph, logs)


@app.post("/care-plan/rereason")
async def care_plan_rereason() -> dict:
    return await run_scheduled_review()


@app.get("/forecast")
async def forecast() -> list[dict]:
    return build_forecast(await store.graph_subset(PATIENT_ID))


@app.post("/caregiver-notes")
async def caregiver_notes(note: CaregiverNoteCreate) -> dict:
    return await process_caregiver_note(store, PATIENT_ID, note.text, note.recorded_at, settings)


@app.patch("/care-intents/{node_id}/clarification")
async def clarify_caregiver_intent(node_id: UUID, update: ClarificationUpdate) -> dict:
    try:
        result = await resolve_caregiver_clarification(store, PATIENT_ID, node_id, update.answer, update.payload_patch, settings)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await refresh_memory_profile(store, PATIENT_ID)
    return result


@app.post("/transcribe")
async def transcribe(request: Request) -> dict:
    try:
        result = await transcribe_audio(await request.body(), request.headers.get("content-type"), settings)
        return result.model_dump()
    except TranscriptionError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.get("/resources/search")
async def resource_search(topic: str, condition: str | None = None) -> list[dict]:
    query = f"{topic} {condition or ''}".strip()
    return await search_verified_resources(query, settings)


@app.get("/grants/search")
async def grant_search(condition: str) -> list[dict]:
    return await search_verified_grants(condition, settings)


@app.get("/notifications")
async def notifications() -> list[dict]:
    graph = await store.graph_subset(PATIENT_ID)
    logs = await store.list_reasoning_logs()
    return build_notifications(graph, logs)


@app.patch("/nodes/{node_id}/status")
async def update_status(node_id: UUID, update: StatusUpdate) -> dict:
    node = await store.update_node_status(node_id, update.status)
    if not node:
        raise HTTPException(404, "Node not found")
    feedback = await store.create_node(
        "caregiver_feedback",
        {
            "patient_id": PATIENT_ID,
            "target_node_id": str(node_id),
            "status": update.status,
            "usefulness_score": update.usefulness_score,
            "feedback_note": update.feedback_note,
            "steer": update.steer,
        },
        "user",
        status="approved",
    )
    await store.create_edge(feedback.id, node_id, "feedback_on")
    await refresh_memory_profile(store, PATIENT_ID)
    return node.model_dump(mode="json")


@app.patch("/nodes/{node_id}")
async def edit_node(node_id: UUID, edit: NodeEdit) -> dict:
    existing = await store.get_node(node_id)
    payload = edit.payload
    if existing and existing.type == "scheduled_action":
        payload = normalize_scheduling_payload({**existing.payload, **edit.payload})
        payload = {key: value for key, value in payload.items() if key in edit.payload or key in {"timing_type", "urgency", "estimated_effort_minutes", "movable_window", "rest_interrupt_allowed", "scheduling_reason"}}
    node = await store.update_node_payload(node_id, payload, edit.status)
    if not node:
        raise HTTPException(404, "Node not found")
    feedback = await store.create_node(
        "caregiver_feedback",
        {"patient_id": PATIENT_ID, "target_node_id": str(node_id), "status": edit.status, "payload_patch": edit.payload},
        "user",
        status="approved",
    )
    await store.create_edge(feedback.id, node_id, "feedback_on")
    await refresh_memory_profile(store, PATIENT_ID)
    return node.model_dump(mode="json")


@app.get("/audit")
async def audit_logs() -> list[dict]:
    patient = PATIENT.model_dump(mode="json")
    return [sanitize_audit_payload(log.model_dump(mode="json"), patient) for log in await store.list_reasoning_logs()]


@app.get("/audit/{log_id}")
async def audit_detail(log_id: UUID) -> dict:
    log = await store.get_reasoning_log(log_id)
    if not log:
        raise HTTPException(404, "Reasoning log not found")
    return sanitize_audit_payload(log.model_dump(mode="json"), PATIENT.model_dump(mode="json"))


@app.post("/dev/redact")
async def dev_redact(payload: dict) -> dict:
    redactor = PiiRedactor()
    redactor.seed_from_patient(PATIENT.model_dump(mode="json"))
    redacted = redactor.redact(payload)
    return {"redacted": redacted, "privacy": redactor.summary()}


@app.get("/eval/care-plan")
async def care_plan_eval() -> dict:
    return evaluate_care_plan(await store.graph_subset(PATIENT_ID), await store.list_reasoning_logs())


@app.get("/eval/human")
async def human_eval_workflow() -> dict:
    graph = await store.graph_subset(PATIENT_ID)
    automated = evaluate_care_plan(graph, await store.list_reasoning_logs())
    evaluations = [node.model_dump(mode="json") for node in graph.nodes if node.type == "human_evaluation"]
    evaluated_ids = {item["payload"].get("action_id") for item in evaluations}
    queue = [
        node.model_dump(mode="json")
        for node in graph.nodes
        if node.type == "scheduled_action" and str(node.id) not in evaluated_ids and node.status != "dismissed"
    ]
    return {
        "automated": automated,
        "evaluations": evaluations,
        "queue": sorted(queue, key=lambda item: item["payload"].get("start_at") or "")[:10],
    }


@app.post("/eval/human")
async def submit_human_eval(evaluation: HumanEvaluationCreate) -> dict:
    try:
        node = await create_human_evaluation(store, PATIENT_ID, evaluation.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return node.model_dump(mode="json")
