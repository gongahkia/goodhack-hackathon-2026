from __future__ import annotations

from uuid import UUID

from .models import Edge, Node


def backtrace_sources(node: Node, nodes: list[Node], edges: list[Edge]) -> list[Node]:
    by_id = {item.id: item for item in nodes}
    sources: list[Node] = []
    for edge in edges:
        if edge.from_node == node.id and edge.type == "derived_from":
            source = by_id.get(edge.to_node)
            if not source:
                continue
            if source.type in {"caregiver_note", "care_intent", "decision_forecast"}:
                sources.append(source)
            elif source.type == "inferred_condition":
                sources.extend(backtrace_sources(source, nodes, edges))
    seen: set[UUID] = set()
    unique = []
    for source in sources:
        if source.id not in seen:
            seen.add(source.id)
            unique.append(source)
    return unique


def forward_actions(record: Node, nodes: list[Node], edges: list[Edge]) -> list[Node]:
    by_id = {item.id: item for item in nodes}
    direct = [by_id[edge.from_node] for edge in edges if edge.to_node == record.id and edge.type == "derived_from" and edge.from_node in by_id]
    actions = [node for node in direct if node.type == "scheduled_action"]
    inferred = [node for node in direct if node.type == "inferred_condition"]
    for condition in inferred:
        for edge in edges:
            if edge.from_node == condition.id and edge.type == "triggers" and edge.to_node in by_id:
                target = by_id[edge.to_node]
                if target.type == "scheduled_action":
                    actions.append(target)
    seen: set[UUID] = set()
    unique = []
    for action in actions:
        if action.id not in seen:
            seen.add(action.id)
            unique.append(action)
    return unique
