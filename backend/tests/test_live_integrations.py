from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.transcript_pipeline as transcript_pipeline
from app.config import Settings
from app.quality import transcript_quality
from app.scheduler import SINGAPORE_TZ
from app.sealion_reviews import sealion_guard_json_review, sealion_regional_json_review
from app.store import MemoryGraphStore, PostgresGraphStore
from app.transcription import transcribe_audio
from app.v2 import tinyfish_search_web


pytestmark = pytest.mark.integration


def _live_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


requires_live_openai = pytest.mark.skipif(
    not (_live_enabled("RUN_LIVE_OPENAI_TESTS") and os.getenv("OPENAI_API_KEY") and os.getenv("LIVE_OPENAI_AUDIO_PATH")),
    reason="set RUN_LIVE_OPENAI_TESTS=1, OPENAI_API_KEY, and LIVE_OPENAI_AUDIO_PATH to run live OpenAI tests",
)
requires_live_tinyfish = pytest.mark.skipif(
    not (_live_enabled("RUN_LIVE_TINYFISH_TESTS") and os.getenv("TINYFISH_API_KEY")),
    reason="set RUN_LIVE_TINYFISH_TESTS=1 and TINYFISH_API_KEY to run live TinyFish tests",
)
requires_postgres = pytest.mark.skipif(
    not (_live_enabled("RUN_POSTGRES_INTEGRATION_TESTS") and os.getenv("TEST_DATABASE_URL")),
    reason="set RUN_POSTGRES_INTEGRATION_TESTS=1 and TEST_DATABASE_URL to run Postgres integration tests",
)
requires_live_sealion = pytest.mark.skipif(
    not (_live_enabled("RUN_LIVE_SEALION_TESTS") and os.getenv("SEALION_API_KEY")),
    reason="set RUN_LIVE_SEALION_TESTS=1 and SEALION_API_KEY to run live SEA-LION tests",
)
requires_live_external_e2e = pytest.mark.skipif(
    not (
        _live_enabled("RUN_LIVE_EXTERNAL_E2E")
        and os.getenv("OPENAI_API_KEY")
        and os.getenv("GOOGLE_CALENDAR_ACCESS_TOKEN")
        and (os.getenv("TINYFISH_API_KEY") or os.getenv("EXA_API_KEY"))
    ),
    reason="set RUN_LIVE_EXTERNAL_E2E=1, OPENAI_API_KEY, GOOGLE_CALENDAR_ACCESS_TOKEN, and TINYFISH_API_KEY or EXA_API_KEY",
)


@requires_live_openai
@pytest.mark.asyncio
async def test_live_openai_transcription_smoke():
    audio_path = Path(os.environ["LIVE_OPENAI_AUDIO_PATH"])
    suffix_to_type = {".wav": "audio/wav", ".webm": "audio/webm", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}
    content_type = suffix_to_type.get(audio_path.suffix.lower(), "application/octet-stream")

    result = await transcribe_audio(
        audio_path.read_bytes(),
        content_type,
        Settings(
            transcription_provider="openai",
            openai_api_key=os.environ["OPENAI_API_KEY"],
            openai_transcription_model=os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-transcribe"),
        ),
    )

    assert result.provider == "openai"
    assert result.model
    assert result.text.strip()


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "ms", "ta", "zh", "th"])
async def test_live_openai_multilingual_transcription_quality(language):
    if not _live_enabled("RUN_LIVE_OPENAI_MULTILINGUAL_TESTS") or not os.getenv("OPENAI_API_KEY"):
        pytest.skip("set RUN_LIVE_OPENAI_MULTILINGUAL_TESTS=1 and OPENAI_API_KEY to run live multilingual transcription tests")
    audio_path_value = os.getenv(f"LIVE_OPENAI_AUDIO_{language.upper()}_PATH")
    reference = os.getenv(f"LIVE_OPENAI_TRANSCRIPT_{language.upper()}")
    if not audio_path_value or not reference:
        pytest.skip(f"set LIVE_OPENAI_AUDIO_{language.upper()}_PATH and LIVE_OPENAI_TRANSCRIPT_{language.upper()} for {language}")

    audio_path = Path(audio_path_value)
    suffix_to_type = {".wav": "audio/wav", ".webm": "audio/webm", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}
    result = await transcribe_audio(
        audio_path.read_bytes(),
        suffix_to_type.get(audio_path.suffix.lower(), "application/octet-stream"),
        Settings(
            transcription_provider="openai",
            openai_api_key=os.environ["OPENAI_API_KEY"],
            openai_transcription_model=os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-transcribe"),
            transcription_language=language,
        ),
    )
    quality = transcript_quality(reference, result.text, language)

    assert result.provider == "openai"
    assert result.text.strip()
    assert quality["passed"], quality


