from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .agent.loop import run_agent_for_trigger
from .approvals import approve_appointment_calendar_write, update_daily_task
from .compliance import (
    ConsentRecordCreate,
    DataSubjectRequestCreate,
    PrivacyIncidentCreate,
    create_data_subject_request,
    create_privacy_incident,
    purge_expired_sensitive_data,
    record_consent,
    record_processing_activity,
)
from .config import get_settings
from .demo import PATIENT, PATIENT_ID, ingest_trigger_records, seed_baseline
from .eval import evaluate_care_plan
from .extraction import process_redacted_transcript
from .graph_queries import backtrace_sources, forward_actions
from .identity import ensure_patient_identity, known_people_for_redaction, learn_alias_candidates_from_transcript, upsert_patient_alias
from .learning import build_learning_context, create_model_evaluation, create_prompt_candidate, list_model_evaluations, list_prompt_candidates
from .models import CaregiverNoteCreate, ClarificationUpdate, HumanEvaluationCreate, IdentityAliasCreate, ModelEvaluationCreate, Node, NodeEdit, PromptCandidateCreate, StatusUpdate
from .notifications import build_notifications
from .privacy import PiiRedactor, sanitize_audit_payload
from .research import run_guarded_research_pipeline
from .scheduler import run_next_day_schedule_check
from .security import InMemoryRateLimiter, key_matches, rate_limit_key, require_pilot_security, sanitize_public
from .transcript_pipeline import ingest_audio_transcription, redact_stored_transcript
from .store import GraphStore, MemoryGraphStore, PostgresGraphStore
from .transcription import TranscriptionError, TranscriptionInputError, normalize_transcription_language, transcribe_audio
from .v2 import (
    build_appointment_prep,
    build_calendar_ics,
    build_care_plan_review,
    build_forecast,
    build_memory_profile,
    event_reasoning_narrative,
    create_human_evaluation,
    load_memory_profile,
    process_caregiver_note,
    refresh_memory_profile,
    resolve_caregiver_clarification,
    sanitize_node_edit_payload,
    search_verified_grants,
    search_verified_resources,
    with_scheduling_metadata,
)

