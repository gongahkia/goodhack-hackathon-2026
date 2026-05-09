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
from app.privacy import PiiRedactor, sanitize_audit_payload
from app.store import MemoryGraphStore
from app.v2 import (
    build_appointment_prep,
    build_calendar_ics,
    build_care_plan_review,
    build_forecast,
    build_memory_profile,
    exa_search_web,
    load_memory_profile,
    process_caregiver_note,
    refresh_memory_profile,
    search_verified_grants,
    search_verified_resources,
    sealion_guard_check,
    sealion_regional_review,
    tinyfish_fetch_urls,
    tinyfish_search_web,
    verify_live_result,
)
from app.v2 import _verify_live_results_with_openai


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
    therapy_memory = next(item for item in profile["action_type_memory"] if item["action_type"] == "therapy")
    assert therapy_memory["policy_scope"] == "preference"
    assert "Down-rank" in therapy_memory["recommendation"]
    assert profile["safety_policy"]["protected_action_types"]
    assert profile["recent_feedback"][0]["action_type"] == "therapy"
    assert any(item["preference_kind"] == "downrank" and item["safety_tier"] == "low_risk" for item in profile["structured_preferences"])


@pytest.mark.asyncio
async def test_v2_memory_does_not_suppress_protected_actions():
    store = MemoryGraphStore()
    await store.init()
    await seed_baseline(store)
    action = await store.create_node(
        "scheduled_action",
        {"patient_id": PATIENT_ID, "title": "Medication reminder", "action_type": "medication"},
        "agent",
    )
    feedback = await store.create_node(
        "caregiver_feedback",
        {"patient_id": PATIENT_ID, "target_node_id": str(action.id), "status": "dismissed", "usefulness_score": 1},
        "user",
        status="approved",
    )
    await store.create_edge(feedback.id, action.id, "feedback_on")

    profile = build_memory_profile(await store.graph_subset(PATIENT_ID))
    medication_memory = next(item for item in profile["structured_preferences"] if item["action_type"] == "medication")

    assert medication_memory["safety_tier"] == "protected"
    assert medication_memory["suppression_allowed"] is False


@pytest.mark.asyncio
async def test_structured_memory_profile_is_persisted_as_graph_node():
    store = MemoryGraphStore()
    await store.init()
    await seed_baseline(store)
    action = await store.create_node(
        "scheduled_action",
        {"patient_id": PATIENT_ID, "title": "Prior therapy prompt", "action_type": "therapy"},
        "agent",
    )
    feedback = await store.create_node(
        "caregiver_feedback",
        {"patient_id": PATIENT_ID, "target_node_id": str(action.id), "status": "dismissed", "usefulness_score": 1},
        "user",
        status="approved",
    )
    await store.create_edge(feedback.id, action.id, "feedback_on")

    memory_node = await refresh_memory_profile(store, PATIENT_ID)
    loaded = await load_memory_profile(store, PATIENT_ID)

    assert memory_node.type == "memory_profile"
    assert memory_node.status == "approved"
    assert loaded["feedback_count"] == 1
    assert any(item["preference_kind"] == "downrank" for item in loaded["structured_preferences"])

    await store.create_node(
        "caregiver_feedback",
        {"patient_id": PATIENT_ID, "target_node_id": str(action.id), "status": "approved", "usefulness_score": 5},
        "user",
        status="approved",
    )
    refreshed = await refresh_memory_profile(store, PATIENT_ID)

    assert refreshed.id == memory_node.id
    assert refreshed.payload["profile"]["feedback_count"] == 2


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


