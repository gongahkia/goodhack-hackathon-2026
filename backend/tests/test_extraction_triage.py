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


async def _native_redaction(store: MemoryGraphStore, text: str, language: str):
    return await store.create_node(
        "pii_redaction",
        {
            "patient_id": "patient-1",
            "redacted_text": text,
            "placeholder_map": {"PERSON_1": "John"},
            "detected_language": language,
            "source_text_kind": "original",
        },
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
    assert research["basis"]
    assert "PERSON_" not in research["basis"]
    assert research["requires_guardrail_review"] is True
    assert research["source_status"] == "pending_guardrail"

    appointment = result["appointment_candidates"][0]["payload"]
    assert appointment["kind"] == "physio"
    assert appointment["date"] == "2027-01-28"
    assert appointment["time"] == "10:00"
    assert appointment["calendar_write_status"] == "pending_user_approval"


@pytest.mark.asyncio
async def test_month_day_year_appointment_requires_calendar_write():
    store = MemoryGraphStore()
    transcript = await _transcript(store, "John has a doctor appointment on June 1, 2026 at 10am.")
    redaction = await redact_stored_transcript(store, transcript)

    result = await process_redacted_transcript(store, redaction, reference_date=date(2026, 5, 9))

    appointment = result["appointment_candidates"][0]["payload"]
    assert appointment["kind"] == "doctor"
    assert appointment["date"] == "2026-06-01"
    assert appointment["time"] == "10:00"
    assert appointment["requires_calendar_write"] is True
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
    monkeypatch.setattr(main, "settings", Settings())

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "text", "expected_kind", "expected_date"),
    [
        (
            "ms",
            "PERSON_1 perlu makan Panadol sebelum makan tengah hari setiap hari. Temu janji doktor pada 2026-06-01 at 10am. Doktor kata mungkin perlu kerusi roda, cari subsidi kerusi roda.",
            "doctor",
            "2026-06-01",
        ),
        (
            "ta",
            "PERSON_1 தினமும் மதிய உணவுக்கு முன் Panadol எடுத்துக்கொள்ள வேண்டும். மருத்துவர் சந்திப்பு 2026-06-01 at 10am. மருத்துவர் சொன்னார் சக்கர நாற்காலி உதவி தேவைப்படலாம்.",
            "doctor",
            "2026-06-01",
        ),
        (
            "zh",
            "PERSON_1 每天午餐前需要吃 Panadol。6月1日 医生预约 at 10am。医生说可能需要轮椅补助。",
            "doctor",
            "2026-06-01",
        ),
        (
            "th",
            "PERSON_1 ต้องกิน Panadol ก่อนอาหารกลางวันทุกวัน. นัดพบแพทย์ 2026-06-01 at 10am. หมอบอกว่าอาจต้องใช้รถเข็น หาเงินช่วยเหลือรถเข็น.",
            "doctor",
            "2026-06-01",
        ),
    ],
)
async def test_native_multilingual_extraction_without_english_normalization(language, text, expected_kind, expected_date):
    store = MemoryGraphStore()
    redaction = await _native_redaction(store, text, language)

    result = await process_redacted_transcript(store, redaction, reference_date=date(2026, 5, 9))

    triage = result["triage_decision"]["payload"]
    task = result["daily_tasks"][0]["payload"]
    appointment = result["appointment_candidates"][0]["payload"]
    research = result["ad_hoc_research_tasks"][0]["payload"]

    assert triage["buckets"] == ["daily_task", "appointment", "ad_hoc_research"]
    assert task["title"] == "Give Panadol before lunch"
    assert task["recurrence"] == "daily"
    assert task["timing_relation"] == "before lunch"
    assert appointment["kind"] == expected_kind
    assert appointment["date"] == expected_date
    assert appointment["time"] == "10:00"
    assert research["basis"]
    assert "PERSON_" not in research["basis"]


