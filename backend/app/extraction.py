from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import PATIENT_TZ, PATIENT_TZ_NAME, Settings
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
    year_inferred: bool = False  # true when year was rolled to next year due to past-date silently


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
    year_inferred: bool = False  # true when date's year was silently rolled
    requires_clarification: bool = False  # true when year_inferred or time missing


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


MEDICATION_ALIASES = {
    "panadol": ("panadol", "பனடோல்", "必理痛", "พานาดอล"),
    "paracetamol": ("paracetamol", "parasetamol", "பாராசிட்டமால்", "扑热息痛", "对乙酰氨基酚", "พาราเซตามอล", "พารา"),
    "insulin": ("insulin", "insulin", "இன்சுலின்", "胰岛素", "อินซูลิน"),
    "metformin": ("metformin", "மெட்ஃபார்மின்", "二甲双胍", "เมตฟอร์มิน"),
    "aspirin": ("aspirin", "ஆஸ்பிரின்", "阿司匹林", "แอสไพริน"),
    "levodopa": ("levodopa", "லெவோடோபா", "左旋多巴", "เลโวโดปา"),
}
MEDICATION_NAMES = tuple(MEDICATION_ALIASES)
MEAL_TERMS = ("breakfast", "lunch", "dinner", "food", "meal")
# Self-sufficient: these terms alone establish a clear care-resource need
RESEARCH_SELF_SUFFICIENT_CUES = (
    "wheelchair",
    "mobility aid",
    "home modification",
    "amputation",
    "amputate",
    "medical social worker",
    "grant",
    "subsidy",
    "scheme",
    "financial assistance",
)
# Trigger-only: these terms need a corroborating clinical warning to justify research
RESEARCH_TRIGGER_CUES = (
    "equipment",
    "research",
    "find out",
    "look up",
    "what support",
)
# Combined set for backward-compat use in audit_research_plan and corpus search
RESEARCH_CUES = (*RESEARCH_SELF_SUFFICIENT_CUES, *RESEARCH_TRIGGER_CUES)
WARNING_CUES = ("doctor said", "clinician said", "warned", "risk", "may need", "might need", "likely")
APPOINTMENT_CUES = ("appointment", "visit", "review", "see the doctor", "physio", "lab")
BODY_PARTS = ("knee", "leg", "foot", "ankle", "hand", "arm", "eye", "heart", "kidney")
CONDITIONS = ("diabetes", "high blood sugar", "parkinson", "dementia", "stroke", "hypertension")
NATIVE_DAILY_CUES = {
    "ms": ("setiap hari", "tiap hari", "tiap-tiap hari", "harian", "setiap pagi", "setiap malam"),
    "ta": ("தினமும்", "தினசரி", "ஒவ்வொரு நாளும்", "நாள் தோறும்", "dhinamum", "thinammum", "ovvoru naalum"),
    "zh": ("每天", "每日", "天天", "每早", "每晚", "mei tian", "meitian", "tian tian"),
    "th": ("ทุกวัน", "วันละ", "เป็นประจำ", "tuk wan", "thuk wan", "wan la"),
}
NATIVE_MEAL_TIMING = {
    "ms": {
        "sebelum sarapan": "before breakfast",
        "selepas sarapan": "after breakfast",
        "sebelum makan pagi": "before breakfast",
        "selepas makan pagi": "after breakfast",
        "sebelum makan tengah hari": "before lunch",
        "sebelum makan tengahari": "before lunch",
        "sebelum makan siang": "before lunch",
        "selepas makan tengah hari": "after lunch",
        "selepas makan tengahari": "after lunch",
        "selepas makan siang": "after lunch",
        "sebelum makan malam": "before dinner",
        "selepas makan malam": "after dinner",
        "sebelum makan": "before food",
        "selepas makan": "after food",
    },
    "ta": {
        "காலை உணவுக்கு முன்": "before breakfast",
        "காலை உணவுக்குப் பிறகு": "after breakfast",
        "காலை சாப்பாட்டுக்கு முன்": "before breakfast",
        "காலை சாப்பாட்டுக்குப் பிறகு": "after breakfast",
        "மதிய உணவுக்கு முன்": "before lunch",
        "மதிய உணவுக்குப் பிறகு": "after lunch",
        "மதிய சாப்பாட்டுக்கு முன்": "before lunch",
        "மதிய சாப்பாட்டுக்குப் பிறகு": "after lunch",
        "இரவு உணவுக்கு முன்": "before dinner",
        "இரவு உணவுக்குப் பிறகு": "after dinner",
        "சாப்பாட்டுக்கு முன்": "before food",
        "சாப்பாட்டுக்குப் பிறகு": "after food",
        "saapadu mun": "before food",
        "saapadu pin": "after food",
        "mathiya saapadu mun": "before lunch",
        "mathiya unavukku mun": "before lunch",
    },
    "zh": {
        "早餐前": "before breakfast",
        "早餐后": "after breakfast",
        "早饭前": "before breakfast",
        "早饭后": "after breakfast",
        "午餐前": "before lunch",
        "午餐后": "after lunch",
        "午饭前": "before lunch",
        "午饭后": "after lunch",
        "中饭前": "before lunch",
        "中饭后": "after lunch",
        "晚餐前": "before dinner",
        "晚餐后": "after dinner",
        "晚饭前": "before dinner",
        "晚饭后": "after dinner",
        "饭前": "before food",
        "饭后": "after food",
        "fan qian": "before food",
        "fan hou": "after food",
        "wu can qian": "before lunch",
        "wucan qian": "before lunch",
        "wu fan qian": "before lunch",
    },
    "th": {
        "ก่อนอาหารเช้า": "before breakfast",
        "หลังอาหารเช้า": "after breakfast",
        "ก่อนอาหารกลางวัน": "before lunch",
        "หลังอาหารกลางวัน": "after lunch",
        "ก่อนมื้อกลางวัน": "before lunch",
        "หลังมื้อกลางวัน": "after lunch",
        "ก่อนอาหารเย็น": "before dinner",
        "หลังอาหารเย็น": "after dinner",
        "ก่อนอาหารค่ำ": "before dinner",
        "หลังอาหารค่ำ": "after dinner",
        "ก่อนกินข้าว": "before food",
        "หลังกินข้าว": "after food",
        "gon ahan": "before food",
        "korn ahan": "before food",
        "lang ahan": "after food",
        "gon ahan glang wan": "before lunch",
        "korn ahan klang wan": "before lunch",
    },
}
NATIVE_APPOINTMENT_CUES = {
    "ms": ("temu janji", "temujanji", "jumpa doktor", "klinik", "hospital", "fisioterapi", "fisio", "rawatan"),
    "ta": ("மருத்துவர்", "மருத்துவமனை", "கிளினிக்", "சந்திப்பு", "நியமனம்", "பிசியோ", "maruthuvar", "doctor", "clinic", "physio"),
    "zh": ("预约", "复诊", "复查", "医生", "看医生", "诊所", "医院", "物理治疗", "理疗", "kan yi sheng", "yisheng", "fu zhen"),
    "th": ("นัด", "นัดหมอ", "พบแพทย์", "พบหมอ", "หมอ", "แพทย์", "คลินิก", "โรงพยาบาล", "กายภาพบำบัด", "กายภาพ", "แล็บ", "ตรวจเลือด", "nad mor", "phop mor", "clinic"),
}
NATIVE_RESEARCH_CUES = {
    "ms": ("subsidi", "geran", "skim", "bantuan", "bantuan kewangan", "dana", "kerusi roda", "sokongan"),
    "ta": ("மானியம்", "உதவி", "ஆதரவு", "சக்கர நாற்காலி", "நிதி", "நிதி உதவி", "உதவித்தொகை", "sakkara naarkali", "nidhi uthavi", "uthavi"),
    "zh": ("补助", "津贴", "资助", "政府补贴", "轮椅", "援助", "经济援助", "辅助器具", "bu zhu", "buzhu", "lun yi", "lunyi", "zi zhu"),
    "th": ("เงินอุดหนุน", "เงินช่วยเหลือ", "ทุน", "สวัสดิการ", "รถเข็น", "ความช่วยเหลือ", "การสนับสนุน", "rot khen", "rod khen", "ngoen chuai luea"),
}
NATIVE_WARNING_CUES = {
    "ms": ("doktor kata", "doktor cakap", "kata doktor", "mungkin perlu", "mungkin memerlukan", "risiko"),
    "ta": ("மருத்துவர் சொன்னார்", "மருத்துவர் கூறினார்", "தேவைப்படலாம்", "வேண்டியிருக்கும்", "ஆபத்து", "doctor sonnar", "maruthuvar sonnar", "thevai padalam"),
    "zh": ("医生说", "医生讲", "医生建议", "可能需要", "也许需要", "风险", "yi sheng shuo", "yisheng shuo", "ke neng xu yao"),
    "th": ("หมอบอก", "แพทย์บอก", "อาจต้อง", "อาจจำเป็น", "ความเสี่ยง", "เสี่ยง", "mor bok", "doctor bok", "aat tong"),
}