def test_pii_redactor_selective_redaction_preserves_clinical_context():
    redactor = PiiRedactor()
    redactor.seed_from_patient({"patient_id": "mdm-tan", "name": "Mdm Tan Siew Lan", "age": 78, "caregiver": "Daughter, Elaine"})
    payload = {
        "patient_id": "mdm-tan",
        "name": "Mdm Tan Siew Lan",
        "age": 78,
        "caregiver": "Daughter, Elaine",
        "email": "elaine@example.com",
        "phone": "+65 9123 4567",
        "nric": "S1234567D",
        "address": "Block 123 Toa Payoh #04-56 Singapore 310123",
        "note": "Levodopa appointment at Tan Tock Seng Hospital Neurology on 28 Jan for Parkinson's.",
    }

    redacted = redactor.redact(payload)

    assert redacted["patient_id"] == "PATIENT_ID_1"
    assert redacted["name"] == "PATIENT_1"
    assert redacted["age"] == "AGE_1"
    assert "CAREGIVER_1" in redacted["caregiver"]
    assert redacted["email"] == "EMAIL_1"
    assert redacted["phone"] == "PHONE_1"
    assert redacted["nric"] == "NRIC_1"
    assert redacted["address"] == "ADDRESS_1"
    assert "Levodopa" in redacted["note"]
    assert "Tan Tock Seng Hospital Neurology" in redacted["note"]
    assert "28 Jan" in redacted["note"]


def test_audit_payload_sanitizer_redacts_patient_identifiers():
    audit = {
        "trigger": "new_nehr_record:123",
        "steps": [
            {
                "kind": "thought",
                "text": "Mdm Tan Siew Lan asked Elaine to call +65 9123 4567 from Block 123 Toa Payoh #04-56 Singapore 310123.",
            }
        ],
    }

    sanitized = sanitize_audit_payload(audit, {"patient_id": "mdm-tan", "name": "Mdm Tan Siew Lan", "caregiver": "Daughter, Elaine"})
    payload = json.dumps(sanitized, default=str)

    assert "Mdm Tan Siew Lan" not in payload
    assert "Elaine" not in payload
    assert "+65 9123 4567" not in payload
    assert "Block 123" not in payload
    assert sanitized["audit_privacy"]["redaction_ran"] is True


@pytest.mark.asyncio
async def test_openai_agent_request_payload_is_pii_redacted(monkeypatch):
    import app.agent.loop as loop

    captured: list[dict] = []

    class FakeResponses:
        async def create(self, **request):
            captured.append(request)
            return type("FakeResponse", (), {"id": "resp_1", "output": [], "output_text": "done"})()

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr(loop, "AsyncOpenAI", FakeOpenAI)

    store = MemoryGraphStore()
    await store.init()
    await seed_baseline(store)
    trigger = await ingest_trigger_records(store)
    await run_agent_for_trigger(store, Settings(demo_agent_mode="openai", openai_api_key="test"), PATIENT_ID, trigger["node_ids"][0])

    payload = json.dumps(captured, default=str)

    assert captured
    assert "Mdm Tan Siew Lan" not in payload
    assert "Elaine" not in payload
    assert "mdm-tan" not in payload
    assert "PATIENT_1" in payload
    assert "CAREGIVER_1" in payload


@pytest.mark.asyncio
async def test_live_search_verification_payload_is_pii_redacted(monkeypatch):
    import app.v2 as v2

    captured: list[dict] = []

    class FakeResponses:
        async def create(self, **request):
            captured.append(request)
            return type(
                "FakeResponse",
                (),
                {"output_text": '{"decisions":[{"url":"https://www.aic.sg/item","status":"safe_to_show","reason":"official"}]}'},
            )()

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr(v2, "AsyncOpenAI", FakeOpenAI)

    await _verify_live_results_with_openai(
        [
            {
                "title": "AIC support",
                "url": "https://www.aic.sg/item",
                "snippet": "Call +65 9123 4567 or email elaine@example.com. NRIC S1234567D. Mdm Tan Siew Lan lives at Block 123 Toa Payoh #04-56 Singapore 310123.",
                "verification_status": "safe_to_show",
            }
        ],
        Settings(demo_agent_mode="openai", openai_api_key="test"),
        "Mdm Tan Siew Lan caregiver Elaine +65 9123 4567",
    )

    payload = json.dumps(captured, default=str)

    assert captured
    assert "+65 9123 4567" not in payload
    assert "elaine@example.com" not in payload
    assert "S1234567D" not in payload
    assert "Mdm Tan Siew Lan" not in payload
    assert "Block 123" not in payload
    assert "PHONE_1" in payload
    assert "EMAIL_1" in payload
    assert "NRIC_1" in payload


