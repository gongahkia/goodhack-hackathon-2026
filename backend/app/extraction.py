from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import Node
from .privacy import rehydrate_placeholders
from .store import GraphStore


PersonRole = Literal["patient", "caregiver", "clinician", "unknown"]
BucketHint = Literal["daily_task", "ad_hoc_research", "appointment", "unclear"]
Urgency = Literal["routine", "clinical", "financial", "urgent"]
AppointmentKind = Literal["doctor", "physio", "lab", "other"]
SchedulingSemantics = Literal["fixed_clinical", "fixed_deadline", "movable_routine", "movable_preference", "unclear"]


class ExtractedPerson(BaseModel):
    placeholder_id: str
    role: PersonRole = "unknown"
    display_name_redacted: str


class ExtractedMedication(BaseModel):
    name: str
    dose: str | None = None
    quantity: str | None = None
    route: str | None = None
    frequency: str | None = None
    timing_relation: str | None = None
    fixed_time_required: bool = True
    safety_notes: list[str] = Field(default_factory=list)


class ExtractedTimeExpression(BaseModel):
    raw_text: str
    normalized_date: str | None = None
    normalized_time_window: str | None = None
    confidence: float = Field(ge=0, le=1)


class ExtractedRecurrence(BaseModel):
    pattern: str
    start_date: str | None = None
    end_date: str | None = None


class ExtractedAppointment(BaseModel):
    kind: AppointmentKind
    date: str | None = None
    time: str | None = None
    location: str | None = None
    requires_calendar_write: bool = False


class ExtractedActionable(BaseModel):
    description: str
    bucket_hint: BucketHint
    urgency: Urgency
    confidence: float = Field(ge=0, le=1)


class ExtractedMedicalContext(BaseModel):
    conditions: list[str] = Field(default_factory=list)
    body_parts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    clinician_warnings: list[str] = Field(default_factory=list)


class ExtractedEntities(BaseModel):
    people: list[ExtractedPerson] = Field(default_factory=list)
    medications: list[ExtractedMedication] = Field(default_factory=list)
    time_expressions: list[ExtractedTimeExpression] = Field(default_factory=list)
    recurrences: list[ExtractedRecurrence] = Field(default_factory=list)
    appointments: list[ExtractedAppointment] = Field(default_factory=list)
    actionables: list[ExtractedActionable] = Field(default_factory=list)
    medical_context: ExtractedMedicalContext = Field(default_factory=ExtractedMedicalContext)
    clarifications_needed: list[str] = Field(default_factory=list)


class TriageResult(BaseModel):
    buckets: list[BucketHint]
    daily_task_count: int = 0
    ad_hoc_research_task_count: int = 0
    appointment_candidate_count: int = 0
    research_allowed: bool = False
    guardrail_reason: str


MEDICATION_NAMES = ("panadol", "paracetamol", "insulin", "metformin", "aspirin", "levodopa")
MEAL_TERMS = ("breakfast", "lunch", "dinner", "food", "meal")
RESEARCH_CUES = (
    "grant",
    "subsidy",
    "scheme",
    "financial assistance",
    "wheelchair",
    "mobility aid",
    "home modification",
    "equipment",
    "amputation",
    "amputate",
    "medical social worker",
    "research",
    "find out",
    "look up",
    "what support",
)
WARNING_CUES = ("doctor said", "clinician said", "warned", "risk", "may need", "might need", "likely")
APPOINTMENT_CUES = ("appointment", "visit", "review", "see the doctor", "physio", "lab")
BODY_PARTS = ("knee", "leg", "foot", "ankle", "hand", "arm", "eye", "heart", "kidney")
CONDITIONS = ("diabetes", "high blood sugar", "parkinson", "dementia", "stroke", "hypertension")


def extract_entities_from_redaction(redaction: Node, reference_date: date | None = None) -> ExtractedEntities:
    if redaction.type != "pii_redaction":
        raise ValueError("Can only extract entities from pii_redaction nodes")
    text = str(redaction.payload.get("redacted_text") or "")
    placeholder_map = _placeholder_map(redaction)
    today = reference_date or datetime.now(UTC).date()

    entities = ExtractedEntities(
        people=[
            ExtractedPerson(placeholder_id=placeholder, display_name_redacted=placeholder)
            for placeholder in sorted(placeholder_map)
            if placeholder.startswith(("PERSON_", "PATIENT_", "CAREGIVER_"))
        ],
        medications=_extract_medications(text),
        time_expressions=_extract_time_expressions(text, today),
        recurrences=_extract_recurrences(text, today),
        appointments=_extract_appointments(text, today),
        actionables=[],
        medical_context=_extract_medical_context(text),
        clarifications_needed=[],
    )
    entities.actionables = _extract_actionables(text, entities)
    if not entities.actionables:
        entities.clarifications_needed.append("No clear actionable care instruction was found.")
    return entities


