from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .config import Settings
from .models import Node
from .store import GraphStore
from .v2 import exa_search_web, search_verified_grants, search_verified_resources, tinyfish_search_web


SourceTier = Literal["official", "high_trust", "informal"]
ClaimStatus = Literal["verified_fact", "needs_verification", "community_tip", "rejected_or_unsafe"]
GuardrailDecision = Literal["approved", "narrowed", "blocked"]


OFFICIAL_DOMAINS = ["gov.sg", "moh.gov.sg", "aic.sg", "healthhub.sg", "cpf.gov.sg", "msf.gov.sg", "sgenable.sg"]
HIGH_TRUST_DOMAINS = ["ttsh.com.sg", "nuhs.edu.sg", "singhealth.com.sg", "sgh.com.sg", "snec.com.sg", "straitstimes.com"]
INFORMAL_DOMAINS = ["reddit.com", "forums.hardwarezone.com.sg", "blogspot.com", "wordpress.com"]


class ResearchQuestion(BaseModel):
    query: str
    source_policy: SourceTier
    rationale: str
    tools: list[str] = Field(default_factory=list)


class ResearchPlan(BaseModel):
    task_id: str
    planner_model: str
    questions: list[ResearchQuestion]
    redacted_basis: str


class GuardrailReview(BaseModel):
    decision: GuardrailDecision
    allowed_questions: list[ResearchQuestion] = Field(default_factory=list)
    blocked_questions: list[ResearchQuestion] = Field(default_factory=list)
    medical_advice_risk: bool = False
    unsupported_eligibility_risk: bool = False
    reason: str


class ResearchSource(BaseModel):
    title: str
    url: str | None = None
    snippet: str = ""
    source_tier: SourceTier
    claim_status: ClaimStatus
    verification_status: str = "needs_review"
    retrieved_at: str
    provider: str


class RecommendationCard(BaseModel):
    title: str
    summary: str
    verified_facts: list[str] = Field(default_factory=list)
    community_tips: list[str] = Field(default_factory=list)
    needs_verification: list[str] = Field(default_factory=list)
    rejected_or_unsafe: list[str] = Field(default_factory=list)
    evidence: list[ResearchSource] = Field(default_factory=list)


class ResearchToolAdapter(Protocol):
    async def search(self, question: ResearchQuestion, settings: Settings) -> list[ResearchSource]: ...


@dataclass
class DefaultResearchToolAdapter:
    async def search(self, question: ResearchQuestion, settings: Settings) -> list[ResearchSource]:
        domains = _domains_for_tier(question.source_policy)
        results: list[ResearchSource] = []
        if question.source_policy == "official":
            for item in await search_verified_grants(question.query, settings, domains):
                results.append(_source_from_result(item, "curated_or_live_grants", "official"))
            for item in await search_verified_resources(question.query, settings, domains):
                results.append(_source_from_result(item, "curated_or_live_resources", "official"))
        else:
            exa = await exa_search_web(question.query, settings, domains, num_results=5)
            tiny = await tinyfish_search_web(question.query, settings, domains)
            for item in [*exa.get("results", []), *tiny.get("results", [])]:
                results.append(_source_from_result(item, str(item.get("provider") or exa.get("provider") or tiny.get("provider")), question.source_policy))
        return _dedupe_sources(results)


