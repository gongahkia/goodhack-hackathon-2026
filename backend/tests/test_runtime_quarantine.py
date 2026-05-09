import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings
from app.store import MemoryGraphStore


@pytest.mark.asyncio
async def test_startup_does_not_seed_nehr_demo_data_when_legacy_demo_is_disabled(monkeypatch):
    test_store = MemoryGraphStore()
    monkeypatch.setattr(main, "store", test_store)
    monkeypatch.setattr(main, "settings", Settings(legacy_demo_enabled=False, scheduled_review_enabled=False))

    await main.startup()

    assert await test_store.list_nodes("mdm-tan") == []
    assert await test_store.list_nehr_raw("mdm-tan") == []


def test_legacy_nehr_demo_runtime_paths_are_gone_by_default(monkeypatch):
    monkeypatch.setattr(main, "store", MemoryGraphStore())
    monkeypatch.setattr(main, "settings", Settings(legacy_demo_enabled=False, scheduled_review_enabled=False))

    with TestClient(main.app) as client:
        assert client.post("/demo/reset").status_code == 410
        assert client.post("/demo/ingest").status_code == 410
        assert client.get("/records").status_code == 410

    with pytest.raises(HTTPException) as exc:
        main.require_legacy_demo_enabled()
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_scheduled_review_is_skipped_without_legacy_demo_runtime(monkeypatch):
    monkeypatch.setattr(main, "store", MemoryGraphStore())
    monkeypatch.setattr(main, "settings", Settings(legacy_demo_enabled=False, scheduled_review_enabled=True))

    result = await main.run_scheduled_review(force=True)

    assert result == {"skipped": True, "reason": "legacy_demo_disabled"}


def test_transcript_first_endpoint_remains_available_when_legacy_demo_is_disabled(monkeypatch):
    async def fake_ingest_audio_transcription(store, patient_id, audio, content_type, settings):
        assert patient_id == "mdm-tan"
        assert audio == b"fake audio"
        assert content_type == "audio/webm"
        return {
            "transcription_session": {"id": "session-1", "type": "transcription_session"},
            "transcript": {"id": "transcript-1", "type": "transcript", "raw_text": "John needs Panadol."},
            "reasoning_log_id": "log-1",
        }

    monkeypatch.setattr(main, "store", MemoryGraphStore())
    monkeypatch.setattr(main, "settings", Settings(legacy_demo_enabled=False, scheduled_review_enabled=False))
    monkeypatch.setattr(main, "ingest_audio_transcription", fake_ingest_audio_transcription)

    with TestClient(main.app) as client:
        response = client.post("/transcriptions", content=b"fake audio", headers={"Content-Type": "audio/webm"})

    assert response.status_code == 200
    assert response.json()["transcript"]["type"] == "transcript"