def extract_entities_from_redaction(redaction: Node, reference_date: date | None = None) -> ExtractedEntities:
    if redaction.type != "pii_redaction":
        raise ValueError("Can only extract entities from pii_redaction nodes")
    text = str(redaction.payload.get("redacted_text") or "")
    placeholder_map = _placeholder_map(redaction)
    today = reference_date or datetime.now(PATIENT_TZ).date()  # patient-day boundary, not utc
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
        time_expressions=_extract_native_time_expressions(text, language, today),
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

    lock_key = f"extract:{redaction.id}"  # idempotency for concurrent reprocess
    if not await store.acquire_system_lock(lock_key, ttl_seconds=180):
        for _ in range(60):  # poll ~120s for in-flight peer
            await asyncio.sleep(2)
            existing = await _existing_processed_result(store, redaction)
            if existing:
                return existing
        raise RuntimeError(f"timed out waiting for in-flight extraction of redaction {redaction.id}")

    existing = await _existing_processed_result(store, redaction)  # double-check under lock
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
    for canonical, alias in _matched_medication_aliases(text):
        if canonical not in MEDICATION_NAMES:
            continue
        display = _match_original_case(text, alias) if alias.isascii() else alias
        dose_match = _dose_after_alias(text, alias)
        quantity_match = re.search(r"\b(one|two|three|1|2|3)\s+(tablet|tablets|pill|pills|capsule|capsules)\b", text, re.IGNORECASE)
        medication_quantity_match = re.search(rf"\b(one|two|three|1|2|3)\s+{re.escape(alias)}\b", text, re.IGNORECASE)
        frequency = _frequency(text)
        timing = _timing_relation(text)
        medications.append(
            ExtractedMedication(
                name=_canonical_medication_display(canonical, display),
                dose=_normalize_dose(dose_match.group(1)) if dose_match else None,
                quantity=" ".join(quantity_match.groups()) if quantity_match else f"{medication_quantity_match.group(1)} tablet" if medication_quantity_match else None,
                route="oral" if quantity_match or canonical in {"panadol", "paracetamol", "aspirin", "metformin", "levodopa"} else None,
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
        normalized, year_inferred = _normalize_day_month(match.group(1), match.group(2), today)
        expressions.append(ExtractedTimeExpression(raw_text=match.group(0), normalized_date=normalized, confidence=0.5 if year_inferred else 0.8, year_inferred=year_inferred))
    for match in re.finditer(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", text, re.IGNORECASE):
        normalized, year_inferred = _normalize_month_day(match.group(1), match.group(2), match.group(3), today)
        expressions.append(ExtractedTimeExpression(raw_text=match.group(0), normalized_date=normalized, confidence=0.5 if year_inferred else (0.85 if match.group(3) else 0.8), year_inferred=year_inferred))
    for match in re.finditer(r"\b(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.IGNORECASE):
        expressions.append(ExtractedTimeExpression(raw_text=match.group(0), normalized_time_window=_normalize_time(match), confidence=0.85))
    return expressions


def _matched_medication_aliases(text: str) -> list[tuple[str, str]]:
    lowered = text.lower()
    matches: list[tuple[str, str]] = []
    for canonical, aliases in MEDICATION_ALIASES.items():
        for alias in aliases:
            if _alias_in_text(alias, lowered, text):
                matches.append((canonical, alias))
                break
    return matches


def _alias_in_text(alias: str, lowered_text: str, raw_text: str) -> bool:
    if alias.isascii():
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(alias.lower())}(?![A-Za-z0-9])", lowered_text))
    return alias in raw_text


def _dose_after_alias(text: str, alias: str) -> re.Match[str] | None:
    units = r"(?:mg|mcg|g|ml|units?|மி\.?கி\.?|毫克|มก\.?)"
    return re.search(rf"{re.escape(alias)}\s+(\d+(?:\.\d+)?\s*{units})", text, re.IGNORECASE)


def _normalize_dose(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("மி.கி.", "mg").replace("மிகி", "mg").replace("毫克", "mg").replace("มก.", "mg")


def _canonical_medication_display(canonical: str, display: str) -> str:
    return "Panadol" if canonical == "panadol" else canonical.title()


def _native_quantity(text: str, language: str) -> str | None:
    haystack = text.lower() if language == "ms" else text
    quantity_patterns = {
        "ms": ((r"\b(satu|1)\s+(biji|tablet|pil)\b", "one tablet"), (r"\b(dua|2)\s+(biji|tablet|pil)\b", "two tablets")),
        "ta": ((r"(ஒரு|1|oru|onnu)\s*(மாத்திரை|tablet)", "one tablet"), (r"(இரண்டு|2|irandu|rendu)\s*(மாத்திரை|tablet)", "two tablets")),
        "zh": ((r"(一|1|yi)\s*(片|粒|tablet|pian)", "one tablet"), (r"(两|二|2|liang|er)\s*(片|粒|tablet|pian)", "two tablets")),
        "th": ((r"(หนึ่ง|1|neung|nueng)\s*(เม็ด|tablet)", "one tablet"), (r"(สอง|2|song)\s*(เม็ด|tablet)", "two tablets")),
    }
    for pattern, normalized in quantity_patterns.get(language, ()):
        if re.search(pattern, haystack, re.IGNORECASE):
            return normalized
    return None


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
    expressions = _extract_time_expressions(text, today)
    date_expr = next((item for item in expressions if item.normalized_date), None)
    date_value = date_expr.normalized_date if date_expr else None
    year_inferred = bool(date_expr and date_expr.year_inferred)
    time_value = next((item.normalized_time_window for item in expressions if item.normalized_time_window and re.match(r"^\d{2}:\d{2}$", item.normalized_time_window)), None)
    needs_clarification = year_inferred or (bool(date_value) and not time_value)
    return [ExtractedAppointment(
        kind=kind,
        date=date_value,
        time=time_value,
        requires_calendar_write=bool(date_value) and not year_inferred and bool(time_value),
        year_inferred=year_inferred,
        requires_clarification=needs_clarification,
    )]


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
    if entities.medical_context.risks or entities.medical_context.clinician_warnings:
        return True
    transcript_excerpt = " ".join(item.description for item in entities.actionables)
    return _has_research_text(transcript_excerpt)


def _has_research_text(text: str) -> bool:
    lowered = text.lower()
    # Self-sufficient cues establish a care-resource need on their own
    if any(cue in lowered for cue in RESEARCH_SELF_SUFFICIENT_CUES):
        return True
    # Trigger-only cues need a clinical warning or financial signal to justify research
    if any(cue in lowered for cue in RESEARCH_TRIGGER_CUES):
        return any(cue in lowered for cue in WARNING_CUES) or _financial_text(lowered)
    return False


def _looks_like_daily_task(text: str) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in ("daily", "every day", "before lunch", "before food", "remind", "give", "take")) and not _has_research_text(lowered)


def _financial_text(text: str) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in ("grant", "subsidy", "scheme", "financial assistance"))


def _extract_native_medications(text: str, language: str) -> list[ExtractedMedication]:
    medications = []
    timing = _native_timing_relation(text, language)
    frequency = _native_frequency(text, language)
    for canonical, alias in _matched_medication_aliases(text):
        display = _match_original_case(text, alias) if alias.isascii() else alias
        dose_match = _dose_after_alias(text, alias)
        medications.append(
            ExtractedMedication(
                name=_canonical_medication_display(canonical, display),
                dose=_normalize_dose(dose_match.group(1)) if dose_match else None,
                quantity=_native_quantity(text, language),
                route="oral" if canonical in {"panadol", "paracetamol", "aspirin", "metformin", "levodopa"} else None,
                frequency=frequency,
                timing_relation=timing,
                fixed_time_required=bool(timing or frequency),
            )
        )
    return medications


def _extract_native_time_expressions(text: str, language: str, today: date) -> list[ExtractedTimeExpression]:
    expressions = _extract_time_expressions(text, today)
    tomorrow_cue = _native_tomorrow_cue(text, language)
    if tomorrow_cue:
        expressions.append(ExtractedTimeExpression(raw_text=tomorrow_cue, normalized_date=(today + timedelta(days=1)).isoformat(), confidence=0.85))
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
        year_inferred = False
        if not match.group(3) and candidate < today:
            candidate = _safe_date(today.year + 1, month, day)
            if not candidate:
                continue
            year_inferred = True
        expressions.append(ExtractedTimeExpression(raw_text=match.group(0), normalized_date=candidate.isoformat(), confidence=0.5 if year_inferred else 0.85, year_inferred=year_inferred))
    for match in re.finditer(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", text):
        candidate = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if candidate:
            expressions.append(ExtractedTimeExpression(raw_text=match.group(0), normalized_date=candidate.isoformat(), confidence=0.95))
    for raw_text, normalized_time in _native_time_windows(text, language):
        expressions.append(ExtractedTimeExpression(raw_text=raw_text, normalized_time_window=normalized_time, confidence=0.85))
    return expressions


def _native_tomorrow_cue(text: str, language: str) -> str | None:
    haystack = text.lower() if language == "ms" else text
    for cue in {
        "ms": ("esok",),
        "ta": ("நாளை", "naalai", "nalai"),
        "zh": ("明天", "ming tian", "mingtian"),
        "th": ("พรุ่งนี้", "phrung ni", "prung ni"),
    }.get(language, ()):
        check = cue if language == "ms" else cue.lower() if cue.isascii() else cue
        target = haystack if language == "ms" else text.lower() if cue.isascii() else text
        if check in target:
            return cue
    return None


def _native_time_windows(text: str, language: str) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    if language == "ms":
        for match in re.finditer(r"\b(?:pukul|jam)\s*(\d{1,2})(?::(\d{2}))?\s*(pagi|tengah hari|petang|malam)?\b", text, re.IGNORECASE):
            normalized = _native_clock_time(match.group(1), match.group(2), match.group(3))
            if normalized:
                matches.append((match.group(0), normalized))
    elif language == "ta":
        for match in re.finditer(r"(காலை|மதியம்|மாலை|இரவு)?\s*(\d{1,2})(?::(\d{2}))?\s*மணி", text):
            normalized = _native_clock_time(match.group(2), match.group(3), match.group(1))
            if normalized:
                matches.append((match.group(0), normalized))
        for match in re.finditer(r"\b(kaalai|madhiyam|maalai|iravu)?\s*(\d{1,2})(?::(\d{2}))?\s*mani\b", text, re.IGNORECASE):
            normalized = _native_clock_time(match.group(2), match.group(3), match.group(1))
            if normalized:
                matches.append((match.group(0), normalized))
    elif language == "zh":
        for match in re.finditer(r"(上午|早上|下午|晚上|傍晚)?\s*(\d{1,2})(?:点|點)(半|:(\d{2}))?", text):
            minute = "30" if match.group(3) == "半" else match.group(4)
            normalized = _native_clock_time(match.group(2), minute, match.group(1))
            if normalized:
                matches.append((match.group(0), normalized))
        for match in re.finditer(r"\b(shang wu|xia wu|wan shang)?\s*(\d{1,2})(?::(\d{2}))?\s*dian\b", text, re.IGNORECASE):
            normalized = _native_clock_time(match.group(2), match.group(3), match.group(1))
            if normalized:
                matches.append((match.group(0), normalized))
    elif language == "th":
        for match in re.finditer(r"(?:เวลา\s*)?(\d{1,2})(?::(\d{2}))?\s*(น\.|โมงเช้า|โมง|ทุ่ม|บ่าย|เย็น)", text):
            normalized = _native_clock_time(match.group(1), match.group(2), match.group(3))
            if normalized:
                matches.append((match.group(0), normalized))
        for match in re.finditer(r"\bwela\s*(\d{1,2})(?::(\d{2}))?\b", text, re.IGNORECASE):
            normalized = _native_clock_time(match.group(1), match.group(2), None)
            if normalized:
                matches.append((match.group(0), normalized))
        for match in re.finditer(r"\b(\d{1,2})(?::(\d{2}))?\s*(mong chao|bai|yen|thum)\b", text, re.IGNORECASE):
            normalized = _native_clock_time(match.group(1), match.group(2), match.group(3))
            if normalized:
                matches.append((match.group(0), normalized))
    return list(dict.fromkeys(matches))


def _native_clock_time(hour_value: str, minute_value: str | None, period: str | None) -> str | None:
    hour = int(hour_value)
    minute = int(minute_value or "0")
    if not 0 <= hour <= 23 or minute > 59:
        return None
    period_text = str(period or "").lower()
    afternoon_cues = ("petang", "malam", "tengah hari", "மதியம்", "மாலை", "இரவு", "madhiyam", "maalai", "iravu", "下午", "晚上", "傍晚", "xia wu", "wan shang", "ทุ่ม", "บ่าย", "เย็น", "bai", "yen", "thum")
    morning_cues = ("pagi", "காலை", "kaalai", "上午", "早上", "shang wu", "โมงเช้า", "mong chao")
    if any(cue in period_text for cue in afternoon_cues) and hour < 12:
        hour += 12
    if any(cue in period_text for cue in morning_cues) and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


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
    elif any(cue in haystack for cue in ("doktor", "மருத்துவர்", "maruthuvar", "doctor", "医生", "kan yi sheng", "yisheng", "yi sheng", "หมอ", "แพทย์", "mor")):
        kind = "doctor"
    date_expr = next((item for item in time_expressions if item.normalized_date), None)
    date_value = date_expr.normalized_date if date_expr else None
    year_inferred = bool(date_expr and date_expr.year_inferred)
    time_value = next((item.normalized_time_window for item in time_expressions if item.normalized_time_window and re.match(r"^\d{2}:\d{2}$", item.normalized_time_window)), None)
    needs_clarification = year_inferred or (bool(date_value) and not time_value)
    return [ExtractedAppointment(
        kind=kind,
        date=date_value,
        time=time_value,
        requires_calendar_write=bool(date_value) and not year_inferred and bool(time_value),
        year_inferred=year_inferred,
        requires_clarification=needs_clarification,
    )]


def _extract_native_medical_context(text: str, language: str) -> ExtractedMedicalContext:
    haystack = text.lower() if language == "ms" else text
    risks = [cue for cue in NATIVE_WARNING_CUES.get(language, ()) if cue in haystack]
    return ExtractedMedicalContext(
        conditions=[condition for condition in CONDITIONS if condition in haystack],
        risks=risks,
        clinician_warnings=risks if any(cue in haystack for cue in ("doktor", "மருத்துவர்", "医生", "หมอ", "แพทย์")) else [],
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
    for phrase, canonical in sorted(NATIVE_MEAL_TIMING.get(language, {}).items(), key=lambda item: len(item[0]), reverse=True):
        check = phrase if language == "ms" else phrase.lower() if phrase.isascii() else phrase
        target = haystack if language == "ms" else text.lower() if phrase.isascii() else text
        if check in target:
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
        "timezone": PATIENT_TZ_NAME,  # explicit task tz; caregiver travel safety
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
    if appointment.requires_calendar_write:
        calendar_write_status = "pending_user_approval"
    elif appointment.requires_clarification:
        calendar_write_status = "needs_clarification"
    else:
        calendar_write_status = "not_required"
    clarification_reasons: list[str] = []
    if appointment.year_inferred:
        clarification_reasons.append("year_silently_rolled")
    if appointment.date and not appointment.time:
        clarification_reasons.append("time_missing")
    payload = {
        "patient_id": patient_id,
        "title": rehydrate_placeholders(title, placeholder_map),
        "kind": appointment.kind,
        "date": appointment.date,
        "time": appointment.time,
        "location": appointment.location,
        "requires_calendar_write": appointment.requires_calendar_write,
        "year_inferred": appointment.year_inferred,
        "requires_clarification": appointment.requires_clarification,
        "clarification_reasons": clarification_reasons,
        "calendar_write_status": calendar_write_status,
    }
    node_status = "clarification_required" if appointment.requires_clarification else "pending_review"
    node = await store.create_node("appointment_candidate", payload, "agent", reasoning_log_id=reasoning_log_id, status=node_status)
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


def _normalize_day_month(day: str, month: str, today: date) -> tuple[str | None, bool]:
    month_num = datetime.strptime(month[:3].title(), "%b").month
    candidate = _safe_date(today.year, month_num, int(day))
    if not candidate:
        return None, False
    inferred = False
    if candidate < today:
        candidate = _safe_date(today.year + 1, month_num, int(day))
        if not candidate:
            return None, False
        inferred = True
    return candidate.isoformat(), inferred


def _normalize_month_day(month: str, day: str, year: str | None, today: date) -> tuple[str | None, bool]:
    month_num = datetime.strptime(month[:3].title(), "%b").month
    candidate_year = int(year) if year else today.year
    candidate = _safe_date(candidate_year, month_num, int(day))
    if not candidate:
        return None, False
    inferred = False
    if not year and candidate < today:
        candidate = _safe_date(today.year + 1, month_num, int(day))
        if not candidate:
            return None, False
        inferred = True
    return candidate.isoformat(), inferred


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
