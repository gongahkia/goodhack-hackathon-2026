from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import Settings
from .models import Node
from .privacy import rehydrate_placeholders
from .sealion_reviews import maybe_localize_artifacts_with_sealion, maybe_review_extraction_with_sealion
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
NATIVE_DAILY_CUES = {
    "ms": ("setiap hari", "tiap hari", "harian"),
    "ta": ("தினமும்", "ஒவ்வொரு நாளும்"),
    "zh": ("每天", "每日"),
    "th": ("ทุกวัน",),
}
NATIVE_MEAL_TIMING = {
    "ms": {
        "sebelum sarapan": "before breakfast",
        "selepas sarapan": "after breakfast",
        "sebelum makan tengah hari": "before lunch",
        "selepas makan tengah hari": "after lunch",
        "sebelum makan malam": "before dinner",
        "selepas makan malam": "after dinner",
    },
    "ta": {
        "காலை உணவுக்கு முன்": "before breakfast",
        "காலை உணவுக்குப் பிறகு": "after breakfast",
        "மதிய உணவுக்கு முன்": "before lunch",
        "மதிய உணவுக்குப் பிறகு": "after lunch",
        "இரவு உணவுக்கு முன்": "before dinner",
        "இரவு உணவுக்குப் பிறகு": "after dinner",
    },
    "zh": {
        "早餐前": "before breakfast",
        "早餐后": "after breakfast",
        "午餐前": "before lunch",
        "午餐后": "after lunch",
        "晚餐前": "before dinner",
        "晚餐后": "after dinner",
    },
    "th": {
        "ก่อนอาหารเช้า": "before breakfast",
        "หลังอาหารเช้า": "after breakfast",
        "ก่อนอาหารกลางวัน": "before lunch",
        "หลังอาหารกลางวัน": "after lunch",
        "ก่อนอาหารเย็น": "before dinner",
        "หลังอาหารเย็น": "after dinner",
        "ก่อนอาหารค่ำ": "before dinner",
        "หลังอาหารค่ำ": "after dinner",
    },
}
NATIVE_APPOINTMENT_CUES = {
    "ms": ("temu janji", "jumpa doktor", "klinik", "fisioterapi", "fisio"),
    "ta": ("மருத்துவர்", "கிளினிக்", "சந்திப்பு", "பிசியோ"),
    "zh": ("预约", "复诊", "医生", "诊所", "物理治疗"),
    "th": ("นัด", "พบแพทย์", "หมอ", "คลินิก", "กายภาพบำบัด", "แล็บ"),
}
NATIVE_RESEARCH_CUES = {
    "ms": ("subsidi", "geran", "bantuan kewangan", "kerusi roda", "sokongan"),
    "ta": ("மானியம்", "உதவி", "சக்கர நாற்காலி", "நிதி உதவி"),
    "zh": ("补助", "津贴", "资助", "轮椅", "援助"),
    "th": ("เงินอุดหนุน", "เงินช่วยเหลือ", "ทุน", "รถเข็น", "ความช่วยเหลือ"),
}
NATIVE_WARNING_CUES = {
    "ms": ("doktor kata", "mungkin perlu", "risiko"),
    "ta": ("மருத்துவர் சொன்னார்", "தேவைப்படலாம்", "ஆபத்து"),
    "zh": ("医生说", "可能需要", "风险"),
    "th": ("หมอบอก", "อาจต้อง", "ความเสี่ยง"),
}


def extract_entities_from_redaction(redaction: Node, reference_date: date | None = None) -> ExtractedEntities:
    if redaction.type != "pii_redaction":
        raise ValueError("Can only extract entities from pii_redaction nodes")
    text = str(redaction.payload.get("redacted_text") or "")
    placeholder_map = _placeholder_map(redaction)
    today = reference_date or datetime.now(UTC).date()
    language = str(redaction.payload.get("detected_language") or redaction.payload.get("requested_language") or redaction.payload.get("original_language") or "")

    entities = _extract_entities_from_text(text, placeholder_map, today)
    original_text = str(redaction.payload.get("original_redacted_text") or "").strip()
    native_text = original_text or text
    if native_text and language in NATIVE_DAILY_CUES:
        entities = _merge_entities(entities, _extract_native_entities(native_text, language, placeholder_map, today))
    if not entities.actionables:
        entities.clarifications_needed.append("No clear actionable care instruction was found.")
    return entities


