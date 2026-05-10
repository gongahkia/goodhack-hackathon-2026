import asyncio
from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.main as main
import app.transcript_pipeline as transcript_pipeline
from app.config import Settings
from app.scheduler import SINGAPORE_TZ
from app.store import MemoryGraphStore
from app.transcription import TranscriptionResult


API_KEY = "test-write-key"


def _install_test_app(monkeypatch):
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
            openai_api_key="test-openai-key",
            google_calendar_access_token=None,
        ),
    )
    return store


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


def _create_transcription(client: TestClient) -> dict:
    response = client.post(
        "/transcriptions",
        content=b"fake wav bytes",
        headers={**_headers(), "Content-Type": "audio/wav"},
    )
    assert response.status_code == 200
    return response.json()


def test_patient_read_and_write_endpoints_require_api_key_but_health_is_public(monkeypatch):
    _install_test_app(monkeypatch)

    with TestClient(main.app) as client:
        health = client.get("/health")
        blocked_read = client.get("/tasks/daily")
        blocked = client.post("/scheduler/next-day-check")
        allowed_read = client.get("/tasks/daily", headers=_headers())
        allowed = client.post("/scheduler/next-day-check", headers=_headers())

    assert health.status_code == 200
    assert health.json() == {"ok": True, "service": "Caregiver Companion API"}
    assert blocked_read.status_code == 401
    assert blocked.status_code == 401
    assert blocked.json()["detail"] == "A valid X-API-Key is required for this operation."
    assert allowed_read.status_code == 200
    assert allowed.status_code == 200
    assert allowed.json()["target_date"]


def test_google_calendar_oauth_routes_are_disabled_by_default(monkeypatch):
    _install_test_app(monkeypatch)

    with TestClient(main.app) as client:
        connect = client.get("/calendar/google/connect", headers=_headers())
        status = client.get("/calendar/google/status", headers=_headers())

    assert connect.status_code == 404
    assert status.status_code == 404


def test_scheduler_cron_endpoint_requires_cron_key_and_is_idempotent(monkeypatch):
    store = _install_test_app(monkeypatch)
    monkeypatch.setattr(main, "settings", Settings(api_write_key=API_KEY, scheduler_cron_key="cron-key", google_calendar_access_token=None))

    async def seed_task():
        return await store.create_node(
            "daily_task",
            {"patient_id": "mdm-tan", "title": "Give Panadol before lunch", "timing_relation": "before lunch", "scheduling_semantics": "fixed_clinical"},
            "agent",
        )

    asyncio.run(seed_task())

    with TestClient(main.app) as client:
        blocked = client.post("/scheduler/cron/next-day-check", headers={"X-Cron-Key": "wrong"})
        first = client.post("/scheduler/cron/next-day-check", headers={"X-Cron-Key": "cron-key"})
        second = client.post("/scheduler/cron/next-day-check", headers={"X-Cron-Key": "cron-key"})

    assert blocked.status_code == 401
    assert first.status_code == 200
    assert first.json()["already_ran"] is False
    assert second.status_code == 200
    assert second.json()["already_ran"] is True


