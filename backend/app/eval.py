from __future__ import annotations

from typing import Any

from .graph_queries import backtrace_sources
from .models import GraphSubset, ReasoningLog

EXPECTED_ACTION_TYPES = {"medication", "therapy", "appointment", "grant", "task"}
FIXED_TIME_TYPES = {"medication", "appointment"}


def evaluate_care_plan(graph: GraphSubset, logs: list[ReasoningLog]) -> dict[str, Any]:
    logs_by_id = {log.id: log for log in logs}
    actions = [node for node in graph.nodes if node.type == "scheduled_action"]
    human_evaluations = [node for node in graph.nodes if node.type == "human_evaluation"]
    human_by_action: dict[str, list[Any]] = {}
    for evaluation in human_evaluations:
        action_id = str(evaluation.payload.get("action_id") or "")
        if action_id:
            human_by_action.setdefault(action_id, []).append(evaluation)
    decisions = []
    ungrounded_actions = []

    for action in actions:
        sources = backtrace_sources(action, graph.nodes, graph.edges)
        log = logs_by_id.get(action.reasoning_log_id) if action.reasoning_log_id else None
        action_type = str(action.payload.get("action_type") or "")
        failures = []
        if not sources:
            failures.append("missing_valid_provenance")
            ungrounded_actions.append(str(action.id))
        if not log or not log.conclusion:
            failures.append("missing_reasoning_log")
        if action_type not in EXPECTED_ACTION_TYPES:
            failures.append("unexpected_action_type")
        if not action.payload.get("title") or not action.payload.get("start_at"):
            failures.append("missing_action_schedule_fields")
        timing_appropriate = bool(action.payload.get("start_at")) and (
            action_type not in FIXED_TIME_TYPES or bool(action.payload.get("end_at") or action.payload.get("recurrence"))
        )
        if not timing_appropriate:
            failures.append("weak_timing_semantics")
        caregiver_burden = _caregiver_burden(action)
        source_specificity = _source_specificity(sources)
        safe_to_show = bool(sources) and bool(log and log.conclusion) and caregiver_burden != "high"
        human_reviews = human_by_action.get(str(action.id), [])

        decisions.append(
            {
                "action_id": str(action.id),
                "title": action.payload.get("title"),
                "action_type": action_type,
                "provenance_correct": bool(sources),
                "reasoning_present": bool(log and log.conclusion),
                "action_appropriate": action_type in EXPECTED_ACTION_TYPES and bool(action.payload.get("title")) and bool(action.payload.get("start_at")),
                "timing_appropriate": timing_appropriate,
                "caregiver_burden": caregiver_burden,
                "source_specificity": source_specificity,
                "safe_to_show": safe_to_show,
                "human_review_count": len(human_reviews),
                "human_scores": [_human_score_summary(review) for review in human_reviews],
                "source_record_ids": [str(source.id) for source in sources],
                "failures": failures,
            }
        )

    passed_decisions = [decision for decision in decisions if not decision["failures"]]
    return {
        "passed": all(not decision["failures"] for decision in decisions),
        "score": round(len(passed_decisions) / len(decisions), 2) if decisions else 1,
        "action_count": len(actions),
        "ungrounded_action_count": len(ungrounded_actions),
        "ungrounded_actions": ungrounded_actions,
        "human_evaluation_count": len(human_evaluations),
        "human_reviewed_action_count": len(human_by_action),
        "coverage": {
            "medication": any(decision["action_type"] == "medication" for decision in decisions),
            "therapy": any(decision["action_type"] == "therapy" for decision in decisions),
            "appointment": any(decision["action_type"] == "appointment" for decision in decisions),
            "grant_or_resource": any(decision["action_type"] == "grant" for decision in decisions),
        },
        "decision_evals": decisions,
    }


def _caregiver_burden(action: Any) -> str:
    text = " ".join(str(action.payload.get(key) or "") for key in ["title", "description", "recurrence"]).lower()
    if "daily" in text and any(word in text for word in ["apply", "appointment", "travel"]):
        return "high"
    if "daily" in text or "weekly" in text:
        return "medium"
    return "low"


def _source_specificity(sources: list[Any]) -> str:
    if not sources:
        return "none"
    if any(source.type == "nehr_record" for source in sources):
        return "clinical_record"
    if any(source.type in {"grant_opportunity", "recommended_resource"} for source in sources):
        return "curated_support"
    return "generic"


def _human_score_summary(review: Any) -> dict[str, Any]:
    scores = review.payload.get("scores") or {}
    numeric = [value for value in scores.values() if isinstance(value, (int, float))]
    return {
        "reviewer_role": review.payload.get("reviewer_role"),
        "average_score": round(sum(numeric) / len(numeric), 2) if numeric else None,
        "scores": scores,
        "notes": review.payload.get("notes"),
        "reviewed_at": review.payload.get("reviewed_at"),
    }
