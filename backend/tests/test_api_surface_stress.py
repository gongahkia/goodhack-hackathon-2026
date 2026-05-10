import asyncio
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings
from app.store import MemoryGraphStore
from app.transcription import TranscriptionResult


API_KEY = "surface-test-key"


def _install_test_app(monkeypatch) -> MemoryGraphStore:
    store = MemoryGraphStore()

    async def fake_init():
        return None

    store.init = fake_init
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(
        main,
        "settings",
        Settings(
            api_write_key=API_KEY,
            clinician_review_key="clinician-test-key",
            openai_api_key=None,
            google_calendar_access_token=None,
        ),
    )
    return store


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


def _clinician_headers() -> dict[str, str]:
    return {"X-Clinician-Key": "clinician-test-key"}


async def _seed_surface_graph(store: MemoryGraphStore) -> dict[str, UUID]:
    log = await store.create_reasoning_log("surface-test")
    await store.append_reasoning_step(log.id, {"kind": "seed", "patient_name": "John Tan"})
    await store.finish_reasoning_log(log.id, "Seeded surface graph for route coverage.")
    source = await store.create_node(
        "caregiver_note",
        {
            "patient_id": "mdm-tan",
            "title": "Neurology review",
            "text": "Doctor reviewed mobility risk and asked caregiver to monitor falls.",
            "summary": "Parkinson symptoms and mobility risk reviewed.",
        },
        "system",
        reasoning_log_id=log.id,
        status="approved",
    )
    action, _ = await store.create_node_with_edge(
        "scheduled_action",
        {
            "patient_id": "mdm-tan",
            "title": "Book physiotherapy review",
            "description": "Follow up on mobility concerns.",
            "action_type": "appointment",
            "start_at": "2026-06-01T10:00:00+08:00",
            "end_at": "2026-06-01T11:00:00+08:00",
            "timing_type": "fixed_time",
            "urgency": "clinical",
            "estimated_effort_minutes": 60,
            "scheduling_reason": "Clinician follow-up.",
            "rest_interrupt_allowed": True,
        },
        "agent",
        log.id,
        "pending_review",
        uuid4(),
        source.id,
        "derived_from",
    )
    daily = await store.create_node(
        "daily_task",
        {
            "patient_id": "mdm-tan",
            "title": "Give Panadol before lunch",
            "description": "John needs Panadol before lunch every day",
            "original_instruction_redacted": "PERSON_1 needs Panadol before lunch every day",
            "scheduling_semantics": "fixed_clinical",
            "timing_relation": "before lunch",
        },
        "agent",
        status="pending_review",
    )
    conflict = await store.create_node(
        "schedule_conflict",
        {
            "patient_id": "mdm-tan",
            "daily_task_id": str(daily.id),
            "category": "next_day_conflict_warning",
            "classification": "movable",
            "reason": "Seeded conflict.",
            "task_time": {"start_at": "2026-06-01T09:00:00+08:00", "end_at": "2026-06-01T09:30:00+08:00"},
            "suggested_time": "2026-06-01T11:00:00+08:00",
        },
        "system",
        status="pending_review",
    )
    appointment = await store.create_node(
        "appointment_candidate",
        {
            "patient_id": "mdm-tan",
            "title": "Doctor appointment",
            "kind": "doctor",
            "date": "2026-06-01",
            "time": "10:00",
            "location": "Clinic A",
            "requires_calendar_write": True,
            "calendar_write_status": "pending_user_approval",
        },
        "agent",
        status="pending_review",
    )
    transcript = await store.create_node(
        "transcript",
        {
            "patient_id": "mdm-tan",
            "raw_text": (
                "John needs Panadol before lunch every day. "
                "John has a doctor appointment on June 1, 2026 at 10am. "
                "Doctor said wheelchair support may be needed, find Singapore wheelchair grants."
            ),
        },
        "system",
        reasoning_log_id=log.id,
        status="approved",
    )
    research_task = await store.create_node(
        "ad_hoc_research_task",
        {
            "patient_id": "mdm-tan",
            "question": "What wheelchair grants are available?",
            "question_redacted": "What wheelchair grants are available?",
            "basis": "Doctor said wheelchair support may be needed.",
            "basis_redacted": "Doctor said wheelchair support may be needed.",
            "requires_guardrail_review": True,
        },
        "agent",
        status="pending_review",
    )
    recommendation = await store.create_node(
        "synthesized_recommendation",
        {"patient_id": "mdm-tan", "title": "Wheelchair grant result", "summary": "AIC support may apply."},
        "agent",
        status="pending_review",
    )
    intent = await store.create_node(
        "care_intent",
        {
            "patient_id": "mdm-tan",
            "intent_type": "appointment_question",
            "question": "Ask about falls risk.",
            "requires_clarification": True,
            "clarification_questions": ["Which appointment date should this question attach to?"],
        },
        "system",
        status="clarification_required",
    )
    return {
        "log": log.id,
        "source": source.id,
        "action": action.id,
        "daily": daily.id,
        "conflict": conflict.id,
        "appointment": appointment.id,
        "transcript": transcript.id,
        "research_task": research_task.id,
        "recommendation": recommendation.id,
        "intent": intent.id,
    }


