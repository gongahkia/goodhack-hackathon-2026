from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import httpx

from ..config import Settings
from ..data import condition_trajectories, educational_resources, grants_database
from ..store import GraphStore


class AgentToolbox:
    def __init__(self, store: GraphStore, settings: Settings, patient_id: str, reasoning_log_id: UUID) -> None:
        self.store = store
        self.settings = settings
        self.patient_id = patient_id
        self.reasoning_log_id = reasoning_log_id
        self.pending_scheduled_actions: dict[UUID, dict[str, Any]] = {}

    def tool_specs(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "read_nehr_records",
                "description": "Read NEHR records for a patient.",
                "parameters": {
                    "type": "object",
                    "properties": {"patient_id": {"type": "string"}, "since": {"type": ["string", "null"]}},
                    "required": ["patient_id"],
                },
            },
            {
                "type": "function",
                "name": "read_graph_context",
                "description": "Read existing knowledge graph context for a patient.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_id": {"type": "string"},
                        "node_types": {"type": ["array", "null"], "items": {"type": "string"}},
                    },
                    "required": ["patient_id"],
                },
            },
            {
                "type": "function",
                "name": "search_grants_database",
                "description": "Search curated Singapore grant and scheme database.",
                "parameters": {
                    "type": "object",
                    "properties": {"condition_keywords": {"type": "array", "items": {"type": "string"}}, "demographics": {"type": "object"}},
                    "required": ["condition_keywords", "demographics"],
                },
            },
            {
                "type": "function",
                "name": "find_educational_resource",
                "description": "Find resources from the curated education catalog.",
                "parameters": {
                    "type": "object",
                    "properties": {"topic": {"type": "string"}, "condition": {"type": ["string", "null"]}},
                    "required": ["topic"],
                },
            },
            {
                "type": "function",
                "name": "get_condition_trajectory",
                "description": "Read a curated condition trajectory by key.",
                "parameters": {"type": "object", "properties": {"condition_key": {"type": "string"}}, "required": ["condition_key"]},
            },
            {
                "type": "function",
                "name": "web_search",
                "description": "Allowlisted web search. Use only as last resort.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}, "allowlist": {"type": ["array", "null"], "items": {"type": "string"}}},
                    "required": ["query"],
                },
            },
            {
                "type": "function",
                "name": "create_node",
                "description": "Create a knowledge graph node. scheduled_action nodes are staged until a derived_from edge is created.",
                "parameters": {
                    "type": "object",
                    "properties": {"type": {"type": "string"}, "payload": {"type": "object"}, "status": {"type": "string", "default": "pending_review"}},
                    "required": ["type", "payload"],
                },
            },
            {
                "type": "function",
                "name": "create_edge",
                "description": "Create a knowledge graph edge.",
                "parameters": {
                    "type": "object",
                    "properties": {"from_node": {"type": "string"}, "to_node": {"type": "string"}, "edge_type": {"type": "string"}},
                    "required": ["from_node", "to_node", "edge_type"],
                },
            },
        ]

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        if not hasattr(self, name):
            raise ValueError(f"Unknown tool: {name}")
        result = await getattr(self, name)(**args)
        await self.store.append_reasoning_step(self.reasoning_log_id, {"kind": "tool_result", "tool": name, "result": result})
        return result

    async def read_nehr_records(self, patient_id: str, since: str | None = None) -> list[dict[str, Any]]:
        since_dt = datetime.fromisoformat(since) if since else None
        rows = await self.store.list_nehr_raw(patient_id, since_dt)
        return [row.model_dump(mode="json") for row in rows]

    async def read_graph_context(self, patient_id: str, node_types: list[str] | None = None) -> dict[str, Any]:
        graph = await self.store.graph_subset(patient_id, node_types)
        return graph.model_dump(mode="json")

    async def search_grants_database(self, condition_keywords: list[str], demographics: dict[str, Any]) -> list[dict[str, Any]]:
        terms = {term.lower() for term in condition_keywords}
        matches = []
        for grant in grants_database():
            haystack = " ".join(grant.get("applicable_conditions", []) + grant.get("eligibility_hints", [])).lower()
            if any(term in haystack for term in terms):
                matches.append(grant)
        return matches[:5]

    async def find_educational_resource(self, topic: str, condition: str | None = None) -> list[dict[str, Any]]:
        topic_words = set(topic.lower().replace("_", " ").split())
        condition_text = (condition or "").lower()
        matches = []
        for resource in educational_resources():
            text = " ".join(
                [
                    resource.get("topic", ""),
                    resource.get("condition", ""),
                    resource.get("title", ""),
                    " ".join(resource.get("tags", [])),
                ]
            ).lower()
            if (not condition or condition_text in text) and any(word in text for word in topic_words):
                matches.append(resource)
        return matches[:5]

    async def get_condition_trajectory(self, condition_key: str) -> dict[str, Any]:
        return condition_trajectories().get(condition_key, {"error": f"Unknown trajectory: {condition_key}"})

    async def web_search(self, query: str, allowlist: list[str] | None = None) -> list[dict[str, Any]]:
        domains = allowlist or ["gov.sg", "healthhub.sg", "aic.sg", "sgenable.sg", "moh.gov.sg"]
        if self.settings.exa_api_key:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.post(
                    "https://api.exa.ai/search",
                    headers={"x-api-key": self.settings.exa_api_key},
                    json={"query": query, "includeDomains": domains, "numResults": 5},
                )
                response.raise_for_status()
                data = response.json()
            return [{"title": item.get("title"), "url": item.get("url"), "snippet": item.get("text", "")[:300]} for item in data.get("results", [])]
        return [{"title": "Web search unavailable", "url": None, "snippet": "No Exa key configured; v1 demo uses curated data."}]

    async def create_node(self, type: str, payload: dict[str, Any], status: str = "pending_review") -> dict[str, str]:
        payload = {"patient_id": self.patient_id, **payload}
        if type == "scheduled_action":
            node_id = uuid4()
            self.pending_scheduled_actions[node_id] = {"type": type, "payload": payload, "status": status}
            return {"node_id": str(node_id), "state": "staged_until_derived_from_edge"}
        node = await self.store.create_node(type, payload, "agent", self.reasoning_log_id, status)
        return {"node_id": str(node.id), "state": "created"}

    async def create_edge(self, from_node: str, to_node: str, edge_type: str) -> dict[str, str]:
        from_id = UUID(from_node)
        to_id = UUID(to_node)
        if from_id in self.pending_scheduled_actions:
            if edge_type != "derived_from":
                return {"error": "scheduled_action must first be grounded with a derived_from edge"}
            source = await self.store.get_node(to_id)
            if not source or source.type not in ("nehr_record", "inferred_condition"):
                return {"error": "derived_from target must be a nehr_record or inferred_condition"}
            pending = self.pending_scheduled_actions.pop(from_id)
            node, edge = await self.store.create_node_with_edge(
                pending["type"], pending["payload"], "agent", self.reasoning_log_id, pending["status"], from_id, to_id, edge_type
            )
            return {"node_id": str(node.id), "edge_id": str(edge.id), "state": "created_with_provenance"}
        edge = await self.store.create_edge(from_id, to_id, edge_type)
        return {"edge_id": str(edge.id), "state": "created"}

    async def finalize(self) -> list[str]:
        errors = []
        for node_id in list(self.pending_scheduled_actions):
            errors.append(f"scheduled_action {node_id} was rejected because it had no derived_from edge")
            self.pending_scheduled_actions.pop(node_id, None)
        for error in errors:
            await self.store.append_reasoning_step(self.reasoning_log_id, {"kind": "tool_rejection", "message": error})
        return errors
