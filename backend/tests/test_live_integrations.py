from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.config import Settings
from app.quality import transcript_quality
from app.sealion_reviews import sealion_guard_json_review, sealion_regional_json_review
from app.store import PostgresGraphStore
from app.transcription import transcribe_audio
from app.v2 import tinyfish_search_web


pytestmark = pytest.mark.integration


def _live_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


requires_live_openai = pytest.mark.skipif(
    not (_live_enabled("RUN_LIVE_OPENAI_TESTS") and os.getenv("OPENAI_API_KEY") and os.getenv("LIVE_OPENAI_AUDIO_PATH")),
    reason="set RUN_LIVE_OPENAI_TESTS=1, OPENAI_API_KEY, and LIVE_OPENAI_AUDIO_PATH to run live OpenAI tests",
)
requires_live_tinyfish = pytest.mark.skipif(
    not (_live_enabled("RUN_LIVE_TINYFISH_TESTS") and os.getenv("TINYFISH_API_KEY")),
    reason="set RUN_LIVE_TINYFISH_TESTS=1 and TINYFISH_API_KEY to run live TinyFish tests",
)
requires_postgres = pytest.mark.skipif(
    not (_live_enabled("RUN_POSTGRES_INTEGRATION_TESTS") and os.getenv("TEST_DATABASE_URL")),
    reason="set RUN_POSTGRES_INTEGRATION_TESTS=1 and TEST_DATABASE_URL to run Postgres integration tests",
)
requires_live_sealion = pytest.mark.skipif(
    not (_live_enabled("RUN_LIVE_SEALION_TESTS") and os.getenv("SEALION_API_KEY")),
    reason="set RUN_LIVE_SEALION_TESTS=1 and SEALION_API_KEY to run live SEA-LION tests",
)


@requires_live_openai
@pytest.mark.asyncio
async def test_live_openai_transcription_smoke():
    audio_path = Path(os.environ["LIVE_OPENAI_AUDIO_PATH"])
    suffix_to_type = {".wav": "audio/wav", ".webm": "audio/webm", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}
    content_type = suffix_to_type.get(audio_path.suffix.lower(), "application/octet-stream")

    result = await transcribe_audio(
        audio_path.read_bytes(),
        content_type,
        Settings(
            transcription_provider="openai",
            openai_api_key=os.environ["OPENAI_API_KEY"],
            openai_transcription_model=os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-transcribe"),
        ),
    )

    assert result.provider == "openai"
    assert result.model
    assert result.text.strip()


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "ms", "ta", "zh", "th"])
async def test_live_openai_multilingual_transcription_quality(language):
    if not _live_enabled("RUN_LIVE_OPENAI_MULTILINGUAL_TESTS") or not os.getenv("OPENAI_API_KEY"):
        pytest.skip("set RUN_LIVE_OPENAI_MULTILINGUAL_TESTS=1 and OPENAI_API_KEY to run live multilingual transcription tests")
    audio_path_value = os.getenv(f"LIVE_OPENAI_AUDIO_{language.upper()}_PATH")
    reference = os.getenv(f"LIVE_OPENAI_TRANSCRIPT_{language.upper()}")
    if not audio_path_value or not reference:
        pytest.skip(f"set LIVE_OPENAI_AUDIO_{language.upper()}_PATH and LIVE_OPENAI_TRANSCRIPT_{language.upper()} for {language}")

    audio_path = Path(audio_path_value)
    suffix_to_type = {".wav": "audio/wav", ".webm": "audio/webm", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}
    result = await transcribe_audio(
        audio_path.read_bytes(),
        suffix_to_type.get(audio_path.suffix.lower(), "application/octet-stream"),
        Settings(
            transcription_provider="openai",
            openai_api_key=os.environ["OPENAI_API_KEY"],
            openai_transcription_model=os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-transcribe"),
            transcription_language=language,
        ),
    )
    quality = transcript_quality(reference, result.text, language)

    assert result.provider == "openai"
    assert result.text.strip()
    assert quality["passed"], quality


@requires_live_sealion
@pytest.mark.asyncio
async def test_live_sealion_regional_json_review_smoke():
    result = await sealion_regional_json_review(
        Settings(sealion_api_key=os.environ["SEALION_API_KEY"]),
        task="live_transcript_qa_smoke",
        target_language="English",
        input_payload={"redacted_transcript": "PERSON_1 needs Panadol before lunch.", "checks": ["date/time ambiguity"]},
        schema={"flags": [], "confidence": 0.0},
        max_tokens=300,
    )

    assert result["provider"] == "sealion"
    assert result["configured"] is True
    assert result["result"] is not None, result


@requires_live_sealion
@pytest.mark.asyncio
async def test_live_sealion_guard_json_review_smoke():
    result = await sealion_guard_json_review(
        Settings(sealion_api_key=os.environ["SEALION_API_KEY"]),
        prompt="Research wheelchair subsidies for PERSON_1 in Singapore. Do not provide medical advice.",
        max_tokens=200,
    )

    assert result["provider"] == "sealion_guard"
    assert result["configured"] is True
    assert result["result"] is not None, result


@requires_live_tinyfish
@pytest.mark.asyncio
async def test_live_tinyfish_search_smoke():
    result = await tinyfish_search_web(
        "Singapore Seniors Mobility Enabling Fund AIC wheelchair",
        Settings(tinyfish_api_key=os.environ["TINYFISH_API_KEY"], openai_api_key=None, live_search_llm_verification=False),
        allowlist=["aic.sg"],
    )

    assert result["provider"] == "tinyfish_search"
    assert result["configured"] is True
    assert "results" in result


@requires_postgres
@pytest.mark.asyncio
async def test_postgres_graph_store_transcript_first_schema_roundtrip():
    store = PostgresGraphStore(os.environ["TEST_DATABASE_URL"], Path("backend/sql/schema.sql"))
    await store.init()
    patient_id = f"postgres-integration-{uuid4()}"

    try:
        log = await store.create_reasoning_log("postgres_integration")
        session = await store.create_node("transcription_session", {"patient_id": patient_id}, "user", log.id, "approved")
        transcript = await store.create_node("transcript", {"patient_id": patient_id, "raw_text": "PERSON_1 needs Panadol."}, "system", log.id, "approved")
        redaction = await store.create_node(
            "pii_redaction",
            {"patient_id": patient_id, "redacted_text": "PERSON_1 needs Panadol.", "placeholder_map": {"PERSON_1": "John"}},
            "system",
            log.id,
            "approved",
        )
        review = await store.create_node(
            "transcript_review",
            {"patient_id": patient_id, "provider": "sealion", "input_privacy": "direct_pii_redacted"},
            "agent",
            log.id,
            "approved",
        )

        await store.create_edge(session.id, transcript.id, "transcribed_to")
        await store.create_edge(transcript.id, redaction.id, "redacted_as")
        await store.create_edge(review.id, redaction.id, "reviewed_from")

        graph = await store.graph_subset(patient_id)
        assert {"transcription_session", "transcript", "pii_redaction", "transcript_review"} <= {node.type for node in graph.nodes}
        assert {"transcribed_to", "redacted_as", "reviewed_from"} <= {edge.type for edge in graph.edges}
    finally:
        if store.pool:
            await store.pool.close()
