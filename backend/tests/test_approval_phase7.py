import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.approvals import approve_appointment_calendar_write, update_daily_task
from app.config import Settings
from app.scheduler import CalendarEvent, SINGAPORE_TZ
from app.store import MemoryGraphStore


class FakeCalendarWriter:
    def __init__(self, response: dict | None = None, error: Exception | None = None) -> None:
        self.response = response or {"id": "google-event-1", "htmlLink": "https://calendar.google.com/event?eid=1"}
        self.error = error
        self.payloads: list[dict] = []

    async def insert_event(self, payload: dict) -> dict:
        self.payloads.append(payload)
        if self.error:
            raise self.error
        return self.response


class BlockingCalendarWriter(FakeCalendarWriter):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def insert_event(self, payload: dict) -> dict:
        self.payloads.append(payload)
        self.started.set()
        await self.release.wait()
        return self.response


class FakeCalendarProvider:
    def __init__(self, events: list[CalendarEvent]) -> None:
        self.events = events
        self.calls: list[tuple] = []

    async def list_events(self, start_at, end_at) -> list[CalendarEvent]:
        self.calls.append((start_at, end_at))
        return self.events


async def _daily_task(store: MemoryGraphStore):
    return await store.create_node(
        "daily_task",
        {
            "patient_id": "patient-1",
            "title": "Give Panadol before lunch",
            "description": "John needs Panadol before lunch daily",
            "original_instruction_redacted": "PERSON_1 needs Panadol before lunch daily",
            "scheduling_semantics": "fixed_clinical",
            "timing_relation": "before lunch",
            "user_override": None,
        },
        "agent",
        status="pending_review",
    )


async def _appointment(store: MemoryGraphStore, patient_id: str = "patient-1"):
    return await store.create_node(
        "appointment_candidate",
        {
            "patient_id": patient_id,
            "title": "Physio appointment",
            "kind": "physio",
            "date": "2026-06-01",
            "time": "10:00",
            "location": "Clinic A",
            "requires_calendar_write": True,
            "calendar_write_status": "pending_user_approval",
        },
        "agent",
        status="pending_review",
    )


@pytest.mark.asyncio
async def test_daily_task_edit_preserves_original_instruction_and_records_feedback():
    store = MemoryGraphStore()
    task = await _daily_task(store)

    result = await update_daily_task(
        store,
        "patient-1",
        task,
        {"scheduling_semantics": "movable_routine", "scheduled_time": "11:00", "reason": "Caregiver prefers this timing."},
    )

    updated = result["daily_task"]["payload"]
    assert updated["original_instruction_redacted"] == "PERSON_1 needs Panadol before lunch daily"
    assert updated["description"] == "John needs Panadol before lunch daily"
    assert updated["user_override"]["scheduling_semantics"] == "movable_routine"
    assert updated["user_override"]["scheduled_time"] == "11:00"
    assert result["feedback"]["type"] == "caregiver_feedback"
    assert any(edge.type == "feedback_on" for edge in await store.list_edges())


@pytest.mark.asyncio
async def test_daily_task_edit_rejects_invalid_schedule_overrides():
    store = MemoryGraphStore()
    task = await _daily_task(store)

    with pytest.raises(ValueError, match="scheduling_semantics"):
        await update_daily_task(store, "patient-1", task, {"scheduling_semantics": "move_whenever"})

    with pytest.raises(ValueError, match="scheduled_time"):
        await update_daily_task(store, "patient-1", task, {"scheduled_time": "25:00"})

    with pytest.raises(ValueError, match="Unsupported meal time"):
        await update_daily_task(store, "patient-1", task, {"meal_times": {"supper": "22:00"}})


@pytest.mark.asyncio
async def test_appointment_calendar_write_requires_explicit_approval_and_writes_event():
    store = MemoryGraphStore()
    appointment = await _appointment(store)
    writer = FakeCalendarWriter()

    assert await store.list_nodes("patient-1", ["calendar_write_request"]) == []
    result = await approve_appointment_calendar_write(store, "patient-1", appointment, Settings(), writer)

    assert writer.payloads == [
        {
            "summary": "Physio appointment",
            "start": {"dateTime": "2026-06-01T10:00:00+08:00", "timeZone": "Asia/Singapore"},
            "end": {"dateTime": "2026-06-01T11:00:00+08:00", "timeZone": "Asia/Singapore"},
            "location": "Clinic A",
        }
    ]
    assert result["user_decision"]["payload"]["decision"] == "approved_calendar_write"
    assert result["calendar_write_request"]["payload"]["status"] == "written"
    assert result["appointment_candidate"]["payload"]["calendar_write_status"] == "written"
    assert {"requires_approval", "approved_by_user", "written_to_calendar"} <= {edge.type for edge in await store.list_edges()}


@pytest.mark.asyncio
async def test_appointment_calendar_write_rejects_duplicate_insert():
    store = MemoryGraphStore()
    appointment = await store.create_node(
        "appointment_candidate",
        {
            "patient_id": "patient-1",
            "date": "2026-06-01",
            "requires_calendar_write": True,
            "calendar_write_status": "written",
            "google_event_id": "existing-google-event",
        },
        "agent",
    )

    with pytest.raises(ValueError, match="already been written"):
        await approve_appointment_calendar_write(store, "patient-1", appointment, Settings(), FakeCalendarWriter())


