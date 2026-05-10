from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from .config import Settings
from .data import singapore_support_corpus
from .models import Node
from .privacy import PiiRedactor
from .sealion_reviews import maybe_secondary_research_guardrail_with_sealion
from .security import sanitize_provider_error, vendor_allowed
from .store import GraphStore
from .v2 import exa_search_web, search_verified_grants, search_verified_resources, tinyfish_fetch_urls, tinyfish_search_web


SourceTier = Literal["official", "high_trust", "informal"]
ClaimStatus = Literal["verified_fact", "needs_verification", "community_tip", "rejected_or_unsafe"]
GuardrailDecision = Literal["approved", "narrowed", "blocked"]


OFFICIAL_DOMAINS = ["gov.sg", "moh.gov.sg", "aic.sg", "healthhub.sg", "cpf.gov.sg", "msf.gov.sg", "sgenable.sg"]
HIGH_TRUST_DOMAINS = ["ttsh.com.sg", "nuhs.edu.sg", "singhealth.com.sg", "sgh.com.sg", "snec.com.sg", "straitstimes.com"]
INFORMAL_DOMAINS = ["reddit.com", "forums.hardwarezone.com.sg", "blogspot.com", "wordpress.com"]
RESEARCH_FETCH_MAX_URLS = 6
RESEARCH_PAGE_MAX_CHARS = 12000


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


class ResearchExtraction(BaseModel):
    summary: str = ""
    relevance_status: str = "unclear"
    verified_facts: list[str] = Field(default_factory=list)
    eligibility_criteria: list[str] = Field(default_factory=list)
    support_amounts: list[str] = Field(default_factory=list)
    required_documents: list[str] = Field(default_factory=list)
    application_steps: list[str] = Field(default_factory=list)
    contact_or_links: list[str] = Field(default_factory=list)
    community_tips: list[str] = Field(default_factory=list)
    needs_verification: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    error: str | None = None
    extraction_provider: str = "none"
    extraction_model: str | None = None
    extracted_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ResearchSource(BaseModel):
    title: str
    url: str | None = None
    snippet: str = ""
    source_tier: SourceTier
    claim_status: ClaimStatus
    verification_status: str = "needs_review"
    retrieved_at: str
    provider: str
    content_provider: str | None = None
    content_retrieved_at: str | None = None
    content_length: int | None = None
    extraction_status: str = "snippet_only"
    extraction_error: str | None = None
    extraction: ResearchExtraction | None = None


class RecommendationCard(BaseModel):
    title: str
    summary: str
    verified_facts: list[str] = Field(default_factory=list)
    eligibility_criteria: list[str] = Field(default_factory=list)
    support_amounts: list[str] = Field(default_factory=list)
    required_documents: list[str] = Field(default_factory=list)
    application_steps: list[str] = Field(default_factory=list)
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
        results: list[ResearchSource] = _search_curated_corpus(question)
        if question.source_policy == "official":
            for item in await search_verified_grants(question.query, settings, domains):
                results.append(_source_from_result(item, "curated_or_live_grants", "official"))
            for item in await search_verified_resources(question.query, settings, domains):
                results.append(_source_from_result(item, "curated_or_live_resources", "official"))
        results.extend(await _search_live_web(question, settings, domains))
        return await _enrich_sources_with_page_research(question, _dedupe_sources(results), settings, domains)


