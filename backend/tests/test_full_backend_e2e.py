from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.transcript_pipeline as transcript_pipeline
from app.approvals import approve_appointment_calendar_write
from app.config import Settings
from app.scheduler import CalendarEvent, SINGAPORE_TZ, run_next_day_schedule_check
from app.store import MemoryGraphStore
from app.transcription import TranscriptionResult


API_KEY = "full-e2e-key"


class FakeCalendarWriter:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def insert_event(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {"id": "google-e2e-event", "htmlLink": "https://calendar.google.com/event?eid=e2e"}


class FakeCalendarProvider:
    async def list_events(self, start_at: datetime, end_at: datetime) -> list[CalendarEvent]:
        return [
            CalendarEvent(
                id="busy-lunch",
                title="Existing lunch appointment",
                start_at=start_at.replace(hour=11, minute=15),
                end_at=start_at.replace(hour=12, minute=15),
            )
        ]


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


def test_full_audio_upload_to_tasks_calendar_scheduler_research_and_notifications_backend_flow(monkeypatch):
    store = MemoryGraphStore()
    writer = FakeCalendarWriter()

    async def fake_init():
        return None

    async def fake_transcribe_audio(audio, content_type, settings):
        assert audio == b"fake browser mp3 bytes"
        assert content_type == "audio/mpeg"
        return TranscriptionResult(
            text=(
                "Mom needs Panadol before lunch every day. "
                "Mom has a doctor appointment on June 1, 2026 at 10am. "
                "Doctor said Mom may need wheelchair support, find Singapore wheelchair grants."
            ),
            provider="openai",
            model="gpt-4o-transcribe",
            language="en",
            requested_language="en",
            detected_language="en",
            language_label="English",
        )

    async def fake_approve(store_arg, patient_id, appointment, settings):
        return await approve_appointment_calendar_write(store_arg, patient_id, appointment, settings, writer)

    async def fake_scheduler(store_arg, patient_id, settings):
        return await run_next_day_schedule_check(
            store_arg,
            patient_id,
            settings,
            calendar_provider=FakeCalendarProvider(),
            now=datetime(2026, 5, 9, 22, 0, tzinfo=SINGAPORE_TZ),
        )

    store.init = fake_init
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(
        main,
        "settings",
        Settings(
            api_write_key=API_KEY,
            openai_api_key="test-openai-key",
            tinyfish_api_key=None,
            exa_api_key=None,
            sealion_api_key=None,
            google_calendar_access_token="test-google-token",
        ),
    )
    monkeypatch.setattr(transcript_pipeline, "transcribe_audio", fake_transcribe_audio)
    monkeypatch.setattr(main, "approve_appointment_calendar_write", fake_approve)
    monkeypatch.setattr(main, "run_next_day_schedule_check", fake_scheduler)

    with TestClient(main.app) as client:
        identity_before = client.get("/patient/identity", headers=_headers())
        manual_alias = client.post(
            "/patient/identity/aliases",
            headers=_headers(),
            json={"alias": "Ah Ma", "source": "caregiver_profile", "confidence": 0.9},
        )
        created = client.post(
            "/transcriptions?language=en",
            content=b"fake browser mp3 bytes",
            headers={**_headers(), "Content-Type": "audio/mpeg"},
        )
        session_id = created.json()["transcription_session"]["id"]
        processed = client.post(f"/transcriptions/{session_id}/process", headers=_headers())
        body = processed.json()
        daily_task = body["daily_tasks"][0]
        appointment = body["appointment_candidates"][0]
        research_task = body["ad_hoc_research_tasks"][0]

        daily_list = client.get("/tasks/daily", headers=_headers())
        calendar_write = client.post(f"/appointments/{appointment['id']}/approve-calendar-write", headers=_headers())
        scheduler = client.post("/scheduler/next-day-check", headers=_headers())
        research = client.post(f"/research/tasks/{research_task['id']}/run", headers=_headers())
        recommendations = client.get("/recommendations", headers=_headers())
        notifications = client.get("/notifications", headers=_headers())

    assert identity_before.status_code == 200
    assert identity_before.json()["payload"]["canonical_name"] == "Mdm Tan Siew Lan"
    assert manual_alias.status_code == 200
    assert any(item["alias"] == "Ah Ma" for item in manual_alias.json()["payload"]["aliases"])
    assert created.status_code == 200
    assert created.json()["transcription_session"]["payload"]["status"] == "transcription_completed"
    assert processed.status_code == 200
    assert daily_task["payload"]["title"] == "Give Panadol before lunch"
    assert daily_task["payload"]["description"] == "Mom needs Panadol before lunch every day"
    assert appointment["payload"]["requires_calendar_write"] is True
    assert research_task["payload"]["requires_guardrail_review"] is True

    identity_nodes = [node for node in store.nodes.values() if node.type == "patient_identity"]
    assert identity_nodes
    assert any(item["alias"] == "mom" for item in identity_nodes[0].payload["aliases"])

    assert daily_list.status_code == 200
    assert daily_list.json()[0]["id"] == daily_task["id"]
    assert calendar_write.status_code == 200
    assert calendar_write.json()["calendar_write_request"]["payload"]["status"] == "written"
    assert writer.payloads[0]["summary"] == "Doctor appointment"

    assert scheduler.status_code == 200
    assert len(scheduler.json()["notification_candidates"]) == 1
    assert research.status_code == 200
    assert research.json()["synthesized_recommendation"]["payload"]["verified_facts"]
    assert recommendations.status_code == 200
    assert recommendations.json()[0]["id"] == research.json()["synthesized_recommendation"]["id"]

    notification_kinds = {item["kind"] for item in notifications.json()}
    assert {"daily task review", "next-day conflict warning", "research result ready"} <= notification_kinds