@pytest.mark.asyncio
async def test_native_multilingual_extraction_tolerates_invalid_dates_and_times():
    store = MemoryGraphStore()
    redaction = await _native_redaction(
        store,
        "PERSON_1 每天午餐前需要吃 Panadol。13月40日 医生预约 at 25:99am。",
        "zh",
    )

    result = await process_redacted_transcript(store, redaction, reference_date=date(2026, 5, 9))

    task = result["daily_tasks"][0]["payload"]
    appointment = result["appointment_candidates"][0]["payload"]

    assert task["recurrence"] == "daily"
    assert task["timing_relation"] == "before lunch"
    assert appointment["kind"] == "doctor"
    assert appointment["date"] is None
    assert appointment["time"] is None


@pytest.mark.asyncio
async def test_sealion_extraction_review_localizes_non_english_artifacts_without_overwriting_canonical_fields(monkeypatch):
    calls = []

    async def fake_sealion_review(settings, *, task, input_payload, schema, target_language="English", max_tokens=800):
        calls.append({"task": task, "input_payload": input_payload, "target_language": target_language})
        if task == "extraction_sanity_check":
            return {
                "provider": "sealion",
                "configured": True,
                "model": settings.sealion_model,
                "task": task,
                "target_language": target_language,
                "result": {
                    "flags": [{"category": "medication_timing_ambiguous", "severity": "warning", "message": "Check lunch timing."}],
                    "clarification_questions": ["Adakah ubat ini perlu diambil sebelum makan tengah hari?"],
                    "confidence": 0.8,
                },
            }
        daily_id = input_payload["artifacts"]["daily_tasks"][0]["id"]
        research_id = input_payload["artifacts"]["ad_hoc_research_tasks"][0]["id"]
        return {
            "provider": "sealion",
            "configured": True,
            "model": settings.sealion_model,
            "task": task,
            "target_language": target_language,
            "result": {
                "daily_tasks": [
                    {
                        "id": daily_id,
                        "title": "Beri Panadol sebelum makan tengah hari",
                        "description": "Beri Panadol sebelum makan tengah hari setiap hari",
                        "clarification_questions": ["Pukul berapa makan tengah hari biasanya?"],
                    }
                ],
                "ad_hoc_research_tasks": [{"id": research_id, "question": "Apakah subsidi kerusi roda yang boleh disemak?"}],
                "appointment_candidates": [],
                "clarification_questions": ["Adakah temujanji sudah ditempah?"],
            },
        }

    monkeypatch.setattr("app.sealion_reviews.sealion_regional_json_review", fake_sealion_review)
    store = MemoryGraphStore()
    redaction = await _native_redaction(
        store,
        "PERSON_1 perlu makan Panadol sebelum makan tengah hari setiap hari. Doktor kata mungkin perlu kerusi roda, cari subsidi kerusi roda.",
        "ms",
    )

    result = await process_redacted_transcript(
        store,
        redaction,
        reference_date=date(2026, 5, 9),
        settings=Settings(sealion_transcript_review_enabled=True, sealion_api_key="test-sealion"),
    )

    task = result["daily_tasks"][0]["payload"]
    research = result["ad_hoc_research_tasks"][0]["payload"]
    reviews = await store.list_nodes("patient-1", ["transcript_review"])

    assert {call["task"] for call in calls} == {"extraction_sanity_check", "caregiver_facing_localization"}
    assert "John" not in str(calls)
    assert task["title"] == "Give Panadol before lunch"
    assert task["localized_display"]["ms"]["title"] == "Beri Panadol sebelum makan tengah hari"
    assert task["sealion_clarification_questions"] == ["Adakah ubat ini perlu diambil sebelum makan tengah hari?"]
    assert task["localized_clarification_questions"]["ms"] == ["Pukul berapa makan tengah hari biasanya?"]
    assert research["localized_display"]["ms"]["question"] == "Apakah subsidi kerusi roda yang boleh disemak?"
    assert {review.payload["kind"] for review in reviews} == {"extraction_sanity_check", "caregiver_facing_localization"}
