import json
from pathlib import Path

import pytest

import app.research as research
from app.config import Settings
from app.data import grants_database, singapore_support_corpus
from app.research import DefaultResearchToolAdapter, GuardrailReview, ResearchExtraction, ResearchQuestion, run_guarded_research_pipeline, synthesize_recommendation
from app.store import MemoryGraphStore


def test_singapore_support_corpus_has_required_source_metadata():
    corpus = singapore_support_corpus()

    assert len(corpus) >= 10
    for entry in corpus:
        assert entry["id"]
        assert entry["title"]
        assert entry["url"].startswith("https://")
        assert entry["source_tier"] in {"official", "high_trust", "informal"}
        assert entry["topics"]
        assert entry["summary"]
        assert entry["claims"]
        assert entry["retrieved_at"]


def test_expanded_grant_catalog_contains_long_term_care_and_training_schemes():
    ids = {grant["id"] for grant in grants_database()}

    assert {
        "caregivers_training_grant",
        "elderfund",
        "idape",
        "aic_seniors_mobility_enabling_fund",
        "home_caregiving_grant",
    } <= ids


@pytest.mark.asyncio
async def test_research_adapter_uses_curated_corpus_before_live_tools_without_api_keys():
    adapter = DefaultResearchToolAdapter()
    question = ResearchQuestion(
        query="wheelchair mobility grant Singapore official subsidy eligibility",
        source_policy="official",
        rationale="Verify official support schemes.",
        tools=["curated_corpus"],
    )

    results = await adapter.search(question, Settings(exa_api_key=None, tinyfish_api_key=None))

    assert results
    assert results[0].provider == "curated_corpus"
    assert results[0].source_tier == "official"
    assert results[0].claim_status == "verified_fact"
    assert any("Seniors' Mobility and Enabling Fund" in result.title for result in results)


@pytest.mark.asyncio
async def test_research_adapter_keeps_local_corpus_and_live_web_results(monkeypatch):
    async def fake_search_verified_grants(query, settings, allowlist=None):
        return []

    async def fake_search_verified_resources(query, settings, allowlist=None):
        return []

    async def fake_exa_search_web(query, settings, allowlist=None, num_results=5, search_type="auto"):
        return {
            "provider": "exa",
            "configured": True,
            "results": [
                {
                    "title": "Live AIC mobility search result",
                    "url": "https://www.aic.sg/financial-assistance/seniors-mobility-enabling-fund-smf/",
                    "snippet": "Live search confirms AIC SMF is relevant to mobility aids.",
                    "verification_status": "safe_to_show",
                    "provider": "exa",
                }
            ],
        }

    async def fake_tinyfish_search_web(query, settings, allowlist=None):
        return {
            "provider": "tinyfish_search",
            "configured": True,
            "results": [
                {
                    "title": "Live SG Enable assistive technology result",
                    "url": "https://www.sgenable.sg/your-first-stop/disability-support/assistive-technology/assistive-technology-fund",
                    "snippet": "Live search finds SG Enable assistive technology support.",
                    "verification_status": "safe_to_show",
                    "provider": "tinyfish_search",
                }
            ],
        }

    monkeypatch.setattr(research, "search_verified_grants", fake_search_verified_grants)
    monkeypatch.setattr(research, "search_verified_resources", fake_search_verified_resources)
    monkeypatch.setattr(research, "exa_search_web", fake_exa_search_web)
    monkeypatch.setattr(research, "tinyfish_search_web", fake_tinyfish_search_web)

    adapter = DefaultResearchToolAdapter()
    question = ResearchQuestion(
        query="wheelchair mobility grant Singapore official subsidy eligibility",
        source_policy="official",
        rationale="Verify official support schemes.",
        tools=["curated_corpus", "exa", "tinyfish"],
    )

    results = await adapter.search(question, Settings(exa_api_key="fake", tinyfish_api_key="fake"))
    providers = [result.provider for result in results]

    assert "curated_corpus" in providers
    assert "exa" in providers
    assert "tinyfish_search" in providers
    assert any(result.url == "https://www.aic.sg/financial-assistance/seniors-mobility-enabling-fund-smf/" and result.provider == "curated_corpus" for result in results)
    assert any(result.url == "https://www.aic.sg/financial-assistance/seniors-mobility-enabling-fund-smf/" and result.provider == "exa" for result in results)


