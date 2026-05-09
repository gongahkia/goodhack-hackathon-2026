from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from ..config import Settings
from ..data import condition_trajectories, educational_resources, grants_database
from ..privacy import PiiRedactor
from ..store import GraphStore
from ..v2 import (
    exa_search_web,
    jina_read_url,
    jina_rerank_documents,
    normalize_scheduling_payload,
    openalex_search_works,
    search_verified_resources,
    sealion_guard_check,
    sealion_regional_review,
    semantic_scholar_search_papers,
    tinyfish_fetch_urls,
    tinyfish_search_web,
)


class AgentToolbox:
    def __init__(self, store: GraphStore, settings: Settings, patient_id: str, reasoning_log_id: UUID, pii_redactor: PiiRedactor | None = None) -> None:
        self.store = store
        self.settings = settings
        self.patient_id = patient_id
        self.reasoning_log_id = reasoning_log_id
        self.pii_redactor = pii_redactor
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
                "description": "Unified allowlisted web search with curated fallback. Use when you need an external resource or grant source and do not need to choose a provider directly.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}, "allowlist": {"type": ["array", "null"], "items": {"type": "string"}}},
                    "required": ["query"],
                },
            },
            {
                "type": "function",
                "name": "exa_search",
                "description": "First-class Exa semantic web search over allowlisted domains. Use for high-quality semantic retrieval, current official pages, research-style lookups, and source discovery.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "allowlist": {"type": ["array", "null"], "items": {"type": "string"}},
                        "num_results": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                        "search_type": {"type": "string", "enum": ["auto", "fast", "deep", "neural"], "default": "auto"},
                    },
                    "required": ["query"],
                },
            },
            {
                "type": "function",
                "name": "tinyfish_search",
                "description": "First-class TinyFish browser-rendered live search over allowlisted domains. Use for fresh, dynamic, or fast-changing pages where rendered search results are useful.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "allowlist": {"type": ["array", "null"], "items": {"type": "string"}},
                        "location": {"type": "string", "default": "SG"},
                        "language": {"type": "string", "default": "en"},
                    },
                    "required": ["query"],
                },
            },
            {
                "type": "function",
                "name": "tinyfish_fetch",
                "description": "Fetch clean markdown from allowlisted URLs with TinyFish Fetch. Use after Exa or TinyFish search when snippets are not enough and you need page content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "urls": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 10},
                        "allowlist": {"type": ["array", "null"], "items": {"type": "string"}},
                        "format": {"type": "string", "enum": ["markdown", "html", "json"], "default": "markdown"},
                    },
                    "required": ["urls"],
                },
            },
            {
                "type": "function",
                "name": "jina_read_url",
                "description": "Use Jina Reader to convert an allowlisted URL into LLM-friendly text. Use for cleaner extraction when TinyFish snippets or fetch output are not enough.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "allowlist": {"type": ["array", "null"], "items": {"type": "string"}},
                        "max_chars": {"type": "integer", "minimum": 500, "maximum": 12000, "default": 5000},
                    },
                    "required": ["url"],
                },
            },
            {
                "type": "function",
                "name": "jina_rerank",
                "description": "Use Jina Reranker to rank retrieved snippets or paper summaries by relevance before deciding which sources to trust or read.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "documents": {"type": "array", "items": {"type": ["string", "object"]}, "minItems": 1, "maxItems": 20},
                        "top_n": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                        "model": {"type": "string", "default": "jina-reranker-v3"},
                    },
                    "required": ["query", "documents"],
                },
            },
            {
                "type": "function",
                "name": "openalex_search",
                "description": "Search OpenAlex scholarly works for offline evidence/evaluation support. Use to audit whether trajectories or recommendations have external research support, not to create direct care actions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "per_page": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                        "publication_year_from": {"type": ["integer", "null"]},
                    },
                    "required": ["query"],
                },
            },
            {
                "type": "function",
                "name": "semantic_scholar_search",
                "description": "Search Semantic Scholar papers for research/evaluation context. Use for citations, abstracts, TLDRs, and open-access paper links; do not turn papers directly into patient instructions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                        "year": {"type": ["string", "null"]},
                    },
                    "required": ["query"],
                },
            },
            {
                "type": "function",
                "name": "sealion_regional_review",
                "description": "Use SEA-LION as a Southeast Asia-aware language and cultural review helper. Best for Singlish, Malay, Tamil, Chinese, or caregiver-facing wording checks. Inputs are kept redacted when privacy redaction is active.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "task": {"type": "string", "default": "caregiver_language_review"},
                        "target_language": {"type": "string", "default": "English"},
                        "max_tokens": {"type": "integer", "minimum": 100, "maximum": 1000, "default": 500},
                    },
                    "required": ["text"],
                },
            },
            {
                "type": "function",
                "name": "sealion_guard_check",
                "description": "Use SEA-Guard through SEA-LION API as a secondary safety classifier for caregiver-facing prompts or responses. Inputs are kept redacted when privacy redaction is active.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "response": {"type": ["string", "null"]},
                    },
                    "required": ["prompt"],
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
        local_args = args if name in self._redacted_external_tools() else self.pii_redactor.restore_placeholders(args) if self.pii_redactor else args
        result = await getattr(self, name)(**local_args)
        model_result = self.pii_redactor.redact(result) if self.pii_redactor else result
        await self.store.append_reasoning_step(self.reasoning_log_id, {"kind": "tool_result", "tool": name, "result": model_result})
        return model_result

    def _redacted_external_tools(self) -> set[str]:
        return {
            "exa_search",
            "tinyfish_search",
            "tinyfish_fetch",
            "jina_read_url",
            "jina_rerank",
            "openalex_search",
            "semantic_scholar_search",
            "sealion_regional_review",
            "sealion_guard_check",
        }

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
        return await search_verified_resources(query, self.settings, allowlist)

    async def exa_search(
        self,
        query: str,
        allowlist: list[str] | None = None,
        num_results: int = 5,
        search_type: str = "auto",
    ) -> dict[str, Any]:
        return await exa_search_web(query, self.settings, allowlist, num_results, search_type)

    async def tinyfish_search(
        self,
        query: str,
        allowlist: list[str] | None = None,
        location: str = "SG",
        language: str = "en",
    ) -> dict[str, Any]:
        return await tinyfish_search_web(query, self.settings, allowlist, location, language)

    async def tinyfish_fetch(self, urls: list[str], allowlist: list[str] | None = None, format: str = "markdown") -> dict[str, Any]:
        return await tinyfish_fetch_urls(urls, self.settings, allowlist, format)

    async def jina_read_url(self, url: str, allowlist: list[str] | None = None, max_chars: int = 5000) -> dict[str, Any]:
        return await jina_read_url(url, self.settings, allowlist, max_chars)

    async def jina_rerank(
        self,
        query: str,
        documents: list[str | dict[str, Any]],
        top_n: int = 5,
        model: str = "jina-reranker-v3",
    ) -> dict[str, Any]:
        return await jina_rerank_documents(query, documents, self.settings, top_n, model)

    async def openalex_search(
        self,
        query: str,
        per_page: int = 5,
        publication_year_from: int | None = None,
    ) -> dict[str, Any]:
        return await openalex_search_works(query, self.settings, per_page, publication_year_from)

    async def semantic_scholar_search(self, query: str, limit: int = 5, year: str | None = None) -> dict[str, Any]:
        return await semantic_scholar_search_papers(query, self.settings, limit, year)

    async def sealion_regional_review(
        self,
        text: str,
        task: str = "caregiver_language_review",
        target_language: str = "English",
        max_tokens: int = 500,
    ) -> dict[str, Any]:
        return await sealion_regional_review(text, self.settings, task, target_language, max_tokens)

    async def sealion_guard_check(self, prompt: str, response: str | None = None) -> dict[str, Any]:
        return await sealion_guard_check(prompt, self.settings, response)

    async def create_node(self, type: str, payload: dict[str, Any], status: str = "pending_review") -> dict[str, str]:
        payload = {"patient_id": self.patient_id, **payload}
        if type == "scheduled_action":
            payload = normalize_scheduling_payload(payload)
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
            if not source or source.type not in ("nehr_record", "inferred_condition", "caregiver_note", "care_intent", "decision_forecast"):
                return {"error": "derived_from target must be a nehr_record, inferred_condition, caregiver_note, care_intent, or decision_forecast"}
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
