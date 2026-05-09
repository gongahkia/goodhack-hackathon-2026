import asyncio
from datetime import date
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings
from app.extraction import process_redacted_transcript
from app.models import GraphSubset
from app.notifications import build_notifications
from app.research import ResearchQuestion, ResearchSource, run_guarded_research_pipeline
from app.store import MemoryGraphStore
from app.transcript_pipeline import redact_stored_transcript


class FakeResearchAdapter:
    def __init__(self) -> None:
        self.queries: list[ResearchQuestion] = []

    async def search(self, question: ResearchQuestion, settings: Settings) -> list[ResearchSource]:
        self.queries.append(question)
        if question.source_policy == "informal":
            return [
                ResearchSource(
                    title="Caregiver forum tip about MSW paperwork",
                    url="https://www.reddit.com/r/singapore/comments/example",
                    snippet="Ask the hospital medical social worker before purchasing equipment.",
                    source_tier="informal",
                    claim_status="community_tip",
                    verification_status="needs_review",
                    retrieved_at="2026-05-09T12:00:00+00:00",
                    provider="fake",
                )
            ]
        return [
            ResearchSource(
                title="AIC mobility support",
                url="https://www.aic.sg/financial-assistance/seniors-mobility-enabling-fund/",
                snippet="Official mobility aid support information.",
                source_tier="official",
                claim_status="verified_fact",
                verification_status="safe_to_show",
                retrieved_at="2026-05-09T12:00:00+00:00",
                provider="fake",
            )
        ]


async def _research_task_from_transcript(store: MemoryGraphStore):
    transcript = await store.create_node(
        "transcript",
        {
            "patient_id": "patient-1",
            "raw_text": "Doctor said if high blood sugar continues John may need amputation, find wheelchair grants.",
        },
        "system",
        status="approved",
    )
    redaction = await redact_stored_transcript(store, transcript)
    processed = await process_redacted_transcript(store, redaction, reference_date=date(2026, 5, 9))
    task_id = processed["ad_hoc_research_tasks"][0]["id"]
    return await store.get_node(UUID(task_id))


@pytest.mark.asyncio
async def test_guarded_research_pipeline_creates_plan_guardrail_results_and_synthesis_without_pii_in_queries():
    store = MemoryGraphStore()
    task = await _research_task_from_transcript(store)
    adapter = FakeResearchAdapter()

    result = await run_guarded_research_pipeline(store, task, Settings(openai_model="gpt-5.5"), adapter)

    assert result["research_plan"]["type"] == "research_plan"
    assert result["guardrail_review"]["payload"]["decision"] == "approved"
    assert len(result["research_results"]) >= 2
    recommendation = result["synthesized_recommendation"]["payload"]
    assert recommendation["verified_facts"]
    assert recommendation["community_tips"]
    assert "Informal" not in recommendation["verified_facts"][0]
    assert all("John" not in query.query for query in adapter.queries)

    graph = await store.graph_subset("patient-1")
    edge_types = {edge.type for edge in graph.edges}
    assert {"researches", "guarded_by", "approved_research", "synthesized_from"} <= edge_types


@pytest.mark.asyncio
async def test_guardrail_blocks_speculative_research_from_simple_daily_instruction():
    store = MemoryGraphStore()
    task = await store.create_node(
        "ad_hoc_research_task",
        {
            "patient_id": "patient-1",
            "question": "Investigate why Panadol is needed",
            "question_redacted": "Investigate why Panadol is needed",
            "basis": "Give John Panadol before lunch daily",
            "basis_redacted": "Give PERSON_1 Panadol before lunch daily",
            "requires_guardrail_review": True,
        },
        "agent",
    )
    adapter = FakeResearchAdapter()

    result = await run_guarded_research_pipeline(store, task, Settings(), adapter)

    assert result["guardrail_review"]["payload"]["decision"] == "blocked"
    assert result["research_results"] == []
    assert result["synthesized_recommendation"]["status"] == "dismissed"
    assert adapter.queries == []
    updated = await store.get_node(task.id)
    assert updated.payload["source_status"] == "blocked_by_guardrail"


@pytest.mark.asyncio
async def test_recommendation_notification_is_polling_visible_after_research_completion():
    store = MemoryGraphStore()
    task = await _research_task_from_transcript(store)
    await run_guarded_research_pipeline(store, task, Settings(), FakeResearchAdapter())

    graph = GraphSubset(nodes=await store.list_nodes("patient-1"), edges=await store.list_edges())
    notifications = build_notifications(graph, await store.list_reasoning_logs())

    assert any(item["kind"] == "research result ready" for item in notifications)


def test_research_task_endpoint_runs_guarded_pipeline(monkeypatch):
    store = MemoryGraphStore()

    async def fake_init():
        return None

    store.init = fake_init
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "settings", Settings(legacy_demo_enabled=False, scheduled_review_enabled=False))

    async def seed():
        task = await store.create_node(
            "ad_hoc_research_task",
            {
                "patient_id": "mdm-tan",
                "question": "What wheelchair grants are available?",
                "question_redacted": "What wheelchair grants are available?",
                "basis": "Doctor said wheelchair may be needed.",
                "basis_redacted": "Doctor said wheelchair may be needed.",
                "requires_guardrail_review": True,
            },
            "agent",
        )
        return task.id

    async def fake_pipeline(store_arg, task, settings):
        rec = await store_arg.create_node(
            "synthesized_recommendation",
            {"patient_id": "mdm-tan", "title": "Research result ready", "summary": "Done"},
            "agent",
            status="pending_review",
        )
        return {"synthesized_recommendation": rec.model_dump(mode="json")}

    task_id = asyncio.run(seed())
    monkeypatch.setattr(main, "run_guarded_research_pipeline", fake_pipeline)

    with TestClient(main.app) as client:
        response = client.post(f"/research/tasks/{task_id}/run")
        recommendations = client.get("/recommendations")

    assert response.status_code == 200
    assert response.json()["synthesized_recommendation"]["payload"]["title"] == "Research result ready"
    assert recommendations.status_code == 200
    assert recommendations.json()[0]["payload"]["summary"] == "Done"