@dataclass(frozen=True)
class ExtractionAttempt:
    extraction: ResearchExtraction | None = None
    error: str | None = None


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

    secondary_guardrail_node = await maybe_secondary_research_guardrail_with_sealion(
        store,
        patient_id,
        task,
        plan_node,
        guardrail_node,
        settings,
        log.id,
    )

    if secondary_guardrail_node and secondary_guardrail_node.payload.get("decision") == "blocked":
        secondary_reason = _secondary_block_reason(secondary_guardrail_node)
        blocked_review = GuardrailReview(
            decision="blocked",
            blocked_questions=guardrail.allowed_questions,
            medical_advice_risk=bool((secondary_guardrail_node.payload.get("result") or {}).get("medical_advice_risk")),
            unsupported_eligibility_risk=True,
            reason=secondary_reason,
        )
        recommendation = await _create_blocked_recommendation(store, patient_id, task, blocked_review, secondary_guardrail_node, log.id)
        await store.update_node_payload(plan_node.id, {"sealion_block_reason": secondary_reason}, "dismissed")
        await store.update_node_payload(task.id, {"source_status": "blocked_by_sealion_guardrail"}, "dismissed")
        await store.append_reasoning_step(log.id, {"kind": "sealion_secondary_block", "reason": secondary_reason})
        await store.finish_reasoning_log(log.id, "Research blocked by Sealion secondary guardrail.")
        return _result(plan_node, guardrail_node, [], recommendation, secondary_guardrail_node)

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
        await store.append_reasoning_step(
            log.id,
            {
                "kind": "research_tool_call",
                "query": question.query,
                "source_policy": question.source_policy,
                "source_count": len(sources),
                "fetch_count": sum(1 for source in sources if source.content_provider),
                "llm_extraction_count": sum(1 for source in sources if source.extraction_status == "llm_extracted"),
                "local_extraction_count": sum(1 for source in sources if source.extraction_status == "local_extracted"),
                "relevant_extraction_count": sum(1 for source in sources if source.extraction and source.extraction.relevance_status == "relevant"),
                "extraction_errors": [
                    {"url": source.url, "status": source.extraction_status, "error": source.extraction_error or source.extraction.error}
                    for source in sources
                    if source.extraction_error or (source.extraction and source.extraction.error)
                ][:5],
            },
        )

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
    return _result(plan_node, guardrail_node, research_result_nodes, recommendation_node, secondary_guardrail_node)


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
    extracted_count = sum(1 for source in sources if source.extraction_status in {"llm_extracted", "local_extracted"} and _usable_extraction(source.extraction))
    summary = (
        "Fetched source pages were reviewed for eligibility criteria, amounts, documents, and application steps. "
        "Informal sources are included only as practical leads, not eligibility or medical advice."
        if extracted_count
        else "Review verified sources first. Informal sources are included only as practical leads, not eligibility or medical advice."
    )
    return RecommendationCard(
        title=title,
        summary=summary,
        verified_facts=_extracted_items(verified, "verified_facts", 6) or [_claim_from_source(source) for source in verified[:5]],
        eligibility_criteria=_extracted_items(verified, "eligibility_criteria", 6),
        support_amounts=_extracted_items(verified, "support_amounts", 5),
        required_documents=_extracted_items(verified, "required_documents", 6),
        application_steps=_extracted_items(verified, "application_steps", 6),
        community_tips=_extracted_items(informal, "community_tips", 5) or [_claim_from_source(source) for source in informal[:5]],
        needs_verification=[
            *_extracted_items(sources, "needs_verification", 5, include_unusable=True),
            *_extracted_items(sources, "caveats", 5, include_unusable=True),
            *[_claim_from_source(source) for source in needs[:5]],
        ][:8],
        rejected_or_unsafe=[],
        evidence=sources[:10],
    )


def _secondary_block_reason(secondary_node: Node) -> str:
    result = secondary_node.payload.get("result") if isinstance(secondary_node.payload, dict) else None
    concerns = result.get("concerns") if isinstance(result, dict) else None
    if isinstance(concerns, list) and concerns:
        return f"Blocked by Sealion secondary guardrail: {' '.join(str(item) for item in concerns)[:400]}"
    notes = result.get("notes") if isinstance(result, dict) else None
    if isinstance(notes, str) and notes.strip():
        return f"Blocked by Sealion secondary guardrail: {notes.strip()[:400]}"
    return "Blocked by Sealion secondary guardrail due to elevated risk."


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
        key = f"{source.provider}:{source.url or source.title}"
        deduped.setdefault(key, source)
    return list(deduped.values())


async def _search_live_web(question: ResearchQuestion, settings: Settings, domains: list[str]) -> list[ResearchSource]:
    sources: list[ResearchSource] = []
    exa = await exa_search_web(question.query, settings, domains, num_results=5)
    tiny = await tinyfish_search_web(question.query, settings, domains)
    for item in exa.get("results", []):
        sources.append(_source_from_result(item, str(item.get("provider") or exa.get("provider") or "exa"), question.source_policy))
    for item in tiny.get("results", []):
        sources.append(_source_from_result(item, str(item.get("provider") or tiny.get("provider") or "tinyfish_search"), question.source_policy))
    return sources


