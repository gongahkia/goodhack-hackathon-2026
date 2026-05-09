from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .models import Node
from .privacy import redact_transcript_direct_pii
from .store import GraphStore
from .transcription import TranscriptionError, transcribe_audio


async def ingest_audio_transcription(
    store: GraphStore,
    patient_id: str,
    audio: bytes,
    content_type: str | None,
    settings: Settings,
) -> dict[str, Any]:
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

    received_at = datetime.now(UTC).isoformat()
    await store.update_node_payload(
        session.id,
        {
            "status": "transcription_completed",
            "transcription_provider": result.provider,
            "transcription_model": result.model,
            "language": result.language,
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
            "provider": result.provider,
            "model": result.model,
            "language": result.language,
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
            "character_count": len(result.text),
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
    known_people: list[str] | None = None,
) -> Node:
    if transcript.type != "transcript":
        raise ValueError("Can only redact transcript nodes")
    patient_id = str(transcript.payload.get("patient_id") or "")
    raw_text = str(transcript.payload.get("raw_text") or "")
    redaction = redact_transcript_direct_pii(raw_text, known_people)
    node = await store.create_node(
        "pii_redaction",
        {
            "patient_id": patient_id,
            "transcript_id": str(transcript.id),
            "redacted_text": redaction["redacted_text"],
            "placeholder_map": redaction["placeholder_map"],
            "privacy": redaction["privacy"],
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
                **redaction["privacy"],
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