def _extract_entities_from_text(text: str, placeholder_map: dict[str, str], today: date) -> ExtractedEntities:
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
    return entities


def _extract_native_entities(text: str, language: str, placeholder_map: dict[str, str], today: date) -> ExtractedEntities:
    entities = ExtractedEntities(
        people=[
            ExtractedPerson(placeholder_id=placeholder, display_name_redacted=placeholder)
            for placeholder in sorted(placeholder_map)
            if placeholder.startswith(("PERSON_", "PATIENT_", "CAREGIVER_"))
        ],
        medications=_extract_native_medications(text, language),
        time_expressions=_extract_native_time_expressions(text, today),
        recurrences=_extract_native_recurrences(text, language, today),
        appointments=[],
        actionables=[],
        medical_context=_extract_native_medical_context(text, language),
        clarifications_needed=[],
    )
    entities.appointments = _extract_native_appointments(text, language, today, entities.time_expressions)
    entities.actionables = _extract_native_actionables(text, language, entities)
    return entities


def _merge_entities(primary: ExtractedEntities, native: ExtractedEntities) -> ExtractedEntities:
    by_bucket = {item.bucket_hint for item in primary.actionables}
    return ExtractedEntities(
        people=_unique_models([*primary.people, *native.people], lambda item: item.placeholder_id),
        medications=_merge_medications(primary.medications, native.medications),
        time_expressions=_unique_models(
            [*primary.time_expressions, *native.time_expressions],
            lambda item: f"{item.raw_text}|{item.normalized_date}|{item.normalized_time_window}",
        ),
        recurrences=_unique_models([*primary.recurrences, *native.recurrences], lambda item: f"{item.pattern}|{item.start_date}"),
        appointments=_unique_models([*primary.appointments, *native.appointments], lambda item: f"{item.kind}|{item.date}|{item.time}"),
        actionables=[*primary.actionables, *[item for item in native.actionables if item.bucket_hint not in by_bucket]],
        medical_context=ExtractedMedicalContext(
            conditions=sorted(set(primary.medical_context.conditions + native.medical_context.conditions)),
            body_parts=sorted(set(primary.medical_context.body_parts + native.medical_context.body_parts)),
            risks=sorted(set(primary.medical_context.risks + native.medical_context.risks)),
            clinician_warnings=sorted(set(primary.medical_context.clinician_warnings + native.medical_context.clinician_warnings)),
        ),
        clarifications_needed=list(dict.fromkeys(primary.clarifications_needed + native.clarifications_needed)),
    )


def _merge_medications(primary: list[ExtractedMedication], native: list[ExtractedMedication]) -> list[ExtractedMedication]:
    by_name = {item.name.lower(): item for item in primary}
    for item in native:
        key = item.name.lower()
        existing = by_name.get(key)
        if not existing:
            by_name[key] = item
            continue
        by_name[key] = existing.model_copy(
            update={
                "dose": existing.dose or item.dose,
                "quantity": existing.quantity or item.quantity,
                "route": existing.route or item.route,
                "frequency": existing.frequency or item.frequency,
                "timing_relation": existing.timing_relation or item.timing_relation,
                "fixed_time_required": existing.fixed_time_required or item.fixed_time_required,
                "safety_notes": list(dict.fromkeys(existing.safety_notes + item.safety_notes)),
            }
        )
    return list(by_name.values())


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
    settings: Settings | None = None,
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

    extraction_review = await maybe_review_extraction_with_sealion(
        store,
        redaction,
        entities_node,
        triage_node,
        daily_tasks,
        research_tasks,
        appointments,
        settings,
    )
    localization_review = await maybe_localize_artifacts_with_sealion(
        store,
        redaction,
        daily_tasks,
        research_tasks,
        appointments,
        settings,
    )
    daily_tasks = await _refresh_nodes(store, daily_tasks)
    research_tasks = await _refresh_nodes(store, research_tasks)
    appointments = await _refresh_nodes(store, appointments)

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
                "sealion_extraction_review_id": str(extraction_review.id) if extraction_review else None,
                "sealion_localization_review_id": str(localization_review.id) if localization_review else None,
            },
        )

    return {
        "extracted_entities": entities_node.model_dump(mode="json"),
        "triage_decision": triage_node.model_dump(mode="json"),
        "daily_tasks": [node.model_dump(mode="json") for node in daily_tasks],
        "ad_hoc_research_tasks": [node.model_dump(mode="json") for node in research_tasks],
        "appointment_candidates": [node.model_dump(mode="json") for node in appointments],
        "transcript_reviews": [
            node.model_dump(mode="json")
            for node in (extraction_review, localization_review)
            if node is not None
        ],
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
        "transcript_reviews": [],
    }