async def run_guarded_research_pipeline(
    store: GraphStore,
    task: Node,
    settings: Settings,
    tool_adapter: ResearchToolAdapter | None = None,
) -> dict[str, Any]:
    if task.type != "ad_hoc_research_task":
        raise ValueError("Can only run research for ad_hoc_research_task nodes")
    patient_id = str(task.payload.get("patient_id") or "")
    log = await store.create_reasoning_log(f"guarded_research:{task.id}")

    plan = plan_research(task, settings)
    plan_node = await store.create_node(
        "research_plan",
        {"patient_id": patient_id, "ad_hoc_research_task_id": str(task.id), **plan.model_dump(mode="json")},
        "agent",
        reasoning_log_id=log.id,
        status="pending_review",
    )
    await store.create_edge(plan_node.id, task.id, "researches")
    await store.append_reasoning_step(log.id, {"kind": "research_planner_proposal", "research_plan_id": str(plan_node.id), "question_count": len(plan.questions)})

    guardrail = audit_research_plan(task, plan)
    guardrail_node = await store.create_node(
        "guardrail_review",
        {"patient_id": patient_id, "research_plan_id": str(plan_node.id), **guardrail.model_dump(mode="json")},
        "agent",
        reasoning_log_id=log.id,
        status="approved" if guardrail.decision in {"approved", "narrowed"} else "dismissed",
    )
    await store.create_edge(plan_node.id, guardrail_node.id, "guarded_by")
    await store.create_edge(guardrail_node.id, plan_node.id, "approved_research" if guardrail.decision in {"approved", "narrowed"} else "blocked_research")
    await store.append_reasoning_step(log.id, {"kind": "guardrail_review", "guardrail_review_id": str(guardrail_node.id), "decision": guardrail.decision, "reason": guardrail.reason})

    if guardrail.decision == "blocked":
        recommendation = await _create_blocked_recommendation(store, patient_id, task, guardrail, guardrail_node, log.id)
        await store.update_node_payload(task.id, {"source_status": "blocked_by_guardrail"}, "dismissed")
        await store.finish_reasoning_log(log.id, "Research blocked by guardrail.")
        return _result(plan_node, guardrail_node, [], recommendation)

    adapter = tool_adapter or DefaultResearchToolAdapter()
    research_result_nodes = []
    all_sources: list[ResearchSource] = []
    for question in guardrail.allowed_questions:
        sources = await adapter.search(question, settings)
        all_sources.extend(sources)
        result_node = await store.create_node(
            "research_result",
            {
                "patient_id": patient_id,
                "research_plan_id": str(plan_node.id),
                "query": question.query,
                "source_policy": question.source_policy,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "sources": [source.model_dump(mode="json") for source in sources],
            },
            "system",
            reasoning_log_id=log.id,
            status="approved" if sources else "clarification_required",
        )
        await store.create_edge(result_node.id, plan_node.id, "researches")
        research_result_nodes.append(result_node)
        await store.append_reasoning_step(log.id, {"kind": "research_tool_call", "query": question.query, "source_policy": question.source_policy, "source_count": len(sources)})

    recommendation_card = synthesize_recommendation(task, guardrail, all_sources)
    recommendation_node = await store.create_node(
        "synthesized_recommendation",
        {
            "patient_id": patient_id,
            "ad_hoc_research_task_id": str(task.id),
            **recommendation_card.model_dump(mode="json"),
        },
        "agent",
        reasoning_log_id=log.id,
        status="pending_review",
    )
    for result_node in research_result_nodes:
        await store.create_edge(recommendation_node.id, result_node.id, "synthesized_from")
    await store.update_node_payload(task.id, {"source_status": "research_completed", "recommendation_id": str(recommendation_node.id)}, "approved")
    await store.append_reasoning_step(log.id, {"kind": "synthesis_model_output", "recommendation_id": str(recommendation_node.id), "evidence_count": len(all_sources)})
    await store.finish_reasoning_log(log.id, "Guarded research completed.")
    return _result(plan_node, guardrail_node, research_result_nodes, recommendation_node)


def plan_research(task: Node, settings: Settings) -> ResearchPlan:
    redacted_basis = str(task.payload.get("basis_redacted") or task.payload.get("question_redacted") or task.payload.get("question") or "")
    query = str(task.payload.get("question_redacted") or task.payload.get("question") or redacted_basis)
    questions = [
        ResearchQuestion(
            query=f"{query} Singapore official grant subsidy eligibility",
            source_policy="official",
            rationale="Verify statutory-board, grant, subsidy, eligibility, and application facts from official sources.",
            tools=["curated", "exa", "tinyfish"],
        )
    ]
    if any(word in query.lower() for word in ("wheelchair", "equipment", "amputation", "mobility", "caregiver")):
        questions.append(
            ResearchQuestion(
                query=f"{query} Singapore hospital charity caregiver support",
                source_policy="high_trust",
                rationale="Look for high-trust institutional or news context without treating it as final eligibility evidence.",
                tools=["exa", "tinyfish"],
            )
        )
        questions.append(
            ResearchQuestion(
                query=f"{query} Singapore caregiver forum reddit practical tips",
                source_policy="informal",
                rationale="Surface lived-experience leads that must be clearly labeled for user judgment.",
                tools=["exa", "tinyfish"],
            )
        )
    return ResearchPlan(task_id=str(task.id), planner_model=settings.openai_model, questions=questions, redacted_basis=redacted_basis)


def audit_research_plan(task: Node, plan: ResearchPlan) -> GuardrailReview:
    text = f"{plan.redacted_basis} {' '.join(question.query for question in plan.questions)}".lower()
    basis_text = plan.redacted_basis.lower()
    basis_substantive = any(cue in basis_text for cue in ("grant", "subsidy", "wheelchair", "equipment", "amputation", "mobility", "support"))
    basis_simple_daily = any(cue in basis_text for cue in ("panadol", "medicine", "daily", "before lunch")) and not basis_substantive
    if basis_simple_daily:
        return GuardrailReview(
            decision="blocked",
            blocked_questions=plan.questions,
            medical_advice_risk=True,
            unsupported_eligibility_risk=True,
            reason="Blocked because the source transcript is only a simple daily medication instruction.",
        )
    substantive_basis = any(cue in text for cue in ("grant", "subsidy", "wheelchair", "equipment", "amputation", "mobility", "support"))
    explicit_basis = substantive_basis or any(cue in text for cue in ("research", "find", "look up"))
    simple_daily_only = any(cue in text for cue in ("panadol", "medicine", "daily", "before lunch")) and not substantive_basis
    if simple_daily_only or not explicit_basis:
        return GuardrailReview(
            decision="blocked",
            blocked_questions=plan.questions,
            medical_advice_risk=True,
            unsupported_eligibility_risk=True,
            reason="Blocked because the plan lacks explicit future risk, grant, equipment, policy, or user research basis.",
        )
    allowed = []
    for question in plan.questions:
        if question.source_policy == "informal":
            allowed.append(question.model_copy(update={"rationale": f"{question.rationale} Informal sources may only create community_tip or needs_verification claims."}))
        else:
            allowed.append(question)
    return GuardrailReview(
        decision="approved",
        allowed_questions=allowed,
        unsupported_eligibility_risk=True,
        reason="Approved with source-tier enforcement and no direct medical advice generation.",
    )


