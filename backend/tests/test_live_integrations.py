from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.config import Settings
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