async def _refresh_nodes(store: GraphStore, nodes: list[Node]) -> list[Node]:
    refreshed = []
    for node in nodes:
        latest = await store.get_node(node.id)
        refreshed.append(latest or node)
    return refreshed


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


def _extract_native_medications(text: str, language: str) -> list[ExtractedMedication]:
    medications = []
    lowered = text.lower()
    timing = _native_timing_relation(text, language)
    frequency = _native_frequency(text, language)
    for name in MEDICATION_NAMES:
        if name not in lowered:
            continue
        display = _match_original_case(text, name)
        dose_match = re.search(rf"\b{re.escape(display)}\b\s+(\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|units?))", text, re.IGNORECASE)
        medications.append(
            ExtractedMedication(
                name=display,
                dose=dose_match.group(1).replace(" ", "") if dose_match else None,
                route="oral" if display.lower() in {"panadol", "paracetamol", "aspirin", "metformin", "levodopa"} else None,
                frequency=frequency,
                timing_relation=timing,
                fixed_time_required=bool(timing or frequency),
            )
        )
    return medications


def _extract_native_time_expressions(text: str, today: date) -> list[ExtractedTimeExpression]:
    expressions = _extract_time_expressions(text, today)
    for match in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        candidate = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if candidate:
            expressions.append(ExtractedTimeExpression(raw_text=match.group(0), normalized_date=candidate.isoformat(), confidence=0.95))
    for match in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text):
        day, month, year = map(int, match.groups())
        candidate = _safe_date(year, month, day)
        if candidate:
            expressions.append(ExtractedTimeExpression(raw_text=match.group(0), normalized_date=candidate.isoformat(), confidence=0.9))
    for match in re.finditer(r"(\d{1,2})月(\d{1,2})日(?:\s*(\d{4})年)?", text):
        month = int(match.group(1))
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        candidate = _safe_date(year, month, day)
        if not candidate:
            continue
        if not match.group(3) and candidate < today:
            candidate = _safe_date(today.year + 1, month, day)
            if not candidate:
                continue
        expressions.append(ExtractedTimeExpression(raw_text=match.group(0), normalized_date=candidate.isoformat(), confidence=0.85))
    return expressions


def _extract_native_recurrences(text: str, language: str, today: date) -> list[ExtractedRecurrence]:
    recurrences = _extract_recurrences(text, today)
    haystack = text.lower() if language == "ms" else text
    if any(cue in haystack for cue in NATIVE_DAILY_CUES.get(language, ())):
        recurrences.append(ExtractedRecurrence(pattern="daily", start_date=today.isoformat()))
    return _unique_models(recurrences, lambda item: f"{item.pattern}|{item.start_date}")


def _extract_native_appointments(
    text: str,
    language: str,
    today: date,
    time_expressions: list[ExtractedTimeExpression],
) -> list[ExtractedAppointment]:
    haystack = text.lower() if language == "ms" else text
    if not any(cue in haystack for cue in NATIVE_APPOINTMENT_CUES.get(language, ())):
        return []
    kind: AppointmentKind = "other"
    if any(cue in haystack for cue in ("fisioterapi", "fisio", "பிசியோ", "物理治疗", "กายภาพ")):
        kind = "physio"
    elif any(cue in haystack for cue in ("lab", "makmal", "化验", "แล็บ", "ตรวจเลือด")):
        kind = "lab"
    elif any(cue in haystack for cue in ("doktor", "மருத்துவர்", "医生", "หมอ", "แพทย์")):
        kind = "doctor"
    date_value = next((item.normalized_date for item in time_expressions if item.normalized_date), None)
    time_value = next((item.normalized_time_window for item in time_expressions if item.normalized_time_window and re.match(r"^\d{2}:\d{2}$", item.normalized_time_window)), None)
    return [ExtractedAppointment(kind=kind, date=date_value, time=time_value, requires_calendar_write=bool(date_value))]


