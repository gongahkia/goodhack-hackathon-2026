import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings
from app.extraction import ExtractedEntities, process_redacted_transcript
from app.store import MemoryGraphStore
from app.transcript_pipeline import redact_stored_transcript


async def _transcript(store: MemoryGraphStore, text: str):
    return await store.create_node(
        "transcript",
        {"patient_id": "patient-1", "raw_text": text},
        "system",
        status="approved",
    )


@pytest.mark.asyncio
async def test_simple_medication_transcript_creates_daily_task_only_and_blocks_research():
    store = MemoryGraphStore()
    transcript = await _transcript(store, "John needs one Panadol 500mg before lunch daily.")
    redaction = await redact_stored_transcript(store, transcript)

    result = await process_redacted_transcript(store, redaction, reference_date=date(2026, 5, 9))

    triage = result["triage_decision"]["payload"]
    assert triage["buckets"] == ["daily_task"]
    assert triage["research_allowed"] is False
    assert result["ad_hoc_research_tasks"] == []
    assert len(result["daily_tasks"]) == 1

    task = result["daily_tasks"][0]["payload"]
    assert task["title"] == "Give Panadol before lunch"
    assert task["description"] == "John needs one Panadol 500mg before lunch daily"
    assert task["action_type"] == "medication"
    assert task["scheduling_semantics"] == "fixed_clinical"
    assert task["medication"]["dose"] == "500mg"
    assert task["medication"]["quantity"] == "one tablet"
    assert task["recurrence"] == "daily"


@pytest.mark.asyncio
async def test_transcript_can_create_daily_research_and_appointment_buckets_without_leaking_placeholders():
    store = MemoryGraphStore()
    transcript = await _transcript(
        store,
        (
            "John needs Panadol before lunch daily. "
            "Doctor said if high blood sugar continues John may need amputation, find wheelchair grants. "
            "Physio appointment on 28 Jan at 10am."
        ),
    )
    redaction = await redact_stored_transcript(store, transcript)

    result = await process_redacted_transcript(store, redaction, reference_date=date(2026, 5, 9))

    triage = result["triage_decision"]["payload"]
    assert triage["buckets"] == ["daily_task", "appointment", "ad_hoc_research"]
    assert triage["research_allowed"] is True
    assert len(result["daily_tasks"]) == 1
    assert len(result["ad_hoc_research_tasks"]) == 1
    assert len(result["appointment_candidates"]) == 1

    research = result["ad_hoc_research_tasks"][0]["payload"]
    assert "John" in research["basis"]
    assert "PERSON_" not in research["basis"]
    assert research["requires_guardrail_review"] is True
    assert research["source_status"] == "pending_guardrail"

    appointment = result["appointment_candidates"][0]["payload"]
    assert appointment["kind"] == "physio"
    assert appointment["date"] == "2027-01-28"
    assert appointment["time"] == "10:00"
    assert appointment["calendar_write_status"] == "pending_user_approval"


@pytest.mark.asyncio
async def test_extraction_payload_conforms_to_strict_schema():
    store = MemoryGraphStore()
    transcript = await _transcript(store, "John needs Panadol before lunch daily.")
    redaction = await redact_stored_transcript(store, transcript)

    result = await process_redacted_transcript(store, redaction, reference_date=date(2026, 5, 9))

    payload = result["extracted_entities"]["payload"]
    parsed = ExtractedEntities.model_validate(payload)
    assert parsed.people[0].placeholder_id == "PERSON_1"
    assert parsed.actionables[0].bucket_hint == "daily_task"


def test_process_transcription_endpoint_auto_redacts_extracts_and_triages(monkeypatch):
    store = MemoryGraphStore()

    async def fake_init():
        return None

    store.init = fake_init
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "settings", Settings(legacy_demo_enabled=False, scheduled_review_enabled=False))

    async def seed_graph():
        session = await store.create_node("transcription_session", {"patient_id": "mdm-tan"}, "user", status="approved")
        transcript = await store.create_node("transcript", {"patient_id": "mdm-tan", "raw_text": "John needs Panadol before lunch daily."}, "system", status="approved")
        await store.create_edge(session.id, transcript.id, "transcribed_to")
        return session.id

    session_id = asyncio.run(seed_graph())

    with TestClient(main.app) as client:
        response = client.post(f"/transcriptions/{session_id}/process")

    assert response.status_code == 200
    body = response.json()
    assert body["triage_decision"]["payload"]["buckets"] == ["daily_task"]
    assert body["daily_tasks"][0]["payload"]["title"] == "Give Panadol before lunch"
    assert asyncio.run(store.list_nodes("mdm-tan", ["pii_redaction"]))