def test_transcript_first_api_flow_is_idempotent_and_preserves_user_facing_pii(monkeypatch):
    store = _install_test_app(monkeypatch)

    async def fake_transcribe_audio(audio, content_type, settings):
        assert audio == b"fake wav bytes"
        assert content_type == "audio/wav"
        return TranscriptionResult(
            text="John needs Panadol before lunch every day. John has a doctor appointment on June 1, 2026 at 10am.",
            provider="openai",
            model="gpt-4o-transcribe",
            language="en",
            metadata={"test": True},
        )

    monkeypatch.setattr(transcript_pipeline, "transcribe_audio", fake_transcribe_audio)

    with TestClient(main.app) as client:
        created = _create_transcription(client)
        session_id = created["transcription_session"]["id"]
        transcript_id = created["transcript"]["id"]

        first = client.post(f"/transcriptions/{session_id}/process", headers=_headers())
        second = client.post(f"/transcriptions/{session_id}/process", headers=_headers())
        direct = client.post(f"/transcripts/{transcript_id}/process", headers=_headers())
        tasks = client.get("/tasks/daily", headers=_headers())

    assert first.status_code == 200
    assert second.status_code == 200
    assert direct.status_code == 200
    first_body = first.json()
    assert first_body == second.json() == direct.json()

    daily = first_body["daily_tasks"][0]["payload"]
    appointment = first_body["appointment_candidates"][0]["payload"]
    assert daily["description"] == "John needs Panadol before lunch every day"
    assert daily["original_instruction_redacted"] == "PERSON_1 needs Panadol before lunch every day"
    assert daily["scheduling_semantics"] == "fixed_clinical"
    assert appointment["date"] == "2026-06-01"
    assert appointment["time"] == "10:00"
    assert appointment["requires_calendar_write"] is True
    assert tasks.json()[0]["id"] == first_body["daily_tasks"][0]["id"]
    assert len(asyncio.run(store.list_nodes("mdm-tan", ["daily_task"]))) == 1
    assert len(asyncio.run(store.list_nodes("mdm-tan", ["appointment_candidate"]))) == 1


def test_daily_task_edit_route_validates_overrides_and_records_feedback(monkeypatch):
    store = _install_test_app(monkeypatch)

    async def seed_task():
        return await store.create_node(
            "daily_task",
            {
                "patient_id": "mdm-tan",
                "title": "Give Panadol before lunch",
                "description": "John needs Panadol before lunch every day",
                "original_instruction_redacted": "PERSON_1 needs Panadol before lunch every day",
                "scheduling_semantics": "fixed_clinical",
                "user_override": None,
            },
            "agent",
            status="pending_review",
        )

    task = asyncio.run(seed_task())

    with TestClient(main.app) as client:
        invalid = client.patch(
            f"/tasks/daily/{task.id}",
            headers=_headers(),
            json={"scheduling_semantics": "whenever"},
        )
        valid = client.patch(
            f"/tasks/daily/{task.id}",
            headers=_headers(),
            json={
                "scheduling_semantics": "movable_routine",
                "scheduled_time": "11:00",
                "meal_times": {"breakfast": "08:00", "lunch": "12:30"},
                "reason": "Caregiver manually adjusted this timing.",
            },
        )

    assert invalid.status_code == 422
    assert valid.status_code == 200
    payload = valid.json()["daily_task"]["payload"]
    assert payload["description"] == "John needs Panadol before lunch every day"
    assert payload["original_instruction_redacted"] == "PERSON_1 needs Panadol before lunch every day"
    assert payload["user_override"]["scheduling_semantics"] == "movable_routine"
    assert payload["user_override"]["scheduled_time"] == "11:00"
    feedback = asyncio.run(store.list_nodes("mdm-tan", ["caregiver_feedback"]))
    assert len(feedback) == 1
    assert feedback[0].payload["target_node_id"] == str(task.id)


def test_appointments_route_returns_active_candidates_only(monkeypatch):
    store = _install_test_app(monkeypatch)

    async def seed_appointments():
        active = await store.create_node(
            "appointment_candidate",
            {
                "patient_id": "mdm-tan",
                "title": "Neurology follow-up",
                "date": "2026-05-25",
                "time": "10:00",
                "calendar_write_status": "pending_user_approval",
            },
            "agent",
            status="pending_review",
        )
        await store.create_node(
            "appointment_candidate",
            {"patient_id": "mdm-tan", "title": "Dismissed appointment", "date": "2026-05-26"},
            "agent",
            status="dismissed",
        )
        return active

    active = asyncio.run(seed_appointments())

    with TestClient(main.app) as client:
        response = client.get("/appointments", headers=_headers())

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(active.id)]
    assert response.json()[0]["payload"]["title"] == "Neurology follow-up"


