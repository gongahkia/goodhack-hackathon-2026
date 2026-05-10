from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

from .calendar_auth import resolve_google_calendar_credentials
from .config import Settings
from .models import Node
from .scheduler import CalendarProvider, GoogleCalendarProvider, SINGAPORE_TZ
from .security import sanitize_provider_error, vendor_allowed
from .store import GraphStore


VALID_SCHEDULING_SEMANTICS = {"fixed_clinical", "fixed_deadline", "movable_routine", "movable_preference", "unclear"}
MEAL_TIME_KEYS = {"breakfast", "lunch", "dinner"}
CALENDAR_WRITE_LOCK_TTL_SECONDS = 120


class CalendarWriteProvider(Protocol):
    async def insert_event(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class GoogleCalendarWriteProvider:
    settings: Settings
    store: GraphStore | None = None
    patient_id: str | None = None

    async def insert_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not vendor_allowed(self.settings, "google_calendar", "calendar_write"):
            raise RuntimeError("Google Calendar is disabled for calendar_write.")
        credentials = await resolve_google_calendar_credentials(self.settings, self.store, self.patient_id)
        if not credentials:
            raise RuntimeError("Google Calendar write requires GOOGLE_CALENDAR_ACCESS_TOKEN.")
        url = f"{self.settings.google_calendar_api_base_url.rstrip('/')}/calendars/{credentials.calendar_id}/events"
        headers = {"Authorization": f"Bearer {credentials.access_token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        return response.json()


async def update_daily_task(
    store: GraphStore,
    patient_id: str,
    task: Node,
    patch: dict[str, Any],
) -> dict[str, Any]:
    if task.type != "daily_task" or task.payload.get("patient_id") != patient_id:
        raise ValueError("Daily task not found")
    allowed = {"title", "description", "scheduled_time", "timing_relation", "scheduling_semantics", "reason", "meal_times", "timezone"}
    unsupported = sorted(set(patch) - allowed)
    if unsupported:
        raise ValueError(f"Unsupported daily task field(s): {', '.join(unsupported)}")
    _validate_daily_task_patch(patch)

    override: dict[str, Any] = {
        **(task.payload.get("user_override") if isinstance(task.payload.get("user_override"), dict) else {}),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    for key in ["scheduled_time", "timing_relation", "scheduling_semantics", "reason", "meal_times", "timezone"]:
        if key in patch:
            override[key] = patch[key]
    payload_patch: dict[str, Any] = {"user_override": override}
    for key in ["title"]:
        if key in patch:
            payload_patch[key] = str(patch[key]).strip()[:200]
    if "description" in patch:
        payload_patch["user_visible_description"] = str(patch["description"]).strip()[:1000]

    updated = await store.update_node_payload(task.id, payload_patch, "edited")
    feedback = await store.create_node(
        "caregiver_feedback",
        {
            "patient_id": patient_id,
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
    return {"daily_task": updated.model_dump(mode="json"), "feedback": feedback.model_dump(mode="json")}


async def approve_appointment_calendar_write(
    store: GraphStore,
    patient_id: str,
    appointment: Node,
    settings: Settings,
    calendar_writer: CalendarWriteProvider | None = None,
    calendar_provider: CalendarProvider | None = None,
) -> dict[str, Any]:
    appointment = await _validated_appointment_for_calendar_write(store, patient_id, appointment)
    lock_key = f"calwrite:{appointment.id}"
    lock_owner = str(uuid4())
    if not await store.acquire_system_lock(lock_key, ttl_seconds=CALENDAR_WRITE_LOCK_TTL_SECONDS):
        latest = await store.get_node(appointment.id)
        if latest and (latest.payload.get("calendar_write_status") == "written" or latest.payload.get("google_event_id")):
            raise ValueError("Appointment candidate has already been written to calendar")
        raise ValueError("Appointment calendar write is already in progress")
    await store.set_system_state(
        lock_key,
        {"owner": lock_owner, "appointment_candidate_id": str(appointment.id), "acquired_at": datetime.now(UTC).isoformat()},
        datetime.now(UTC) + timedelta(seconds=CALENDAR_WRITE_LOCK_TTL_SECONDS),
    )
    try:
        return await _approve_appointment_calendar_write_locked(store, patient_id, appointment, settings, calendar_writer, calendar_provider)
    finally:
        await _release_calendar_write_lock(store, lock_key, lock_owner)


async def _approve_appointment_calendar_write_locked(
    store: GraphStore,
    patient_id: str,
    appointment: Node,
    settings: Settings,
    calendar_writer: CalendarWriteProvider | None,
    calendar_provider: CalendarProvider | None,
) -> dict[str, Any]:
    appointment = await _validated_appointment_for_calendar_write(store, patient_id, appointment)

    decision = await store.create_node(
        "user_decision",
        {
            "patient_id": patient_id,
            "target_node_id": str(appointment.id),
            "decision": "approved_calendar_write",
            "created_at": datetime.now(UTC).isoformat(),
        },
        "user",
        status="approved",
    )
    request = await store.create_node(
        "calendar_write_request",
        {
            "patient_id": patient_id,
            "appointment_candidate_id": str(appointment.id),
            "provider": "google_calendar",
            "operation": "insert_event",
            "status": "approved_pending_write",
            "requested_at": datetime.now(UTC).isoformat(),
        },
        "system",
        status="pending_review",
    )
    await store.create_edge(request.id, appointment.id, "requires_approval")
    await store.create_edge(request.id, decision.id, "approved_by_user")

    event_payload = _event_payload_from_appointment(appointment)
    conflict_payload = await _pending_appointment_conflict_payload(store, patient_id, appointment)
    provider = calendar_provider if calendar_provider is not None else (GoogleCalendarProvider(settings, store, patient_id) if calendar_writer is None else None)
    try:
        conflict_payload = conflict_payload or (await _appointment_write_conflict_payload(appointment, provider) if provider else None)
    except Exception as exc:
        updated_request = await store.update_node_payload(
            request.id,
            {"status": "conflict_check_failed", "error": sanitize_provider_error(exc), "event_payload": event_payload},
            "clarification_required",
        )
        return {
            "user_decision": decision.model_dump(mode="json"),
            "calendar_write_request": updated_request.model_dump(mode="json"),
            "calendar_event": None,
        }
    if conflict_payload:
        conflict = await store.create_node(
            "schedule_conflict",
            {"patient_id": patient_id, "appointment_candidate_id": str(appointment.id), **conflict_payload},
            "system",
            status="clarification_required",
        )
        await store.create_edge(conflict.id, appointment.id, "conflicts_with")
        updated_request = await store.update_node_payload(
            request.id,
            {"status": "blocked_conflict", "schedule_conflict_id": str(conflict.id), "event_payload": event_payload},
            "clarification_required",
        )
        return {
            "user_decision": decision.model_dump(mode="json"),
            "calendar_write_request": updated_request.model_dump(mode="json"),
            "schedule_conflict": conflict.model_dump(mode="json"),
            "calendar_event": None,
        }
    try:
        writer = calendar_writer or GoogleCalendarWriteProvider(settings, store, patient_id)
        response = await writer.insert_event(event_payload)
    except Exception as exc:
        updated_request = await store.update_node_payload(
            request.id,
            {"status": "write_failed", "error": sanitize_provider_error(exc), "event_payload": event_payload},
            "clarification_required",
        )
        return {
            "user_decision": decision.model_dump(mode="json"),
            "calendar_write_request": updated_request.model_dump(mode="json"),
            "calendar_event": None,
        }

    updated_request = await store.update_node_payload(
        request.id,
        {
            "status": "written",
            "event_payload": event_payload,
            "google_event_id": response.get("id"),
            "html_link": response.get("htmlLink"),
            "written_at": datetime.now(UTC).isoformat(),
        },
        "approved",
    )
    updated_appointment = await store.update_node_payload(
        appointment.id,
        {
            "calendar_write_status": "written",
            "google_event_id": response.get("id"),
            "calendar_write_request_id": str(request.id),
        },
        "approved",
    )
    await store.create_edge(updated_request.id, updated_appointment.id, "written_to_calendar")
    return {
        "user_decision": decision.model_dump(mode="json"),
        "calendar_write_request": updated_request.model_dump(mode="json"),
        "appointment_candidate": updated_appointment.model_dump(mode="json"),
        "calendar_event": response,
    }


async def _validated_appointment_for_calendar_write(store: GraphStore, patient_id: str, appointment: Node) -> Node:
    current = await store.get_node(appointment.id)
    if not current:
        raise ValueError("Appointment candidate not found")
    appointment = current
    if appointment.type != "appointment_candidate" or appointment.payload.get("patient_id") != patient_id:
        raise ValueError("Appointment candidate not found")
    if appointment.payload.get("calendar_write_status") == "written" or appointment.payload.get("google_event_id"):
        raise ValueError("Appointment candidate has already been written to calendar")
    if not appointment.payload.get("requires_calendar_write"):
        raise ValueError("Appointment candidate does not require calendar write")
    if not appointment.payload.get("date"):
        raise ValueError("Appointment candidate needs a date before calendar write")
    if not appointment.payload.get("time"):
        raise ValueError("Appointment candidate needs a clarified time before calendar write")
    if appointment.payload.get("requires_clarification"):
        reasons = appointment.payload.get("clarification_reasons") or []
        raise ValueError(f"Appointment candidate needs clarification before calendar write: {', '.join(reasons) or 'see clarification_reasons'}")
    return appointment


async def _release_calendar_write_lock(store: GraphStore, lock_key: str, lock_owner: str) -> None:
    state = await store.get_system_state(lock_key)
    if state and isinstance(state.get("value"), dict) and state["value"].get("owner") == lock_owner:
        await store.set_system_state(lock_key, {"released_at": datetime.now(UTC).isoformat()}, locked_until=None)


async def _appointment_write_conflict_payload(appointment: Node, calendar_provider: CalendarProvider) -> dict[str, Any] | None:
    start = _appointment_start(appointment.payload)
    end = start + timedelta(minutes=int(appointment.payload.get("duration_minutes") or 60))
    events = await calendar_provider.list_events(start, end)
    overlap = next((event for event in events if event.busy and _overlaps(start, end, event.start_at, event.end_at)), None)
    if not overlap:
        return None
    return {
        "category": "appointment_write_conflict",
        "classification": "fixed",
        "reason": f"Appointment overlaps existing calendar event '{overlap.title}'.",
        "appointment_time": {"start_at": start.isoformat(), "end_at": end.isoformat()},
        "calendar_event_id": overlap.id,
        "calendar_event_title": overlap.title,
        "detected_at": datetime.now(UTC).isoformat(),
    }


async def _pending_appointment_conflict_payload(store: GraphStore, patient_id: str, appointment: Node) -> dict[str, Any] | None:
    start = _appointment_start(appointment.payload)
    end = start + timedelta(minutes=int(appointment.payload.get("duration_minutes") or 60))
    appointments = [node for node in await store.list_nodes(patient_id, ["appointment_candidate"]) if node.id != appointment.id and node.status != "dismissed"]
    for candidate in appointments:
        if not candidate.payload.get("date") or not candidate.payload.get("time"):
            continue
        try:
            candidate_start = _appointment_start(candidate.payload)
        except Exception:
            continue
        candidate_end = candidate_start + timedelta(minutes=int(candidate.payload.get("duration_minutes") or 60))
        if _overlaps(start, end, candidate_start, candidate_end):
            title = str(candidate.payload.get("title") or "Appointment")
            return {
                "category": "appointment_write_conflict",
                "classification": "fixed",
                "reason": f"Appointment overlaps pending appointment '{title}'.",
                "appointment_time": {"start_at": start.isoformat(), "end_at": end.isoformat()},
                "conflicting_appointment_candidate_id": str(candidate.id),
                "conflicting_appointment_title": title,
                "detected_at": datetime.now(UTC).isoformat(),
            }
    return None


def _event_payload_from_appointment(appointment: Node) -> dict[str, Any]:
    payload = appointment.payload
    start = _appointment_start(payload)
    end = start + timedelta(minutes=int(payload.get("duration_minutes") or 60))
    event: dict[str, Any] = {
        "summary": payload.get("title") or f"{str(payload.get('kind') or 'Appointment').title()} appointment",
        "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Singapore"},
        "end": {"dateTime": end.isoformat(), "timeZone": "Asia/Singapore"},
    }
    if payload.get("location"):
        event["location"] = payload["location"]
    if payload.get("description"):
        event["description"] = payload["description"]
    return event


def _appointment_start(payload: dict[str, Any]) -> datetime:
    date_value = str(payload["date"])
    time_value = payload.get("time")
    if not time_value:
        raise ValueError("Appointment candidate has no clarified time; refusing to default")
    return datetime.combine(datetime.fromisoformat(date_value).date(), time.fromisoformat(str(time_value)), tzinfo=SINGAPORE_TZ)


def _overlaps(left_start: datetime, left_end: datetime, right_start: datetime, right_end: datetime) -> bool:
    return left_start < right_end and right_start < left_end


def _validate_daily_task_patch(patch: dict[str, Any]) -> None:
    if "scheduling_semantics" in patch and patch["scheduling_semantics"] not in VALID_SCHEDULING_SEMANTICS:
        raise ValueError(f"scheduling_semantics must be one of: {', '.join(sorted(VALID_SCHEDULING_SEMANTICS))}")
    if "scheduled_time" in patch and patch["scheduled_time"] is not None:
        _parse_hhmm(str(patch["scheduled_time"]), "scheduled_time")
    if "timezone" in patch and patch["timezone"] is not None:
        try:
            ZoneInfo(str(patch["timezone"]))
        except Exception as exc:
            raise ValueError(f"timezone must be a valid IANA name: {exc}") from exc
    if "meal_times" in patch:
        meal_times = patch["meal_times"]
        if meal_times is not None and not isinstance(meal_times, dict):
            raise ValueError("meal_times must be an object keyed by meal name")
        if isinstance(meal_times, dict):
            unsupported = sorted(set(meal_times) - MEAL_TIME_KEYS)
            if unsupported:
                raise ValueError(f"Unsupported meal time field(s): {', '.join(unsupported)}")
            for key, value in meal_times.items():
                if value is not None:
                    _parse_hhmm(str(value), f"meal_times.{key}")


def _parse_hhmm(value: str, field_name: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use HH:MM format") from exc
    if parsed.second or parsed.microsecond:
        raise ValueError(f"{field_name} must use HH:MM format")
    return parsed
