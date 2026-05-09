from datetime import datetime, timedelta

import httpx
import pytest
from zoneinfo import ZoneInfo

from app.config import Settings
from app.models import GraphSubset
from app.notifications import build_notifications
from app.scheduler import CalendarEvent, GoogleCalendarProvider, SINGAPORE_TZ, run_next_day_schedule_check
from app.store import MemoryGraphStore


class FakeCalendarProvider:
    def __init__(self, events: list[CalendarEvent]) -> None:
        self.events = events
        self.calls: list[tuple[datetime, datetime]] = []

    async def list_events(self, start_at: datetime, end_at: datetime) -> list[CalendarEvent]:
        self.calls.append((start_at, end_at))
        return self.events


async def _daily_task(store: MemoryGraphStore, payload: dict):
    return await store.create_node(
        "daily_task",
        {"patient_id": "patient-1", "title": "Care task", "scheduling_semantics": "fixed_clinical", **payload},
        "agent",
        status="pending_review",
    )


@pytest.mark.asyncio
async def test_next_day_scheduler_reads_only_tomorrow_and_flags_fixed_clinical_calendar_conflict():
    store = MemoryGraphStore()
    task = await _daily_task(
        store,
        {
            "title": "Give Panadol before lunch",
            "action_type": "medication",
            "timing_relation": "before lunch",
            "medication": {"name": "Panadol", "frequency": "daily", "timing_relation": "before lunch"},
        },
    )
    tomorrow = datetime(2026, 5, 10, tzinfo=SINGAPORE_TZ)
    provider = FakeCalendarProvider(
        [
            CalendarEvent(
                id="calendar-1",
                title="Lunch appointment",
                start_at=tomorrow.replace(hour=11, minute=15),
                end_at=tomorrow.replace(hour=12, minute=15),
            )
        ]
    )

    result = await run_next_day_schedule_check(
        store,
        "patient-1",
        Settings(google_calendar_access_token=None),
        calendar_provider=provider,
        now=datetime(2026, 5, 9, 22, 0, tzinfo=SINGAPORE_TZ),
    )

    assert provider.calls == [(tomorrow, tomorrow + timedelta(days=1))]
    assert result["calendar_event_count"] == 1
    assert result["daily_task_count"] == 1
    assert len(result["schedule_conflicts"]) == 1
    conflict = result["schedule_conflicts"][0]["payload"]
    assert conflict["classification"] == "fixed"
    assert conflict["calendar_event_id"] == "calendar-1"
    assert "should not be silently moved" in conflict["reason"]

    notifications = await store.list_nodes("patient-1", ["notification_candidate"])
    assert len(notifications) == 1
    assert notifications[0].payload["send_at"] == "2026-05-09T22:00:00+08:00"
    assert notifications[0].payload["source_daily_task_id"] == str(task.id)


@pytest.mark.asyncio
async def test_scheduler_flags_three_times_daily_medication_spacing_as_unsafe():
    store = MemoryGraphStore()
    await _daily_task(
        store,
        {
            "title": "Give medicine before food",
            "action_type": "medication",
            "timing_relation": "before food",
            "meal_times": {"breakfast": "10:00", "lunch": "11:30", "dinner": "18:00"},
            "medication": {"name": "Panadol", "frequency": "three_times_daily", "timing_relation": "before food"},
        },
    )

    result = await run_next_day_schedule_check(
        store,
        "patient-1",
        Settings(),
        calendar_provider=FakeCalendarProvider([]),
        now=datetime(2026, 5, 9, 22, 0, tzinfo=SINGAPORE_TZ),
    )

    assert len(result["schedule_conflicts"]) == 1
    conflict = result["schedule_conflicts"][0]["payload"]
    assert conflict["classification"] == "unsafe_unclear"
    assert "too close together" in conflict["reason"]
    assert conflict["task_time"]["minimum_gap_minutes"] == 90
    assert len(result["notification_candidates"]) == 1


@pytest.mark.asyncio
async def test_scheduler_suggests_alternative_for_movable_routine_conflict():
    store = MemoryGraphStore()
    await _daily_task(
        store,
        {
            "title": "Morning walk",
            "action_type": "task",
            "timing_relation": "morning",
            "scheduling_semantics": "movable_routine",
            "estimated_duration_minutes": 30,
        },
    )
    tomorrow = datetime(2026, 5, 10, tzinfo=SINGAPORE_TZ)
    provider = FakeCalendarProvider(
        [CalendarEvent(id="calendar-2", title="Work call", start_at=tomorrow.replace(hour=9), end_at=tomorrow.replace(hour=9, minute=30))]
    )

    result = await run_next_day_schedule_check(
        store,
        "patient-1",
        Settings(),
        calendar_provider=provider,
        now=datetime(2026, 5, 9, 22, 0, tzinfo=SINGAPORE_TZ),
    )

    conflict = result["schedule_conflicts"][0]["payload"]
    assert conflict["classification"] == "movable"
    assert conflict["suggested_time"]


@pytest.mark.asyncio
async def test_google_calendar_provider_uses_next_day_event_list_parameters(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_get(self, url, params=None, headers=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "event-1",
                        "summary": "Busy",
                        "start": {"dateTime": "2026-05-10T03:15:00Z"},
                        "end": {"dateTime": "2026-05-10T04:15:00Z"},
                    }
                ]
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    provider = GoogleCalendarProvider(Settings(google_calendar_access_token="token", google_calendar_id="primary"))
    start_at = datetime(2026, 5, 10, tzinfo=SINGAPORE_TZ)
    end_at = start_at + timedelta(days=1)

    events = await provider.list_events(start_at, end_at)

    assert captured["url"].endswith("/calendars/primary/events")
    assert captured["params"] == {
        "timeMin": "2026-05-09T16:00:00Z",
        "timeMax": "2026-05-10T16:00:00Z",
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    assert captured["headers"] == {"Authorization": "Bearer token"}
    assert events[0].start_at.hour == 11
    assert events[0].start_at.tzinfo == SINGAPORE_TZ


@pytest.mark.asyncio
async def test_persisted_notification_candidates_are_returned_by_notification_builder():
    store = MemoryGraphStore()
    await _daily_task(store, {"title": "Give Panadol before lunch", "timing_relation": "before lunch"})
    tomorrow = datetime(2026, 5, 10, tzinfo=SINGAPORE_TZ)
    await run_next_day_schedule_check(
        store,
        "patient-1",
        Settings(),
        calendar_provider=FakeCalendarProvider(
            [CalendarEvent(id="calendar-1", title="Lunch appointment", start_at=tomorrow.replace(hour=11, minute=15), end_at=tomorrow.replace(hour=12))]
        ),
        now=datetime(2026, 5, 9, 22, 0, tzinfo=SINGAPORE_TZ),
    )

    graph = GraphSubset(nodes=await store.list_nodes("patient-1"), edges=await store.list_edges())
    notifications = build_notifications(graph, await store.list_reasoning_logs())

    assert any(item["id"].startswith("notification:") and item["kind"] == "next-day conflict warning" for item in notifications)
