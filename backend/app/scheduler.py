from __future__ import annotations

from dataclasses import dataclass
import asyncio
import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx

from .calendar_auth import resolve_google_calendar_credentials
from .config import PATIENT_TZ, Settings
from .models import Node
from .security import vendor_allowed
from .store import GraphStore


SINGAPORE_TZ = PATIENT_TZ  # backwards-compat alias
SCHEDULER_LOG = logging.getLogger("app.scheduler.loop")
DEFAULT_MEAL_TIMES = {"breakfast": "08:00", "lunch": "12:00", "dinner": "18:00"}
MIN_THREE_TIMES_DAILY_SPACING_MINUTES = 4 * 60
NEXTDAY_LOCK_TTL_SECONDS = 600
RESOLUTION_ACTIONS = {"accept_suggested_time", "custom_time", "keep_fixed", "dismiss", "recompute"}


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
    def __init__(self, settings: Settings, store: GraphStore | None = None, patient_id: str | None = None) -> None:
        self.settings = settings
        self.store = store
        self.patient_id = patient_id

    async def list_events(self, start_at: datetime, end_at: datetime) -> list[CalendarEvent]:
        if not vendor_allowed(self.settings, "google_calendar", "calendar_read"):
            return []
        credentials = await resolve_google_calendar_credentials(self.settings, self.store, self.patient_id)
        if not credentials:
            return []
        url = f"{self.settings.google_calendar_api_base_url.rstrip('/')}/calendars/{credentials.calendar_id}/events"
        params = {
            "timeMin": start_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "timeMax": end_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        headers = {"Authorization": f"Bearer {credentials.access_token}"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
        return [_calendar_event_from_google(item, start_at.tzinfo or SINGAPORE_TZ) for item in response.json().get("items", [])]


async def build_day_schedule(
    store: GraphStore,
    patient_id: str,
    settings: Settings,
    target_date: date,
    calendar_provider: CalendarProvider | None = None,
) -> dict[str, Any]:
    window_start = datetime.combine(target_date, time.min, tzinfo=SINGAPORE_TZ)
    window_end = window_start + timedelta(days=1)
    provider = calendar_provider or GoogleCalendarProvider(settings, store, patient_id)
    events = await provider.list_events(window_start, window_end)
    tasks = [node for node in await store.list_nodes(patient_id, ["daily_task"]) if node.status != "dismissed"]

    items: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for task in tasks:
        candidate = _candidate_time_for_task(task, target_date)
        if not candidate:
            items.append(_schedule_item(task, "goal", None, None, None))
            continue
        start_at, end_at = candidate
        overlap = next((event for event in events if event.busy and _overlaps(start_at, end_at, event.start_at, event.end_at)), None)
        conflict = _day_schedule_conflict(task, start_at, end_at, overlap, events, target_date) if overlap else None
        if conflict:
            conflicts.append(conflict)
        items.append(_schedule_item(task, "scheduled", start_at, end_at, conflict))

    return {
        "date": target_date.isoformat(),
        "timezone": SINGAPORE_TZ.key,
        "items": sorted(items, key=_schedule_item_sort_key),
        "calendar_events": [_calendar_event_payload(event) for event in events],
        "conflicts": conflicts,
    }


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
    provider = calendar_provider or GoogleCalendarProvider(settings, store, patient_id)

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


async def run_next_day_schedule_check_once(
    store: GraphStore,
    patient_id: str,
    settings: Settings,
    calendar_provider: CalendarProvider | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> dict[str, Any]:
    run_at = now.astimezone(SINGAPORE_TZ) if now else datetime.now(SINGAPORE_TZ)
    target_date = (run_at + timedelta(days=1)).date()
    run_key = _nextday_run_key(patient_id, target_date)
    existing = await store.get_system_state(run_key)
    if not force and _system_state_status(existing) == "completed":
        return {"already_ran": True, "run_key": run_key, **dict(existing["value"].get("summary") or {})}
    if not await store.acquire_system_lock(run_key, ttl_seconds=NEXTDAY_LOCK_TTL_SECONDS):
        existing = await store.get_system_state(run_key)
        if not force and _system_state_status(existing) == "completed":
            return {"already_ran": True, "run_key": run_key, **dict(existing["value"].get("summary") or {})}
        return {"already_running": True, "run_key": run_key, "target_date": target_date.isoformat(), "timezone": "Asia/Singapore"}
    await store.set_system_state(
        run_key,
        {"status": "running", "target_date": target_date.isoformat(), "started_at": datetime.now(UTC).isoformat()},
        datetime.now(UTC) + timedelta(seconds=NEXTDAY_LOCK_TTL_SECONDS),
    )
    try:
        summary = await run_next_day_schedule_check(store, patient_id, settings, calendar_provider, now=run_at)
    except Exception:
        await store.set_system_state(
            run_key,
            {"status": "failed", "target_date": target_date.isoformat(), "failed_at": datetime.now(UTC).isoformat()},
            locked_until=None,
        )
        raise
    await store.set_system_state(
        run_key,
        {"status": "completed", "target_date": target_date.isoformat(), "completed_at": datetime.now(UTC).isoformat(), "summary": summary},
        locked_until=None,
    )
    return {"already_ran": False, "run_key": run_key, **summary}


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
    explicit = _effective_payload_value(payload, "scheduled_time") or _effective_payload_value(payload, "time")
    timing = str(_effective_payload_value(payload, "timing_relation") or "").lower()
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


def _schedule_item(task: Node, bucket: str, start_at: datetime | None, end_at: datetime | None, conflict: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "node_id": str(task.id),
        "title": str(task.payload.get("title") or "Daily task"),
        "detail": _task_detail(task),
        "status": task.status,
        "bucket": bucket,
        "start_at": start_at.isoformat() if start_at else None,
        "end_at": end_at.isoformat() if end_at else None,
        "time_label": _time_label(start_at) if start_at else "Anytime",
        "schedule_source": _schedule_source(task),
        "conflict": conflict,
    }


def _schedule_item_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    return (0 if item["bucket"] == "scheduled" else 1, str(item.get("start_at") or ""), str(item["title"]).lower())


def _task_detail(task: Node) -> str | None:
    payload = task.payload
    return payload.get("user_visible_description") or payload.get("description") or payload.get("instructions") or payload.get("original_instruction_redacted")


def _schedule_source(task: Node) -> str:
    payload = task.payload
    if _effective_payload_value(payload, "scheduled_time") or _effective_payload_value(payload, "time"):
        return "explicit"
    if _effective_payload_value(payload, "timing_relation"):
        return "timing_relation"
    return "unspecified"


def _day_schedule_conflict(
    task: Node,
    start_at: datetime,
    end_at: datetime,
    event: CalendarEvent,
    events: list[CalendarEvent],
    target_date: date,
) -> dict[str, Any]:
    semantics = _effective_semantics(task)
    fixed = semantics in {"fixed_clinical", "fixed_deadline"}
    return {
        "id": f"computed:{task.id}:{event.id}:{start_at.isoformat()}",
        "node_id": str(task.id),
        "calendar_event_id": event.id,
        "calendar_event_title": event.title,
        "calendar_event_start_at": event.start_at.isoformat(),
        "calendar_event_end_at": event.end_at.isoformat(),
        "classification": "fixed" if fixed else "movable",
        "reason": _conflict_reason(task, event, fixed),
        "task_time": {"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
        "suggested_time": None if fixed else _suggest_alternative_time(start_at, end_at, events, target_date),
        "source": "computed",
    }


def _calendar_event_payload(event: CalendarEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "title": event.title,
        "start_at": event.start_at.isoformat(),
        "end_at": event.end_at.isoformat(),
        "busy": event.busy,
    }


def _time_label(value: datetime) -> str:
    hour = value.hour % 12 or 12
    suffix = "AM" if value.hour < 12 else "PM"
    return f"{hour}:{value.minute:02d} {suffix}"


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
    override = payload.get("user_override") if isinstance(payload.get("user_override"), dict) else {}
    configured = payload.get("meal_times") if isinstance(payload.get("meal_times"), dict) else {}
    override_meals = override.get("meal_times") if isinstance(override.get("meal_times"), dict) else {}
    configured = {**configured, **override_meals}
    return {name: _parse_time(str(configured.get(name) or DEFAULT_MEAL_TIMES[name])) for name in DEFAULT_MEAL_TIMES}


def _effective_semantics(task: Node) -> str:
    override = task.payload.get("user_override")
    if isinstance(override, dict) and override.get("scheduling_semantics"):
        return str(override["scheduling_semantics"])
    return str(task.payload.get("scheduling_semantics") or "unclear")


def _effective_payload_value(payload: dict[str, Any], key: str) -> Any:
    override = payload.get("user_override")
    if isinstance(override, dict) and key in override:
        return override[key]
    return payload.get(key)


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
            if _system_state_status(await store.get_system_state(f"nextday:{patient_id}:{target_date_iso}")) != "completed":
                await run_next_day_schedule_check_once(store, patient_id, settings, calendar_provider, now=target)
        except asyncio.CancelledError:
            raise
        except Exception:
            SCHEDULER_LOG.exception("daily_scheduler_loop iteration failed; retrying after backoff")
            await asyncio.sleep(60)


async def list_active_schedule_conflicts(store: GraphStore, patient_id: str, settings: Settings, calendar_provider: CalendarProvider | None = None) -> list[Node]:
    await reconcile_stale_schedule_conflicts(store, patient_id, settings, calendar_provider)
    conflicts = await store.list_nodes(patient_id, ["schedule_conflict"])
    return [
        conflict
        for conflict in conflicts
        if conflict.status in {"pending_review", "clarification_required"}
        and conflict.payload.get("resolution_status") not in {"resolved", "dismissed", "auto_resolved"}
    ]


async def resolve_schedule_conflict(
    store: GraphStore,
    patient_id: str,
    conflict: Node,
    settings: Settings,
    action: str,
    scheduled_time: str | None = None,
    reason: str | None = None,
    calendar_provider: CalendarProvider | None = None,
) -> dict[str, Any]:
    if conflict.type != "schedule_conflict" or conflict.payload.get("patient_id") != patient_id:
        raise ValueError("Schedule conflict not found")
    if action not in RESOLUTION_ACTIONS:
        raise ValueError(f"Unsupported conflict resolution action: {action}")
    if conflict.status == "dismissed" or conflict.payload.get("resolution_status") in {"resolved", "dismissed", "auto_resolved"}:
        raise ValueError("Schedule conflict is already resolved")

    if action == "dismiss":
        decision = await _record_conflict_decision(store, patient_id, conflict, action, reason, None)
        updated = await store.update_node_payload(
            conflict.id,
            {"resolution_status": "dismissed", "resolved_at": datetime.now(UTC).isoformat(), "resolution_reason": reason},
            "dismissed",
        )
        return {"schedule_conflict": updated.model_dump(mode="json"), "user_decision": decision.model_dump(mode="json")}

    task = await _conflict_daily_task(store, conflict)
    if not task:
        if action == "keep_fixed":
            decision = await _record_conflict_decision(store, patient_id, conflict, action, reason, None)
            updated = await store.update_node_payload(
                conflict.id,
                {"resolution_status": "resolved", "resolved_at": datetime.now(UTC).isoformat(), "resolution_reason": reason},
                "approved",
            )
            return {"schedule_conflict": updated.model_dump(mode="json"), "user_decision": decision.model_dump(mode="json")}
        raise ValueError("Only daily task conflicts support timing resolution")

    target_date = _conflict_target_date(conflict)
    if not target_date:
        raise ValueError("Schedule conflict has no target date")
    solver = await _build_conflict_solver(store, patient_id, settings, target_date, exclude_task_id=str(task.id), calendar_provider=calendar_provider)

    if action == "recompute":
        candidate = _find_open_slot(task, target_date, solver["busy"])
        updated = await store.update_node_payload(conflict.id, {"suggested_time": candidate.isoformat() if candidate else None}, conflict.status)
        return {"schedule_conflict": updated.model_dump(mode="json"), "suggested_time": candidate.isoformat() if candidate else None}
    if action == "keep_fixed":
        decision = await _record_conflict_decision(store, patient_id, conflict, action, reason, None)
        updated = await store.update_node_payload(
            conflict.id,
            {"resolution_status": "resolved", "resolved_at": datetime.now(UTC).isoformat(), "resolution_reason": reason},
            "approved",
        )
        return {"schedule_conflict": updated.model_dump(mode="json"), "user_decision": decision.model_dump(mode="json")}

    start = _resolution_start(conflict, action, scheduled_time, target_date)
    end = start + _task_duration(task, target_date)
    overlap = next((slot for slot in solver["busy"] if _overlaps(start, end, slot["start_at"], slot["end_at"])), None)
    if overlap:
        decision = await _record_conflict_decision(store, patient_id, conflict, f"{action}_rejected", reason, {"overlap": overlap["title"]})
        updated = await store.update_node_payload(
            conflict.id,
            {"resolution_status": "still_conflicting", "last_resolution_error": f"Selected time overlaps {overlap['title']}"},
            "clarification_required",
        )
        return {"schedule_conflict": updated.model_dump(mode="json"), "user_decision": decision.model_dump(mode="json"), "accepted": False}

    patch = {"scheduled_time": start.strftime("%H:%M"), "scheduling_semantics": "movable_routine", "reason": reason or f"Resolved schedule conflict {conflict.id}."}
    updated_task = await _apply_task_resolution(store, task, patch)
    decision = await _record_conflict_decision(store, patient_id, conflict, action, reason, {"scheduled_time": patch["scheduled_time"]})
    updated_conflict = await store.update_node_payload(
        conflict.id,
        {
            "resolution_status": "resolved",
            "resolved_at": datetime.now(UTC).isoformat(),
            "resolved_scheduled_time": patch["scheduled_time"],
            "resolution_reason": reason,
        },
        "approved",
    )
    return {
        "schedule_conflict": updated_conflict.model_dump(mode="json"),
        "daily_task": updated_task["daily_task"].model_dump(mode="json"),
        "feedback": updated_task["feedback"].model_dump(mode="json"),
        "user_decision": decision.model_dump(mode="json"),
        "accepted": True,
    }


async def reconcile_stale_schedule_conflicts(store: GraphStore, patient_id: str, settings: Settings, calendar_provider: CalendarProvider | None = None) -> list[Node]:
    del settings, calendar_provider
    updated = []
    conflicts = await store.list_nodes(patient_id, ["schedule_conflict"])
    for conflict in conflicts:
        if conflict.status not in {"pending_review", "clarification_required"} or conflict.payload.get("resolution_status"):
            continue
        task = await _conflict_daily_task(store, conflict)
        original = _time_window_from_payload(conflict.payload.get("task_time"))
        if not task or not original:
            continue
        target_date = original[0].astimezone(SINGAPORE_TZ).date()
        current = _candidate_time_for_task(task, target_date)
        if current and not _overlaps(current[0], current[1], original[0], original[1]):
            log = await store.create_reasoning_log("schedule_conflict_reconciliation")
            await store.append_reasoning_step(log.id, {"kind": "conflict_resolved", "schedule_conflict_id": str(conflict.id), "daily_task_id": str(task.id)})
            await store.finish_reasoning_log(log.id, "Schedule conflict auto-resolved after task timing changed.")
            node = await store.update_node_payload(
                conflict.id,
                {"resolution_status": "auto_resolved", "resolved_at": datetime.now(UTC).isoformat(), "resolution_reason": "Task timing no longer overlaps original conflict window."},
                "approved",
            )
            updated.append(node)
    return updated


def _nextday_run_key(patient_id: str, target_date: date) -> str:
    return f"nextday:{patient_id}:{target_date.isoformat()}"


def _system_state_status(state: dict[str, Any] | None) -> str | None:
    value = state.get("value") if state else None
    return str(value.get("status")) if isinstance(value, dict) and value.get("status") else None


async def _conflict_daily_task(store: GraphStore, conflict: Node) -> Node | None:
    task_id = conflict.payload.get("daily_task_id")
    if not task_id:
        return None
    try:
        from uuid import UUID

        node = await store.get_node(UUID(str(task_id)))
    except Exception:
        return None
    return node if node and node.type == "daily_task" and node.status != "dismissed" else None


def _conflict_target_date(conflict: Node) -> date | None:
    window = _time_window_from_payload(conflict.payload.get("task_time") or conflict.payload.get("appointment_time"))
    return window[0].astimezone(SINGAPORE_TZ).date() if window else None


def _time_window_from_payload(value: Any) -> tuple[datetime, datetime] | None:
    if not isinstance(value, dict) or not value.get("start_at") or not value.get("end_at"):
        return None
    try:
        return (
            datetime.fromisoformat(str(value["start_at"]).replace("Z", "+00:00")),
            datetime.fromisoformat(str(value["end_at"]).replace("Z", "+00:00")),
        )
    except ValueError:
        return None


async def _build_conflict_solver(
    store: GraphStore,
    patient_id: str,
    settings: Settings,
    target_date: date,
    exclude_task_id: str,
    calendar_provider: CalendarProvider | None = None,
) -> dict[str, Any]:
    window_start = datetime.combine(target_date, time.min, tzinfo=SINGAPORE_TZ)
    window_end = window_start + timedelta(days=1)
    provider = calendar_provider or GoogleCalendarProvider(settings, store, patient_id)
    events = await provider.list_events(window_start, window_end)
    busy = [
        {"start_at": event.start_at, "end_at": event.end_at, "title": event.title, "source": "google_calendar"}
        for event in events
        if event.busy
    ]
    for task in await store.list_nodes(patient_id, ["daily_task"]):
        if str(task.id) == exclude_task_id or task.status == "dismissed":
            continue
        candidate = _candidate_time_for_task(task, target_date)
        if candidate:
            busy.append({"start_at": candidate[0], "end_at": candidate[1], "title": str(task.payload.get("title") or "Daily task"), "source": "daily_task"})
    for appointment in await store.list_nodes(patient_id, ["appointment_candidate"]):
        if appointment.status == "dismissed" or not appointment.payload.get("date") or not appointment.payload.get("time"):
            continue
        try:
            start = datetime.combine(datetime.fromisoformat(str(appointment.payload["date"])).date(), _parse_time(str(appointment.payload["time"])), tzinfo=SINGAPORE_TZ)
        except ValueError:
            continue
        if start.date() != target_date:
            continue
        end = start + timedelta(minutes=int(appointment.payload.get("duration_minutes") or 60))
        busy.append({"start_at": start, "end_at": end, "title": str(appointment.payload.get("title") or "Appointment"), "source": "appointment_candidate"})
    return {"busy": sorted(busy, key=lambda slot: slot["start_at"])}


def _find_open_slot(task: Node, target_date: date, busy: list[dict[str, Any]]) -> datetime | None:
    duration = _task_duration(task, target_date)
    cursor = datetime.combine(target_date, time(7, 0), tzinfo=SINGAPORE_TZ)
    day_end = datetime.combine(target_date, time(21, 0), tzinfo=SINGAPORE_TZ)
    while cursor + duration <= day_end:
        candidate_end = cursor + duration
        if not any(_overlaps(cursor, candidate_end, slot["start_at"], slot["end_at"]) for slot in busy):
            return cursor
        cursor += timedelta(minutes=15)
    return None


def _task_duration(task: Node, target_date: date) -> timedelta:
    candidate = _candidate_time_for_task(task, target_date)
    if candidate:
        return candidate[1] - candidate[0]
    return timedelta(minutes=max(5, min(int(task.payload.get("estimated_duration_minutes") or task.payload.get("estimated_effort_minutes") or 15), 240)))


def _resolution_start(conflict: Node, action: str, scheduled_time: str | None, target_date: date) -> datetime:
    if action == "custom_time":
        if not scheduled_time:
            raise ValueError("scheduled_time is required for custom_time")
        return datetime.combine(target_date, _parse_time(scheduled_time), tzinfo=SINGAPORE_TZ)
    suggested = conflict.payload.get("suggested_time")
    if not suggested:
        raise ValueError("Schedule conflict has no suggested_time to accept")
    return datetime.fromisoformat(str(suggested).replace("Z", "+00:00")).astimezone(SINGAPORE_TZ)


async def _apply_task_resolution(store: GraphStore, task: Node, patch: dict[str, Any]) -> dict[str, Node]:
    override = {
        **(task.payload.get("user_override") if isinstance(task.payload.get("user_override"), dict) else {}),
        **patch,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    daily_task = await store.update_node_payload(task.id, {"user_override": override}, "edited")
    feedback = await store.create_node(
        "caregiver_feedback",
        {
            "patient_id": task.payload.get("patient_id"),
            "target_node_id": str(task.id),
            "status": "edited",
            "payload_patch": patch,
            "feedback_note": patch.get("reason"),
            "created_at": datetime.now(UTC).isoformat(),
        },
        "user",
        status="approved",
    )
    await store.create_edge(feedback.id, task.id, "feedback_on")
    return {"daily_task": daily_task, "feedback": feedback}


async def _record_conflict_decision(
    store: GraphStore,
    patient_id: str,
    conflict: Node,
    action: str,
    reason: str | None,
    result: dict[str, Any] | None,
) -> Node:
    decision = await store.create_node(
        "user_decision",
        {
            "patient_id": patient_id,
            "target_node_id": str(conflict.id),
            "decision": "resolved_schedule_conflict",
            "action": action,
            "reason": reason,
            "result": result or {},
            "created_at": datetime.now(UTC).isoformat(),
        },
        "user",
        status="approved",
    )
    await store.create_edge(decision.id, conflict.id, "approved_by_user")
    return decision
