from __future__ import annotations

from dataclasses import dataclass
import asyncio
import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx

from .config import PATIENT_TZ, Settings
from .models import Node
from .security import vendor_allowed
from .store import GraphStore


SINGAPORE_TZ = PATIENT_TZ  # backwards-compat alias
SCHEDULER_LOG = logging.getLogger("app.scheduler.loop")
DEFAULT_MEAL_TIMES = {"breakfast": "08:00", "lunch": "12:00", "dinner": "18:00"}
MIN_THREE_TIMES_DAILY_SPACING_MINUTES = 4 * 60


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    title: str
    start_at: datetime
    end_at: datetime
    busy: bool = True


class CalendarProvider(Protocol):
    async def list_events(self, start_at: datetime, end_at: datetime) -> list[CalendarEvent]: ...


class GoogleCalendarProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def list_events(self, start_at: datetime, end_at: datetime) -> list[CalendarEvent]:
        if not vendor_allowed(self.settings, "google_calendar", "calendar_read"):
            return []
        if not self.settings.google_calendar_access_token:
            return []
        url = f"{self.settings.google_calendar_api_base_url.rstrip('/')}/calendars/{self.settings.google_calendar_id}/events"
        params = {
            "timeMin": start_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "timeMax": end_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        headers = {"Authorization": f"Bearer {self.settings.google_calendar_access_token}"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
        return [_calendar_event_from_google(item, start_at.tzinfo or SINGAPORE_TZ) for item in response.json().get("items", [])]


async def run_next_day_schedule_check(
    store: GraphStore,
    patient_id: str,
    settings: Settings,
    calendar_provider: CalendarProvider | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    run_at = now.astimezone(SINGAPORE_TZ) if now else datetime.now(SINGAPORE_TZ)
    target_date = (run_at + timedelta(days=1)).date()
    window_start = datetime.combine(target_date, time.min, tzinfo=SINGAPORE_TZ)
    window_end = window_start + timedelta(days=1)
    provider = calendar_provider or GoogleCalendarProvider(settings)

    log = await store.create_reasoning_log("scheduler_next_day_check")
    events = await provider.list_events(window_start, window_end)
    tasks = [node for node in await store.list_nodes(patient_id, ["daily_task"]) if node.status != "dismissed"]

    await store.append_reasoning_step(
        log.id,
        {
            "kind": "calendar_read",
            "policy": "next_day_only",
            "timezone": "Asia/Singapore",
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "event_count": len(events),
            "task_count": len(tasks),
        },
    )

    conflicts = []
    notifications = []
    for task in tasks:
        task_conflicts = _detect_task_conflicts(task, events, target_date)
        for conflict_payload in task_conflicts:
            conflict = await store.create_node(
                "schedule_conflict",
                {"patient_id": patient_id, "daily_task_id": str(task.id), **conflict_payload},
                "system",
                reasoning_log_id=log.id,
                status="clarification_required" if conflict_payload["classification"] in {"fixed", "unsafe_unclear"} else "pending_review",
            )
            await store.create_edge(conflict.id, task.id, "conflicts_with")
            conflicts.append(conflict)
            notification = await _create_conflict_notification(store, patient_id, conflict, task, window_start, log.id)
            notifications.append(notification)

    await store.append_reasoning_step(
        log.id,
        {
            "kind": "conflict_detection_result",
            "conflict_count": len(conflicts),
            "notification_candidate_count": len(notifications),
            "fixed_or_unsafe_count": sum(1 for node in conflicts if node.payload.get("classification") in {"fixed", "unsafe_unclear"}),
        },
    )
    await store.finish_reasoning_log(log.id, f"Next-day schedule check created {len(conflicts)} conflict(s) and {len(notifications)} notification candidate(s).")

    return {
        "target_date": target_date.isoformat(),
        "timezone": "Asia/Singapore",
        "calendar_event_count": len(events),
        "daily_task_count": len(tasks),
        "schedule_conflicts": [node.model_dump(mode="json") for node in conflicts],
        "notification_candidates": [node.model_dump(mode="json") for node in notifications],
        "reasoning_log_id": str(log.id),
    }


def _detect_task_conflicts(task: Node, events: list[CalendarEvent], target_date: date) -> list[dict[str, Any]]:
    conflicts = []
    spacing = _medication_spacing_conflict(task, target_date)
    if spacing:
        conflicts.append(spacing)

    candidate = _candidate_time_for_task(task, target_date)
    if not candidate:
        conflicts.append(
            {
                "category": "clarification_required",
                "classification": "unsafe_unclear",
                "reason": "Task timing is under-specified and needs user review before scheduling.",
                "task_time": None,
                "calendar_event_id": None,
                "calendar_event_title": None,
            }
        )
        return conflicts

    start_at, end_at = candidate
    overlap = next((event for event in events if event.busy and _overlaps(start_at, end_at, event.start_at, event.end_at)), None)
    if overlap:
        semantics = _effective_semantics(task)
        fixed = semantics in {"fixed_clinical", "fixed_deadline"}
        conflicts.append(
            {
                "category": "next_day_conflict_warning",
                "classification": "fixed" if fixed else "movable",
                "reason": _conflict_reason(task, overlap, fixed),
                "task_time": {"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
                "calendar_event_id": overlap.id,
                "calendar_event_title": overlap.title,
                "suggested_time": None if fixed else _suggest_alternative_time(start_at, end_at, events, target_date),
            }
        )
    return conflicts


async def _create_conflict_notification(
    store: GraphStore,
    patient_id: str,
    conflict: Node,
    task: Node,
    window_start: datetime,
    reasoning_log_id,
) -> Node:
    send_at = datetime.combine(window_start.date() - timedelta(days=1), time(22, 0), tzinfo=SINGAPORE_TZ)
    notification = await store.create_node(
        "notification_candidate",
        {
            "patient_id": patient_id,
            "category": "next-day conflict warning",
            "title": "Tomorrow's care schedule needs review",
            "body": conflict.payload.get("reason"),
            "send_at": send_at.isoformat(),
            "timezone": "Asia/Singapore",
            "source_conflict_id": str(conflict.id),
            "source_daily_task_id": str(task.id),
            "delivery_status": "pending",
        },
        "system",
        reasoning_log_id=reasoning_log_id,
        status="pending_review",
    )
    await store.create_edge(notification.id, conflict.id, "notifies_about")
    return notification


def _candidate_time_for_task(task: Node, target_date: date) -> tuple[datetime, datetime] | None:
    payload = task.payload
    explicit = payload.get("scheduled_time") or payload.get("time")
    timing = str(payload.get("timing_relation") or "").lower()
    meal_times = _meal_times(payload)
    if explicit:
        start_time = _parse_time(str(explicit))
    elif "before lunch" in timing:
        start_time = _minus_minutes(meal_times["lunch"], 30)
    elif "before breakfast" in timing:
        start_time = _minus_minutes(meal_times["breakfast"], 30)
    elif "before dinner" in timing or "before food" in timing or "before meal" in timing:
        start_time = _minus_minutes(meal_times["dinner"], 30)
    elif "morning" in timing:
        start_time = time(9, 0)
    else:
        return None
    duration = int(payload.get("estimated_duration_minutes") or payload.get("estimated_effort_minutes") or 15)
    start_at = datetime.combine(target_date, start_time, tzinfo=_task_tz(payload))
    return start_at, start_at + timedelta(minutes=max(5, min(duration, 240)))


def _task_tz(payload: dict[str, Any]):
    override = payload.get("user_override") if isinstance(payload.get("user_override"), dict) else None
    name = (override.get("timezone") if override else None) or payload.get("timezone")
    if name:
        try:
            return ZoneInfo(str(name))
        except Exception:
            pass
    return SINGAPORE_TZ


def _medication_spacing_conflict(task: Node, target_date: date) -> dict[str, Any] | None:
    medication = task.payload.get("medication") or {}
    frequency = str(medication.get("frequency") or task.payload.get("recurrence") or "").lower()
    timing = str(task.payload.get("timing_relation") or medication.get("timing_relation") or "").lower()
    if frequency not in {"three_times_daily", "3_times_daily"} and "three_times" not in frequency:
        return None
    if "before" not in timing:
        return None
    meal_times = _meal_times(task.payload)
    dose_times = [_minus_minutes(meal_times[name], 30) for name in ("breakfast", "lunch", "dinner")]
    dose_datetimes = [datetime.combine(target_date, item, tzinfo=_task_tz(task.payload)) for item in dose_times]
    gaps = [(dose_datetimes[index + 1] - dose_datetimes[index]).total_seconds() / 60 for index in range(len(dose_datetimes) - 1)]
    if min(gaps) >= MIN_THREE_TIMES_DAILY_SPACING_MINUTES:
        return None
    return {
        "category": "clarification_required",
        "classification": "unsafe_unclear",
        "reason": "Three-times-daily medication doses are too close together based on known meal times; user or clinician review is required.",
        "task_time": {"candidate_dose_times": [item.isoformat() for item in dose_datetimes], "minimum_gap_minutes": min(gaps)},
        "calendar_event_id": None,
        "calendar_event_title": None,
    }


def _meal_times(payload: dict[str, Any]) -> dict[str, time]:
    configured = payload.get("meal_times") if isinstance(payload.get("meal_times"), dict) else {}
    return {name: _parse_time(str(configured.get(name) or DEFAULT_MEAL_TIMES[name])) for name in DEFAULT_MEAL_TIMES}


def _effective_semantics(task: Node) -> str:
    override = task.payload.get("user_override")
    if isinstance(override, dict) and override.get("scheduling_semantics"):
        return str(override["scheduling_semantics"])
    return str(task.payload.get("scheduling_semantics") or "unclear")


def _conflict_reason(task: Node, event: CalendarEvent, fixed: bool) -> str:
    title = task.payload.get("title") or "Daily task"
    if fixed:
        return f"{title} conflicts with calendar event '{event.title}', but the task is fixed and should not be silently moved."
    return f"{title} conflicts with calendar event '{event.title}' and can be reviewed for a safer time."


def _suggest_alternative_time(start_at: datetime, end_at: datetime, events: list[CalendarEvent], target_date: date) -> str | None:
    duration = end_at - start_at
    day_start = datetime.combine(target_date, time(7, 0), tzinfo=SINGAPORE_TZ)
    day_end = datetime.combine(target_date, time(21, 0), tzinfo=SINGAPORE_TZ)
    cursor = day_start
    busy = sorted([event for event in events if event.busy], key=lambda item: item.start_at)
    while cursor + duration <= day_end:
        candidate_end = cursor + duration
        if not any(_overlaps(cursor, candidate_end, event.start_at, event.end_at) for event in busy):
            return cursor.isoformat()
        cursor += timedelta(minutes=15)
    return None


def _calendar_event_from_google(item: dict[str, Any], tzinfo) -> CalendarEvent:
    start_at = _parse_google_datetime(item.get("start", {}), tzinfo)
    end_at = _parse_google_datetime(item.get("end", {}), tzinfo)
    return CalendarEvent(
        id=str(item.get("id") or ""),
        title=str(item.get("summary") or "Busy"),
        start_at=start_at,
        end_at=end_at,
        busy=item.get("transparency") != "transparent",
    )


def _parse_google_datetime(value: dict[str, Any], tzinfo) -> datetime:
    raw = value.get("dateTime")
    if raw:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(SINGAPORE_TZ)
    date_value = date.fromisoformat(str(value.get("date")))
    return datetime.combine(date_value, time.min, tzinfo=tzinfo).astimezone(SINGAPORE_TZ)


def _overlaps(left_start: datetime, left_end: datetime, right_start: datetime, right_end: datetime) -> bool:
    return left_start < right_end and right_start < left_end


def _parse_time(value: str) -> time:
    return time.fromisoformat(value)


def _minus_minutes(value: time, minutes: int) -> time:
    base = datetime.combine(date(2000, 1, 1), value)
    return (base - timedelta(minutes=minutes)).time()


async def daily_scheduler_loop(
    store: GraphStore,
    patient_id: str,
    settings: Settings,
    calendar_provider: CalendarProvider | None = None,
) -> None:
    while True:
        try:
            now = datetime.now(PATIENT_TZ)
            target = now.replace(
                hour=settings.scheduler_run_hour,
                minute=settings.scheduler_run_minute,
                second=0,
                microsecond=0,
            )
            if target <= now:
                target = target + timedelta(days=1)
            await asyncio.sleep((target - now).total_seconds())
            target_date_iso = (target + timedelta(days=1)).date().isoformat()
            lock_key = f"nextday:{patient_id}:{target_date_iso}"
            if await store.acquire_system_lock(lock_key, ttl_seconds=600):
                await run_next_day_schedule_check(store, patient_id, settings, calendar_provider, now=target)
        except asyncio.CancelledError:
            raise
        except Exception:
            SCHEDULER_LOG.exception("daily_scheduler_loop iteration failed; retrying after backoff")
            await asyncio.sleep(60)