async def _enrich_sources_with_page_research(
    question: ResearchQuestion,
    sources: list[ResearchSource],
    settings: Settings,
    domains: list[str],
) -> list[ResearchSource]:
    candidates = _rank_fetch_candidates([
        source
        for source in sources
        if source.url and source.verification_status != "reject" and source.claim_status != "rejected_or_unsafe"
    ])[:RESEARCH_FETCH_MAX_URLS]
    if not candidates:
        return sources

    urls = list(dict.fromkeys(str(source.url) for source in candidates if source.url))
    fetched = await tinyfish_fetch_urls(urls, settings, domains, format="markdown")
    if not isinstance(fetched, dict):
        return sources
    fetched_results = fetched.get("results")
    if not isinstance(fetched_results, list) or not fetched_results:
        status = "fetch_unavailable" if fetched.get("configured") is False else "fetch_failed"
        return [
            source.model_copy(update={"extraction_status": status, "extraction_error": str(fetched.get("error") or "")[:300] or None})
            if source in candidates
            else source
            for source in sources
        ]

    pages_by_url = _fetched_pages_by_url(fetched_results)
    pages_by_source_key: dict[str, dict[str, Any]] = {}
    for source in candidates:
        fetched_page = _fetched_page_for_source(source, pages_by_url)
        text = _clean_page_text(fetched_page.get("text") if fetched_page else None)
        if not fetched_page or not text:
            continue
        pages_by_source_key[_source_key(source)] = {
            "url": source.url,
            "title": source.title,
            "source_provider": source.provider,
            "source_tier": source.source_tier,
            "claim_status": source.claim_status,
            "text": text,
            "content_length": len(text),
            "content_retrieved_at": datetime.now(UTC).isoformat(),
            "content_provider": str(fetched.get("provider") or "tinyfish_fetch"),
        }

    if not pages_by_source_key:
        return sources

    llm_extractions = await _extract_research_pages_with_openai(question, list(pages_by_source_key.values()), settings)
    enriched: list[ResearchSource] = []
    for source in sources:
        page = pages_by_source_key.get(_source_key(source))
        if not page:
            enriched.append(source)
            continue
        extraction_result = llm_extractions.get(_source_key(source))
        extraction = extraction_result.extraction if extraction_result else None
        status = "llm_extracted"
        error = None
        if not extraction:
            extraction = _extract_research_page_locally(source, str(page.get("text") or ""))
            status = "local_extracted"
            error = extraction_result.error if extraction_result else "OpenAI research extraction was unavailable or returned no usable extraction."
        enriched.append(
            source.model_copy(
                update={
                    "content_provider": page["content_provider"],
                    "content_retrieved_at": page["content_retrieved_at"],
                    "content_length": page["content_length"],
                    "extraction_status": status,
                    "extraction_error": error,
                    "extraction": extraction,
                }
            )
        )
    return enriched


async def _extract_research_pages_with_openai(
    question: ResearchQuestion,
    pages: list[dict[str, Any]],
    settings: Settings,
) -> dict[str, ExtractionAttempt]:
    if not pages or settings.use_scripted_agent:
        return {}
    if not vendor_allowed(settings, "openai", "research_extraction"):
        return {}

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    attempts: dict[str, ExtractionAttempt] = {}
    for page in pages:
        key = _page_source_key(page)
        attempts[key] = await _extract_single_research_page_with_openai(question, page, settings, client)
    return attempts


