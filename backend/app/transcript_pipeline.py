from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .models import Node
from .privacy import redact_transcript_direct_pii
from .store import GraphStore
from .transcription import TranscriptionError, TranscriptionInputError, normalize_transcript_to_english, transcribe_audio
from .v2 import sealion_regional_review


async def ingest_audio_transcription(
    store: GraphStore,
    patient_id: str,
    audio: bytes,
    content_type: str | None,
    settings: Settings,
) -> dict[str, Any]:
    if not audio:
        raise TranscriptionInputError("No audio was received.")
    if len(audio) > settings.transcription_max_bytes:
        raise TranscriptionInputError(f"Audio is too large. Max size is {settings.transcription_max_bytes // (1024 * 1024)} MB.")

    log = await store.create_reasoning_log("audio_transcription")
    requested_at = datetime.now(UTC).isoformat()
    session = await store.create_node(
        "transcription_session",
        {
            "patient_id": patient_id,
            "status": "transcription_requested",
            "audio_metadata": {
                "content_type": content_type,
                "byte_size": len(audio),
            },
            "transcription_provider": settings.transcription_provider,
            "transcription_model": _requested_transcription_model(settings),
            "requested_language": result_language_setting(settings),
            "requested_at": requested_at,
        },
        "user",
        reasoning_log_id=log.id,
        status="pending_review",
    )
    await store.append_reasoning_step(
        log.id,
        {
            "kind": "audio_transcription_requested",
            "session_id": str(session.id),
            "content_type": content_type,
            "byte_size": len(audio),
            "provider": settings.transcription_provider,
            "model": _requested_transcription_model(settings),
            "requested_language": result_language_setting(settings),
        },
    )

    try:
        result = await transcribe_audio(audio, content_type, settings)
    except TranscriptionError as exc:
        await store.update_node_payload(
            session.id,
            {
                "status": "transcription_failed",
                "failed_at": datetime.now(UTC).isoformat(),
                "error": str(exc),
            },
            "clarification_required",
        )
        await store.append_reasoning_step(
            log.id,
            {
                "kind": "transcription_failed",
                "session_id": str(session.id),
                "error": str(exc),
            },
        )
        await store.finish_reasoning_log(log.id, "Audio transcription failed.")
        raise

    normalization = await normalize_transcript_to_english(result.text, result.detected_language or result.language or result.requested_language, settings)
    received_at = datetime.now(UTC).isoformat()
    await store.update_node_payload(
        session.id,
        {
            "status": "transcription_completed",
            "transcription_provider": result.provider,
            "transcription_model": result.model,
            "language": result.language,
            "requested_language": result.requested_language,
            "detected_language": result.detected_language,
            "language_label": result.language_label,
            "normalization_status": normalization.status,
            "completed_at": received_at,
        },
        "approved",
    )
    transcript = await store.create_node(
        "transcript",
        {
            "patient_id": patient_id,
            "transcription_session_id": str(session.id),
            "raw_text": result.text,
            "normalized_english_text": normalization.normalized_english_text,
            "provider": result.provider,
            "model": result.model,
            "language": result.language,
            "requested_language": result.requested_language,
            "detected_language": result.detected_language,
            "language_label": result.language_label,
            "normalization_provider": normalization.provider,
            "normalization_model": normalization.model,
            "normalization_status": normalization.status,
            "normalization_metadata": normalization.metadata or {},
            "metadata": result.metadata or {},
            "created_at": received_at,
        },
        "system",
        reasoning_log_id=log.id,
        status="approved",
    )
    await store.create_edge(session.id, transcript.id, "transcribed_to")
    await store.append_reasoning_step(
        log.id,
        {
            "kind": "transcription_response_received",
            "session_id": str(session.id),
            "transcript_id": str(transcript.id),
            "provider": result.provider,
            "model": result.model,
            "requested_language": result.requested_language,
            "detected_language": result.detected_language,
            "language_label": result.language_label,
            "normalization_status": normalization.status,
            "character_count": len(result.text),
            "normalized_character_count": len(normalization.normalized_english_text or ""),
        },
    )
    await store.finish_reasoning_log(log.id, "Stored transcript from uploaded audio.")

    return {
        "transcription_session": session.model_dump(mode="json"),
        "transcript": transcript.model_dump(mode="json"),
        "reasoning_log_id": str(log.id),
    }