def synthesize_recommendation(task: Node, guardrail: GuardrailReview, sources: list[ResearchSource]) -> RecommendationCard:
    if guardrail.decision == "blocked":
        return RecommendationCard(
            title="Research blocked for safety",
            summary=guardrail.reason,
            rejected_or_unsafe=[guardrail.reason],
            evidence=[],
        )
    verified = [source for source in sources if source.claim_status == "verified_fact"]
    informal = [source for source in sources if source.claim_status == "community_tip"]
    needs = [source for source in sources if source.claim_status == "needs_verification"]
    title = "Research result ready"
    if "wheelchair" in str(task.payload.get("question") or "").lower():
        title = "Wheelchair and mobility support research"
    summary = "Review verified sources first. Informal sources are included only as practical leads, not eligibility or medical advice."
    return RecommendationCard(
        title=title,
        summary=summary,
        verified_facts=[_claim_from_source(source) for source in verified[:5]],
        community_tips=[_claim_from_source(source) for source in informal[:5]],
        needs_verification=[_claim_from_source(source) for source in needs[:5]],
        rejected_or_unsafe=[],
        evidence=sources[:10],
    )


async def _create_blocked_recommendation(
    store: GraphStore,
    patient_id: str,
    task: Node,
    guardrail: GuardrailReview,
    guardrail_node: Node,
    reasoning_log_id,
) -> Node:
    card = synthesize_recommendation(task, guardrail, [])
    node = await store.create_node(
        "synthesized_recommendation",
        {"patient_id": patient_id, "ad_hoc_research_task_id": str(task.id), **card.model_dump(mode="json")},
        "agent",
        reasoning_log_id=reasoning_log_id,
        status="dismissed",
    )
    await store.create_edge(node.id, guardrail_node.id, "synthesized_from")
    return node


def _source_from_result(item: dict[str, Any], provider: str, requested_tier: SourceTier) -> ResearchSource:
    url = item.get("url")
    tier = _source_tier(str(url or ""), requested_tier)
    return ResearchSource(
        title=str(item.get("title") or "Untitled source"),
        url=str(url) if url else None,
        snippet=str(item.get("snippet") or ""),
        source_tier=tier,
        claim_status=_claim_status(tier, item),
        verification_status=str(item.get("verification_status") or "needs_review"),
        retrieved_at=str(item.get("retrieved_at") or datetime.now(UTC).isoformat()),
        provider=provider,
    )


def _source_tier(url: str, requested_tier: SourceTier) -> SourceTier:
    domain = _domain(url)
    if any(domain == allowed or domain.endswith(f".{allowed}") for allowed in OFFICIAL_DOMAINS):
        return "official"
    if any(domain == allowed or domain.endswith(f".{allowed}") for allowed in HIGH_TRUST_DOMAINS):
        return "high_trust"
    if any(domain == allowed or domain.endswith(f".{allowed}") for allowed in INFORMAL_DOMAINS):
        return "informal"
    return requested_tier


def _claim_status(tier: SourceTier, item: dict[str, Any]) -> ClaimStatus:
    if str(item.get("verification_status")) == "reject":
        return "rejected_or_unsafe"
    if tier in {"official", "high_trust"}:
        return "verified_fact"
    if tier == "informal":
        return "community_tip"
    return "needs_verification"


def _domains_for_tier(tier: SourceTier) -> list[str]:
    if tier == "official":
        return OFFICIAL_DOMAINS
    if tier == "high_trust":
        return [*OFFICIAL_DOMAINS, *HIGH_TRUST_DOMAINS]
    return [*OFFICIAL_DOMAINS, *HIGH_TRUST_DOMAINS, *INFORMAL_DOMAINS]


def _domain(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _dedupe_sources(sources: list[ResearchSource]) -> list[ResearchSource]:
    deduped: dict[str, ResearchSource] = {}
    for source in sources:
        key = source.url or source.title
        deduped.setdefault(key, source)
    return list(deduped.values())


def _claim_from_source(source: ResearchSource) -> str:
    label = source.title
    if source.source_tier == "informal":
        return f"Community lead: {label}. Verify before acting."
    if source.source_tier == "high_trust":
        return f"High-trust reference: {label}."
    return f"Verified source: {label}."


def _result(plan_node: Node, guardrail_node: Node, research_result_nodes: list[Node], recommendation_node: Node) -> dict[str, Any]:
    return {
        "research_plan": plan_node.model_dump(mode="json"),
        "guardrail_review": guardrail_node.model_dump(mode="json"),
        "research_results": [node.model_dump(mode="json") for node in research_result_nodes],
        "synthesized_recommendation": recommendation_node.model_dump(mode="json"),
    }
