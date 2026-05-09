import json
from pathlib import Path
from uuid import UUID

import pytest

from app.agent.loop import run_agent_for_trigger
from app.config import Settings
from app.demo import PATIENT_ID, ingest_trigger_records, seed_baseline
from app.eval import evaluate_care_plan
from app.graph_queries import backtrace_sources, forward_actions
from app.notifications import build_notifications
from app.store import MemoryGraphStore
from app.v2 import (
    build_appointment_prep,
    build_calendar_ics,
    build_care_plan_review,
    build_forecast,
    build_memory_profile,
    search_verified_grants,
    search_verified_resources,
    verify_live_result,
)


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
        assert action.payload["timing_type"] in {"fixed_time", "flexible_window", "deadline", "movable"}
        assert action.payload["urgency"] in {"clinical", "financial", "routine"}
        assert action.payload["estimated_effort_minutes"] > 0
        assert action.payload["scheduling_reason"]

    grant_tasks = [action for action in actions if "Seniors' Mobility" in action.payload["title"]]
    assert len(grant_tasks) == 1
    assert grant_tasks[0].payload["timing_type"] == "deadline"


@pytest.mark.asyncio
async def test_golden_parkinsons_schedule_expectations():
    fixture = json.loads((Path(__file__).parent / "golden" / "parkinsons_expected_schedule.json").read_text())
    store = MemoryGraphStore()
    await store.init()
    await seed_baseline(store)
    trigger = await ingest_trigger_records(store)
    await run_agent_for_trigger(store, Settings(demo_agent_mode="scripted"), PATIENT_ID, trigger["node_ids"][0])

    actions = await store.list_nodes(PATIENT_ID, ["scheduled_action"])
    titles = {action.payload["title"] for action in actions}
    action_types = {action.payload["action_type"] for action in actions}

    assert set(fixture["expected_action_types"]) <= action_types
    assert set(fixture["must_include_titles"]) <= titles


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


@pytest.mark.asyncio
async def test_notifications_include_pending_and_dismissed_care_actions():
    store = MemoryGraphStore()
    await store.init()
    await seed_baseline(store)
    trigger = await ingest_trigger_records(store)
    await run_agent_for_trigger(store, Settings(demo_agent_mode="scripted"), PATIENT_ID, trigger["node_ids"][0])

    action = (await store.list_nodes(PATIENT_ID, ["scheduled_action"]))[0]
    await store.update_node_status(action.id, "dismissed")
    feedback = await store.create_node(
        "caregiver_feedback",
        {"patient_id": PATIENT_ID, "target_node_id": str(action.id), "status": "dismissed", "usefulness_score": 1, "steer": "less"},
        "user",
        status="approved",
    )
    await store.create_edge(feedback.id, action.id, "feedback_on")

    notifications = build_notifications(await store.graph_subset(PATIENT_ID))

    assert any(item["kind"] == "review" for item in notifications)
    assert any(item["kind"] == "dismissed" and item["source_node_id"] == str(action.id) for item in notifications)


@pytest.mark.asyncio
async def test_v2_memory_profile_learns_from_feedback():
    store = MemoryGraphStore()
    await store.init()
    await seed_baseline(store)
    trigger = await ingest_trigger_records(store)
    await run_agent_for_trigger(store, Settings(demo_agent_mode="scripted"), PATIENT_ID, trigger["node_ids"][0])

    action = next(node for node in await store.list_nodes(PATIENT_ID, ["scheduled_action"]) if node.payload["action_type"] == "therapy")
    await store.update_node_status(action.id, "dismissed")
    feedback = await store.create_node(
        "caregiver_feedback",
        {"patient_id": PATIENT_ID, "target_node_id": str(action.id), "status": "dismissed", "usefulness_score": 1, "steer": "less"},
        "user",
        status="approved",
    )
    await store.create_edge(feedback.id, action.id, "feedback_on")

    profile = build_memory_profile(await store.graph_subset(PATIENT_ID))

    assert profile["feedback_count"] == 1
    assert profile["by_action_type"]["therapy"]["dismissed"] == 1
    assert profile["average_scores"]["therapy"] == 1
    assert any(item["kind"] == "downrank" for item in profile["learned_preferences"])
    assert any(item["kind"] == "steer_less" for item in profile["learned_preferences"])