settings = get_settings()
store: GraphStore = (
    PostgresGraphStore(settings.database_url, settings.repo_root / "backend" / "sql" / "schema.sql", settings.data_encryption_key)
    if settings.database_url
    else MemoryGraphStore(settings.data_encryption_key)
)
rate_limiter = InMemoryRateLimiter()

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.on_event("startup")
async def startup() -> None:
    require_pilot_security(settings)
    if "*" in [origin.strip() for origin in settings.cors_origins.split(",")]:
        raise RuntimeError("CORS_ORIGINS must be explicit when credentials are enabled.")
    await store.init()
    if settings.legacy_demo_enabled and not await store.list_nodes(PATIENT_ID):
        await rebuild_care_plan()
    if settings.legacy_demo_enabled and settings.scheduled_review_enabled:
        app.state.scheduled_review_task = asyncio.create_task(scheduled_review_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    task = getattr(app.state, "scheduled_review_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "service": settings.app_name,
    }


def require_read_access(x_api_key: str | None = Header(default=None), x_clinician_key: str | None = Header(default=None)) -> None:
    if settings.api_read_key or settings.api_write_key or settings.clinician_review_key:
        if not key_matches(x_api_key, [settings.api_read_key, settings.api_write_key]) and not key_matches(x_clinician_key, [settings.clinician_review_key]):
            raise HTTPException(401, "A valid API key is required for this operation.")


def require_write_access(x_api_key: str | None = Header(default=None)) -> None:
    if settings.api_write_key and not key_matches(x_api_key, [settings.api_write_key]):
        raise HTTPException(401, "A valid X-API-Key is required for this operation.")


def require_clinician_access(x_clinician_key: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> None:
    if settings.clinician_review_key:
        if not key_matches(x_clinician_key, [settings.clinician_review_key]):
            raise HTTPException(403, "Clinician review access is required.")
        return
    require_write_access(x_api_key)


def require_legacy_demo_enabled() -> None:
    if not settings.legacy_demo_enabled:
        raise HTTPException(410, "Legacy NEHR/demo runtime paths are disabled. Use transcript-first ingestion.")


@app.post("/demo/reset", dependencies=[Depends(require_write_access)])
async def reset_demo() -> dict:
    require_legacy_demo_enabled()
    return await rebuild_care_plan()


@app.post("/demo/ingest", dependencies=[Depends(require_write_access)])
async def ingest_demo() -> dict:
    require_legacy_demo_enabled()
    result = await ingest_trigger_records(store)
    agent_result = await run_agent_for_trigger(store, settings, PATIENT_ID, result["node_ids"][0])
    return {**result, "agent": agent_result}


async def rebuild_care_plan() -> dict:
    require_legacy_demo_enabled()
    baseline = await seed_baseline(store)
    trigger = await ingest_trigger_records(store)
    agent_result = await run_agent_for_trigger(store, settings, PATIENT_ID, trigger["node_ids"][0])
    return {**baseline, "trigger": trigger, "agent": agent_result}


async def scheduled_review_loop() -> None:
    while True:
        await asyncio.sleep(max(60, settings.scheduled_review_interval_seconds))
        with suppress(Exception):
            await run_scheduled_review(force=False)


async def run_scheduled_review(force: bool = False) -> dict:
    if not settings.legacy_demo_enabled:
        return {"skipped": True, "reason": "legacy_demo_disabled"}
    lock_key = "scheduled_review"
    if not force and not await store.acquire_system_lock(lock_key, settings.scheduled_review_lock_ttl_seconds):
        state = await store.get_system_state(lock_key)
        return {"skipped": True, "reason": "scheduled_review_lock_held", "state": state}
    graph = await store.graph_subset(PATIENT_ID)
    logs = await store.list_reasoning_logs()
    review = build_care_plan_review(graph, logs)
    log = await store.create_reasoning_log("scheduled_review")
    conclusion = " ".join(review["narrative"][:3])
    await store.append_reasoning_step(
        log.id,
        {
            "kind": "care_plan_review",
            "record_count": review["record_count"],
            "condition_count": review["condition_count"],
            "pending_review_count": review["pending_review_count"],
            "upcoming_30_day_count": review["upcoming_30_day_count"],
            "memory_instructions": review["memory_instructions"],
        },
    )
    await store.finish_reasoning_log(log.id, conclusion)
    await store.set_system_state(
        lock_key,
        {
            "last_run_at": datetime.now(UTC).isoformat(),
            "last_reasoning_log_id": str(log.id),
            "last_conclusion": conclusion,
            "record_count": review["record_count"],
            "pending_review_count": review["pending_review_count"],
        },
        locked_until=None,
    )
    return {"reasoning_log_id": str(log.id), "conclusion": conclusion, "review": review}


@app.get("/patient/summary", dependencies=[Depends(require_read_access)])
async def patient_summary() -> dict:
    graph = await store.graph_subset(PATIENT_ID, ["inferred_condition"])
    conditions = [node.payload.get("display_name") for node in graph.nodes if node.payload.get("display_name")]
    patient = PATIENT.model_copy(update={"key_conditions": list(dict.fromkeys(PATIENT.key_conditions + conditions))})
    return sanitize_public(patient.model_dump())


@app.get("/patient/identity", dependencies=[Depends(require_read_access)])
async def get_patient_identity() -> dict:
    identity = await ensure_patient_identity(store, PATIENT_ID, PATIENT.model_dump(mode="json"))
    return sanitize_public(identity.model_dump(mode="json"))


@app.post("/patient/identity/aliases", dependencies=[Depends(require_write_access)])
async def create_patient_alias(alias: IdentityAliasCreate) -> dict:
    identity = await upsert_patient_alias(
        store,
        PATIENT_ID,
        PATIENT.model_dump(mode="json"),
        alias.alias,
        alias.entity,
        alias.source,
        alias.confidence,
        alias.status,
    )
    return sanitize_public(identity.model_dump(mode="json"))


@app.get("/records", dependencies=[Depends(require_read_access)])
async def records() -> list[dict]:
    require_legacy_demo_enabled()
    graph = await store.graph_subset(PATIENT_ID)
    record_nodes = [node for node in graph.nodes if node.type == "nehr_record"]
    return sanitize_public([
        {**node.model_dump(mode="json"), "forward_actions": [action.model_dump(mode="json") for action in forward_actions(node, graph.nodes, graph.edges)]}
        for node in record_nodes
    ])


@app.get("/records/{record_id}", dependencies=[Depends(require_read_access)])
async def record_detail(record_id: UUID) -> dict:
    require_legacy_demo_enabled()
    graph = await store.graph_subset(PATIENT_ID)
    node = await store.get_node(record_id)
    if not node:
        raise HTTPException(404, "Record not found")
    return sanitize_public({
        **node.model_dump(mode="json"),
        "forward_actions": [action.model_dump(mode="json") for action in forward_actions(node, graph.nodes, graph.edges)],
    })


@app.get("/events", dependencies=[Depends(require_read_access)])
async def events() -> list[dict]:
    nodes = await store.list_nodes(PATIENT_ID, ["scheduled_action"])
    return sanitize_public([with_scheduling_metadata(node).model_dump(mode="json") for node in nodes if node.status != "dismissed"])


@app.get("/events/{event_id}", dependencies=[Depends(require_read_access)])
async def event_detail(event_id: UUID) -> dict:
    graph = await store.graph_subset(PATIENT_ID)
    node = await store.get_node(event_id)
    if not node:
        raise HTTPException(404, "Event not found")
    node = with_scheduling_metadata(node)
    related_edges = [edge for edge in graph.edges if edge.from_node == event_id or edge.to_node == event_id]
    related_ids = {edge.from_node for edge in related_edges} | {edge.to_node for edge in related_edges}
    related_nodes = [item for item in graph.nodes if item.id in related_ids and item.id != event_id]
    log = await store.get_reasoning_log(node.reasoning_log_id) if node.reasoning_log_id else None
    return sanitize_public({
        **node.model_dump(mode="json"),
        "source_records": [source.model_dump(mode="json") for source in backtrace_sources(node, graph.nodes, graph.edges)],
        "related_nodes": [item.model_dump(mode="json") for item in related_nodes],
        "related_edges": [edge.model_dump(mode="json") for edge in related_edges],
        "reasoning_log": log.model_dump(mode="json") if log else None,
        "reasoning_narrative": event_reasoning_narrative(node, graph, log),
        "appointment_prep": build_appointment_prep(node, graph),
    })


@app.get("/calendar.ics", dependencies=[Depends(require_read_access)])
async def calendar_export() -> Response:
    nodes = await store.list_nodes(PATIENT_ID, ["scheduled_action"])
    active = [node for node in nodes if node.status != "dismissed"]
    return Response(
        build_calendar_ics(active, f"{PATIENT.name} Care Plan"),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="caregiver-companion-care-plan.ics"'},
    )


@app.get("/calendar/feed.ics", dependencies=[Depends(require_read_access)])
async def calendar_feed() -> Response:
    nodes = await store.list_nodes(PATIENT_ID, ["scheduled_action"])
    active = [node for node in nodes if node.status != "dismissed"]
    return Response(
        build_calendar_ics(active, f"{PATIENT.name} Care Plan"),
        media_type="text/calendar; charset=utf-8",
    )


@app.get("/memory", dependencies=[Depends(require_read_access)])
async def memory_profile() -> dict:
    return sanitize_public(await load_memory_profile(store, PATIENT_ID))


@app.get("/care-plan/review", dependencies=[Depends(require_read_access)])
async def care_plan_review() -> dict:
    graph = await store.graph_subset(PATIENT_ID)
    logs = await store.list_reasoning_logs()
    return sanitize_public(build_care_plan_review(graph, logs))


@app.post("/care-plan/rereason", dependencies=[Depends(require_write_access)])
async def care_plan_rereason() -> dict:
    return await run_scheduled_review(force=True)


@app.get("/forecast", dependencies=[Depends(require_read_access)])
async def forecast() -> list[dict]:
    return sanitize_public(build_forecast(await store.graph_subset(PATIENT_ID)))


@app.post("/caregiver-notes", dependencies=[Depends(require_write_access)])
async def caregiver_notes(note: CaregiverNoteCreate) -> dict:
    await record_consent(store, PATIENT_ID, "caregiver_note_processing")
    result = await process_caregiver_note(store, PATIENT_ID, note.text, note.recorded_at, settings)
    await record_processing_activity(store, PATIENT_ID, "caregiver_note_processing", ["caregiver_note", "health_context"])
    return sanitize_public(result)


@app.patch("/care-intents/{node_id}/clarification", dependencies=[Depends(require_write_access)])
async def clarify_caregiver_intent(node_id: UUID, update: ClarificationUpdate) -> dict:
    try:
        result = await resolve_caregiver_clarification(store, PATIENT_ID, node_id, update.answer, update.payload_patch, settings)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await refresh_memory_profile(store, PATIENT_ID)
    return sanitize_public(result)


@app.post("/transcribe", dependencies=[Depends(require_write_access)])
async def transcribe(request: Request, language: str | None = Query(default=None)) -> dict:
    rate_limiter.check(rate_limit_key(request, "transcribe"), settings.transcription_rate_limit, 3600)
    try:
        request_settings = transcription_settings_for_language(language)
        result = await transcribe_audio(await request.body(), request.headers.get("content-type"), request_settings)
        return sanitize_public(result.model_dump())
    except TranscriptionInputError as exc:
        raise HTTPException(422 if "Unsupported transcription language" in str(exc) else exc.status_code, str(exc)) from exc
    except TranscriptionError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.post("/transcriptions", dependencies=[Depends(require_write_access)])
async def create_transcription(request: Request, language: str | None = Query(default=None)) -> dict:
    rate_limiter.check(rate_limit_key(request, "transcriptions"), settings.transcription_rate_limit, 3600)
    try:
        request_settings = transcription_settings_for_language(language)
        await record_consent(store, PATIENT_ID, "audio_transcription")
        result = await ingest_audio_transcription(store, PATIENT_ID, await request.body(), request.headers.get("content-type"), request_settings)
        transcript_id = result.get("transcript", {}).get("id")
        await record_processing_activity(
            store,
            PATIENT_ID,
            "audio_transcription",
            ["audio", "transcript", "health_context"],
            transcript_id,
            request_settings.transcription_provider,
            "provider_default",
        )
        return sanitize_public(result)
    except TranscriptionInputError as exc:
        raise HTTPException(422 if "Unsupported transcription language" in str(exc) else exc.status_code, str(exc)) from exc
    except TranscriptionError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


def transcription_settings_for_language(language: str | None):
    if language is None:
        return settings
    normalized = normalize_transcription_language(language)
    return settings.model_copy(update={"transcription_language": normalized})


@app.post("/transcripts/{transcript_id}/redact", dependencies=[Depends(require_write_access)])
async def redact_transcript(transcript_id: UUID) -> dict:
    transcript = await store.get_node(transcript_id)
    if not transcript or transcript.type != "transcript":
        raise HTTPException(404, "Transcript not found")
    redaction = await _redact_transcript_with_identity(transcript)
    return sanitize_public(redaction.model_dump(mode="json"))


@app.post("/transcriptions/{session_id}/process", dependencies=[Depends(require_write_access)])
async def process_transcription(session_id: UUID) -> dict:
    transcript = await _transcript_for_session(session_id)
    if not transcript:
        raise HTTPException(404, "Transcript not found for transcription session")
    redaction = await _redaction_for_transcript(transcript)
    return sanitize_public(await process_redacted_transcript(store, redaction, settings=settings))


@app.post("/transcripts/{transcript_id}/process", dependencies=[Depends(require_write_access)])
async def process_transcript(transcript_id: UUID) -> dict:
    transcript = await store.get_node(transcript_id)
    if not transcript or transcript.type != "transcript":
        raise HTTPException(404, "Transcript not found")
    redaction = await _redaction_for_transcript(transcript)
    return sanitize_public(await process_redacted_transcript(store, redaction, settings=settings))


async def _transcript_for_session(session_id: UUID):
    session = await store.get_node(session_id)
    if not session or session.type != "transcription_session":
        return None
    for edge in await store.list_edges():
        if edge.from_node == session_id and edge.type == "transcribed_to":
            transcript = await store.get_node(edge.to_node)
            if transcript and transcript.type == "transcript":
                return transcript
    return None


async def _redaction_for_transcript(transcript: Node):
    for edge in await store.list_edges():
        if edge.from_node == transcript.id and edge.type == "redacted_as":
            redaction = await store.get_node(edge.to_node)
            if redaction and redaction.type == "pii_redaction":
                return redaction
    return await _redact_transcript_with_identity(transcript)


async def _redact_transcript_with_identity(transcript: Node):
    await learn_alias_candidates_from_transcript(store, transcript, PATIENT.model_dump(mode="json"))
    known_people = await known_people_for_redaction(store, PATIENT_ID, PATIENT.model_dump(mode="json"))
    return await redact_stored_transcript(store, transcript, settings, known_people=known_people)


@app.get("/resources/search", dependencies=[Depends(require_read_access)])
async def resource_search(topic: str, condition: str | None = None) -> list[dict]:
    query = f"{topic} {condition or ''}".strip()
    return sanitize_public(await search_verified_resources(query, settings))


@app.get("/grants/search", dependencies=[Depends(require_read_access)])
async def grant_search(condition: str) -> list[dict]:
    return sanitize_public(await search_verified_grants(condition, settings))


@app.get("/notifications", dependencies=[Depends(require_read_access)])
async def notifications() -> list[dict]:
    graph = await store.graph_subset(PATIENT_ID)
    logs = await store.list_reasoning_logs()
    return sanitize_public(build_notifications(graph, logs))


@app.get("/tasks/daily", dependencies=[Depends(require_read_access)])
async def daily_tasks() -> list[dict]:
    nodes = await store.list_nodes(PATIENT_ID, ["daily_task"])
    return sanitize_public([node.model_dump(mode="json") for node in nodes if node.status != "dismissed"])


@app.patch("/tasks/daily/{task_id}", dependencies=[Depends(require_write_access)])
async def patch_daily_task(task_id: UUID, patch: dict) -> dict:
    task = await store.get_node(task_id)
    if not task or task.type != "daily_task":
        raise HTTPException(404, "Daily task not found")
    try:
        return sanitize_public(await update_daily_task(store, PATIENT_ID, task, patch))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/scheduler/next-day-check", dependencies=[Depends(require_write_access)])
async def scheduler_next_day_check() -> dict:
    return sanitize_public(await run_next_day_schedule_check(store, PATIENT_ID, settings))


@app.get("/research/tasks", dependencies=[Depends(require_read_access)])
async def research_tasks() -> list[dict]:
    nodes = await store.list_nodes(PATIENT_ID, ["ad_hoc_research_task"])
    return sanitize_public([node.model_dump(mode="json") for node in nodes if node.status != "dismissed"])


@app.post("/research/tasks/{task_id}/run", dependencies=[Depends(require_write_access)])
async def run_research_task(task_id: UUID) -> dict:
    task = await store.get_node(task_id)
    if not task or task.type != "ad_hoc_research_task":
        raise HTTPException(404, "Research task not found")
    return sanitize_public(await run_guarded_research_pipeline(store, task, settings))


@app.get("/recommendations", dependencies=[Depends(require_read_access)])
async def recommendations() -> list[dict]:
    nodes = await store.list_nodes(PATIENT_ID, ["synthesized_recommendation"])
    return sanitize_public([node.model_dump(mode="json") for node in nodes if node.status != "dismissed"])


@app.post("/appointments/{appointment_id}/approve-calendar-write", dependencies=[Depends(require_write_access)])
async def approve_appointment_write(appointment_id: UUID) -> dict:
    appointment = await store.get_node(appointment_id)
    if not appointment or appointment.type != "appointment_candidate":
        raise HTTPException(404, "Appointment candidate not found")
    try:
        return sanitize_public(await approve_appointment_calendar_write(store, PATIENT_ID, appointment, settings))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.patch("/nodes/{node_id}/status", dependencies=[Depends(require_write_access)])
async def update_status(node_id: UUID, update: StatusUpdate) -> dict:
    node = await store.update_node_status(node_id, update.status)
    if not node:
        raise HTTPException(404, "Node not found")
    feedback = await store.create_node(
        "caregiver_feedback",
        {
            "patient_id": PATIENT_ID,
            "target_node_id": str(node_id),
            "status": update.status,
            "usefulness_score": update.usefulness_score,
            "feedback_note": update.feedback_note,
            "steer": update.steer,
        },
        "user",
        status="approved",
    )
    await store.create_edge(feedback.id, node_id, "feedback_on")
    await refresh_memory_profile(store, PATIENT_ID)
    return sanitize_public(node.model_dump(mode="json"))


@app.patch("/nodes/{node_id}", dependencies=[Depends(require_write_access)])
async def edit_node(node_id: UUID, edit: NodeEdit) -> dict:
    existing = await store.get_node(node_id)
    payload = edit.payload
    if not existing:
        raise HTTPException(404, "Node not found")
    try:
        payload = sanitize_node_edit_payload(existing, edit.payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    node = await store.update_node_payload(node_id, payload, edit.status)
    if not node:
        raise HTTPException(404, "Node not found")
    feedback = await store.create_node(
        "caregiver_feedback",
        {"patient_id": PATIENT_ID, "target_node_id": str(node_id), "status": edit.status, "payload_patch": edit.payload},
        "user",
        status="approved",
    )
    await store.create_edge(feedback.id, node_id, "feedback_on")
    await refresh_memory_profile(store, PATIENT_ID)
    return sanitize_public(node.model_dump(mode="json"))


@app.get("/audit", dependencies=[Depends(require_read_access)])
async def audit_logs() -> list[dict]:
    patient = PATIENT.model_dump(mode="json")
    return sanitize_public([sanitize_audit_payload(log.model_dump(mode="json"), patient) for log in await store.list_reasoning_logs()])


@app.get("/audit/{log_id}", dependencies=[Depends(require_read_access)])
async def audit_detail(log_id: UUID) -> dict:
    log = await store.get_reasoning_log(log_id)
    if not log:
        raise HTTPException(404, "Reasoning log not found")
    return sanitize_public(sanitize_audit_payload(log.model_dump(mode="json"), PATIENT.model_dump(mode="json")))


@app.post("/dev/redact", dependencies=[Depends(require_write_access)])
async def dev_redact(payload: dict) -> dict:
    redactor = PiiRedactor()
    redactor.seed_from_patient(PATIENT.model_dump(mode="json"))
    redacted = redactor.redact(payload)
    return sanitize_public({"redacted": redacted, "privacy": redactor.summary()})


@app.post("/privacy/consents", dependencies=[Depends(require_write_access)])
async def create_consent_record(consent: ConsentRecordCreate) -> dict:
    node = await record_consent(store, PATIENT_ID, consent.purpose, consent.notice_version, consent.channel, consent.granted)
    return sanitize_public(node.model_dump(mode="json"))


@app.get("/privacy/consents", dependencies=[Depends(require_read_access)])
async def consent_records() -> list[dict]:
    return sanitize_public([node.model_dump(mode="json") for node in await store.list_nodes(PATIENT_ID, ["consent_record"])])


@app.post("/privacy/requests", dependencies=[Depends(require_write_access)])
async def create_privacy_request(request: DataSubjectRequestCreate) -> dict:
    node = await create_data_subject_request(store, PATIENT_ID, request)
    return sanitize_public(node.model_dump(mode="json"))


@app.get("/privacy/requests", dependencies=[Depends(require_read_access)])
async def privacy_requests() -> list[dict]:
    return sanitize_public([node.model_dump(mode="json") for node in await store.list_nodes(PATIENT_ID, ["data_subject_request"])])


@app.post("/privacy/incidents", dependencies=[Depends(require_clinician_access)])
async def create_incident(incident: PrivacyIncidentCreate) -> dict:
    node = await create_privacy_incident(store, incident)
    return sanitize_public(node.model_dump(mode="json"))


@app.get("/privacy/incidents", dependencies=[Depends(require_clinician_access)])
async def privacy_incidents() -> list[dict]:
    return sanitize_public([node.model_dump(mode="json") for node in await store.list_nodes(None, ["privacy_incident"])])


@app.post("/privacy/retention/purge", dependencies=[Depends(require_clinician_access)])
async def retention_purge() -> dict:
    return await purge_expired_sensitive_data(store, PATIENT_ID, settings)


@app.get("/eval/care-plan", dependencies=[Depends(require_read_access)])
async def care_plan_eval() -> dict:
    return sanitize_public(evaluate_care_plan(await store.graph_subset(PATIENT_ID), await store.list_reasoning_logs()))


@app.get("/learning/context", dependencies=[Depends(require_clinician_access)])
async def learning_context() -> dict:
    return build_learning_context(await store.list_nodes(PATIENT_ID))


@app.get("/learning/model-evaluations", dependencies=[Depends(require_clinician_access)])
async def model_evaluations() -> list[dict]:
    nodes = await store.list_nodes(PATIENT_ID, ["model_evaluation"])
    return list_model_evaluations(nodes)


@app.post("/learning/model-evaluations", dependencies=[Depends(require_clinician_access)])
async def create_learning_model_evaluation(evaluation: ModelEvaluationCreate) -> dict:
    return await create_model_evaluation(store, PATIENT_ID, evaluation)


@app.get("/learning/prompt-candidates", dependencies=[Depends(require_clinician_access)])
async def prompt_candidates() -> list[dict]:
    nodes = await store.list_nodes(PATIENT_ID, ["prompt_candidate"])
    return list_prompt_candidates(nodes)


@app.post("/learning/prompt-candidates", dependencies=[Depends(require_clinician_access)])
async def create_learning_prompt_candidate(candidate: PromptCandidateCreate) -> dict:
    return await create_prompt_candidate(store, PATIENT_ID, candidate)


@app.get("/eval/human", dependencies=[Depends(require_clinician_access)])
async def human_eval_workflow() -> dict:
    graph = await store.graph_subset(PATIENT_ID)
    automated = evaluate_care_plan(graph, await store.list_reasoning_logs())
    evaluations = [node.model_dump(mode="json") for node in graph.nodes if node.type == "human_evaluation"]
    evaluated_ids = {item["payload"].get("action_id") for item in evaluations}
    queue = [
        node.model_dump(mode="json")
        for node in graph.nodes
        if node.type == "scheduled_action" and str(node.id) not in evaluated_ids and node.status != "dismissed"
    ]
    return {
        "automated": automated,
        "evaluations": evaluations,
        "queue": sorted(queue, key=lambda item: item["payload"].get("start_at") or "")[:10],
    }


@app.post("/eval/human", dependencies=[Depends(require_clinician_access)])
async def submit_human_eval(evaluation: HumanEvaluationCreate) -> dict:
    try:
        node = await create_human_evaluation(store, PATIENT_ID, evaluation.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return node.model_dump(mode="json")
