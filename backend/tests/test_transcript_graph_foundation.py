from pathlib import Path

import pytest

from app.store import MemoryGraphStore


TRANSCRIPT_FIRST_NODE_TYPES = {
    "transcription_session",
    "transcript",
    "transcript_review",
    "pii_redaction",
    "extracted_entities",
    "triage_decision",
    "daily_task",
    "schedule_conflict",
    "notification_candidate",
    "ad_hoc_research_task",
    "research_plan",
    "guardrail_review",
    "research_result",
    "synthesized_recommendation",
    "appointment_candidate",
    "calendar_write_request",
    "user_decision",
}

TRANSCRIPT_FIRST_EDGE_TYPES = {
    "transcribed_to",
    "redacted_as",
    "reviewed_from",
    "extracted_from",
    "triaged_from",
    "classified_as",
    "scheduled_from",
    "conflicts_with",
    "notifies_about",
    "researches",
    "guarded_by",
    "approved_research",
    "blocked_research",
    "synthesized_from",
    "requires_approval",
    "approved_by_user",
    "written_to_calendar",
}


@pytest.mark.asyncio
async def test_memory_graph_store_accepts_transcript_first_nodes_and_edges():
    patient_id = "patient-transcript-first"
    store = MemoryGraphStore()
    await store.init()

    session = await store.create_node(
        "transcription_session",
        {"patient_id": patient_id, "source": "audio_upload", "status": "received"},
        "user",
        status="approved",
    )
    transcript = await store.create_node(
        "transcript",
        {"patient_id": patient_id, "text": "John needs Panadol before lunch daily."},
        "system",
        status="approved",
    )
    redaction = await store.create_node(
        "pii_redaction",
        {
            "patient_id": patient_id,
            "redacted_text": "PERSON_1 needs Panadol before lunch daily.",
            "placeholder_map": {"PERSON_1": "John"},
        },
        "system",
        status="approved",
    )
    review = await store.create_node(
        "transcript_review",
        {
            "patient_id": patient_id,
            "pii_redaction_id": str(redaction.id),
            "provider": "sealion",
            "input_privacy": "direct_pii_redacted",
        },
        "agent",
        status="approved",
    )
    entities = await store.create_node(
        "extracted_entities",
        {
            "patient_id": patient_id,
            "people": [{"placeholder": "PERSON_1"}],
            "medications": [{"name": "Panadol", "timing": "before lunch"}],
            "recurrences": [{"frequency": "daily"}],
        },
        "agent",
    )
    triage = await store.create_node(
        "triage_decision",
        {"patient_id": patient_id, "buckets": ["daily_task"], "research_allowed": False},
        "agent",
    )
    daily_task = await store.create_node(
        "daily_task",
        {"patient_id": patient_id, "title": "Give Panadol before lunch", "fixed_clinical": True},
        "agent",
    )
    conflict = await store.create_node(
        "schedule_conflict",
        {"patient_id": patient_id, "reason": "meal spacing needs review"},
        "agent",
    )
    notification = await store.create_node(
        "notification_candidate",
        {"patient_id": patient_id, "send_at": "22:00", "timezone": "Asia/Singapore"},
        "system",
    )
    research_task = await store.create_node(
        "ad_hoc_research_task",
        {"patient_id": patient_id, "question": "Check wheelchair grant eligibility"},
        "agent",
    )
    research_plan = await store.create_node(
        "research_plan",
        {"patient_id": patient_id, "queries": ["Singapore wheelchair grant"]},
        "agent",
    )
    guardrail = await store.create_node(
        "guardrail_review",
        {"patient_id": patient_id, "decision": "approved"},
        "agent",
    )
    research_result = await store.create_node(
        "research_result",
        {"patient_id": patient_id, "source_tier": "official", "url": "https://www.aic.sg/"},
        "agent",
    )
    recommendation = await store.create_node(
        "synthesized_recommendation",
        {"patient_id": patient_id, "summary": "Review official mobility support options."},
        "agent",
    )
    appointment = await store.create_node(
        "appointment_candidate",
        {"patient_id": patient_id, "title": "Physio appointment", "requires_calendar_write": True},
        "agent",
    )
    calendar_request = await store.create_node(
        "calendar_write_request",
        {"patient_id": patient_id, "provider": "google_calendar", "status": "pending_user_approval"},
        "system",
    )
    user_decision = await store.create_node(
        "user_decision",
        {"patient_id": patient_id, "decision": "approved_calendar_write"},
        "user",
        status="approved",
    )

    await store.create_edge(session.id, transcript.id, "transcribed_to")
    await store.create_edge(transcript.id, redaction.id, "redacted_as")
    await store.create_edge(review.id, redaction.id, "reviewed_from")
    await store.create_edge(entities.id, redaction.id, "extracted_from")
    await store.create_edge(triage.id, entities.id, "triaged_from")
    await store.create_edge(daily_task.id, triage.id, "classified_as")
    await store.create_edge(daily_task.id, entities.id, "scheduled_from")
    await store.create_edge(conflict.id, daily_task.id, "conflicts_with")
    await store.create_edge(notification.id, conflict.id, "notifies_about")
    await store.create_edge(research_plan.id, research_task.id, "researches")
    await store.create_edge(research_plan.id, guardrail.id, "guarded_by")
    await store.create_edge(guardrail.id, research_plan.id, "approved_research")
    await store.create_edge(guardrail.id, research_task.id, "blocked_research")
    await store.create_edge(recommendation.id, research_result.id, "synthesized_from")
    await store.create_edge(calendar_request.id, appointment.id, "requires_approval")
    await store.create_edge(calendar_request.id, user_decision.id, "approved_by_user")
    await store.create_edge(calendar_request.id, appointment.id, "written_to_calendar")

    graph = await store.graph_subset(patient_id)

    assert TRANSCRIPT_FIRST_NODE_TYPES <= {node.type for node in graph.nodes}
    assert TRANSCRIPT_FIRST_EDGE_TYPES <= {edge.type for edge in graph.edges}


def test_postgres_schema_lists_transcript_first_node_and_edge_types():
    schema = (Path(__file__).resolve().parents[1] / "sql" / "schema.sql").read_text(encoding="utf-8")

    for node_type in TRANSCRIPT_FIRST_NODE_TYPES:
        assert f"'{node_type}'" in schema

    for edge_type in TRANSCRIPT_FIRST_EDGE_TYPES:
        assert f"'{edge_type}'" in schema
