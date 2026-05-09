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
        if node.type == "notification_candidate":
            items.append(
                {
                    "id": f"notification:{node.id}",
                    "kind": node.payload.get("category") or "notification",
                    "title": node.payload.get("title") or "Notification",
                    "body": node.payload.get("body") or "",
                    "created_at": node.created_at.isoformat(),
                    "href": "/notifications",
                    "source_node_id": node.payload.get("source_daily_task_id") or node.payload.get("source_conflict_id"),
                    "node_status": node.status,
                    "occurred_at": node.payload.get("send_at"),
                }
            )
            continue
        if node.type == "synthesized_recommendation" and node.status == "pending_review":
            items.append(
                {
                    "id": f"recommendation:{node.id}:pending_review",
                    "kind": "research result ready",
                    "title": node.payload.get("title") or "Research result ready",
                    "body": node.payload.get("summary") or "",
                    "created_at": node.created_at.isoformat(),
                    "href": "/recommendations",
                    "source_node_id": str(node.id),
                    "node_status": node.status,
                    "occurred_at": node.created_at.isoformat(),
                }
            )
            continue
        if node.type == "daily_task":
            if node.status == "pending_review":
                items.append(
                    {
                        "id": f"daily-task:{node.id}:pending_review",
                        "kind": "daily task review",
                        "title": "Daily task needs review",
                        "body": title,
                        "created_at": node.created_at.isoformat(),
                        "href": "/tasks/daily",
                        "source_node_id": str(node.id),
                        "node_status": node.status,
                        "occurred_at": node.payload.get("scheduled_time") or node.payload.get("timing_relation"),
                    }
                )
            elif node.status == "dismissed":
                items.append(
                    {
                        "id": f"daily-task:{node.id}:dismissed",
                        "kind": "dismissed",
                        "title": "Daily task dismissed",
                        "body": title,
                        "created_at": node.created_at.isoformat(),
                        "href": "/tasks/daily",
                        "source_node_id": str(node.id),
                        "node_status": node.status,
                        "occurred_at": node.payload.get("scheduled_time") or node.payload.get("timing_relation"),
                    }
                )
            continue
        if node.type == "calendar_write_request":
            if node.status == "clarification_required" or node.payload.get("status") == "write_failed":
                items.append(
                    {
                        "id": f"calendar-write:{node.id}:write_failed",
                        "kind": "calendar write failed",
                        "title": "Calendar write needs attention",
                        "body": node.payload.get("error") or "The calendar write could not be completed.",
                        "created_at": node.created_at.isoformat(),
                        "href": "/notifications",
                        "source_node_id": str(node.id),
                        "node_status": node.status,
                        "occurred_at": node.payload.get("requested_at"),
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
        if not target or target.type not in {"scheduled_action", "daily_task"}:
            continue
        status = feedback.payload.get("status", "edited")
        status_label = {"approved": "approved", "dismissed": "dismissed", "edited": "edited"}.get(status, status)
        href = f"/event/{target.id}" if target.type == "scheduled_action" else "/tasks/daily"
        items.append(
            {
                "id": f"feedback:{feedback.id}",
                "kind": status_label,
                "title": f"{'Care action' if target.type == 'scheduled_action' else 'Daily task'} {status_label}",
                "body": target.payload.get("title") or "Care action",
                "created_at": feedback.created_at.isoformat(),
                "href": href,
                "source_node_id": str(target.id),
                "node_status": target.status,
                "occurred_at": target.payload.get("start_at") or target.payload.get("scheduled_time") or target.payload.get("timing_relation"),
            }
        )

    return sorted(items, key=lambda item: item["created_at"], reverse=True)
