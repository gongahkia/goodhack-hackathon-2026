from uuid import UUID

import pytest

from app.agent.loop import run_agent_for_trigger
from app.config import Settings
from app.demo import PATIENT_ID, ingest_trigger_records, seed_baseline
from app.graph_queries import backtrace_sources, forward_actions
from app.notifications import build_notifications
from app.store import MemoryGraphStore


@pytest.mark.asyncio
async def test_demo_flow_creates_grounded_actions():
    store = MemoryGraphStore()
    await store.init()
    await seed_baseline(store)
    trigger = await ingest_trigger_records(store)

    result = await run_agent_for_trigger(
        store,
        Settings(demo_agent_mode="scripted"),
        PATIENT_ID,
        trigger["node_ids"][0],
    )

    assert UUID(result["reasoning_log_id"])
    actions = await store.list_nodes(PATIENT_ID, ["scheduled_action"])
    assert len(actions) == 4
    edges = await store.list_edges()
    for action in actions:
        assert any(edge.from_node == action.id and edge.type == "derived_from" for edge in edges)

    grant_tasks = [action for action in actions if "Seniors' Mobility" in action.payload["title"]]
    assert len(grant_tasks) == 1


@pytest.mark.asyncio
async def test_bidirectional_trace_helpers():
    store = MemoryGraphStore()
    await store.init()
    await seed_baseline(store)
    trigger = await ingest_trigger_records(store)
    await run_agent_for_trigger(store, Settings(demo_agent_mode="scripted"), PATIENT_ID, trigger["node_ids"][0])

    graph = await store.graph_subset(PATIENT_ID)
    diagnosis = next(node for node in graph.nodes if node.id == UUID(trigger["node_ids"][0]))
    spawned = forward_actions(diagnosis, graph.nodes, graph.edges)
    assert any("exercise" in action.payload["title"].lower() for action in spawned)

    grant_task = next(node for node in graph.nodes if node.type == "scheduled_action" and "Seniors' Mobility" in node.payload["title"])
    sources = backtrace_sources(grant_task, graph.nodes, graph.edges)
    assert any(source.type == "nehr_record" for source in sources)


@pytest.mark.asyncio
async def test_unprovenanced_scheduled_action_is_rejected_by_toolbox():
    from app.agent.tools import AgentToolbox

    store = MemoryGraphStore()
    log = await store.create_reasoning_log("test")
    toolbox = AgentToolbox(store, Settings(demo_agent_mode="scripted"), PATIENT_ID, log.id)

    result = await toolbox.create_node("scheduled_action", {"title": "Ungrounded task"})
    assert result["state"] == "staged_until_derived_from_edge"
    errors = await toolbox.finalize()

    assert errors
    assert await store.list_nodes(PATIENT_ID, ["scheduled_action"]) == []