def test_openapi_route_surface_matches_expected_backend_contract(monkeypatch):
    _install_test_app(monkeypatch)
    expected = {
        ("GET", "/health"),
        ("GET", "/patient/summary"),
        ("GET", "/patient/identity"),
        ("POST", "/patient/identity/aliases"),
        ("GET", "/events"),
        ("GET", "/events/{event_id}"),
        ("GET", "/calendar.ics"),
        ("GET", "/calendar/feed.ics"),
        ("GET", "/calendar/google/connect"),
        ("GET", "/calendar/google/callback"),
        ("GET", "/calendar/google/status"),
        ("DELETE", "/calendar/google/disconnect"),
        ("GET", "/memory"),
        ("GET", "/care-plan/review"),
        ("GET", "/forecast"),
        ("POST", "/caregiver-notes"),
        ("PATCH", "/care-intents/{node_id}/clarification"),
        ("POST", "/transcribe"),
        ("POST", "/transcriptions"),
        ("POST", "/transcripts/{transcript_id}/redact"),
        ("POST", "/transcriptions/{session_id}/process"),
        ("POST", "/transcripts/{transcript_id}/process"),
        ("GET", "/resources/search"),
        ("GET", "/grants/search"),
        ("GET", "/notifications"),
        ("GET", "/tasks/daily"),
        ("PATCH", "/tasks/daily/{task_id}"),
        ("GET", "/appointments"),
        ("GET", "/schedule/day"),
        ("POST", "/scheduler/next-day-check"),
        ("POST", "/scheduler/cron/next-day-check"),
        ("GET", "/schedule-conflicts"),
        ("POST", "/schedule-conflicts/{conflict_id}/resolve"),
        ("GET", "/research/tasks"),
        ("POST", "/research/tasks/{task_id}/run"),
        ("GET", "/recommendations"),
        ("POST", "/appointments/{appointment_id}/approve-calendar-write"),
        ("PATCH", "/nodes/{node_id}/status"),
        ("PATCH", "/nodes/{node_id}"),
        ("GET", "/audit"),
        ("GET", "/audit/{log_id}"),
        ("POST", "/dev/redact"),
        ("GET", "/eval/care-plan"),
        ("GET", "/learning/context"),
        ("GET", "/learning/model-evaluations"),
        ("POST", "/learning/model-evaluations"),
        ("GET", "/learning/prompt-candidates"),
        ("POST", "/learning/prompt-candidates"),
        ("GET", "/eval/human"),
        ("POST", "/eval/human"),
        ("POST", "/privacy/consents"),
        ("GET", "/privacy/consents"),
        ("POST", "/privacy/requests"),
        ("GET", "/privacy/requests"),
        ("POST", "/privacy/incidents"),
        ("GET", "/privacy/incidents"),
        ("POST", "/privacy/retention/purge"),
    }
    actual = {
        (method, route.path)
        for route in main.app.routes
        for method in getattr(route, "methods", set())
        if method not in {"HEAD", "OPTIONS"} and not route.path.startswith(("/docs", "/redoc", "/openapi"))
    }

    assert actual == expected