def _extract_native_medical_context(text: str, language: str) -> ExtractedMedicalContext:
    haystack = text.lower() if language == "ms" else text
    risks = [cue for cue in NATIVE_WARNING_CUES.get(language, ()) if cue in haystack]
    return ExtractedMedicalContext(
        conditions=[condition for condition in CONDITIONS if condition in haystack],
        risks=risks,
        clinician_warnings=risks if any(cue in haystack for cue in ("doktor", "மருத்துவர்", "医生")) else [],
    )


def _extract_native_actionables(text: str, language: str, entities: ExtractedEntities) -> list[ExtractedActionable]:
    haystack = text.lower() if language == "ms" else text
    actionables = []
    if entities.medications or _native_frequency(text, language):
        actionables.append(ExtractedActionable(description=_first_sentence(text), bucket_hint="daily_task", urgency="clinical" if entities.medications else "routine", confidence=0.78))
    if entities.appointments:
        actionables.append(ExtractedActionable(description="Create pending appointment candidate", bucket_hint="appointment", urgency="routine", confidence=0.74))
    if any(cue in haystack for cue in NATIVE_RESEARCH_CUES.get(language, ())) and (
        entities.medical_context.risks or any(cue in haystack for cue in ("kerusi roda", "சக்கர நாற்காலி", "轮椅", "รถเข็น"))
    ):
        actionables.append(ExtractedActionable(description=_native_research_description(text, language), bucket_hint="ad_hoc_research", urgency="financial", confidence=0.72))
    return actionables


def _native_frequency(text: str, language: str) -> str | None:
    haystack = text.lower() if language == "ms" else text
    if any(cue in haystack for cue in NATIVE_DAILY_CUES.get(language, ())):
        return "daily"
    return None


def _native_timing_relation(text: str, language: str) -> str | None:
    haystack = text.lower() if language == "ms" else text
    for phrase, canonical in NATIVE_MEAL_TIMING.get(language, {}).items():
        if phrase in haystack:
            return canonical
    return None


def _native_research_description(text: str, language: str) -> str:
    haystack = text.lower() if language == "ms" else text
    for sentence in re.split(r"[.!?。！？]", text):
        check = sentence.lower() if language == "ms" else sentence
        if any(cue in check for cue in NATIVE_RESEARCH_CUES.get(language, ())) or any(cue in check for cue in NATIVE_WARNING_CUES.get(language, ())):
            return sentence.strip()
    return _first_sentence(text)


def _unique_models(items: list[Any], key_fn) -> list[Any]:
    seen = set()
    unique = []
    for item in items:
        key = key_fn(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


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


def _normalize_day_month(day: str, month: str, today: date) -> str | None:
    month_num = datetime.strptime(month[:3].title(), "%b").month
    candidate = _safe_date(today.year, month_num, int(day))
    if not candidate:
        return None
    if candidate < today:
        candidate = _safe_date(today.year + 1, month_num, int(day))
        if not candidate:
            return None
    return candidate.isoformat()


def _normalize_month_day(month: str, day: str, year: str | None, today: date) -> str | None:
    month_num = datetime.strptime(month[:3].title(), "%b").month
    candidate_year = int(year) if year else today.year
    candidate = _safe_date(candidate_year, month_num, int(day))
    if not candidate:
        return None
    if not year and candidate < today:
        candidate = _safe_date(today.year + 1, month_num, int(day))
        if not candidate:
            return None
    return candidate.isoformat()


def _normalize_time(match: re.Match[str]) -> str | None:
    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    if not 1 <= hour <= 12 or minute > 59:
        return None
    meridiem = match.group(3).lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _match_original_case(text: str, needle: str) -> str:
    match = re.search(rf"\b{re.escape(needle)}\b", text, re.IGNORECASE)
    return match.group(0) if match else needle


def _first_sentence(text: str) -> str:
    return re.split(r"[.!?。！？]", text.strip(), maxsplit=1)[0].strip()


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