@pytest.mark.asyncio
async def test_v2_care_plan_review_and_calendar_export():
    store = MemoryGraphStore()
    await store.init()
    await seed_baseline(store)
    trigger = await ingest_trigger_records(store)
    await run_agent_for_trigger(store, Settings(demo_agent_mode="scripted"), PATIENT_ID, trigger["node_ids"][0])

    graph = await store.graph_subset(PATIENT_ID)
    review = build_care_plan_review(graph, await store.list_reasoning_logs())
    calendar = build_calendar_ics(await store.list_nodes(PATIENT_ID, ["scheduled_action"]), "Test Care Plan")

    assert review["record_count"] >= 1
    assert review["narrative"]
    assert "BEGIN:VCALENDAR" in calendar
    assert "BEGIN:VEVENT" in calendar
    assert "Daily seated Parkinson's exercise".replace("'", "\\'") not in calendar
    assert "Daily seated Parkinson's exercise" in calendar


@pytest.mark.asyncio
async def test_v2_memory_conditions_scripted_reasoning():
    store = MemoryGraphStore()
    await store.init()
    await seed_baseline(store)
    previous_action = await store.create_node(
        "scheduled_action",
        {"patient_id": PATIENT_ID, "title": "Prior therapy prompt", "action_type": "therapy"},
        "agent",
    )
    feedback = await store.create_node(
        "caregiver_feedback",
        {"patient_id": PATIENT_ID, "target_node_id": str(previous_action.id), "status": "dismissed"},
        "user",
        status="approved",
    )
    await store.create_edge(feedback.id, previous_action.id, "feedback_on")
    trigger = await ingest_trigger_records(store)

    await run_agent_for_trigger(store, Settings(demo_agent_mode="scripted"), PATIENT_ID, trigger["node_ids"][0])

    actions = await store.list_nodes(PATIENT_ID, ["scheduled_action"])
    assert any(action.payload.get("title") == "Optional seated Parkinson's exercise" for action in actions)


@pytest.mark.asyncio
async def test_v2_verified_search_uses_allowlist_and_curated_fallback():
    rejected = verify_live_result({"title": "Bad source", "url": "https://example.com/item", "snippet": "Nope"})
    resources = await search_verified_resources("parkinson exercise", Settings(demo_agent_mode="scripted"))
    grants = await search_verified_grants("mobility parkinson", Settings(demo_agent_mode="scripted"))

    assert rejected["verification_status"] == "reject"
    assert resources
    assert all(item["verification_status"] == "safe_to_show" for item in resources)
    assert any("Seniors' Mobility" in item["title"] for item in grants)


@pytest.mark.asyncio
async def test_v2_appointment_prep_and_forecast():
    store = MemoryGraphStore()
    await store.init()
    await seed_baseline(store)
    trigger = await ingest_trigger_records(store)
    await run_agent_for_trigger(store, Settings(demo_agent_mode="scripted"), PATIENT_ID, trigger["node_ids"][0])

    graph = await store.graph_subset(PATIENT_ID)
    appointment = next(node for node in graph.nodes if node.type == "scheduled_action" and node.payload["action_type"] == "appointment")
    prep = build_appointment_prep(appointment, graph)
    forecast = build_forecast(graph)

    assert prep
    assert any("falls" in question.lower() for question in prep["questions_for_clinician"])
    assert prep["evidence"]
    assert any(item["title"] == "Apply for Seniors' Mobility and Enabling Fund" for item in forecast)
    smf = next(item for item in forecast if item["title"] == "Apply for Seniors' Mobility and Enabling Fund")
    assert smf["category"] == "grant"
    assert any(step["label"] == "Eligibility evidence" for step in smf["timeline"])


@pytest.mark.asyncio
async def test_v2_eval_harness_checks_each_decision():
    store = MemoryGraphStore()
    await store.init()
    await seed_baseline(store)
    trigger = await ingest_trigger_records(store)
    await run_agent_for_trigger(store, Settings(demo_agent_mode="scripted"), PATIENT_ID, trigger["node_ids"][0])

    result = evaluate_care_plan(await store.graph_subset(PATIENT_ID), await store.list_reasoning_logs())

    assert result["passed"]
    assert result["action_count"] == 4
    assert result["ungrounded_action_count"] == 0
    assert all(decision["provenance_correct"] for decision in result["decision_evals"])
    assert all(decision["reasoning_present"] for decision in result["decision_evals"])