def test_write_and_clinician_routes_enforce_configured_auth(monkeypatch):
    ids = asyncio.run(_seed_surface_graph(_install_test_app(monkeypatch)))
    write_requests = [
        ("post", "/patient/identity/aliases", {"json": {"alias": "Ah Ma"}}),
        ("post", "/caregiver-notes", {"json": {"text": "Ask doctor about falls at the next appointment."}}),
        ("patch", f"/care-intents/{ids['intent']}/clarification", {"json": {"answer": "Use the June appointment."}}),
        ("post", "/transcribe", {"content": b"fake", "headers": {"Content-Type": "audio/wav"}}),
        ("post", "/transcriptions", {"content": b"fake", "headers": {"Content-Type": "audio/wav"}}),
        ("post", f"/transcripts/{ids['transcript']}/redact", {}),
        ("post", f"/transcriptions/{uuid4()}/process", {}),
        ("post", f"/transcripts/{ids['transcript']}/process", {}),
        ("patch", f"/tasks/daily/{ids['daily']}", {"json": {"scheduling_semantics": "movable_routine"}}),
        ("get", "/calendar/google/connect", {}),
        ("delete", "/calendar/google/disconnect", {}),
        ("post", "/scheduler/next-day-check", {}),
        ("post", "/scheduler/cron/next-day-check", {}),
        ("post", f"/schedule-conflicts/{ids['conflict']}/resolve", {"json": {"action": "dismiss"}}),
        ("post", f"/research/tasks/{ids['research_task']}/run", {}),
        ("post", f"/appointments/{ids['appointment']}/approve-calendar-write", {}),
        ("patch", f"/nodes/{ids['action']}/status", {"json": {"status": "approved"}}),
        ("patch", f"/nodes/{ids['action']}", {"json": {"payload": {"title": "Updated title"}, "status": "edited"}}),
        ("post", "/dev/redact", {"json": {"name": "John Tan", "note": "Lives in Toa Payoh."}}),
    ]

    with TestClient(main.app) as client:
        for method, path, kwargs in write_requests:
            response = getattr(client, method)(path, **kwargs)
            assert response.status_code == 401, (method, path, response.text)

        assert client.get("/eval/human").status_code == 403
        assert client.post(
            "/eval/human",
            json={
                "action_id": str(ids["action"]),
                "provenance_score": 5,
                "reasoning_score": 5,
                "appropriateness_score": 5,
                "burden_score": 3,
            },
        ).status_code == 403
        assert client.get("/learning/context").status_code == 403
        assert client.get("/learning/model-evaluations").status_code == 403
        assert client.post("/learning/model-evaluations", json={"component": "triage"}).status_code == 403
        assert client.get("/learning/prompt-candidates").status_code == 403
        assert client.post(
            "/learning/prompt-candidates",
            json={
                "component": "triage",
                "proposed_prompt": "Keep speculative research blocked.",
                "rationale": "Auth check.",
            },
        ).status_code == 403
        assert client.get("/learning/context", headers=_clinician_headers()).status_code == 200
        assert client.get("/learning/model-evaluations", headers=_clinician_headers()).status_code == 200
        assert client.get("/learning/prompt-candidates", headers=_clinician_headers()).status_code == 200
        assert client.get("/eval/human", headers=_clinician_headers()).status_code == 200