@requires_live_sealion
@pytest.mark.asyncio
async def test_live_sealion_regional_json_review_smoke():
    result = await sealion_regional_json_review(
        Settings(sealion_api_key=os.environ["SEALION_API_KEY"]),
        task="live_transcript_qa_smoke",
        target_language="English",
        input_payload={"redacted_transcript": "PERSON_1 needs Panadol before lunch.", "checks": ["date/time ambiguity"]},
        schema={"flags": [], "confidence": 0.0},
        max_tokens=300,
    )

    assert result["provider"] == "sealion"
    assert result["configured"] is True
    assert result["result"] is not None, result


@requires_live_sealion
@pytest.mark.asyncio
async def test_live_sealion_guard_json_review_smoke():
    result = await sealion_guard_json_review(
        Settings(sealion_api_key=os.environ["SEALION_API_KEY"]),
        prompt="Research wheelchair subsidies for PERSON_1 in Singapore. Do not provide medical advice.",
        max_tokens=200,
    )

    assert result["provider"] == "sealion_guard"
    assert result["configured"] is True
    assert result["result"] is not None, result


@requires_live_tinyfish
@pytest.mark.asyncio
async def test_live_tinyfish_search_smoke():
    result = await tinyfish_search_web(
        "Singapore Seniors Mobility Enabling Fund AIC wheelchair",
        Settings(tinyfish_api_key=os.environ["TINYFISH_API_KEY"], openai_api_key=None, live_search_llm_verification=False),
        allowlist=["aic.sg"],
    )

    assert result["provider"] == "tinyfish_search"
    assert result["configured"] is True
    assert "results" in result


@requires_live_external_e2e
def test_live_external_provider_full_api_e2e(monkeypatch):
    audio, content_type, expected_text = _live_e2e_audio()
    api_key = os.getenv("LIVE_EXTERNAL_E2E_API_KEY", "live-external-e2e-key")
    calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    access_token = os.environ["GOOGLE_CALENDAR_ACCESS_TOKEN"]
    settings = Settings(
        api_write_key=api_key,
        transcription_provider="openai",
        openai_api_key=os.environ["OPENAI_API_KEY"],
        openai_transcription_model=os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-transcribe"),
        tinyfish_api_key=os.getenv("TINYFISH_API_KEY"),
        exa_api_key=os.getenv("EXA_API_KEY"),
        sealion_api_key=None,
        sealion_transcript_review_enabled=False,
        live_search_llm_verification=False,
        google_calendar_access_token=access_token,
        google_calendar_id=calendar_id,
    )
    store = MemoryGraphStore()
    created_calendar_event_ids: list[str] = []

    async def fake_init():
        return None

    store.init = fake_init
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(transcript_pipeline, "transcribe_audio", transcribe_audio)

    busy_event_id = _create_live_calendar_busy_event(settings)
    created_calendar_event_ids.append(busy_event_id)

    headers = {"X-API-Key": api_key}
    try:
        with TestClient(main.app) as client:
            created = client.post(
                "/transcriptions?language=en",
                content=audio,
                headers={**headers, "Content-Type": content_type},
            )
            assert created.status_code == 200, created.text
            transcript_text = created.json()["transcript"]["payload"]["raw_text"]
            assert _contains_core_terms(transcript_text), {"expected": expected_text, "actual": transcript_text}

            session_id = created.json()["transcription_session"]["id"]
            processed = client.post(f"/transcriptions/{session_id}/process", headers=headers)
            assert processed.status_code == 200, processed.text
            body = processed.json()
            assert body["daily_tasks"], body
            assert body["appointment_candidates"], body
            assert body["ad_hoc_research_tasks"], body

            daily_task = body["daily_tasks"][0]
            appointment = body["appointment_candidates"][0]
            research_task = body["ad_hoc_research_tasks"][0]
            assert daily_task["payload"]["title"] == "Give Panadol before lunch"
            assert appointment["payload"]["requires_calendar_write"] is True
            assert research_task["payload"]["requires_guardrail_review"] is True

            calendar_write = client.post(f"/appointments/{appointment['id']}/approve-calendar-write", headers=headers)
            assert calendar_write.status_code == 200, calendar_write.text
            calendar_event = calendar_write.json()["calendar_event"]
            assert calendar_event and calendar_event.get("id"), calendar_write.json()
            created_calendar_event_ids.append(calendar_event["id"])

            scheduler = client.post("/scheduler/next-day-check", headers=headers)
            assert scheduler.status_code == 200, scheduler.text
            scheduler_body = scheduler.json()
            assert scheduler_body["calendar_event_count"] >= 1, scheduler_body
            assert scheduler_body["schedule_conflicts"], scheduler_body

            research = client.post(f"/research/tasks/{research_task['id']}/run", headers=headers)
            assert research.status_code == 200, research.text
            recommendation = research.json()["synthesized_recommendation"]["payload"]
            assert recommendation["evidence"], recommendation
            assert any(source["provider"] != "curated_corpus" for source in recommendation["evidence"]), recommendation["evidence"]

            notifications = client.get("/notifications", headers=headers)
            assert notifications.status_code == 200, notifications.text
            kinds = {item["kind"] for item in notifications.json()}
            assert {"daily task review", "next-day conflict warning", "research result ready"} <= kinds
    finally:
        if os.getenv("LIVE_EXTERNAL_E2E_CLEANUP_CALENDAR", "1").strip().lower() not in {"0", "false", "no", "off"}:
            for event_id in reversed(created_calendar_event_ids):
                _delete_live_calendar_event(settings, event_id)


