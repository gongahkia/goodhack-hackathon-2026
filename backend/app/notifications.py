from __future__ import annotations

from uuid import UUID

from .models import GraphSubset, ReasoningLog


def build_notifications(graph: GraphSubset, logs: list[ReasoningLog] | None = None) -> list[dict]:
    nodes_by_id = {node.id: node for node in graph.nodes}
    items: list[dict] = []

    for node in graph.nodes:
        title = node.payload.get("title") or "Care action"
        when = node.payload.get("start_at")
        if node.type == "care_intent":
            title = node.payload.get("question") or node.payload.get("topic") or node.payload.get("normalized", {}).get("topic") or "Captured note"
            if node.status == "clarification_required":
                items.append(
                    {
                        "id": f"node:{node.id}:clarification_required",
                        "kind": "review",
                        "title": "Captured note needs clarification",
                        "body": title,
                        "created_at": node.created_at.isoformat(),
                        "href": "/capture",
                        "source_node_id": str(node.id),
                        "node_status": node.status,
                        "occurred_at": node.payload.get("target_date"),
                    }
                )
            elif node.status == "pending_review":
                items.append(
                    {
                        "id": f"node:{node.id}:pending_review",
                        "kind": "review",
                        "title": "Captured note needs approval",
                        "body": title,
                        "created_at": node.created_at.isoformat(),
                        "href": "/capture",
                        "source_node_id": str(node.id),
                        "node_status": node.status,
                        "occurred_at": node.payload.get("target_date"),
                    }
                )
            continue
        if node.type != "scheduled_action":
            continue
        if node.status == "pending_review":
            items.append(
                {
                    "id": f"node:{node.id}:pending_review",
                    "kind": "review",
                    "title": "Care action needs review",
                    "body": title,
                    "created_at": node.created_at.isoformat(),
                    "href": f"/event/{node.id}",
                    "source_node_id": str(node.id),
                    "node_status": node.status,
                    "occurred_at": when,
                }
            )
        elif node.status == "dismissed":
            items.append(
                {
                    "id": f"node:{node.id}:dismissed",
                    "kind": "dismissed",
                    "title": "Care action dismissed",
                    "body": title,
                    "created_at": node.created_at.isoformat(),
                    "href": f"/event/{node.id}",
                    "source_node_id": str(node.id),
                    "node_status": node.status,
                    "occurred_at": when,
                }
            )

    for feedback in graph.nodes:
        if feedback.type != "caregiver_feedback":
            continue
        target_id = feedback.payload.get("target_node_id")
        if not target_id:
            continue
        target = nodes_by_id.get(UUID(target_id))
        if not target or target.type != "scheduled_action":
            continue
        status = feedback.payload.get("status", "edited")
        status_label = {"approved": "approved", "dismissed": "dismissed", "edited": "edited"}.get(status, status)
        items.append(
            {
                "id": f"feedback:{feedback.id}",
                "kind": status_label,
                "title": f"Care action {status_label}",
                "body": target.payload.get("title") or "Care action",
                "created_at": feedback.created_at.isoformat(),
                "href": f"/event/{target.id}",
                "source_node_id": str(target.id),
                "node_status": target.status,
                "occurred_at": target.payload.get("start_at"),
            }
        )

    for log in logs or []:
        if not log.trigger.startswith("scheduled_review"):
            continue
        items.append(
            {
                "id": f"review-log:{log.id}",
                "kind": "system",
                "title": "Care plan reviewed",
                "body": log.conclusion or "Care plan was rechecked against records, pending actions, and caregiver feedback.",
                "created_at": log.created_at.isoformat(),
                "href": "/notifications",
                "source_node_id": None,
                "node_status": None,
                "occurred_at": log.created_at.isoformat(),
            }
        )

    return sorted(items, key=lambda item: item["created_at"], reverse=True)