async def _extract_single_research_page_with_openai(
    question: ResearchQuestion,
    page: dict[str, Any],
    settings: Settings,
    client: AsyncOpenAI,
) -> ExtractionAttempt:
    payload = PiiRedactor(redact_age=False).redact(
        {
            "research_question": question.model_dump(mode="json"),
            "source": {
                "url": page["url"],
                "title": page["title"],
                "source_tier": page["source_tier"],
                "claim_status": page["claim_status"],
                "page_text": str(page["text"])[:RESEARCH_PAGE_MAX_CHARS],
            },
        }
    )
    try:
        response = await client.responses.create(
            model=settings.openai_model,
            instructions=(
                "Extract structured caregiver support research from one fetched page. "
                "Use only source.page_text, not search snippets or prior knowledge. "
                "Return one compact JSON object only with keys: url, relevance_status, summary, "
                "verified_facts, eligibility_criteria, support_amounts, required_documents, application_steps, "
                "contact_or_links, community_tips, needs_verification, caveats. "
                "relevance_status must be relevant, not_relevant, error_page, or unclear. "
                "Use error_page for 404/not-found/login/scam-warning pages that do not contain the requested research details. "
                "Use at most 4 short items per list and keep each item under 25 words. "
                "Paraphrase; do not give medical advice; leave a list empty when the page does not state it."
            ),
            input=json.dumps(payload, ensure_ascii=False, default=str),
            max_output_tokens=1800,
        )
        raw = getattr(response, "output_text", "") or "{}"
        parsed = _parse_json_object(raw)
        incomplete = getattr(response, "incomplete_details", None)
    except Exception as exc:
        return ExtractionAttempt(error=f"OpenAI research extraction failed: {sanitize_research_error(exc)}")

    if incomplete:
        return ExtractionAttempt(error=f"OpenAI research extraction incomplete: {incomplete}")
    if not parsed:
        return ExtractionAttempt(error="OpenAI research extraction returned invalid or empty JSON.")

    extraction = _research_extraction_from_payload(parsed, settings)
    if not _extraction_has_content(extraction):
        return ExtractionAttempt(error="OpenAI research extraction returned no usable fields.")
    return ExtractionAttempt(extraction=extraction)


def _research_extraction_from_payload(item: dict[str, Any], settings: Settings) -> ResearchExtraction:
    relevance = str(item.get("relevance_status") or "unclear").strip().lower()
    if relevance not in {"relevant", "not_relevant", "error_page", "unclear"}:
        relevance = "unclear"
    return ResearchExtraction(
        summary=_trim_text(item.get("summary"), 500),
        relevance_status=relevance,
        verified_facts=_clean_items(item.get("verified_facts"), 6),
        eligibility_criteria=_clean_items(item.get("eligibility_criteria"), 6),
        support_amounts=_clean_items(item.get("support_amounts"), 5),
        required_documents=_clean_items(item.get("required_documents"), 6),
        application_steps=_clean_items(item.get("application_steps"), 6),
        contact_or_links=_clean_items(item.get("contact_or_links"), 5),
        community_tips=_clean_items(item.get("community_tips"), 4),
        needs_verification=_clean_items(item.get("needs_verification"), 5),
        caveats=_clean_items(item.get("caveats"), 5),
        extraction_provider="openai",
        extraction_model=settings.openai_model,
    )


def sanitize_research_error(exc: Exception | str) -> str:
    return sanitize_provider_error(exc)


def _extract_research_page_locally(source: ResearchSource, page_text: str) -> ResearchExtraction:
    lines = _candidate_lines(page_text)
    summary = next((line for line in lines if len(line) >= 40), source.snippet or source.title)
    relevance = _local_relevance_status(source, page_text)
    verified_facts = [] if relevance in {"error_page", "not_relevant"} else _keyword_items(lines, ("scheme", "fund", "grant", "subsidy", "support", "assistance"), 5)
    return ResearchExtraction(
        summary=_trim_text(summary, 500),
        relevance_status=relevance,
        verified_facts=verified_facts,
        eligibility_criteria=[] if relevance != "relevant" else _keyword_items(lines, ("eligible", "eligibility", "criteria", "qualify", "singapore citizen", "permanent resident", "means-test"), 6),
        support_amounts=[] if relevance != "relevant" else _keyword_items(lines, ("$", "amount", "cap", "subsid", "up to", "%", "per month", "per year", "co-payment"), 5),
        required_documents=[] if relevance != "relevant" else _keyword_items(lines, ("document", "form", "nric", "quotation", "invoice", "assessment", "prescription", "referral"), 6),
        application_steps=[] if relevance != "relevant" else _keyword_items(lines, ("apply", "submit", "contact", "approach", "call", "email", "singpass", "medical social worker"), 6),
        needs_verification=_keyword_items(lines, ("check", "latest", "updated", "subject to", "terms", "conditions"), 4),
        caveats=["Fetched page did not contain relevant research details."] if relevance in {"error_page", "not_relevant"} else [],
        extraction_provider="local_fallback",
        extraction_model=None,
    )


