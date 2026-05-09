import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

import app.main as main
from app.compliance import PrivacyIncidentCreate, create_privacy_incident
from app.config import Settings
from app.store import MemoryGraphStore


API_KEY = "security-test-key"
CLINICIAN_KEY = "clinician-test-key"


def _install_test_app(monkeypatch, settings: Settings | None = None):
    store = MemoryGraphStore(settings.data_encryption_key if settings else None)

    async def fake_init():
        return None

    store.init = fake_init
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(
        main,
        "settings",
        settings
        or Settings(
            api_write_key=API_KEY,
            clinician_review_key=CLINICIAN_KEY,
            legacy_demo_enabled=False,
            scheduled_review_enabled=False,
        ),
    )
    return store


def test_privacy_workflow_routes_record_consent_dsar_incident_and_retention(monkeypatch):
    store = _install_test_app(monkeypatch)

    old_created_at = datetime.now(UTC) - timedelta(days=40)

    async def seed_sensitive_nodes():
        transcript = await store.create_node(
            "transcript",
            {"patient_id": "mdm-tan", "raw_text": "John raw transcript", "normalized_english_text": "John normalized"},
            "system",
            status="approved",
        )
        redaction = await store.create_node(
            "pii_redaction",
            {"patient_id": "mdm-tan", "redacted_text": "PERSON_1 transcript", "placeholder_map": {"PERSON_1": "John"}},
            "system",
            status="approved",
        )
        store.nodes[transcript.id] = store.nodes[transcript.id].model_copy(update={"created_at": old_created_at})
        store.nodes[redaction.id] = store.nodes[redaction.id].model_copy(update={"created_at": old_created_at})
        return transcript, redaction

    asyncio.run(seed_sensitive_nodes())

    with TestClient(main.app) as client:
        consent = client.post(
            "/privacy/consents",
            headers={"X-API-Key": API_KEY},
            json={"purpose": "audio_transcription", "notice_version": "pilot.v1"},
        )
        request = client.post(
            "/privacy/requests",
            headers={"X-API-Key": API_KEY},
            json={"request_type": "access", "requester": "caregiver"},
        )
        incident = client.post(
            "/privacy/incidents",
            headers={"X-Clinician-Key": CLINICIAN_KEY},
            json={"summary": "Possible transcript exposure", "affected_data_categories": ["transcript"], "assessed_at": "2026-05-09T00:00:00Z"},
        )
        purge = client.post("/privacy/retention/purge", headers={"X-Clinician-Key": CLINICIAN_KEY})

    assert consent.status_code == 200
    assert consent.json()["payload"]["purpose"] == "audio_transcription"
    assert request.status_code == 200
    assert request.json()["payload"]["request_type"] == "access"
    assert incident.status_code == 200
    assert incident.json()["payload"]["singapore_pdpc_notify_by"] == "2026-05-12T00:00:00+00:00"
    assert purge.status_code == 200
    assert purge.json()["purged_count"] == 2
    transcripts = asyncio.run(store.list_nodes("mdm-tan", ["transcript"]))
    redactions = asyncio.run(store.list_nodes("mdm-tan", ["pii_redaction"]))
    assert transcripts[0].payload["raw_text"] is None
    assert transcripts[0].payload["normalized_english_text"] is None
    assert redactions[0].payload["placeholder_map"] == {}


def test_memory_store_encrypts_sensitive_fields_when_key_is_configured():
    store = MemoryGraphStore(encryption_key="local-test-secret")

    async def create_and_read():
        node = await store.create_node(
            "transcript",
            {"patient_id": "mdm-tan", "raw_text": "John raw transcript", "provider": "openai"},
            "system",
            status="approved",
        )
        stored_payload = store.nodes[node.id].payload
        listed = await store.list_nodes("mdm-tan", ["transcript"])
        return stored_payload, listed[0].payload

    stored_payload, read_payload = asyncio.run(create_and_read())
    assert stored_payload["raw_text"]["__encrypted__"] == "fernet-v1"
    assert "John raw transcript" not in str(stored_payload)
    assert read_payload["raw_text"] == "John raw transcript"


def test_incident_deadlines_can_be_computed_without_routes():
    store = MemoryGraphStore()
    assessed = datetime(2026, 5, 9, tzinfo=UTC)
    incident = asyncio.run(
        create_privacy_incident(
            store,
            PrivacyIncidentCreate(summary="Possible calendar leak", assessed_at=assessed, affected_user_count=1),
        )
    )
    assert incident.payload["singapore_pdpc_notify_by"] == "2026-05-12T00:00:00+00:00"
    assert incident.payload["regional_72h_notify_by"] == "2026-05-12T00:00:00+00:00"