def triage_extracted_entities(entities: ExtractedEntities) -> TriageResult:
    has_daily = any(item.bucket_hint == "daily_task" for item in entities.actionables)
    has_appointment = bool(entities.appointments) or any(item.bucket_hint == "appointment" for item in entities.actionables)
    explicit_research = any(item.bucket_hint == "ad_hoc_research" for item in entities.actionables)
    research_allowed = explicit_research and _has_research_basis(entities)

    buckets: list[BucketHint] = []
    if has_daily:
        buckets.append("daily_task")
    if has_appointment:
        buckets.append("appointment")
    if research_allowed:
        buckets.append("ad_hoc_research")
    if not buckets:
        buckets.append("unclear")

    guardrail_reason = (
        "Research allowed because transcript includes explicit risk, equipment, grant, policy, or research cues."
        if research_allowed
        else "Research blocked unless transcript explicitly includes future risk, uncertainty, grants, equipment, policy needs, or a user research request."
    )
    return TriageResult(
        buckets=buckets,
        daily_task_count=sum(1 for item in entities.actionables if item.bucket_hint == "daily_task"),
        ad_hoc_research_task_count=sum(1 for item in entities.actionables if item.bucket_hint == "ad_hoc_research" and research_allowed),
        appointment_candidate_count=len(entities.appointments),
        research_allowed=research_allowed,
        guardrail_reason=guardrail_reason,
    )


async def process_redacted_transcript(
    store: GraphStore,
    redaction: Node,
    reference_date: date | None = None,
) -> dict[str, Any]:
    existing = await _existing_processed_result(store, redaction)
    if existing:
        return existing

    entities = extract_entities_from_redaction(redaction, reference_date)
    triage = triage_extracted_entities(entities)
    patient_id = str(redaction.payload.get("patient_id") or "")
    placeholder_map = _placeholder_map(redaction)

    entities_node = await store.create_node(
        "extracted_entities",
        {"patient_id": patient_id, "pii_redaction_id": str(redaction.id), **entities.model_dump(mode="json")},
        "agent",
        reasoning_log_id=redaction.reasoning_log_id,
        status="approved" if not entities.clarifications_needed else "clarification_required",
    )
    await store.create_edge(entities_node.id, redaction.id, "extracted_from")

    triage_node = await store.create_node(
        "triage_decision",
        {"patient_id": patient_id, "extracted_entities_id": str(entities_node.id), **triage.model_dump(mode="json")},
        "agent",
        reasoning_log_id=redaction.reasoning_log_id,
        status="approved" if triage.buckets != ["unclear"] else "clarification_required",
    )
    await store.create_edge(triage_node.id, entities_node.id, "triaged_from")

    daily_tasks = []
    research_tasks = []
    appointments = []
    for actionable in entities.actionables:
        if actionable.bucket_hint == "daily_task":
            node = await _create_daily_task(store, patient_id, actionable, entities, triage_node, entities_node, placeholder_map, redaction.reasoning_log_id)
            daily_tasks.append(node)
        elif actionable.bucket_hint == "ad_hoc_research" and triage.research_allowed:
            node = await _create_research_task(store, patient_id, actionable, entities, triage_node, placeholder_map, redaction.reasoning_log_id)
            research_tasks.append(node)

    for appointment in entities.appointments:
        node = await _create_appointment_candidate(store, patient_id, appointment, triage_node, placeholder_map, redaction.reasoning_log_id)
        appointments.append(node)

    if redaction.reasoning_log_id:
        await store.append_reasoning_step(
            redaction.reasoning_log_id,
            {
                "kind": "entity_extraction_and_triage",
                "pii_redaction_id": str(redaction.id),
                "extracted_entities_id": str(entities_node.id),
                "triage_decision_id": str(triage_node.id),
                "buckets": triage.buckets,
                "daily_task_count": len(daily_tasks),
                "research_task_count": len(research_tasks),
                "appointment_candidate_count": len(appointments),
                "research_allowed": triage.research_allowed,
            },
        )

    return {
        "extracted_entities": entities_node.model_dump(mode="json"),
        "triage_decision": triage_node.model_dump(mode="json"),
        "daily_tasks": [node.model_dump(mode="json") for node in daily_tasks],
        "ad_hoc_research_tasks": [node.model_dump(mode="json") for node in research_tasks],
        "appointment_candidates": [node.model_dump(mode="json") for node in appointments],
    }


