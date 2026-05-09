import asyncio

from fastapi.testclient import TestClient

import app.main as main
import app.transcript_pipeline as transcript_pipeline
from app.config import Settings
from app.store import MemoryGraphStore
from app.transcription import TranscriptionResult


API_KEY = "test-write-key"


def _install_test_app(monkeypatch):
    store = MemoryGraphStore()

    async def fake_init():
        return None

    store.init = fake_init
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(
        main,
        "settings",
        Settings(
            legacy_demo_enabled=False,
            scheduled_review_enabled=False,
            api_write_key=API_KEY,
            openai_api_key="test-openai-key",
            google_calendar_access_token=None,
        ),
    )
    return store


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


def _create_transcription(client: TestClient) -> dict:
    response = client.post(
        "/transcriptions",
        content=b"fake wav bytes",
        headers={**_headers(), "Content-Type": "audio/wav"},
    )
    assert response.status_code == 200
    return response.json()


def test_write_endpoints_require_api_key_but_read_endpoints_remain_public(monkeypatch):
    _install_test_app(monkeypatch)

    with TestClient(main.app) as client:
        health = client.get("/health")
        blocked = client.post("/scheduler/next-day-check")
        allowed = client.post("/scheduler/next-day-check", headers=_headers())

    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert blocked.status_code == 401
    assert blocked.json()["detail"] == "A valid X-API-Key is required for this operation."
    assert allowed.status_code == 200
    assert allowed.json()["target_date"]


def test_transcript_first_api_flow_is_idempotent_and_preserves_user_facing_pii(monkeypatch):
    store = _install_test_app(monkeypatch)

    async def fake_transcribe_audio(audio, content_type, settings):
        assert audio == b"fake wav bytes"
        assert content_type == "audio/wav"
        return TranscriptionResult(
            text="John needs Panadol before lunch every day. John has a doctor appointment on June 1, 2026 at 10am.",
            provider="openai",
            model="gpt-4o-transcribe",
            language="en",
            metadata={"test": True},
        )

    monkeypatch.setattr(transcript_pipeline, "transcribe_audio", fake_transcribe_audio)

    with TestClient(main.app) as client:
        created = _create_transcription(client)
        session_id = created["transcription_session"]["id"]
        transcript_id = created["transcript"]["id"]

        first = client.post(f"/transcriptions/{session_id}/process", headers=_headers())
        second = client.post(f"/transcriptions/{session_id}/process", headers=_headers())
        direct = client.post(f"/transcripts/{transcript_id}/process", headers=_headers())
        tasks = client.get("/tasks/daily")

    assert first.status_code == 200
    assert second.status_code == 200
    assert direct.status_code == 200
    first_body = first.json()
    assert first_body == second.json() == direct.json()

    daily = first_body["daily_tasks"][0]["payload"]
    appointment = first_body["appointment_candidates"][0]["payload"]
    assert daily["description"] == "John needs Panadol before lunch every day"
    assert daily["original_instruction_redacted"] == "PERSON_1 needs Panadol before lunch every day"
    assert daily["scheduling_semantics"] == "fixed_clinical"
    assert appointment["date"] == "2026-06-01"
    assert appointment["time"] == "10:00"
    assert appointment["requires_calendar_write"] is True
    assert tasks.json()[0]["id"] == first_body["daily_tasks"][0]["id"]
    assert len(asyncio.run(store.list_nodes("mdm-tan", ["daily_task"]))) == 1
    assert len(asyncio.run(store.list_nodes("mdm-tan", ["appointment_candidate"]))) == 1


