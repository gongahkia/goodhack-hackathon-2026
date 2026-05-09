import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings
from app.models import Node
from app.store import MemoryGraphStore


def test_legacy_nehr_demo_routes_are_physically_removed(monkeypatch):
    monkeypatch.setattr(main, "store", MemoryGraphStore())
    monkeypatch.setattr(main, "settings", Settings())

    with TestClient(main.app) as client:
        assert client.post("/demo/reset").status_code == 404
        assert client.post("/demo/ingest").status_code == 404
        assert client.get("/records").status_code == 404

    route_paths = {route.path for route in main.app.routes}
    assert "/demo/reset" not in route_paths
    assert "/demo/ingest" not in route_paths
    assert "/records" not in route_paths


@pytest.mark.asyncio
async def test_startup_initializes_without_seeding_legacy_data(monkeypatch):
    test_store = MemoryGraphStore()
    monkeypatch.setattr(main, "store", test_store)
    monkeypatch.setattr(main, "settings", Settings())

    await main.startup()

    assert await test_store.list_nodes("mdm-tan") == []


def test_transcript_first_endpoint_remains_available(monkeypatch):
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
    monkeypatch.setattr(main, "settings", Settings())
    monkeypatch.setattr(main, "ingest_audio_transcription", fake_ingest_audio_transcription)

    with TestClient(main.app) as client:
        response = client.post("/transcriptions", content=b"fake audio", headers={"Content-Type": "audio/webm"})

    assert response.status_code == 200
    assert response.json()["transcript"]["type"] == "transcript"


def test_nehr_node_type_is_no_longer_valid():
    with pytest.raises(Exception):
        Node(
            id="00000000-0000-0000-0000-000000000001",
            type="nehr_record",
            payload={"patient_id": "mdm-tan"},
            created_by="system",
            created_at="2026-05-10T00:00:00+08:00",
        )
