from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .agent.loop import run_agent_for_trigger
from .config import get_settings
from .demo import PATIENT, PATIENT_ID, ingest_trigger_records, seed_baseline
from .graph_queries import backtrace_sources, forward_actions
from .models import NodeEdit, StatusUpdate
from .store import GraphStore, MemoryGraphStore, PostgresGraphStore

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
    return [node.model_dump(mode="json") for node in nodes if node.status != "dismissed"]


@app.get("/events/{event_id}")
async def event_detail(event_id: UUID) -> dict:
    graph = await store.graph_subset(PATIENT_ID)
    node = await store.get_node(event_id)
    if not node:
        raise HTTPException(404, "Event not found")
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
    }


@app.patch("/nodes/{node_id}/status")
async def update_status(node_id: UUID, update: StatusUpdate) -> dict:
    node = await store.update_node_status(node_id, update.status)
    if not node:
        raise HTTPException(404, "Node not found")
    feedback = await store.create_node(
        "caregiver_feedback",
        {"patient_id": PATIENT_ID, "target_node_id": str(node_id), "status": update.status},
        "user",
        status="approved",
    )
    await store.create_edge(feedback.id, node_id, "feedback_on")
    return node.model_dump(mode="json")


@app.patch("/nodes/{node_id}")
async def edit_node(node_id: UUID, edit: NodeEdit) -> dict:
    node = await store.update_node_payload(node_id, edit.payload, edit.status)
    if not node:
        raise HTTPException(404, "Node not found")
    feedback = await store.create_node(
        "caregiver_feedback",
        {"patient_id": PATIENT_ID, "target_node_id": str(node_id), "status": edit.status, "payload_patch": edit.payload},
        "user",
        status="approved",
    )
    await store.create_edge(feedback.id, node_id, "feedback_on")
    return node.model_dump(mode="json")


@app.get("/audit")
async def audit_logs() -> list[dict]:
    return [log.model_dump(mode="json") for log in await store.list_reasoning_logs()]


@app.get("/audit/{log_id}")
async def audit_detail(log_id: UUID) -> dict:
    log = await store.get_reasoning_log(log_id)
    if not log:
        raise HTTPException(404, "Reasoning log not found")
    return log.model_dump(mode="json")