async def _existing_processed_result(store: GraphStore, redaction: Node) -> dict[str, Any] | None:
    edges = await store.list_edges()
    entity_nodes = []
    for edge in edges:
        if edge.to_node == redaction.id and edge.type == "extracted_from":
            node = await store.get_node(edge.from_node)
            if node and node.type == "extracted_entities":
                entity_nodes.append(node)
    if not entity_nodes:
        return None

    entities_node = sorted(entity_nodes, key=lambda item: item.created_at, reverse=True)[0]
    triage_nodes = []
    for edge in edges:
        if edge.to_node == entities_node.id and edge.type == "triaged_from":
            node = await store.get_node(edge.from_node)
            if node and node.type == "triage_decision":
                triage_nodes.append(node)
    if not triage_nodes:
        return None

    triage_node = sorted(triage_nodes, key=lambda item: item.created_at, reverse=True)[0]
    artifacts: dict[str, list[Node]] = {
        "daily_tasks": [],
        "ad_hoc_research_tasks": [],
        "appointment_candidates": [],
    }
    for edge in edges:
        if edge.to_node != triage_node.id or edge.type != "classified_as":
            continue
        node = await store.get_node(edge.from_node)
        if not node:
            continue
        if node.type == "daily_task":
            artifacts["daily_tasks"].append(node)
        elif node.type == "ad_hoc_research_task":
            artifacts["ad_hoc_research_tasks"].append(node)
        elif node.type == "appointment_candidate":
            artifacts["appointment_candidates"].append(node)

    return {
        "extracted_entities": entities_node.model_dump(mode="json"),
        "triage_decision": triage_node.model_dump(mode="json"),
        "daily_tasks": [node.model_dump(mode="json") for node in sorted(artifacts["daily_tasks"], key=lambda item: item.created_at)],
        "ad_hoc_research_tasks": [node.model_dump(mode="json") for node in sorted(artifacts["ad_hoc_research_tasks"], key=lambda item: item.created_at)],
        "appointment_candidates": [node.model_dump(mode="json") for node in sorted(artifacts["appointment_candidates"], key=lambda item: item.created_at)],
    }


def _extract_medications(text: str) -> list[ExtractedMedication]:
    medications = []
    lowered = text.lower()
    for name in MEDICATION_NAMES:
        if name not in lowered:
            continue
        display = _match_original_case(text, name)
        dose_match = re.search(rf"\b{re.escape(display)}\b\s+(\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|units?))", text, re.IGNORECASE)
        quantity_match = re.search(r"\b(one|two|three|1|2|3)\s+(tablet|tablets|pill|pills|capsule|capsules)\b", text, re.IGNORECASE)
        medication_quantity_match = re.search(rf"\b(one|two|three|1|2|3)\s+{re.escape(display)}\b", text, re.IGNORECASE)
        frequency = _frequency(text)
        timing = _timing_relation(text)
        medications.append(
            ExtractedMedication(
                name=display,
                dose=dose_match.group(1).replace(" ", "") if dose_match else None,
                quantity=" ".join(quantity_match.groups()) if quantity_match else f"{medication_quantity_match.group(1)} tablet" if medication_quantity_match else None,
                route="oral" if quantity_match or display.lower() in {"panadol", "paracetamol", "aspirin", "metformin", "levodopa"} else None,
                frequency=frequency,
                timing_relation=timing,
                fixed_time_required=bool(timing or frequency),
            )
        )
    return medications


