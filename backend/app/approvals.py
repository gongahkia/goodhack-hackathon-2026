from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Protocol

import httpx

from .config import Settings
from .models import Node
from .scheduler import SINGAPORE_TZ
from .security import sanitize_provider_error, vendor_allowed
from .store import GraphStore


VALID_SCHEDULING_SEMANTICS = {"fixed_clinical", "fixed_deadline", "movable_routine", "movable_preference", "unclear"}
MEAL_TIME_KEYS = {"breakfast", "lunch", "dinner"}


class CalendarWriteProvider(Protocol):
    async def insert_event(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class GoogleCalendarWriteProvider:
    settings: Settings

    async def insert_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not vendor_allowed(self.settings, "google_calendar", "calendar_write"):
            raise RuntimeError("Google Calendar is disabled for calendar_write.")
        if not self.settings.google_calendar_access_token:
            raise RuntimeError("Google Calendar write requires GOOGLE_CALENDAR_ACCESS_TOKEN.")
        url = f"{self.settings.google_calendar_api_base_url.rstrip('/')}/calendars/{self.settings.google_calendar_id}/events"
        headers = {"Authorization": f"Bearer {self.settings.google_calendar_access_token}", "Content-Type": "application/json"}
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
    allowed = {"title", "description", "scheduled_time", "timing_relation", "scheduling_semantics", "reason", "meal_times"}
    unsupported = sorted(set(patch) - allowed)
    if unsupported:
        raise ValueError(f"Unsupported daily task field(s): {', '.join(unsupported)}")
    _validate_daily_task_patch(patch)

    override: dict[str, Any] = {
        **(task.payload.get("user_override") if isinstance(task.payload.get("user_override"), dict) else {}),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    for key in ["scheduled_time", "timing_relation", "scheduling_semantics", "reason", "meal_times"]:
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
) -> dict[str, Any]:
    if appointment.type != "appointment_candidate" or appointment.payload.get("patient_id") != patient_id:
        raise ValueError("Appointment candidate not found")
    if not appointment.payload.get("requires_calendar_write"):
        raise ValueError("Appointment candidate does not require calendar write")
    if not appointment.payload.get("date"):
        raise ValueError("Appointment candidate needs a date before calendar write")
    if appointment.payload.get("calendar_write_status") == "written" or appointment.payload.get("google_event_id"):
        raise ValueError("Appointment candidate has already been written to calendar")

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
    try:
        writer = calendar_writer or GoogleCalendarWriteProvider(settings)
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
    time_value = str(payload.get("time") or "09:00")
    return datetime.combine(datetime.fromisoformat(date_value).date(), time.fromisoformat(time_value), tzinfo=SINGAPORE_TZ)


def _validate_daily_task_patch(patch: dict[str, Any]) -> None:
    if "scheduling_semantics" in patch and patch["scheduling_semantics"] not in VALID_SCHEDULING_SEMANTICS:
        raise ValueError(f"scheduling_semantics must be one of: {', '.join(sorted(VALID_SCHEDULING_SEMANTICS))}")
    if "scheduled_time" in patch and patch["scheduled_time"] is not None:
        _parse_hhmm(str(patch["scheduled_time"]), "scheduled_time")
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