def test_schedule_day_route_returns_deterministic_scheduled_and_goal_buckets(monkeypatch):
    store = _install_test_app(monkeypatch)

    async def seed_tasks():
        scheduled = await store.create_node(
            "daily_task",
            {
                "patient_id": "mdm-tan",
                "title": "Aspirin 100mg",
                "description": "Take with breakfast.",
                "scheduled_time": "08:00",
                "scheduling_semantics": "fixed_clinical",
            },
            "agent",
            status="pending_review",
        )
        goal = await store.create_node(
            "daily_task",
            {"patient_id": "mdm-tan", "title": "Fluid intake", "description": "6 to 8 cups."},
            "agent",
            status="approved",
        )
        return scheduled, goal

    scheduled, goal = asyncio.run(seed_tasks())

    with TestClient(main.app) as client:
        response = client.get("/schedule/day", headers=_headers(), params={"date": "2026-05-10"})

    assert response.status_code == 200
    body = response.json()
    assert body["date"] == "2026-05-10"
    assert body["timezone"] == "Asia/Singapore"
    by_id = {item["node_id"]: item for item in body["items"]}
    assert by_id[str(scheduled.id)]["bucket"] == "scheduled"
    assert by_id[str(scheduled.id)]["time_label"] == "8:00 AM"
    assert by_id[str(scheduled.id)]["schedule_source"] == "explicit"
    assert by_id[str(goal.id)]["bucket"] == "goal"
    assert by_id[str(goal.id)]["time_label"] == "Anytime"
    assert body["calendar_events"] == []
    assert body["conflicts"] == []


def test_cors_default_allows_vite_dev_origins():
    settings = Settings(_env_file=None)
    origins = set(settings.cors_origins.split(","))

    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5173" in origins


def test_schedule_conflict_resolution_rejects_collision_then_accepts_safe_custom_time(monkeypatch):
    store = _install_test_app(monkeypatch)

    async def seed_conflict():
        task = await store.create_node(
            "daily_task",
            {
                "patient_id": "mdm-tan",
                "title": "Morning walk",
                "timing_relation": "morning",
                "scheduling_semantics": "movable_routine",
                "estimated_duration_minutes": 30,
            },
            "agent",
        )
        await store.create_node(
            "appointment_candidate",
            {
                "patient_id": "mdm-tan",
                "title": "Existing appointment",
                "date": "2026-05-11",
                "time": "10:00",
                "requires_calendar_write": True,
                "calendar_write_status": "pending_user_approval",
            },
            "agent",
        )
        conflict = await store.create_node(
            "schedule_conflict",
            {
                "patient_id": "mdm-tan",
                "daily_task_id": str(task.id),
                "category": "next_day_conflict_warning",
                "classification": "movable",
                "reason": "Morning walk conflicts with calendar event.",
                "task_time": {
                    "start_at": datetime(2026, 5, 11, 9, 0, tzinfo=SINGAPORE_TZ).isoformat(),
                    "end_at": datetime(2026, 5, 11, 9, 30, tzinfo=SINGAPORE_TZ).isoformat(),
                },
                "suggested_time": datetime(2026, 5, 11, 10, 0, tzinfo=SINGAPORE_TZ).isoformat(),
            },
            "system",
            status="pending_review",
        )
        return task, conflict

    task, conflict = asyncio.run(seed_conflict())

    with TestClient(main.app) as client:
        listed = client.get("/schedule-conflicts", headers=_headers())
        rejected = client.post(f"/schedule-conflicts/{conflict.id}/resolve", headers=_headers(), json={"action": "accept_suggested_time"})
        accepted = client.post(
            f"/schedule-conflicts/{conflict.id}/resolve",
            headers=_headers(),
            json={"action": "custom_time", "scheduled_time": "11:00", "reason": "Caregiver picked a clear slot."},
        )

    assert listed.status_code == 200
    assert listed.json()[0]["id"] == str(conflict.id)
    assert rejected.status_code == 200
    assert rejected.json()["accepted"] is False
    assert accepted.status_code == 200
    assert accepted.json()["accepted"] is True
    updated = asyncio.run(store.get_node(task.id))
    assert updated.payload["user_override"]["scheduled_time"] == "11:00"
    assert accepted.json()["schedule_conflict"]["payload"]["resolution_status"] == "resolved"