def test_daily_task_edit_route_validates_overrides_and_records_feedback(monkeypatch):
    store = _install_test_app(monkeypatch)

    async def seed_task():
        return await store.create_node(
            "daily_task",
            {
                "patient_id": "mdm-tan",
                "title": "Give Panadol before lunch",
                "description": "John needs Panadol before lunch every day",
                "original_instruction_redacted": "PERSON_1 needs Panadol before lunch every day",
                "scheduling_semantics": "fixed_clinical",
                "user_override": None,
            },
            "agent",
            status="pending_review",
        )

    task = asyncio.run(seed_task())

    with TestClient(main.app) as client:
        invalid = client.patch(
            f"/tasks/daily/{task.id}",
            headers=_headers(),
            json={"scheduling_semantics": "whenever"},
        )
        valid = client.patch(
            f"/tasks/daily/{task.id}",
            headers=_headers(),
            json={
                "scheduling_semantics": "movable_routine",
                "scheduled_time": "11:00",
                "meal_times": {"breakfast": "08:00", "lunch": "12:30"},
                "reason": "Caregiver manually adjusted this timing.",
            },
        )

    assert invalid.status_code == 422
    assert valid.status_code == 200
    payload = valid.json()["daily_task"]["payload"]
    assert payload["description"] == "John needs Panadol before lunch every day"
    assert payload["original_instruction_redacted"] == "PERSON_1 needs Panadol before lunch every day"
    assert payload["user_override"]["scheduling_semantics"] == "movable_routine"
    assert payload["user_override"]["scheduled_time"] == "11:00"
    feedback = asyncio.run(store.list_nodes("mdm-tan", ["caregiver_feedback"]))
    assert len(feedback) == 1
    assert feedback[0].payload["target_node_id"] == str(task.id)


def test_calendar_approval_route_audits_missing_google_token_without_marking_written(monkeypatch):
    store = _install_test_app(monkeypatch)

    async def seed_appointment():
        return await store.create_node(
            "appointment_candidate",
            {
                "patient_id": "mdm-tan",
                "title": "Doctor appointment",
                "kind": "doctor",
                "date": "2026-06-01",
                "time": "10:00",
                "requires_calendar_write": True,
                "calendar_write_status": "pending_user_approval",
            },
            "agent",
            status="pending_review",
        )

    appointment = asyncio.run(seed_appointment())

    with TestClient(main.app) as client:
        response = client.post(f"/appointments/{appointment.id}/approve-calendar-write", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["user_decision"]["payload"]["decision"] == "approved_calendar_write"
    assert body["calendar_write_request"]["payload"]["status"] == "write_failed"
    assert body["calendar_write_request"]["status"] == "clarification_required"
    assert body["calendar_event"] is None
    updated = asyncio.run(store.get_node(appointment.id))
    assert updated.payload["calendar_write_status"] == "pending_user_approval"


def test_notifications_surface_daily_tasks_calendar_failures_and_dismissal_feedback(monkeypatch):
    store = _install_test_app(monkeypatch)

    async def seed_nodes():
        task = await store.create_node(
            "daily_task",
            {
                "patient_id": "mdm-tan",
                "title": "Give Panadol before lunch",
                "description": "John needs Panadol before lunch every day",
                "scheduling_semantics": "fixed_clinical",
            },
            "agent",
            status="pending_review",
        )
        request = await store.create_node(
            "calendar_write_request",
            {
                "patient_id": "mdm-tan",
                "appointment_candidate_id": "appointment-id",
                "provider": "google_calendar",
                "operation": "insert_event",
                "status": "write_failed",
                "error": "Google Calendar write requires GOOGLE_CALENDAR_ACCESS_TOKEN.",
            },
            "system",
            status="clarification_required",
        )
        return task, request

    task, request = asyncio.run(seed_nodes())

    with TestClient(main.app) as client:
        before = client.get("/notifications")
        dismiss = client.patch(
            f"/nodes/{task.id}/status",
            headers=_headers(),
            json={"status": "dismissed", "feedback_note": "Not needed today."},
        )
        after = client.get("/notifications")

    assert before.status_code == 200
    kinds = {item["kind"] for item in before.json()}
    assert "daily task review" in kinds
    assert any(item["source_node_id"] == str(request.id) for item in before.json())
    assert dismiss.status_code == 200
    dismissed = [item for item in after.json() if item["source_node_id"] == str(task.id)]
    assert dismissed
    assert dismissed[0]["kind"] == "dismissed"