def _extract_time_expressions(text: str, today: date) -> list[ExtractedTimeExpression]:
    expressions = []
    lowered = text.lower()
    if "tomorrow morning" in lowered:
        expressions.append(ExtractedTimeExpression(raw_text="tomorrow morning", normalized_date=(today + timedelta(days=1)).isoformat(), normalized_time_window="morning", confidence=0.9))
    elif "tomorrow" in lowered:
        expressions.append(ExtractedTimeExpression(raw_text="tomorrow", normalized_date=(today + timedelta(days=1)).isoformat(), confidence=0.85))
    for match in re.finditer(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b", text, re.IGNORECASE):
        normalized = _normalize_day_month(match.group(1), match.group(2), today)
        expressions.append(ExtractedTimeExpression(raw_text=match.group(0), normalized_date=normalized, confidence=0.8))
    for match in re.finditer(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", text, re.IGNORECASE):
        normalized = _normalize_month_day(match.group(1), match.group(2), match.group(3), today)
        expressions.append(ExtractedTimeExpression(raw_text=match.group(0), normalized_date=normalized, confidence=0.85 if match.group(3) else 0.8))
    for match in re.finditer(r"\b(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.IGNORECASE):
        expressions.append(ExtractedTimeExpression(raw_text=match.group(0), normalized_time_window=_normalize_time(match), confidence=0.85))
    return expressions


def _extract_recurrences(text: str, today: date) -> list[ExtractedRecurrence]:
    lowered = text.lower()
    recurrences = []
    if "daily" in lowered or "every day" in lowered:
        recurrences.append(ExtractedRecurrence(pattern="daily", start_date=today.isoformat()))
    if "three times a day" in lowered or "3 times a day" in lowered:
        recurrences.append(ExtractedRecurrence(pattern="three_times_daily", start_date=today.isoformat()))
    return recurrences


def _extract_appointments(text: str, today: date) -> list[ExtractedAppointment]:
    lowered = text.lower()
    if not any(cue in lowered for cue in APPOINTMENT_CUES):
        return []
    kind: AppointmentKind = "other"
    if "physio" in lowered:
        kind = "physio"
    elif "lab" in lowered:
        kind = "lab"
    elif "doctor" in lowered or "dr" in lowered:
        kind = "doctor"
    date_value = next((item.normalized_date for item in _extract_time_expressions(text, today) if item.normalized_date), None)
    time_value = next((item.normalized_time_window for item in _extract_time_expressions(text, today) if item.normalized_time_window and re.match(r"^\d{2}:\d{2}$", item.normalized_time_window)), None)
    return [ExtractedAppointment(kind=kind, date=date_value, time=time_value, requires_calendar_write=bool(date_value))]


def _extract_medical_context(text: str) -> ExtractedMedicalContext:
    lowered = text.lower()
    return ExtractedMedicalContext(
        conditions=[condition for condition in CONDITIONS if condition in lowered],
        body_parts=[part for part in BODY_PARTS if part in lowered],
        risks=[cue for cue in WARNING_CUES if cue in lowered],
        clinician_warnings=[cue for cue in WARNING_CUES if cue in lowered and ("doctor" in lowered or "clinician" in lowered)],
    )


def _extract_actionables(text: str, entities: ExtractedEntities) -> list[ExtractedActionable]:
    actionables = []
    if entities.medications or _looks_like_daily_task(text):
        description = _first_sentence(text)
        actionables.append(ExtractedActionable(description=description, bucket_hint="daily_task", urgency="clinical" if entities.medications else "routine", confidence=0.82))
    if entities.appointments:
        actionables.append(ExtractedActionable(description="Create pending appointment candidate", bucket_hint="appointment", urgency="routine", confidence=0.78))
    if _has_research_text(text):
        actionables.append(ExtractedActionable(description=_research_description(text), bucket_hint="ad_hoc_research", urgency="financial" if _financial_text(text) else "clinical", confidence=0.76))
    return actionables


def _has_research_basis(entities: ExtractedEntities) -> bool:
    text = " ".join(item.description for item in entities.actionables).lower()
    return _has_research_text(text) or bool(entities.medical_context.risks or entities.medical_context.clinician_warnings)


def _has_research_text(text: str) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in RESEARCH_CUES) and (
        any(cue in lowered for cue in WARNING_CUES) or _financial_text(lowered) or any(cue in lowered for cue in ("wheelchair", "equipment", "amputation", "amputate", "research", "find out", "look up"))
    )


def _looks_like_daily_task(text: str) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in ("daily", "every day", "before lunch", "before food", "remind", "give", "take")) and not _has_research_text(lowered)


def _financial_text(text: str) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in ("grant", "subsidy", "scheme", "financial assistance"))


async def _create_daily_task(
    store: GraphStore,
    patient_id: str,
    actionable: ExtractedActionable,
    entities: ExtractedEntities,
    triage_node: Node,
    entities_node: Node,
    placeholder_map: dict[str, str],
    reasoning_log_id,
) -> Node:
    description = rehydrate_placeholders(actionable.description, placeholder_map)
    medication = entities.medications[0] if entities.medications else None
    payload = {
        "patient_id": patient_id,
        "title": _daily_title(description, medication),
        "description": description,
        "original_instruction_redacted": actionable.description,
        "action_type": "medication" if medication else "task",
        "scheduling_semantics": "fixed_clinical" if medication else "movable_routine",
        "user_override": None,
        "medication": medication.model_dump(mode="json") if medication else None,
        "recurrence": entities.recurrences[0].pattern if entities.recurrences else None,
        "timing_relation": medication.timing_relation if medication else _timing_relation(actionable.description),
        "requires_user_review": bool(entities.clarifications_needed),
    }
    node = await store.create_node("daily_task", payload, "agent", reasoning_log_id=reasoning_log_id, status="pending_review")
    await store.create_edge(node.id, triage_node.id, "classified_as")
    await store.create_edge(node.id, entities_node.id, "scheduled_from")
    return node