def test_calendar_approval_route_audits_missing_google_token_without_marking_written(monkeypatch):
    store = _install_test_app(monkeypatch)

    async def seed_appointment():
        return await store.create_node(
            "appointment_candidate",
            {
                "patient_id": "mdm-tan",
                "title": "Doctor appointment",
                "kind": "doctor",
                "date": "2026-06-01",
                "time": "10:00",
                "requires_calendar_write": True,
                "calendar_write_status": "pending_user_approval",
            },
            "agent",
            status="pending_review",
        )

    appointment = asyncio.run(seed_appointment())

    with TestClient(main.app) as client:
        response = client.post(f"/appointments/{appointment.id}/approve-calendar-write", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["user_decision"]["payload"]["decision"] == "approved_calendar_write"
    assert body["calendar_write_request"]["payload"]["status"] == "write_failed"
    assert body["calendar_write_request"]["status"] == "clarification_required"
    assert body["calendar_event"] is None
    updated = asyncio.run(store.get_node(appointment.id))
    assert updated.payload["calendar_write_status"] == "pending_user_approval"


def test_notifications_surface_daily_tasks_calendar_failures_and_dismissal_feedback(monkeypatch):
    store = _install_test_app(monkeypatch)

    async def seed_nodes():
        task = await store.create_node(
            "daily_task",
            {
                "patient_id": "mdm-tan",
                "title": "Give Panadol before lunch",
                "description": "John needs Panadol before lunch every day",
                "scheduling_semantics": "fixed_clinical",
            },
            "agent",
            status="pending_review",
        )
        request = await store.create_node(
            "calendar_write_request",
            {
                "patient_id": "mdm-tan",
                "appointment_candidate_id": "appointment-id",
                "provider": "google_calendar",
                "operation": "insert_event",
                "status": "write_failed",
                "error": "Google Calendar write requires GOOGLE_CALENDAR_ACCESS_TOKEN.",
            },
            "system",
            status="clarification_required",
        )
        return task, request

    task, request = asyncio.run(seed_nodes())

    with TestClient(main.app) as client:
        before = client.get("/notifications", headers=_headers())
        dismiss = client.patch(
            f"/nodes/{task.id}/status",
            headers=_headers(),
            json={"status": "dismissed", "feedback_note": "Not needed today."},
        )
        after = client.get("/notifications", headers=_headers())

    assert before.status_code == 200
    kinds = {item["kind"] for item in before.json()}
    assert "daily task review" in kinds
    assert any(item["source_node_id"] == str(request.id) for item in before.json())
    assert dismiss.status_code == 200
    dismissed = [item for item in after.json() if item["source_node_id"] == str(task.id)]
    assert dismissed
    assert dismissed[0]["kind"] == "dismissed"


def test_long_transcript_route_creates_daily_appointment_and_research_without_duplicate_artifacts(monkeypatch):
    store = _install_test_app(monkeypatch)
    long_context = " ".join(
        [
            "The caregiver gave detailed context about mobility, diabetes, home routines, transport, and family availability."
            for _ in range(40)
        ]
    )
    transcript_text = (
        f"{long_context} "
        "John needs Panadol before lunch every day. "
        "John has a physio appointment on June 1, 2026 at 10am. "
        "Doctor said if high blood sugar continues John may need amputation and wheelchair support, find Singapore wheelchair grants."
    )

    async def seed_transcript():
        return await store.create_node(
            "transcript",
            {"patient_id": "mdm-tan", "raw_text": transcript_text},
            "system",
            status="approved",
        )

    transcript = asyncio.run(seed_transcript())

    with TestClient(main.app) as client:
        first = client.post(f"/transcripts/{transcript.id}/process", headers=_headers())
        second = client.post(f"/transcripts/{transcript.id}/process", headers=_headers())
        research_tasks = client.get("/research/tasks", headers=_headers())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    body = first.json()
    assert len(body["daily_tasks"]) == 1
    assert len(body["appointment_candidates"]) == 1
    assert len(body["ad_hoc_research_tasks"]) == 1
    appointment = body["appointment_candidates"][0]["payload"]
    assert appointment["kind"] == "physio"
    assert appointment["date"] == "2026-06-01"
    assert appointment["requires_calendar_write"] is True
    research = body["ad_hoc_research_tasks"][0]["payload"]
    assert "John" in research["basis"]
    assert "PERSON_" not in research["basis"]
    assert "PERSON_" in research["basis_redacted"]
    assert research_tasks.status_code == 200
    assert research_tasks.json()[0]["id"] == body["ad_hoc_research_tasks"][0]["id"]
    assert len(asyncio.run(store.list_nodes("mdm-tan", ["daily_task"]))) == 1
    assert len(asyncio.run(store.list_nodes("mdm-tan", ["appointment_candidate"]))) == 1
    assert len(asyncio.run(store.list_nodes("mdm-tan", ["ad_hoc_research_task"]))) == 1


def test_negative_api_contracts_for_missing_or_wrong_node_types(monkeypatch):
    store = _install_test_app(monkeypatch)

    async def seed_nodes():
        daily = await store.create_node(
            "daily_task",
            {"patient_id": "mdm-tan", "title": "Task", "description": "Task", "scheduling_semantics": "fixed_clinical"},
            "agent",
        )
        transcript = await store.create_node(
            "transcript",
            {"patient_id": "mdm-tan", "raw_text": "John needs Panadol before lunch daily."},
            "system",
        )
        return daily, transcript

    daily, transcript = asyncio.run(seed_nodes())
    missing_id = uuid4()

    with TestClient(main.app) as client:
        missing_session = client.post(f"/transcriptions/{missing_id}/process", headers=_headers())
        wrong_redact_type = client.post(f"/transcripts/{daily.id}/redact", headers=_headers())
        wrong_research_type = client.post(f"/research/tasks/{daily.id}/run", headers=_headers())
        wrong_appointment_type = client.post(f"/appointments/{transcript.id}/approve-calendar-write", headers=_headers())
        malformed_daily_patch = client.patch(
            f"/tasks/daily/{daily.id}",
            headers=_headers(),
            json={"scheduled_time": "11:00:30"},
        )
        unsupported_daily_patch = client.patch(
            f"/tasks/daily/{daily.id}",
            headers=_headers(),
            json={"delete_everything": True},
        )

    assert missing_session.status_code == 404
    assert wrong_redact_type.status_code == 404
    assert wrong_research_type.status_code == 404
    assert wrong_appointment_type.status_code == 404
    assert malformed_daily_patch.status_code == 422
    assert "scheduled_time must use HH:MM format" in malformed_daily_patch.json()["detail"]
    assert unsupported_daily_patch.status_code == 422
    assert "Unsupported daily task field" in unsupported_daily_patch.json()["detail"]


def test_transcription_route_rejects_empty_audio_before_provider_call(monkeypatch):
    _install_test_app(monkeypatch)
    called = False

    async def fake_transcribe_audio(audio, content_type, settings):
        nonlocal called
        called = True
        return TranscriptionResult(text="should not happen", provider="openai", model="gpt-4o-transcribe")

    monkeypatch.setattr(transcript_pipeline, "transcribe_audio", fake_transcribe_audio)

    with TestClient(main.app) as client:
        response = client.post(
            "/transcriptions",
            content=b"",
            headers={**_headers(), "Content-Type": "audio/wav"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "No audio was received."
    assert called is False


def test_live_transcription_ws_buffers_audio_and_persists_on_commit(monkeypatch):
    store = _install_test_app(monkeypatch)
    captured = {}

    async def fake_ingest_audio_transcription(store_arg, patient_id, audio, content_type, settings):
        captured["audio"] = audio
        captured["content_type"] = content_type
        captured["language"] = settings.transcription_language
        session = await store_arg.create_node(
            "transcription_session",
            {"patient_id": patient_id, "status": "transcription_completed"},
            "user",
            status="approved",
        )
        transcript = await store_arg.create_node(
            "transcript",
            {"patient_id": patient_id, "raw_text": "John needs Panadol before lunch.", "language": "en"},
            "system",
            status="approved",
        )
        await store_arg.create_edge(session.id, transcript.id, "transcribed_to")
        return {"transcription_session": session.model_dump(mode="json"), "transcript": transcript.model_dump(mode="json")}

    monkeypatch.setattr(main, "ingest_audio_transcription", fake_ingest_audio_transcription)

    with TestClient(main.app) as client:
        with client.websocket_connect(f"/transcriptions/live?api_key={API_KEY}&language=en&content_type=audio/webm") as websocket:
            ready = websocket.receive_json()
            websocket.send_json({"type": "start", "content_type": "audio/webm;codecs=opus"})
            started = websocket.receive_json()
            websocket.send_bytes(b"fake ")
            first_ack = websocket.receive_json()
            websocket.send_bytes(b"audio")
            second_ack = websocket.receive_json()
            websocket.send_json({"type": "commit"})
            final = websocket.receive_json()

    assert ready["type"] == "ready"
    assert ready["partial_transcripts"] is False
    assert ready["fallback"] == "browser_speech_recognition"
    assert started == {"type": "started", "content_type": "audio/webm;codecs=opus"}
    assert first_ack == {"type": "ack", "bytes_received": 5, "total_bytes": 5}
    assert second_ack == {"type": "ack", "bytes_received": 5, "total_bytes": 10}
    assert final["type"] == "final"
    assert final["result"]["transcript"]["payload"]["raw_text"] == "[redacted]"
    assert captured == {"audio": b"fake audio", "content_type": "audio/webm;codecs=opus", "language": "en"}
    consents = asyncio.run(store.list_nodes("mdm-tan", ["consent_record"]))
    activities = asyncio.run(store.list_nodes("mdm-tan", ["processing_activity"]))
    assert len(consents) == 1
    assert len(activities) == 1


def test_live_transcription_ws_rejects_missing_write_key(monkeypatch):
    _install_test_app(monkeypatch)

    with TestClient(main.app) as client:
        try:
            with client.websocket_connect("/transcriptions/live"):
                raise AssertionError("websocket should not connect")
        except WebSocketDisconnect as exc:
            assert exc.code == 1008


def test_transcription_routes_accept_language_override_and_reject_unsupported_language(monkeypatch):
    store = _install_test_app(monkeypatch)
    captured = {}

    async def fake_transcribe_audio(audio, content_type, settings):
        captured.setdefault("languages", []).append(settings.transcription_language)
        return TranscriptionResult(
            text="சாப்பாட்டுக்கு முன் Panadol கொடுக்கவும்.",
            provider="openai",
            model="gpt-4o-transcribe",
            language="ta",
            requested_language="ta",
            detected_language="ta",
            language_label="Tamil",
        )

    async def fake_normalize(text, source_language, settings):
        from app.transcription import TranscriptNormalization

        return TranscriptNormalization(
            normalized_english_text="Give Panadol before food.",
            provider="openai",
            model=settings.openai_model,
            status="completed",
            source_language=source_language,
        )

    monkeypatch.setattr(main, "transcribe_audio", fake_transcribe_audio)
    monkeypatch.setattr(transcript_pipeline, "transcribe_audio", fake_transcribe_audio)
    monkeypatch.setattr(transcript_pipeline, "normalize_transcript_to_english", fake_normalize)

    with TestClient(main.app) as client:
        direct = client.post(
            "/transcribe?language=ta",
            content=b"fake wav bytes",
            headers={**_headers(), "Content-Type": "audio/wav"},
        )
        created = client.post(
            "/transcriptions?language=ta",
            content=b"fake wav bytes",
            headers={**_headers(), "Content-Type": "audio/wav"},
        )
        invalid = client.post(
            "/transcriptions?language=fr",
            content=b"fake wav bytes",
            headers={**_headers(), "Content-Type": "audio/wav"},
        )

    assert direct.status_code == 200
    assert direct.json()["requested_language"] == "ta"
    assert direct.json()["language_label"] == "Tamil"
    assert created.status_code == 200
    assert created.json()["transcript"]["payload"]["requested_language"] == "ta"
    assert created.json()["transcript"]["payload"]["normalized_english_text"] == "[redacted]"
    stored_transcripts = asyncio.run(store.list_nodes("mdm-tan", ["transcript"]))
    assert stored_transcripts[0].payload["normalized_english_text"] == "Give Panadol before food."
    assert invalid.status_code == 422
    assert captured["languages"] == ["ta", "ta"]