@pytest.mark.asyncio
async def test_concurrent_appointment_calendar_write_uses_lock_to_prevent_duplicate_insert():
    store = MemoryGraphStore()
    appointment = await _appointment(store)
    writer = BlockingCalendarWriter()

    first = asyncio.create_task(approve_appointment_calendar_write(store, "patient-1", appointment, Settings(), writer))
    await writer.started.wait()
    with pytest.raises(ValueError, match="already in progress"):
        await approve_appointment_calendar_write(store, "patient-1", appointment, Settings(), writer)
    writer.release.set()
    result = await first

    assert result["calendar_write_request"]["payload"]["status"] == "written"
    assert len(writer.payloads) == 1
    assert len(await store.list_nodes("patient-1", ["calendar_write_request"])) == 1


@pytest.mark.asyncio
async def test_appointment_calendar_write_blocks_insert_when_google_conflict_exists():
    store = MemoryGraphStore()
    appointment = await _appointment(store)
    writer = FakeCalendarWriter()
    provider = FakeCalendarProvider(
        [
            CalendarEvent(
                id="busy-1",
                title="Existing appointment",
                start_at=datetime(2026, 6, 1, 10, 30, tzinfo=SINGAPORE_TZ),
                end_at=datetime(2026, 6, 1, 11, 30, tzinfo=SINGAPORE_TZ),
            )
        ]
    )

    result = await approve_appointment_calendar_write(store, "patient-1", appointment, Settings(), writer, provider)

    assert writer.payloads == []
    assert provider.calls == [(datetime(2026, 6, 1, 10, 0, tzinfo=SINGAPORE_TZ), datetime(2026, 6, 1, 11, 0, tzinfo=SINGAPORE_TZ))]
    assert result["calendar_event"] is None
    assert result["calendar_write_request"]["payload"]["status"] == "blocked_conflict"
    assert result["schedule_conflict"]["payload"]["calendar_event_id"] == "busy-1"
    updated = await store.get_node(appointment.id)
    assert updated.payload["calendar_write_status"] == "pending_user_approval"
    assert await store.list_nodes("patient-1", ["schedule_conflict"])


@pytest.mark.asyncio
async def test_appointment_calendar_write_blocks_insert_when_pending_appointment_overlaps():
    store = MemoryGraphStore()
    appointment = await _appointment(store)
    existing = await store.create_node(
        "appointment_candidate",
        {
            "patient_id": "patient-1",
            "title": "Existing physio",
            "date": "2026-06-01",
            "time": "10:30",
            "requires_calendar_write": True,
            "calendar_write_status": "pending_user_approval",
        },
        "agent",
    )
    writer = FakeCalendarWriter()
    provider = FakeCalendarProvider([])

    result = await approve_appointment_calendar_write(store, "patient-1", appointment, Settings(), writer, provider)

    assert writer.payloads == []
    assert provider.calls == []
    assert result["calendar_write_request"]["payload"]["status"] == "blocked_conflict"
    assert result["schedule_conflict"]["payload"]["conflicting_appointment_candidate_id"] == str(existing.id)


@pytest.mark.asyncio
async def test_calendar_write_failure_is_audited_without_marking_appointment_written():
    store = MemoryGraphStore()
    appointment = await _appointment(store)

    result = await approve_appointment_calendar_write(store, "patient-1", appointment, Settings(), FakeCalendarWriter(error=RuntimeError("no token")))

    assert result["calendar_event"] is None
    assert result["calendar_write_request"]["payload"]["status"] == "write_failed"
    updated = await store.get_node(appointment.id)
    assert updated.payload["calendar_write_status"] == "pending_user_approval"


@pytest.mark.asyncio
async def test_appointment_without_calendar_write_need_is_rejected():
    store = MemoryGraphStore()
    appointment = await store.create_node(
        "appointment_candidate",
        {"patient_id": "patient-1", "date": "2026-06-01", "requires_calendar_write": False},
        "agent",
    )

    with pytest.raises(ValueError, match="does not require"):
        await approve_appointment_calendar_write(store, "patient-1", appointment, Settings(), FakeCalendarWriter())


def test_phase7_routes_patch_daily_task_and_approve_appointment(monkeypatch):
    store = MemoryGraphStore()

    async def fake_init():
        return None

    store.init = fake_init
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "settings", Settings())

    async def seed():
        task = await store.create_node(
            "daily_task",
            {
                "patient_id": "mdm-tan",
                "title": "Give Panadol",
                "description": "Original instruction",
                "original_instruction_redacted": "Original instruction",
                "scheduling_semantics": "fixed_clinical",
            },
            "agent",
        )
        appointment = await store.create_node(
            "appointment_candidate",
            {
                "patient_id": "mdm-tan",
                "title": "Doctor appointment",
                "date": "2026-06-01",
                "time": "09:00",
                "requires_calendar_write": True,
            },
            "agent",
        )
        return task.id, appointment.id

    async def fake_approve(store_arg, patient_id, appointment, settings):
        writer = FakeCalendarWriter()
        return await approve_appointment_calendar_write(store_arg, patient_id, appointment, settings, writer)

    task_id, appointment_id = asyncio.run(seed())
    monkeypatch.setattr(main, "approve_appointment_calendar_write", fake_approve)

    with TestClient(main.app) as client:
        task_response = client.patch(f"/tasks/daily/{task_id}", json={"scheduling_semantics": "movable_routine", "reason": "User edit"})
        appointment_response = client.post(f"/appointments/{appointment_id}/approve-calendar-write")

    assert task_response.status_code == 200
    assert task_response.json()["daily_task"]["payload"]["user_override"]["scheduling_semantics"] == "movable_routine"
    assert appointment_response.status_code == 200
    assert appointment_response.json()["calendar_write_request"]["payload"]["status"] == "written"
