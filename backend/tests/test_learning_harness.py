import asyncio

from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings
from app.learning import build_learning_context, create_model_evaluation
from app.models import ModelEvaluationCreate
from app.store import MemoryGraphStore


API_KEY = "learning-test-key"


def _install_test_app(monkeypatch):
    store = MemoryGraphStore()

    async def fake_init():
        return None

    store.init = fake_init
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "settings", Settings(api_write_key=API_KEY, legacy_demo_enabled=False, scheduled_review_enabled=False))
    return store


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


async def _seed_learning_graph(store: MemoryGraphStore):
    transcript = await store.create_node(
        "transcript",
        {"patient_id": "mdm-tan", "raw_text": "John needs Panadol before lunch every day."},
        "system",
        status="approved",
    )
    task = await store.create_node(
        "daily_task",
        {
            "patient_id": "mdm-tan",
            "title": "Give Panadol before lunch",
            "description": "John needs Panadol before lunch every day",
            "original_instruction_redacted": "PERSON_1 needs Panadol before lunch every day",
            "scheduling_semantics": "fixed_clinical",
        },
        "agent",
        status="pending_review",
    )
    feedback = await store.create_node(
        "caregiver_feedback",
        {
            "patient_id": "mdm-tan",
            "target_node_id": str(task.id),
            "status": "dismissed",
            "usefulness_score": 1,
            "feedback_note": "Duplicate reminder.",
        },
        "user",
        status="approved",
    )
    memory = await store.create_node(
        "memory_profile",
        {
            "patient_id": "mdm-tan",
            "profile": {
                "feedback_count": 1,
                "recent_feedback": [{"note": "Duplicate reminder."}],
                "action_type_memory": [{"action_type": "medication", "recommendation": "Avoid duplicate reminders."}],
            },
        },
        "system",
        status="approved",
    )
    await store.create_edge(feedback.id, task.id, "feedback_on")
    return transcript, task, feedback, memory


def test_learning_context_uses_feedback_and_memory_without_training_export_payloads():
    store = MemoryGraphStore()
    _, task, _, _ = asyncio.run(_seed_learning_graph(store))
    asyncio.run(
        create_model_evaluation(
            store,
            "mdm-tan",
            ModelEvaluationCreate(
                component="triage",
                input_node_ids=[task.id],
                outcome="fail",
                scores={"specificity": 0.3},
                failure_tags=["duplicate_task"],
                recommended_follow_up="Keep medication reminders deduplicated.",
            ),
        )
    )

    context = build_learning_context(asyncio.run(store.list_nodes("mdm-tan")))

    assert context["schema_version"] == "learning_context.v1"
    assert context["privacy"]["raw_transcripts_included"] is False
    assert context["privacy"]["placeholder_maps_included"] is False
    assert "model_training" in context["privacy"]["not_for"]
    assert context["feedback_count"] == 1
    assert context["recent_feedback"][0]["feedback_note"] == "Duplicate reminder."
    assert "reward" not in context["recent_feedback"][0]
    assert context["memory_profile"]["feedback_count"] == 1
    assert context["model_evaluations"][0]["failure_tags"] == ["duplicate_task"]
    assert "John needs Panadol" not in str(context)


def test_model_evaluation_node_records_context_evidence_edges_without_training_actions():
    store = MemoryGraphStore()
    _, task, _, _ = asyncio.run(_seed_learning_graph(store))

    result = asyncio.run(
        create_model_evaluation(
            store,
            "mdm-tan",
            ModelEvaluationCreate(component="research_guardrail", input_node_ids=[task.id], outcome="pass"),
        )
    )

    evaluation = result["model_evaluation"]
    assert evaluation["type"] == "model_evaluation"
    assert evaluation["payload"]["training_action_allowed"] is False
    assert evaluation["payload"]["autonomous_prompt_update_allowed"] is False
    assert any(edge.type == "evaluates" for edge in asyncio.run(store.list_edges()))


def test_learning_routes_are_protected_and_prompt_candidates_are_not_auto_active(monkeypatch):
    store = _install_test_app(monkeypatch)
    _, task, _, _ = asyncio.run(_seed_learning_graph(store))

    with TestClient(main.app) as client:
        blocked_context = client.get("/learning/context")
        blocked_eval = client.post("/learning/model-evaluations", json={"component": "triage"})
        created_eval = client.post(
            "/learning/model-evaluations",
            headers=_headers(),
            json={
                "component": "triage",
                "input_node_ids": [str(task.id)],
                "outcome": "fail",
                "scores": {"specificity": 0.4},
                "failure_tags": ["unwanted_research"],
                "recommended_follow_up": "Block research for simple daily medication reminders.",
            },
        )
        evaluation_id = created_eval.json()["model_evaluation"]["id"]
        created_candidate = client.post(
            "/learning/prompt-candidates",
            headers=_headers(),
            json={
                "component": "triage",
                "current_prompt_version": "triage.v1",
                "proposed_prompt": "Classify simple medication reminders as daily tasks only.",
                "rationale": "Evaluation showed speculative research should stay blocked.",
                "source_model_evaluation_id": evaluation_id,
            },
        )
        listed_context = client.get("/learning/context", headers=_headers())
        listed_evals = client.get("/learning/model-evaluations", headers=_headers())
        listed_candidates = client.get("/learning/prompt-candidates", headers=_headers())
        removed_export = client.post("/learning/dataset/export", headers=_headers(), json={"purpose": "offline_eval"})

    assert blocked_context.status_code == 401
    assert blocked_eval.status_code == 401
    assert created_eval.status_code == 200
    assert created_candidate.status_code == 200
    candidate = created_candidate.json()["prompt_candidate"]
    assert candidate["status"] == "pending_review"
    assert candidate["payload"]["deployment_status"] == "pending_human_review"
    assert candidate["payload"]["autonomous_activation_allowed"] is False
    assert listed_context.status_code == 200
    assert listed_evals.json()[0]["id"] == evaluation_id
    assert listed_candidates.json()[0]["id"] == candidate["id"]
    assert removed_export.status_code == 404
    assert any(edge.type == "candidate_from" for edge in asyncio.run(store.list_edges()))