async def _create_research_task(
    store: GraphStore,
    patient_id: str,
    actionable: ExtractedActionable,
    entities: ExtractedEntities,
    triage_node: Node,
    placeholder_map: dict[str, str],
    reasoning_log_id,
) -> Node:
    description = rehydrate_placeholders(actionable.description, placeholder_map)
    payload = {
        "patient_id": patient_id,
        "question": _research_question(description),
        "question_redacted": _research_question(actionable.description),
        "source_status": "pending_guardrail",
        "basis": description,
        "basis_redacted": actionable.description,
        "medical_context": entities.medical_context.model_dump(mode="json"),
        "requires_guardrail_review": True,
    }
    node = await store.create_node("ad_hoc_research_task", payload, "agent", reasoning_log_id=reasoning_log_id, status="pending_review")
    await store.create_edge(node.id, triage_node.id, "classified_as")
    return node


async def _create_appointment_candidate(
    store: GraphStore,
    patient_id: str,
    appointment: ExtractedAppointment,
    triage_node: Node,
    placeholder_map: dict[str, str],
    reasoning_log_id,
) -> Node:
    title = f"{appointment.kind.title()} appointment"
    payload = {
        "patient_id": patient_id,
        "title": rehydrate_placeholders(title, placeholder_map),
        "kind": appointment.kind,
        "date": appointment.date,
        "time": appointment.time,
        "location": appointment.location,
        "requires_calendar_write": appointment.requires_calendar_write,
        "calendar_write_status": "pending_user_approval" if appointment.requires_calendar_write else "not_required",
    }
    node = await store.create_node("appointment_candidate", payload, "agent", reasoning_log_id=reasoning_log_id, status="pending_review")
    await store.create_edge(node.id, triage_node.id, "classified_as")
    return node


def _placeholder_map(redaction: Node) -> dict[str, str]:
    value = redaction.payload.get("placeholder_map") or {}
    if not isinstance(value, dict):
        raise ValueError("pii_redaction node has malformed placeholder_map")
    return {str(key): str(raw) for key, raw in value.items()}


def _frequency(text: str) -> str | None:
    lowered = text.lower()
    if "three times a day" in lowered or "3 times a day" in lowered:
        return "three_times_daily"
    if "daily" in lowered or "every day" in lowered:
        return "daily"
    return None


def _timing_relation(text: str) -> str | None:
    lowered = text.lower()
    for meal in MEAL_TERMS:
        if f"before {meal}" in lowered:
            return f"before {meal}"
        if f"after {meal}" in lowered:
            return f"after {meal}"
    if "morning" in lowered:
        return "morning"
    return None


def _normalize_day_month(day: str, month: str, today: date) -> str:
    month_num = datetime.strptime(month[:3].title(), "%b").month
    candidate = date(today.year, month_num, int(day))
    if candidate < today:
        candidate = date(today.year + 1, month_num, int(day))
    return candidate.isoformat()


def _normalize_month_day(month: str, day: str, year: str | None, today: date) -> str:
    month_num = datetime.strptime(month[:3].title(), "%b").month
    candidate_year = int(year) if year else today.year
    candidate = date(candidate_year, month_num, int(day))
    if not year and candidate < today:
        candidate = date(today.year + 1, month_num, int(day))
    return candidate.isoformat()


def _normalize_time(match: re.Match[str]) -> str:
    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    meridiem = match.group(3).lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def _match_original_case(text: str, needle: str) -> str:
    match = re.search(rf"\b{re.escape(needle)}\b", text, re.IGNORECASE)
    return match.group(0) if match else needle


def _first_sentence(text: str) -> str:
    return re.split(r"[.!?]", text.strip(), maxsplit=1)[0].strip()


def _research_description(text: str) -> str:
    for sentence in re.split(r"[.!?]", text):
        if _has_research_text(sentence):
            return sentence.strip()
    return _first_sentence(text)


def _daily_title(description: str, medication: ExtractedMedication | None) -> str:
    if medication:
        timing = f" {medication.timing_relation}" if medication.timing_relation else ""
        return f"Give {medication.name}{timing}".strip()
    return description[:120]


def _research_question(description: str) -> str:
    if "?" in description:
        return description
    return f"What support, grants, equipment, or care steps should be checked for: {description}"
