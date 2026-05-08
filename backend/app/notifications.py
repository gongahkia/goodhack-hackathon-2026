from __future__ import annotations

from uuid import UUID

from .models import GraphSubset


def build_notifications(graph: GraphSubset) -> list[dict]:
    nodes_by_id = {node.id: node for node in graph.nodes}
    items: list[dict] = []

    for node in graph.nodes:
        if node.type != "scheduled_action":
            continue
        title = node.payload.get("title") or "Care action"
        when = node.payload.get("start_at")
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

    return sorted(items, key=lambda item: item["created_at"], reverse=True)