def _local_relevance_status(source: ResearchSource, page_text: str) -> str:
    lowered = f"{source.title} {page_text}".lower()
    if any(cue in lowered for cue in ("page not found", "cannot find the page", "404", "not found", "access denied", "login required")):
        return "error_page"
    relevant_terms = ("eligibility", "eligible", "apply", "application", "subsid", "grant", "fund", "scheme", "wheelchair", "mobility", "assistive")
    return "relevant" if any(term in lowered for term in relevant_terms) else "not_relevant"


def _fetched_pages_by_url(results: list[Any]) -> dict[str, dict[str, Any]]:
    pages: dict[str, dict[str, Any]] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        for key in (_url_key(str(item.get("url") or "")), _url_key(str(item.get("final_url") or ""))):
            if key:
                pages.setdefault(key, item)
    return pages


def _rank_fetch_candidates(sources: list[ResearchSource]) -> list[ResearchSource]:
    return sorted(sources, key=_fetch_candidate_rank)


def _fetch_candidate_rank(source: ResearchSource) -> tuple[int, int, int, str]:
    live_rank = 0 if source.provider not in {"curated_corpus", "curated_or_live_grants", "curated_or_live_resources"} else 1
    tier_rank = {"official": 0, "high_trust": 1, "informal": 2}.get(source.source_tier, 3)
    stale_rank = 1 if _looks_stale_url(source.url or "") else 0
    return (tier_rank, stale_rank, live_rank, source.title)


def _looks_stale_url(url: str) -> bool:
    lowered = url.lower()
    stale_fragments = ("-smf", "seniors-mobility-enabling-fund-smf")
    return any(fragment in lowered for fragment in stale_fragments)


def _source_key(source: ResearchSource) -> str:
    return f"{source.provider}:{_url_key(source.url or source.title)}"


def _page_source_key(page: dict[str, Any]) -> str:
    return f"{page.get('source_provider') or page.get('provider') or ''}:{_url_key(str(page.get('url') or page.get('title') or ''))}"


def _fetched_page_for_source(source: ResearchSource, pages_by_url: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    key = _url_key(source.url or "")
    if key in pages_by_url:
        return pages_by_url[key]
    source_path = urlparse(source.url or "").path.rstrip("/")
    for page_key, page in pages_by_url.items():
        page_path = urlparse(page_key).path.rstrip("/")
        if source_path and page_path and (source_path.endswith(page_path) or page_path.endswith(source_path)):
            return page
    return None


def _url_key(value: str) -> str:
    parsed = urlparse(value)
    domain = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    if not domain:
        return value.lower().rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"https://{domain}{path}{query}".lower()


def _clean_page_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:RESEARCH_PAGE_MAX_CHARS]


def _parse_json_object(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(0))
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}