async def redact_stored_transcript(
    store: GraphStore,
    transcript: Node,
    settings: Settings | None = None,
    known_people: list[str] | None = None,
) -> Node:
    if transcript.type != "transcript":
        raise ValueError("Can only redact transcript nodes")
    patient_id = str(transcript.payload.get("patient_id") or "")
    raw_text = str(transcript.payload.get("raw_text") or "")
    normalized_text = str(transcript.payload.get("normalized_english_text") or "").strip()
    source_text = normalized_text or raw_text
    redaction = redact_transcript_direct_pii(source_text, known_people)
    original_redaction = redact_transcript_direct_pii(raw_text, known_people) if normalized_text else None
    node = await store.create_node(
        "pii_redaction",
        {
            "patient_id": patient_id,
            "transcript_id": str(transcript.id),
            "redacted_text": redaction["redacted_text"],
            "placeholder_map": redaction["placeholder_map"],
            "privacy": redaction["privacy"],
            "source_text_kind": "normalized_english" if normalized_text else "original",
            "original_language": transcript.payload.get("language"),
            "requested_language": transcript.payload.get("requested_language"),
            "detected_language": transcript.payload.get("detected_language"),
            "language_label": transcript.payload.get("language_label"),
            "normalization_status": transcript.payload.get("normalization_status"),
            "original_redacted_text": original_redaction["redacted_text"] if original_redaction else None,
            "created_at": datetime.now(UTC).isoformat(),
        },
        "system",
        reasoning_log_id=transcript.reasoning_log_id,
        status="approved",
    )
    await store.create_edge(transcript.id, node.id, "redacted_as")
    if transcript.reasoning_log_id:
        await store.append_reasoning_step(
            transcript.reasoning_log_id,
            {
                "kind": "pii_redaction_summary",
                "transcript_id": str(transcript.id),
                "pii_redaction_id": str(node.id),
                "source_text_kind": node.payload["source_text_kind"],
                "requested_language": node.payload.get("requested_language"),
                "detected_language": node.payload.get("detected_language"),
                **redaction["privacy"],
            },
        )
    await maybe_review_redacted_transcript_with_sealion(store, node, settings)
    return node


async def maybe_review_redacted_transcript_with_sealion(
    store: GraphStore,
    redaction: Node,
    settings: Settings | None,
) -> Node | None:
    if not settings or not settings.sealion_transcript_review_enabled:
        return None
    patient_id = str(redaction.payload.get("patient_id") or "")
    redacted_text = str(redaction.payload.get("redacted_text") or "")
    review = await sealion_regional_review(
        redacted_text,
        settings,
        task="redacted_transcript_care_reasoning_review",
        target_language="English",
        max_tokens=700,
    )
    node = await store.create_node(
        "transcript_review",
        {
            "patient_id": patient_id,
            "pii_redaction_id": str(redaction.id),
            "provider": review.get("provider"),
            "configured": review.get("configured"),
            "model": review.get("model"),
            "task": review.get("task") or "redacted_transcript_care_reasoning_review",
            "result": review.get("result"),
            "error": review.get("error"),
            "input_privacy": "direct_pii_redacted",
            "redacted_input_chars": len(redacted_text),
            "created_at": datetime.now(UTC).isoformat(),
        },
        "agent",
        reasoning_log_id=redaction.reasoning_log_id,
        status="approved" if review.get("result") else "clarification_required",
    )
    await store.create_edge(node.id, redaction.id, "reviewed_from")
    if redaction.reasoning_log_id:
        await store.append_reasoning_step(
            redaction.reasoning_log_id,
            {
                "kind": "sealion_transcript_review",
                "pii_redaction_id": str(redaction.id),
                "transcript_review_id": str(node.id),
                "configured": review.get("configured"),
                "provider": review.get("provider"),
                "model": review.get("model"),
                "input_privacy": "direct_pii_redacted",
            },
        )
    return node


def _requested_transcription_model(settings: Settings) -> str:
    provider = settings.transcription_provider.lower().strip()
    if provider in {"openai", "openai-api"}:
        return settings.openai_transcription_model
    if provider == "groq":
        return settings.groq_transcription_model
    return settings.mlx_whisper_model if settings.local_transcription_backend in {"auto", "mlx", "mlx-whisper"} else settings.faster_whisper_model


def result_language_setting(settings: Settings) -> str | None:
    return settings.transcription_language or None