@pytest.mark.asyncio
async def test_caregiver_note_appointment_question_intent():
    store = MemoryGraphStore()
    await store.init()
    await seed_baseline(store)

    result = await process_caregiver_note(store, PATIENT_ID, "for 28 Jan appointment, remind me to ask doc about the new lump")
    graph = await store.graph_subset(PATIENT_ID)

    assert result["created"] == ["caregiver_note", "care_intent"]
    assert any(node.type == "caregiver_note" for node in graph.nodes)
    intent = next(node for node in graph.nodes if node.type == "care_intent")
    assert intent.payload["intent_type"] == "appointment_question"
    assert "new lump" in intent.payload["question"]
    assert any(edge.from_node == intent.id and edge.type == "extracted_from" for edge in graph.edges)


@pytest.mark.asyncio
async def test_caregiver_note_decision_forecast_flow():
    store = MemoryGraphStore()
    await store.init()
    await seed_baseline(store)

    result = await process_caregiver_note(store, PATIENT_ID, "doctor said consider wheelchair, decide by 15 June")
    graph = await store.graph_subset(PATIENT_ID)

    assert "decision_forecast" in result["created"]
    assert any(node.type == "decision_forecast" and "wheelchair" in node.payload["topic"] for node in graph.nodes)
    assert any(node.type == "research_note" for node in graph.nodes)
    scheduled = [node for node in graph.nodes if node.type == "scheduled_action"]
    assert len(scheduled) == 3
    assert all(any(edge.from_node == node.id and edge.type == "derived_from" for edge in graph.edges) for node in scheduled)


@pytest.mark.asyncio
async def test_v2_exa_and_tinyfish_are_first_class_agent_tools_without_keys():
    from app.agent.tools import AgentToolbox

    store = MemoryGraphStore()
    log = await store.create_reasoning_log("test")
    settings = Settings(demo_agent_mode="scripted")
    toolbox = AgentToolbox(store, settings, PATIENT_ID, log.id)
    tool_names = {tool["name"] for tool in toolbox.tool_specs()}

    assert {"exa_search", "tinyfish_search", "tinyfish_fetch", "sealion_regional_review", "sealion_guard_check"} <= tool_names
    assert (await toolbox.exa_search("AIC mobility grants"))["configured"] is False
    assert (await toolbox.tinyfish_search("HealthHub Parkinson exercise"))["configured"] is False
    fetch = await toolbox.tinyfish_fetch(["https://example.com/nope", "https://www.aic.sg/"])
    assert fetch["configured"] is False
    assert "https://example.com/nope" in fetch["rejected_urls"]
    assert (await toolbox.sealion_regional_review("Make this clearer"))["configured"] is False
    assert (await toolbox.sealion_guard_check("Is this safe?"))["configured"] is False


@pytest.mark.asyncio
async def test_v2_provider_wrappers_fail_closed_when_unconfigured():
    settings = Settings(demo_agent_mode="scripted")

    exa = await exa_search_web("MOH caregiver grants", settings)
    tiny_search = await tinyfish_search_web("MOH caregiver grants", settings)
    tiny_fetch = await tinyfish_fetch_urls(["https://www.moh.gov.sg/"], settings)
    sealion = await sealion_regional_review("Please simplify this reminder.", settings)
    guard = await sealion_guard_check("Caregiver prompt", settings)

    assert exa["provider"] == "exa"
    assert tiny_search["provider"] == "tinyfish_search"
    assert tiny_fetch["provider"] == "tinyfish_fetch"
    assert sealion["provider"] == "sealion"
    assert guard["provider"] == "sealion_guard"
    assert exa["configured"] is False
    assert tiny_search["configured"] is False
    assert tiny_fetch["configured"] is False
    assert sealion["configured"] is False
    assert guard["configured"] is False


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