def test_every_api_surface_smoke_handles_representative_inputs_without_500(monkeypatch):
    ids = asyncio.run(_seed_surface_graph(_install_test_app(monkeypatch)))

    async def fake_transcribe_audio(audio, content_type, settings):
        assert audio
        return TranscriptionResult(text="John needs Panadol before lunch every day.", provider="fake", model="fake-model")

    async def fake_ingest_audio_transcription(store, patient_id, audio, content_type, settings):
        session = await store.create_node("transcription_session", {"patient_id": patient_id}, "user", status="approved")
        transcript = await store.create_node("transcript", {"patient_id": patient_id, "raw_text": "John needs Panadol before lunch."}, "system", status="approved")
        await store.create_edge(session.id, transcript.id, "transcribed_to")
        return {"transcription_session": session.model_dump(mode="json"), "transcript": transcript.model_dump(mode="json")}

    async def fake_research_pipeline(store, task, settings):
        node = await store.create_node(
            "synthesized_recommendation",
            {"patient_id": "mdm-tan", "title": "Research complete", "summary": "Done."},
            "agent",
            status="pending_review",
        )
        return {"synthesized_recommendation": node.model_dump(mode="json")}

    monkeypatch.setattr(main, "transcribe_audio", fake_transcribe_audio)
    monkeypatch.setattr(main, "ingest_audio_transcription", fake_ingest_audio_transcription)
    monkeypatch.setattr(main, "run_guarded_research_pipeline", fake_research_pipeline)

    requests = [
        ("get", "/health", {}),
        ("get", "/patient/summary", {}),
        ("get", "/patient/identity", {}),
        ("post", "/patient/identity/aliases", {"headers": _headers(), "json": {"alias": "Ah Ma", "source": "surface_smoke", "confidence": 0.9}}),
        ("get", "/events", {}),
        ("get", f"/events/{ids['action']}", {}),
        ("get", "/calendar.ics", {}),
        ("get", "/calendar/feed.ics", {}),
        ("get", "/calendar/google/connect", {"headers": _headers(), "expected": {404}}),
        ("get", "/calendar/google/callback", {"params": {"code": "code", "state": "state"}, "expected": {404}}),
        ("get", "/calendar/google/status", {"headers": _headers(), "expected": {404}}),
        ("delete", "/calendar/google/disconnect", {"headers": _headers(), "expected": {404}}),
        ("get", "/memory", {}),
        ("get", "/care-plan/review", {}),
        ("get", "/forecast", {}),
        ("post", "/caregiver-notes", {"headers": _headers(), "json": {"text": "Ask doctor about falls at the June appointment."}}),
        ("patch", f"/care-intents/{ids['intent']}/clarification", {"headers": _headers(), "json": {"answer": "Use June 1 appointment.", "payload_patch": {"target_date": "2026-06-01"}}}),
        ("post", "/transcribe", {"headers": {**_headers(), "Content-Type": "audio/wav"}, "content": b"fake"}),
        ("post", "/transcriptions", {"headers": {**_headers(), "Content-Type": "audio/wav"}, "content": b"fake"}),
        ("post", f"/transcripts/{ids['transcript']}/redact", {"headers": _headers()}),
        ("post", f"/transcriptions/{uuid4()}/process", {"headers": _headers(), "expected": {404}}),
        ("post", f"/transcripts/{ids['transcript']}/process", {"headers": _headers()}),
        ("get", "/resources/search", {"params": {"topic": "falls prevention", "condition": "parkinson"}}),
        ("get", "/grants/search", {"params": {"condition": "wheelchair"}}),
        ("get", "/notifications", {}),
        ("get", "/tasks/daily", {}),
        ("patch", f"/tasks/daily/{ids['daily']}", {"headers": _headers(), "json": {"scheduling_semantics": "movable_routine", "scheduled_time": "11:00"}}),
        ("get", "/appointments", {}),
        ("get", "/schedule/day", {"params": {"date": "2026-06-01"}}),
        ("post", "/scheduler/next-day-check", {"headers": _headers()}),
        ("post", "/scheduler/cron/next-day-check", {"headers": _headers()}),
        ("get", "/schedule-conflicts", {}),
        ("post", f"/schedule-conflicts/{ids['conflict']}/resolve", {"headers": _headers(), "json": {"action": "dismiss"}, "expected": {200, 422}}),
        ("get", "/research/tasks", {}),
        ("post", f"/research/tasks/{ids['research_task']}/run", {"headers": _headers()}),
        ("get", "/recommendations", {}),
        ("post", f"/appointments/{ids['appointment']}/approve-calendar-write", {"headers": _headers()}),
        ("patch", f"/nodes/{ids['action']}/status", {"headers": _headers(), "json": {"status": "approved", "usefulness_score": 5}}),
        ("patch", f"/nodes/{ids['action']}", {"headers": _headers(), "json": {"payload": {"description": "Bring updated medication list.", "reschedule_reason": "No schedule change."}, "status": "edited"}}),
        ("get", "/audit", {}),
        ("get", f"/audit/{ids['log']}", {}),
        ("post", "/dev/redact", {"headers": _headers(), "json": {"patient": "John Tan", "note": "Lives near Toa Payoh."}}),
        ("post", "/privacy/consents", {"headers": _headers(), "json": {"purpose": "pilot testing", "notice_version": "pilot.v1", "channel": "api", "granted": True}}),
        ("get", "/privacy/consents", {}),
        ("post", "/privacy/requests", {"headers": _headers(), "json": {"request_type": "access", "requester": "caregiver", "details": "Surface smoke."}}),
        ("get", "/privacy/requests", {}),
        ("post", "/privacy/incidents", {"headers": _clinician_headers(), "json": {"summary": "Surface smoke incident.", "affected_data_categories": ["transcript"], "affected_user_count": 0}}),
        ("get", "/privacy/incidents", {"headers": _clinician_headers()}),
        ("post", "/privacy/retention/purge", {"headers": _clinician_headers()}),
        ("get", "/eval/care-plan", {}),
        ("get", "/learning/context", {"headers": _clinician_headers()}),
        ("get", "/learning/model-evaluations", {"headers": _clinician_headers()}),
        ("post", "/learning/model-evaluations", {"headers": _clinician_headers(), "json": {"component": "triage", "input_node_ids": [str(ids["daily"])], "outcome": "needs_review", "failure_tags": ["surface_smoke"]}}),
        ("get", "/learning/prompt-candidates", {"headers": _clinician_headers()}),
        ("post", "/learning/prompt-candidates", {"headers": _clinician_headers(), "json": {"component": "triage", "proposed_prompt": "Classify daily medications as daily tasks only.", "rationale": "Surface smoke test."}}),
        ("get", "/eval/human", {"headers": _clinician_headers()}),
        ("post", "/eval/human", {"headers": _clinician_headers(), "json": {"action_id": str(ids["action"]), "provenance_score": 5, "reasoning_score": 5, "appropriateness_score": 4, "burden_score": 3}}),
    ]

    with TestClient(main.app) as client:
        for method, path, kwargs in requests:
            expected = kwargs.pop("expected", {200})
            if method == "get" and path != "/health" and "headers" not in kwargs:
                kwargs["headers"] = _headers()
            response = getattr(client, method)(path, **kwargs)
            assert response.status_code in expected, (method, path, response.status_code, response.text)
            assert response.status_code < 500, (method, path, response.text)


