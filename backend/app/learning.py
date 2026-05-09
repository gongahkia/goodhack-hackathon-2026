from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .models import ModelEvaluationCreate, Node, PromptCandidateCreate
from .store import GraphStore


def build_learning_context(nodes: list[Node]) -> dict[str, Any]:
    """Build compact context for future API calls without exporting training data."""
    nodes_by_id = {str(node.id): node for node in nodes}
    latest_memory = next(
        iter(sorted([node for node in nodes if node.type == "memory_profile"], key=lambda item: item.created_at, reverse=True)),
        None,
    )
    feedback = [_feedback_summary(node, nodes_by_id) for node in nodes if node.type == "caregiver_feedback"]
    evaluations = [_evaluation_summary(node) for node in nodes if node.type == "model_evaluation"]

    return {
        "schema_version": "learning_context.v1",
        "privacy": {
            "raw_transcripts_included": False,
            "placeholder_maps_included": False,
            "not_for": ["model_training", "rlhf", "rlaif", "autonomous_self_editing", "automatic_prompt_deployment"],
        },
        "memory_profile": (latest_memory.payload.get("profile") if latest_memory else None),
        "feedback_count": len(feedback),
        "recent_feedback": sorted(feedback, key=lambda item: item["created_at"], reverse=True)[:8],
        "model_evaluations": sorted(evaluations, key=lambda item: item["created_at"], reverse=True)[:12],
    }


async def create_model_evaluation(
    store: GraphStore,
    patient_id: str,
    evaluation: ModelEvaluationCreate,
) -> dict[str, Any]:
    node = await store.create_node(
        "model_evaluation",
        {
            "patient_id": patient_id,
            **evaluation.model_dump(mode="json"),
            "training_action_allowed": False,
            "autonomous_prompt_update_allowed": False,
            "created_at": datetime.now(UTC).isoformat(),
        },
        "system",
        status="pending_review",
    )
    for input_node_id in evaluation.input_node_ids:
        source = await store.get_node(input_node_id)
        if source:
            await store.create_edge(node.id, source.id, "evaluates")
    return {"model_evaluation": node.model_dump(mode="json")}


async def create_prompt_candidate(
    store: GraphStore,
    patient_id: str,
    candidate: PromptCandidateCreate,
) -> dict[str, Any]:
    node = await store.create_node(
        "prompt_candidate",
        {
            "patient_id": patient_id,
            **candidate.model_dump(mode="json"),
            "deployment_status": "pending_human_review",
            "autonomous_activation_allowed": False,
            "created_at": datetime.now(UTC).isoformat(),
        },
        "user",
        status="pending_review",
    )
    if candidate.source_model_evaluation_id:
        source = await store.get_node(candidate.source_model_evaluation_id)
        if source and source.type == "model_evaluation":
            await store.create_edge(node.id, source.id, "candidate_from")
    return {"prompt_candidate": node.model_dump(mode="json")}


def list_model_evaluations(nodes: list[Node]) -> list[dict[str, Any]]:
    return [node.model_dump(mode="json") for node in nodes if node.type == "model_evaluation"]


def list_prompt_candidates(nodes: list[Node]) -> list[dict[str, Any]]:
    return [node.model_dump(mode="json") for node in nodes if node.type == "prompt_candidate"]


def _feedback_summary(feedback: Node, nodes_by_id: dict[str, Node]) -> dict[str, Any]:
    target_id = str(feedback.payload.get("target_node_id") or "")
    target = nodes_by_id.get(target_id)
    usefulness = feedback.payload.get("usefulness_score")
    status = str(feedback.payload.get("status") or feedback.status)
    return {
        "feedback_id": str(feedback.id),
        "target_node_id": target_id,
        "target_type": target.type if target else None,
        "status": status,
        "usefulness_score": usefulness,
        "feedback_note": feedback.payload.get("feedback_note"),
        "steer": feedback.payload.get("steer"),
        "created_at": feedback.created_at.isoformat(),
    }


def _evaluation_summary(evaluation: Node) -> dict[str, Any]:
    return {
        "evaluation_id": str(evaluation.id),
        "component": evaluation.payload.get("component"),
        "outcome": evaluation.payload.get("outcome"),
        "scores": evaluation.payload.get("scores", {}),
        "failure_tags": evaluation.payload.get("failure_tags", []),
        "recommended_follow_up": evaluation.payload.get("recommended_follow_up"),
        "created_at": evaluation.created_at.isoformat(),
    }