@requires_postgres
@pytest.mark.asyncio
async def test_postgres_graph_store_transcript_first_schema_roundtrip():
    store = PostgresGraphStore(os.environ["TEST_DATABASE_URL"], Path("backend/sql/schema.sql"))
    await store.init()
    patient_id = f"postgres-integration-{uuid4()}"

    try:
        log = await store.create_reasoning_log("postgres_integration")
        session = await store.create_node("transcription_session", {"patient_id": patient_id}, "user", log.id, "approved")
        transcript = await store.create_node("transcript", {"patient_id": patient_id, "raw_text": "PERSON_1 needs Panadol."}, "system", log.id, "approved")
        redaction = await store.create_node(
            "pii_redaction",
            {"patient_id": patient_id, "redacted_text": "PERSON_1 needs Panadol.", "placeholder_map": {"PERSON_1": "John"}},
            "system",
            log.id,
            "approved",
        )
        review = await store.create_node(
            "transcript_review",
            {"patient_id": patient_id, "provider": "sealion", "input_privacy": "direct_pii_redacted"},
            "agent",
            log.id,
            "approved",
        )

        await store.create_edge(session.id, transcript.id, "transcribed_to")
        await store.create_edge(transcript.id, redaction.id, "redacted_as")
        await store.create_edge(review.id, redaction.id, "reviewed_from")

        graph = await store.graph_subset(patient_id)
        assert {"transcription_session", "transcript", "pii_redaction", "transcript_review"} <= {node.type for node in graph.nodes}
        assert {"transcribed_to", "redacted_as", "reviewed_from"} <= {edge.type for edge in graph.edges}
    finally:
        if store.pool:
            await store.pool.close()


def _live_e2e_audio() -> tuple[bytes, str, str]:
    transcript = os.getenv(
        "LIVE_EXTERNAL_E2E_TRANSCRIPT",
        (
            "Mom needs Panadol before lunch every day. "
            "Mom has a doctor appointment on June first twenty twenty six at ten AM. "
            "Doctor said Mom may need wheelchair support, find Singapore wheelchair grants."
        ),
    )
    audio_path = os.getenv("LIVE_EXTERNAL_E2E_AUDIO_PATH")
    if audio_path:
        path = Path(audio_path)
        suffix_to_type = {".wav": "audio/wav", ".webm": "audio/webm", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}
        return path.read_bytes(), suffix_to_type.get(path.suffix.lower(), "application/octet-stream"), transcript

    if not shutil.which("say") or not shutil.which("afconvert"):
        pytest.skip("set LIVE_EXTERNAL_E2E_AUDIO_PATH or run on macOS with say and afconvert available")

    with tempfile.TemporaryDirectory() as tmp:
        aiff_path = Path(tmp) / "live-external-e2e.aiff"
        wav_path = Path(tmp) / "live-external-e2e.wav"
        subprocess.run(["say", "-o", str(aiff_path), transcript], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16", str(aiff_path), str(wav_path)], check=True)
        return wav_path.read_bytes(), "audio/wav", transcript


def _create_live_calendar_busy_event(settings: Settings) -> str:
    target_date = (datetime.now(SINGAPORE_TZ) + timedelta(days=1)).date()
    start_at = datetime.combine(target_date, datetime.strptime("11:15", "%H:%M").time(), tzinfo=SINGAPORE_TZ)
    end_at = start_at + timedelta(hours=1)
    payload = {
        "summary": "LIVE_E2E_BUSY_CONFLICT",
        "description": "Temporary event created by Caregiver Companion live external E2E test.",
        "start": {"dateTime": start_at.isoformat(), "timeZone": "Asia/Singapore"},
        "end": {"dateTime": end_at.isoformat(), "timeZone": "Asia/Singapore"},
    }
    url = f"{settings.google_calendar_api_base_url.rstrip('/')}/calendars/{settings.google_calendar_id}/events"
    headers = {"Authorization": f"Bearer {settings.google_calendar_access_token}", "Content-Type": "application/json"}
    response = httpx.post(url, json=payload, headers=headers, timeout=20)
    response.raise_for_status()
    return str(response.json()["id"])


def _delete_live_calendar_event(settings: Settings, event_id: str) -> None:
    url = f"{settings.google_calendar_api_base_url.rstrip('/')}/calendars/{settings.google_calendar_id}/events/{event_id}"
    headers = {"Authorization": f"Bearer {settings.google_calendar_access_token}"}
    with httpx.Client(timeout=20) as client:
        response = client.delete(url, headers=headers)
    if response.status_code not in {204, 404, 410}:
        response.raise_for_status()


def _contains_core_terms(text: str) -> bool:
    lowered = text.lower()
    return "panadol" in lowered and "appointment" in lowered and "wheelchair" in lowered
