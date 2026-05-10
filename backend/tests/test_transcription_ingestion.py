from uuid import UUID

import httpx
import pytest

from app.config import Settings
from app.extraction import process_redacted_transcript
from app.privacy import redact_transcript_direct_pii, rehydrate_placeholders
from app.store import MemoryGraphStore
from app.transcript_pipeline import ingest_audio_transcription, redact_stored_transcript
from app.transcription import TranscriptionInputError, TranscriptionResult, TranscriptionUnavailable, normalize_transcription_language, transcribe_audio, transcription_prompt


@pytest.mark.asyncio
async def test_openai_transcription_provider_calls_audio_transcriptions_endpoint(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_post(self, url, headers=None, data=None, files=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["data"] = data
        captured["files"] = files
        return httpx.Response(
            200,
            json={"text": "John needs Panadol before lunch.", "usage": {"total_tokens": 12}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await transcribe_audio(
        b"fake webm bytes",
        "audio/webm;codecs=opus",
        Settings(
            transcription_provider="openai",
            openai_api_key="sk-test",
            openai_transcription_model="gpt-4o-transcribe",
            transcription_language="en",
        ),
    )

    assert result.text == "John needs Panadol before lunch."
    assert result.provider == "openai"
    assert result.model == "gpt-4o-transcribe"
    assert result.metadata == {"usage": {"total_tokens": 12}}
    assert captured["url"] == "https://api.openai.com/v1/audio/transcriptions"
    assert captured["headers"] == {"Authorization": "Bearer sk-test"}
    assert captured["data"]["model"] == "gpt-4o-transcribe"
    assert captured["data"]["response_format"] == "json"
    assert captured["files"]["file"][0] == "recording.webm"


@pytest.mark.asyncio
async def test_openai_transcription_auto_language_omits_language_hint(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_post(self, url, headers=None, data=None, files=None):
        captured["data"] = data
        return httpx.Response(
            200,
            json={"text": "John needs Panadol before lunch.", "language": "english"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await transcribe_audio(
        b"fake webm bytes",
        "audio/webm",
        Settings(transcription_provider="openai", openai_api_key="sk-test", transcription_language=None),
    )

    assert "language" not in captured["data"]
    assert result.requested_language is None
    assert result.detected_language == "en"
    assert result.language_label == "English"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "expected_label"),
    [("en", "English"), ("ms", "Malay/Bahasa"), ("ta", "Tamil"), ("zh", "Mandarin Chinese"), ("th", "Thai")],
)
async def test_openai_transcription_first_class_language_hints(monkeypatch, language, expected_label):
    captured: dict[str, object] = {}

    async def fake_post(self, url, headers=None, data=None, files=None):
        captured["data"] = data
        return httpx.Response(
            200,
            json={"text": "transcribed text", "language": language},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await transcribe_audio(
        b"fake webm bytes",
        "audio/webm",
        Settings(transcription_provider="openai", openai_api_key="sk-test", transcription_language=language),
    )

    assert captured["data"]["language"] == language
    assert result.requested_language == language
    assert result.detected_language == language
    assert result.language_label == expected_label
    assert captured["data"]["prompt"]
    assert "medication names" in captured["data"]["prompt"]
    if language == "zh":
        assert "Simplified Chinese" in captured["data"]["prompt"]


@pytest.mark.parametrize(
    ("raw_language", "expected"),
    [
        ("en-SG", "en"),
        ("bahasa melayu", "ms"),
        ("melayu", "ms"),
        ("தமிழ்", "ta"),
        ("zh-Hans", "zh"),
        ("cmn", "zh"),
        ("普通话", "zh"),
        ("ภาษาไทย", "th"),
    ],
)
def test_supported_language_aliases_normalize_to_first_class_codes(raw_language, expected):
    assert normalize_transcription_language(raw_language) == expected
    if expected:
        assert transcription_prompt(expected)


@pytest.mark.asyncio
async def test_transcription_rejects_unsupported_language():
    with pytest.raises(TranscriptionInputError, match="Unsupported transcription language"):
        await transcribe_audio(
            b"fake webm bytes",
            "audio/webm",
            Settings(transcription_provider="openai", openai_api_key="sk-test", transcription_language="fr"),
        )


@pytest.mark.asyncio
async def test_openai_transcription_provider_requires_api_key():
    with pytest.raises(TranscriptionUnavailable, match="OPENAI_API_KEY"):
        await transcribe_audio(b"fake audio", "audio/webm", Settings(transcription_provider="openai", openai_api_key=None))


def test_transcript_direct_pii_redaction_preserves_quasi_identifiers_and_medication_context():
    redaction = redact_transcript_direct_pii(
        "John aged 78 needs Panadol 500mg before lunch on 28 Jan. Call +65 9123 4567.",
    )

    assert redaction["redacted_text"] == "PERSON_1 aged 78 needs Panadol 500mg before lunch on 28 Jan. Call PHONE_1."
    assert redaction["placeholder_map"] == {"PERSON_1": "John", "PHONE_1": "+65 9123 4567"}
    assert "AGE" not in redaction["privacy"]["detected_categories"]


def test_rehydrate_placeholders_rejects_unknown_placeholder_ids():
    payload = {"task": "Give Panadol to PERSON_1", "bad": "Unknown PERSON_2"}

    with pytest.raises(ValueError, match="PERSON_2"):
        rehydrate_placeholders(payload, {"PERSON_1": "John"})

    assert rehydrate_placeholders({"task": "Give Panadol to PERSON_1"}, {"PERSON_1": "John"}) == {"task": "Give Panadol to John"}


@pytest.mark.asyncio
async def test_ingest_audio_transcription_persists_session_transcript_and_redaction(monkeypatch):
    async def fake_transcribe_audio(audio, content_type, settings):
        assert audio == b"fake audio"
        assert content_type == "audio/webm"
        return TranscriptionResult(
            text="John needs Panadol before lunch.",
            provider="openai",
            model="gpt-4o-transcribe",
            language="en",
            metadata={"usage": {"total_tokens": 12}},
        )

    monkeypatch.setattr("app.transcript_pipeline.transcribe_audio", fake_transcribe_audio)
    store = MemoryGraphStore()
    await store.init()

    result = await ingest_audio_transcription(
        store,
        "patient-1",
        b"fake audio",
        "audio/webm",
        Settings(transcription_provider="openai", openai_api_key="sk-test"),
    )

    session_id = result["transcription_session"]["id"]
    transcript_id = result["transcript"]["id"]
    graph = await store.graph_subset("patient-1")

    assert {node.type for node in graph.nodes} >= {"transcription_session", "transcript"}
    assert any(edge.type == "transcribed_to" and str(edge.from_node) == session_id and str(edge.to_node) == transcript_id for edge in graph.edges)

    transcript = await store.get_node(UUID(result["transcript"]["id"]))
    redaction = await redact_stored_transcript(store, transcript)
    graph = await store.graph_subset("patient-1")

    assert redaction.payload["redacted_text"] == "PERSON_1 needs Panadol before lunch."
    assert redaction.payload["placeholder_map"] == {"PERSON_1": "John"}
    assert any(edge.type == "redacted_as" and str(edge.from_node) == transcript_id and edge.to_node == redaction.id for edge in graph.edges)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "label", "source_text"),
    [
        ("ms", "Malay/Bahasa", "John perlu makan Panadol sebelum makan tengah hari setiap hari."),
        ("ta", "Tamil", "John தினமும் மதிய உணவுக்கு முன் Panadol எடுத்துக்கொள்ள வேண்டும்."),
        ("zh", "Mandarin Chinese", "John 每天午餐前需要吃 Panadol。"),
        ("th", "Thai", "John ต้องกิน Panadol ก่อนอาหารกลางวันทุกวัน."),
    ],
)
async def test_non_english_transcription_persists_original_and_normalized_english(monkeypatch, language, label, source_text):
    async def fake_transcribe_audio(audio, content_type, settings):
        assert settings.transcription_language == language
        return TranscriptionResult(
            text=source_text,
            provider="openai",
            model="gpt-4o-transcribe",
            language=language,
            requested_language=language,
            detected_language=language,
            language_label=label,
        )

    async def fake_normalize(text, source_language, settings):
        from app.transcription import TranscriptNormalization

        assert source_language == language
        return TranscriptNormalization(
            normalized_english_text="John needs Panadol before lunch every day.",
            provider="openai",
            model=settings.openai_model,
            status="completed",
            source_language=language,
            metadata={"notes": []},
        )

    monkeypatch.setattr("app.transcript_pipeline.transcribe_audio", fake_transcribe_audio)
    monkeypatch.setattr("app.transcript_pipeline.normalize_transcript_to_english", fake_normalize)
    store = MemoryGraphStore()
    await store.init()

    result = await ingest_audio_transcription(
        store,
        "patient-1",
        b"fake audio",
        "audio/webm",
        Settings(transcription_provider="openai", openai_api_key="sk-test", transcription_language=language),
    )

    transcript = await store.get_node(UUID(result["transcript"]["id"]))
    redaction = await redact_stored_transcript(store, transcript)
    processed = await process_redacted_transcript(store, redaction)

    assert transcript.payload["raw_text"] == source_text
    assert transcript.payload["normalized_english_text"] == "John needs Panadol before lunch every day."
    assert transcript.payload["requested_language"] == language
    assert transcript.payload["detected_language"] == language
    assert transcript.payload["language_label"] == label
    assert transcript.payload["normalization_status"] == "completed"
    assert redaction.payload["source_text_kind"] == "normalized_english"
    assert redaction.payload["redacted_text"] == "PERSON_1 needs Panadol before lunch every day."
    assert "John" not in redaction.payload["original_redacted_text"]
    assert "PERSON_1" in redaction.payload["original_redacted_text"]
    assert processed["daily_tasks"][0]["payload"]["description"] == "John needs Panadol before lunch every day"


@pytest.mark.asyncio
async def test_sealion_transcript_review_uses_redacted_text_and_persists_review(monkeypatch):
    captured = {}

    async def fake_sealion_regional_review(settings, *, task, input_payload, schema, target_language="English", max_tokens=800):
        captured["input_payload"] = input_payload
        captured["task"] = task
        captured["target_language"] = target_language
        return {
            "provider": "sealion",
            "configured": True,
            "model": settings.sealion_model,
            "task": task,
            "target_language": target_language,
            "result": {"flags": [], "locale_notes": ["clear"], "confidence": 0.9},
        }

    monkeypatch.setattr("app.sealion_reviews.sealion_regional_json_review", fake_sealion_regional_review)
    store = MemoryGraphStore()
    await store.init()
    transcript = await store.create_node(
        "transcript",
        {"patient_id": "patient-1", "raw_text": "John needs Panadol before lunch."},
        "system",
        status="approved",
    )

    redaction = await redact_stored_transcript(
        store,
        transcript,
        Settings(sealion_transcript_review_enabled=True, sealion_api_key="test-sealion"),
    )

    assert captured["input_payload"]["redacted_transcript"] == "PERSON_1 needs Panadol before lunch."
    assert "John" not in str(captured["input_payload"])
    assert captured["task"] == "multilingual_transcript_qa"
    reviews = await store.list_nodes("patient-1", ["transcript_review"])
    assert len(reviews) == 1
    assert reviews[0].payload["kind"] == "multilingual_transcript_qa"
    assert reviews[0].payload["pii_redaction_id"] == str(redaction.id)
    assert reviews[0].payload["input_privacy"] == "direct_pii_redacted"
    assert reviews[0].payload["configured"] is True
    assert reviews[0].payload["result"]["locale_notes"] == ["clear"]
    assert any(edge.type == "reviewed_from" and edge.from_node == reviews[0].id and edge.to_node == redaction.id for edge in await store.list_edges())


@pytest.mark.asyncio
async def test_sealion_transcript_review_stores_parse_errors_without_crashing(monkeypatch):
    async def fake_completion(settings, model, prompt, *, max_tokens, temperature):
        return "not json"

    monkeypatch.setattr("app.sealion_reviews._sealion_chat_completion", fake_completion)
    store = MemoryGraphStore()
    transcript = await store.create_node(
        "transcript",
        {"patient_id": "patient-1", "raw_text": "John needs Panadol before lunch."},
        "system",
        status="approved",
    )

    await redact_stored_transcript(
        store,
        transcript,
        Settings(sealion_transcript_review_enabled=True, sealion_api_key="test-sealion"),
    )

    reviews = await store.list_nodes("patient-1", ["transcript_review"])
    assert len(reviews) == 1
    assert reviews[0].status == "clarification_required"
    assert reviews[0].payload["kind"] == "multilingual_transcript_qa"
    assert reviews[0].payload["result"] is None
    assert reviews[0].payload["raw_result"] == "not json"
    assert reviews[0].payload["parse_error"] == "response_is_not_json"