def test_api_idempotency_and_write_stress_keeps_graph_bounded(monkeypatch):
    store = _install_test_app(monkeypatch)
    transcript_id = asyncio.run(
        store.create_node(
            "transcript",
            {
                "patient_id": "mdm-tan",
                "raw_text": (
                    "John needs Panadol before lunch every day. "
                    "John has a physio appointment on June 1, 2026 at 10am. "
                    "Doctor said wheelchair support may be needed, find Singapore wheelchair grants."
                ),
            },
            "system",
            status="approved",
        )
    ).id

    with TestClient(main.app) as client:
        processed = [client.post(f"/transcripts/{transcript_id}/process", headers=_headers()) for _ in range(25)]
        note_responses = [
            client.post(
                "/caregiver-notes",
                headers=_headers(),
                json={"text": f"Ask doctor about falls risk at appointment number {index}."},
            )
            for index in range(30)
        ]
        daily_task_id = processed[0].json()["daily_tasks"][0]["id"]
        edit_responses = [
            client.patch(
                f"/tasks/daily/{daily_task_id}",
                headers=_headers(),
                json={"scheduling_semantics": "movable_routine", "scheduled_time": f"{8 + index % 4:02d}:00"},
            )
            for index in range(20)
        ]
        notifications = client.get("/notifications", headers=_headers())
        memory = client.get("/memory", headers=_headers())

    assert all(response.status_code == 200 for response in processed)
    assert len({response.text for response in processed}) == 1
    assert all(response.status_code == 200 for response in note_responses)
    assert all(response.status_code == 200 for response in edit_responses)
    assert notifications.status_code == 200
    assert memory.status_code == 200

    daily_tasks = asyncio.run(store.list_nodes("mdm-tan", ["daily_task"]))
    appointments = asyncio.run(store.list_nodes("mdm-tan", ["appointment_candidate"]))
    research_tasks = asyncio.run(store.list_nodes("mdm-tan", ["ad_hoc_research_task"]))
    care_notes = asyncio.run(store.list_nodes("mdm-tan", ["caregiver_note"]))
    feedback = asyncio.run(store.list_nodes("mdm-tan", ["caregiver_feedback"]))

    assert len(daily_tasks) == 1
    assert len(appointments) == 1
    assert len(research_tasks) == 1
    assert len(care_notes) == 30
    assert len(feedback) == 20
    assert len(notifications.json()) >= 30
    assert memory.json()["feedback_count"] == 20