def _clean_items(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = _trim_text(item, 280)
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _trim_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _extraction_has_content(extraction: ResearchExtraction) -> bool:
    return bool(
        extraction.summary
        or extraction.verified_facts
        or extraction.eligibility_criteria
        or extraction.support_amounts
        or extraction.required_documents
        or extraction.application_steps
    )


def _candidate_lines(page_text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", page_text).strip()
    if not normalized:
        return []
    chunks = re.split(r"(?<=[.!?])\s+| [•*] | \| ", normalized)
    lines = [_trim_text(chunk, 280) for chunk in chunks if len(chunk.strip()) >= 25]
    return list(dict.fromkeys(lines))


def _keyword_items(lines: list[str], keywords: tuple[str, ...], limit: int) -> list[str]:
    matches = []
    for line in lines:
        lowered = line.lower()
        if any(keyword in lowered for keyword in keywords):
            matches.append(line)
        if len(matches) >= limit:
            break
    return matches


def _search_curated_corpus(question: ResearchQuestion, limit: int = 5) -> list[ResearchSource]:
    query_terms = _search_terms(question.query)
    if not query_terms:
        return []

    scored: list[tuple[int, dict[str, Any]]] = []
    for entry in singapore_support_corpus():
        tier = str(entry.get("source_tier") or "official")
        if question.source_policy == "official" and tier != "official":
            continue
        if question.source_policy == "high_trust" and tier not in {"official", "high_trust"}:
            continue
        text = _corpus_search_text(entry)
        score = sum(4 for topic in entry.get("topics", []) if any(term in str(topic).lower() for term in query_terms))
        score += sum(1 for term in query_terms if term in text)
        if score:
            scored.append((score, entry))

    scored.sort(key=lambda item: (-item[0], str(item[1].get("title") or "")))
    return [_source_from_corpus_entry(entry, question.source_policy) for _, entry in scored[:limit]]


def _source_from_corpus_entry(entry: dict[str, Any], requested_tier: SourceTier) -> ResearchSource:
    url = str(entry.get("url") or "")
    tier = _source_tier(url, requested_tier)
    if entry.get("source_tier") in {"official", "high_trust", "informal"}:
        tier = entry["source_tier"]
    claims = entry.get("claims") if isinstance(entry.get("claims"), list) else []
    snippet = str(entry.get("summary") or "")
    if claims:
        snippet = f"{snippet} {' '.join(str(claim) for claim in claims[:2])}".strip()
    return ResearchSource(
        title=str(entry.get("title") or "Curated corpus source"),
        url=url or None,
        snippet=snippet,
        source_tier=tier,
        claim_status=_claim_status(tier, {"verification_status": "safe_to_show"}),
        verification_status="safe_to_show",
        retrieved_at=str(entry.get("retrieved_at") or datetime.now(UTC).date().isoformat()),
        provider="curated_corpus",
    )


def _search_terms(query: str) -> set[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "available",
        "be",
        "care",
        "for",
        "from",
        "in",
        "is",
        "of",
        "official",
        "or",
        "singapore",
        "source",
        "support",
        "the",
        "to",
        "what",
        "with",
    }
    return {term for term in re_split_words(query) if len(term) > 2 and term not in stopwords}


def re_split_words(value: str) -> list[str]:
    import re

    return re.findall(r"[a-z0-9]+", value.lower())


def _corpus_search_text(entry: dict[str, Any]) -> str:
    parts = [
        entry.get("id", ""),
        entry.get("title", ""),
        entry.get("source", ""),
        entry.get("summary", ""),
        " ".join(str(item) for item in entry.get("topics", [])),
        " ".join(str(item) for item in entry.get("claims", [])),
    ]
    return " ".join(str(part).lower() for part in parts)


def _claim_from_source(source: ResearchSource) -> str:
    label = source.title
    if source.source_tier == "informal":
        return f"Community lead: {label}. Verify before acting."
    if source.source_tier == "high_trust":
        return f"High-trust reference: {label}."
    return f"Verified source: {label}."


def _usable_extraction(extraction: ResearchExtraction | None) -> bool:
    return bool(extraction and extraction.relevance_status == "relevant" and _extraction_has_content(extraction))


def _extracted_items(sources: list[ResearchSource], field: str, limit: int, *, include_unusable: bool = False) -> list[str]:
    items: list[str] = []
    for source in sources:
        extraction = source.extraction
        if not extraction:
            continue
        if not include_unusable and not _usable_extraction(extraction):
            continue
        values = getattr(extraction, field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            text = _trim_text(value, 260)
            if not text:
                continue
            item = f"{text} Source: {source.title}."
            if item not in items:
                items.append(item)
            if len(items) >= limit:
                return items
    return items


def _result(
    plan_node: Node,
    guardrail_node: Node,
    research_result_nodes: list[Node],
    recommendation_node: Node,
    secondary_guardrail_node: Node | None = None,
) -> dict[str, Any]:
    return {
        "research_plan": plan_node.model_dump(mode="json"),
        "guardrail_review": guardrail_node.model_dump(mode="json"),
        "secondary_guardrail_review": secondary_guardrail_node.model_dump(mode="json") if secondary_guardrail_node else None,
        "research_results": [node.model_dump(mode="json") for node in research_result_nodes],
        "synthesized_recommendation": recommendation_node.model_dump(mode="json"),
    }