@pytest.mark.asyncio
async def test_research_adapter_fetches_pages_and_synthesis_uses_extracted_details(monkeypatch):
    async def fake_search_verified_grants(query, settings, allowlist=None):
        return []

    async def fake_search_verified_resources(query, settings, allowlist=None):
        return []

    async def fake_exa_search_web(query, settings, allowlist=None, num_results=5, search_type="auto"):
        return {"provider": "exa", "configured": True, "results": []}

    async def fake_tinyfish_search_web(query, settings, allowlist=None):
        return {
            "provider": "tinyfish_search",
            "configured": True,
            "results": [
                {
                    "title": "Live AIC mobility search result",
                    "url": "https://www.aic.sg/financial-assistance/seniors-mobility-enabling-fund-smf/",
                    "snippet": "Search snippet only says this page is about mobility support.",
                    "verification_status": "safe_to_show",
                    "provider": "tinyfish_search",
                }
            ],
        }

    async def fake_tinyfish_fetch_urls(urls, settings, allowlist=None, format="markdown"):
        return {
            "provider": "tinyfish_fetch",
            "configured": True,
            "results": [
                {
                    "url": url,
                    "final_url": url,
                    "title": "Fetched mobility support page",
                    "text": (
                        "Applicants must be Singapore Citizens or Permanent Residents. "
                        "The scheme may subsidise approved mobility devices up to a capped amount. "
                        "Prepare the application form, NRIC, and therapist assessment. "
                        "Apply through an AIC-appointed assessor or ask the hospital medical social worker."
                    ),
                }
                for url in urls
            ],
            "errors": [],
            "rejected_urls": [],
        }

    async def fake_extract_pages(question, pages, settings):
        assert any("Applicants must be Singapore Citizens or Permanent Residents" in page["text"] for page in pages)
        return {
            research._url_key(page["url"]): ResearchExtraction(
                summary="The page explains mobility support eligibility and application requirements.",
                verified_facts=["The support page describes an official mobility aid scheme."],
                eligibility_criteria=["Applicants must be Singapore Citizens or Permanent Residents."],
                support_amounts=["The page says subsidies may be capped for approved mobility devices."],
                required_documents=["Prepare the application form, NRIC, and therapist assessment."],
                application_steps=["Apply through an AIC-appointed assessor or ask the hospital medical social worker."],
                extraction_provider="openai",
                extraction_model=settings.openai_model,
            )
            for page in pages
        }

    monkeypatch.setattr(research, "search_verified_grants", fake_search_verified_grants)
    monkeypatch.setattr(research, "search_verified_resources", fake_search_verified_resources)
    monkeypatch.setattr(research, "exa_search_web", fake_exa_search_web)
    monkeypatch.setattr(research, "tinyfish_search_web", fake_tinyfish_search_web)
    monkeypatch.setattr(research, "tinyfish_fetch_urls", fake_tinyfish_fetch_urls)
    monkeypatch.setattr(research, "_extract_research_pages_with_openai", fake_extract_pages)

    adapter = DefaultResearchToolAdapter()
    question = ResearchQuestion(
        query="wheelchair mobility grant Singapore official subsidy eligibility",
        source_policy="official",
        rationale="Verify official support schemes.",
        tools=["curated_corpus", "tinyfish"],
    )

    results = await adapter.search(question, Settings(openai_api_key="fake-openai", tinyfish_api_key="fake-tinyfish"))

    assert any(result.extraction_status == "llm_extracted" for result in results)
    assert any(result.extraction and result.extraction.application_steps for result in results)

    store = MemoryGraphStore()
    task = await store.create_node(
        "ad_hoc_research_task",
        {
            "patient_id": "patient-1",
            "question": "What wheelchair grants are available in Singapore?",
            "question_redacted": "What wheelchair grants are available in Singapore?",
        },
        "agent",
    )
    recommendation = synthesize_recommendation(task, GuardrailReview(decision="approved", reason="ok"), results)

    assert any("Singapore Citizens or Permanent Residents" in item for item in recommendation.eligibility_criteria)
    assert any("AIC-appointed assessor" in item for item in recommendation.application_steps)
    assert "Fetched source pages" in recommendation.summary


@pytest.mark.asyncio
async def test_guarded_research_pipeline_persists_corpus_sources_as_evidence():
    store = MemoryGraphStore()
    task = await store.create_node(
        "ad_hoc_research_task",
        {
            "patient_id": "patient-1",
            "question": "What wheelchair grants are available in Singapore?",
            "question_redacted": "What wheelchair grants are available in Singapore?",
            "basis": "Doctor said wheelchair may be needed after mobility decline.",
            "basis_redacted": "Doctor said wheelchair may be needed after mobility decline.",
            "source_status": "pending_guardrail",
            "requires_guardrail_review": True,
        },
        "agent",
        status="pending_review",
    )

    result = await run_guarded_research_pipeline(store, task, Settings(exa_api_key=None, tinyfish_api_key=None))

    sources = [
        source
        for node in result["research_results"]
        for source in node["payload"]["sources"]
    ]
    assert any(source["provider"] == "curated_corpus" for source in sources)
    assert any(source["claim_status"] == "verified_fact" for source in sources)
    recommendation = result["synthesized_recommendation"]["payload"]
    assert recommendation["evidence"]
    assert recommendation["verified_facts"]


def test_all_data_json_files_are_valid_and_nonempty():
    for path in Path("data").glob("*.json"):
        parsed = json.loads(path.read_text(encoding="utf-8"))
        assert parsed
