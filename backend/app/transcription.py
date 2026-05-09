from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from openai import AsyncOpenAI

from .config import Settings
from .security import sanitize_provider_error, vendor_allowed


class TranscriptionError(RuntimeError):
    status_code = 500


class TranscriptionUnavailable(TranscriptionError):
    status_code = 503


class TranscriptionInputError(TranscriptionError):
    status_code = 400


SUPPORTED_TRANSCRIPTION_LANGUAGES = {
    "en": "English",
    "ms": "Malay/Bahasa",
    "ta": "Tamil",
    "zh": "Mandarin Chinese",
    "th": "Thai",
}
LANGUAGE_ALIASES = {
    "": None,
    "auto": None,
    "detect": None,
    "english": "en",
    "eng": "en",
    "malay": "ms",
    "bahasa": "ms",
    "bahasa melayu": "ms",
    "bahasa malaysia": "ms",
    "tamil": "ta",
    "mandarin": "zh",
    "chinese": "zh",
    "mandarin chinese": "zh",
    "simplified chinese": "zh",
    "thai": "th",
}


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    provider: str
    model: str
    language: str | None = None
    metadata: dict[str, Any] | None = None
    requested_language: str | None = None
    detected_language: str | None = None
    language_label: str | None = None

    def model_dump(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "language": self.language,
            "requested_language": self.requested_language,
            "detected_language": self.detected_language,
            "language_label": self.language_label,
            "metadata": self.metadata or {},
        }


@dataclass(frozen=True)
class TranscriptNormalization:
    normalized_english_text: str | None
    provider: str | None
    model: str | None
    status: str
    source_language: str | None
    metadata: dict[str, Any] | None = None


CONTENT_TYPE_SUFFIXES = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/aiff": ".aiff",
    "audio/x-aiff": ".aiff",
}


async def transcribe_audio(audio: bytes, content_type: str | None, settings: Settings) -> TranscriptionResult:
    if not audio:
        raise TranscriptionInputError("No audio was received.")
    if len(audio) > settings.transcription_max_bytes:
        raise TranscriptionInputError(f"Audio is too large. Max size is {settings.transcription_max_bytes // (1024 * 1024)} MB.")

    requested_language = normalize_transcription_language(settings.transcription_language)
    provider = settings.transcription_provider.lower().strip()
    errors: list[str] = []
    if provider in {"local", "auto", "mlx", "mlx-whisper"}:
        try:
            return await _transcribe_locally(audio, content_type, settings, requested_language)
        except TranscriptionUnavailable as exc:
            errors.append(str(exc))
            if provider not in {"auto"}:
                raise

    if provider in {"openai", "openai-api"}:
        if not vendor_allowed(settings, "openai", "transcription"):
            raise TranscriptionUnavailable("OpenAI transcription is disabled for this purpose.")
        return await _transcribe_with_openai(audio, content_type, settings, requested_language)

    if provider in {"groq", "auto"}:
        try:
            if not vendor_allowed(settings, "groq", "transcription"):
                raise TranscriptionUnavailable("Groq transcription is disabled for this purpose.")
            return await _transcribe_with_groq(audio, content_type, settings, requested_language)
        except TranscriptionUnavailable as exc:
            errors.append(str(exc))
            raise TranscriptionUnavailable(" ".join(errors) if errors else str(exc)) from exc

    raise TranscriptionUnavailable(
        f"Unknown transcription provider '{settings.transcription_provider}'. Use 'local', 'openai', 'groq', or 'auto'."
    )


async def _transcribe_locally(audio: bytes, content_type: str | None, settings: Settings, requested_language: str | None) -> TranscriptionResult:
    backend = settings.local_transcription_backend.lower().strip()
    errors: list[str] = []
    if backend in {"auto", "mlx", "mlx-whisper"}:
        try:
            return await _transcribe_with_mlx_whisper(audio, content_type, settings, requested_language)
        except TranscriptionUnavailable as exc:
            errors.append(str(exc))
            if backend != "auto":
                raise
    if backend in {"auto", "faster", "faster-whisper", "cpu"}:
        try:
            return await _transcribe_with_faster_whisper(audio, content_type, settings, requested_language)
        except TranscriptionUnavailable as exc:
            errors.append(str(exc))
            raise TranscriptionUnavailable(" ".join(errors) if errors else str(exc)) from exc
    raise TranscriptionUnavailable(
        f"Unknown local transcription backend '{settings.local_transcription_backend}'. Use 'auto', 'mlx-whisper', or 'faster-whisper'."
    )


async def _transcribe_with_mlx_whisper(audio: bytes, content_type: str | None, settings: Settings, requested_language: str | None) -> TranscriptionResult:
    return await asyncio.to_thread(_run_mlx_whisper, audio, content_type, settings, requested_language)


def _run_mlx_whisper(audio: bytes, content_type: str | None, settings: Settings, requested_language: str | None) -> TranscriptionResult:
    try:
        import mlx_whisper
    except Exception as exc:
        raise TranscriptionUnavailable("MLX Whisper is unavailable in this runtime. Falling back to CPU local transcription when configured.") from exc

    suffix = _suffix_for_content_type(content_type)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as audio_file:
            audio_file.write(audio)
            temp_path = Path(audio_file.name)
        kwargs: dict[str, Any] = {"path_or_hf_repo": settings.mlx_whisper_model}
        if requested_language:
            kwargs["language"] = requested_language
        output = mlx_whisper.transcribe(str(temp_path), **kwargs)
    except TranscriptionUnavailable:
        raise
    except Exception as exc:
        raise TranscriptionUnavailable(f"Local mlx-whisper transcription failed: {exc}") from exc
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)

    text = str(output.get("text", "") if isinstance(output, dict) else "").strip()
    if not text:
        raise TranscriptionInputError("No speech was detected in the audio.")
    return TranscriptionResult(
        text=text,
        provider="mlx-whisper",
        model=settings.mlx_whisper_model,
        language=requested_language,
        requested_language=requested_language,
        detected_language=requested_language,
        language_label=language_label(requested_language),
    )


async def _transcribe_with_faster_whisper(audio: bytes, content_type: str | None, settings: Settings, requested_language: str | None) -> TranscriptionResult:
    return await asyncio.to_thread(_run_faster_whisper, audio, content_type, settings, requested_language)


def _run_faster_whisper(audio: bytes, content_type: str | None, settings: Settings, requested_language: str | None) -> TranscriptionResult:
    try:
        model = _faster_whisper_model(settings.faster_whisper_model, settings.faster_whisper_compute_type)
    except ImportError as exc:
        raise TranscriptionUnavailable("CPU local transcription requires faster-whisper. Run: cd backend && uv pip install faster-whisper") from exc
    except Exception as exc:
        raise TranscriptionUnavailable(f"faster-whisper model load failed: {exc}") from exc

    suffix = _suffix_for_content_type(content_type)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as audio_file:
            audio_file.write(audio)
            temp_path = Path(audio_file.name)
        segments, _info = model.transcribe(
            str(temp_path),
            language=requested_language,
            beam_size=5,
            vad_filter=True,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        detected_language = canonical_transcription_language(getattr(_info, "language", None))
    except Exception as exc:
        raise TranscriptionUnavailable(f"faster-whisper transcription failed: {exc}") from exc
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)

    if not text:
        raise TranscriptionInputError("No speech was detected in the audio.")
    return TranscriptionResult(
        text=text,
        provider="faster-whisper",
        model=settings.faster_whisper_model,
        language=detected_language or requested_language,
        requested_language=requested_language,
        detected_language=detected_language or requested_language,
        language_label=language_label(detected_language or requested_language),
    )


@lru_cache(maxsize=2)
def _faster_whisper_model(model_name: str, compute_type: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_name, device="cpu", compute_type=compute_type)


async def _transcribe_with_groq(audio: bytes, content_type: str | None, settings: Settings, requested_language: str | None) -> TranscriptionResult:
    if not vendor_allowed(settings, "groq", "transcription"):
        raise TranscriptionUnavailable("Groq transcription is disabled for this purpose.")
    if not settings.groq_api_key:
        raise TranscriptionUnavailable("Groq transcription requires GROQ_API_KEY.")

    suffix = _suffix_for_content_type(content_type)
    files = {"file": (f"recording{suffix}", audio, content_type or "application/octet-stream")}
    data = {
        "model": settings.groq_transcription_model,
        "response_format": "json",
        "temperature": "0",
    }
    if requested_language:
        data["language"] = requested_language

    try:
        async with httpx.AsyncClient(timeout=settings.transcription_timeout_seconds) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                data=data,
                files=files,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise TranscriptionUnavailable(f"Groq transcription failed: {sanitize_provider_error(exc)}") from exc

    payload = response.json()
    text = str(payload.get("text", "")).strip()
    if not text:
        raise TranscriptionInputError("No speech was detected in the audio.")
    detected_language = canonical_transcription_language(payload.get("language")) or requested_language
    return TranscriptionResult(
        text=text,
        provider="groq",
        model=settings.groq_transcription_model,
        language=detected_language,
        requested_language=requested_language,
        detected_language=detected_language,
        language_label=language_label(detected_language),
        metadata=_transcription_metadata(payload),
    )


async def _transcribe_with_openai(audio: bytes, content_type: str | None, settings: Settings, requested_language: str | None) -> TranscriptionResult:
    if not vendor_allowed(settings, "openai", "transcription"):
        raise TranscriptionUnavailable("OpenAI transcription is disabled for this purpose.")
    if not settings.openai_api_key:
        raise TranscriptionUnavailable("OpenAI transcription requires OPENAI_API_KEY.")

    suffix = _suffix_for_content_type(content_type)
    files = {"file": (f"recording{suffix}", audio, content_type or "application/octet-stream")}
    data = {
        "model": settings.openai_transcription_model,
        "response_format": "json",
        "temperature": "0",
    }
    if requested_language:
        data["language"] = requested_language
    prompt = transcription_prompt(requested_language)
    if prompt:
        data["prompt"] = prompt

    try:
        async with httpx.AsyncClient(timeout=settings.transcription_timeout_seconds) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                data=data,
                files=files,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = _http_error_detail(exc.response)
        raise TranscriptionUnavailable(f"OpenAI transcription failed: {sanitize_provider_error(detail)}") from exc
    except httpx.HTTPError as exc:
        raise TranscriptionUnavailable(f"OpenAI transcription failed: {sanitize_provider_error(exc)}") from exc

    payload = response.json()
    text = str(payload.get("text", "")).strip()
    if not text:
        raise TranscriptionInputError("No speech was detected in the audio.")
    detected_language = canonical_transcription_language(payload.get("language")) or requested_language
    return TranscriptionResult(
        text=text,
        provider="openai",
        model=settings.openai_transcription_model,
        language=detected_language,
        requested_language=requested_language,
        detected_language=detected_language,
        language_label=language_label(detected_language),
        metadata=_transcription_metadata(payload),
    )


async def normalize_transcript_to_english(text: str, source_language: str | None, settings: Settings) -> TranscriptNormalization:
    language = canonical_transcription_language(source_language)
    if not text.strip():
        return TranscriptNormalization(None, None, None, "empty", language)
    if language == "en":
        return TranscriptNormalization(None, "system", None, "not_required", language)
    if not settings.openai_api_key:
        return TranscriptNormalization(None, None, None, "unavailable_no_openai_api_key", language)
    if not vendor_allowed(settings, "openai", "translation"):
        return TranscriptNormalization(None, "openai", settings.openai_model, "vendor_disabled", language)

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        response = await client.responses.create(
            model=settings.openai_model,
            instructions=(
                "Translate and normalize caregiver speech into clear English for a Singapore care-planning system. "
                "Preserve medications, dosages, dates, times, agencies, appointment details, and uncertainty. "
                "Return compact JSON only with keys normalized_english_text and notes. Do not add medical advice."
            ),
            input=json.dumps({"source_language": language or "auto", "transcript": text}, ensure_ascii=False),
            max_output_tokens=900,
        )
        payload = json.loads(getattr(response, "output_text", "") or "{}")
    except Exception as exc:
        return TranscriptNormalization(None, "openai", settings.openai_model, "failed", language, {"error": sanitize_provider_error(exc)})

    normalized = str(payload.get("normalized_english_text") or "").strip()
    if not normalized:
        return TranscriptNormalization(None, "openai", settings.openai_model, "empty", language, {"raw_response": payload})
    return TranscriptNormalization(
        normalized,
        "openai",
        settings.openai_model,
        "completed",
        language,
        {"notes": payload.get("notes")},
    )


def normalize_transcription_language(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().lower().replace("_", "-")
    if cleaned in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[cleaned]
    cleaned = cleaned.split("-", 1)[0]
    if cleaned in SUPPORTED_TRANSCRIPTION_LANGUAGES:
        return cleaned
    raise TranscriptionInputError(
        "Unsupported transcription language. Use auto, en, ms, ta, zh, or th."
    )


def canonical_transcription_language(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return normalize_transcription_language(str(value))
    except TranscriptionInputError:
        return None


def language_label(language: str | None) -> str | None:
    return SUPPORTED_TRANSCRIPTION_LANGUAGES.get(language or "")


def transcription_prompt(language: str | None) -> str | None:
    if language == "zh":
        return "Transcribe Mandarin Chinese using Simplified Chinese characters. Preserve medication names, dates, and clinic names exactly."
    if language == "ms":
        return "Transcribe Malay/Bahasa caregiver speech. Preserve medication names, dates, and clinic names exactly."
    if language == "ta":
        return "Transcribe Tamil caregiver speech in Tamil script. Preserve medication names, dates, and clinic names exactly."
    if language == "th":
        return "Transcribe Thai caregiver speech in Thai script. Preserve medication names, dates, and clinic names exactly."
    return None


def _transcription_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "text"}


def _http_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return response.text or f"HTTP {response.status_code}"


def _suffix_for_content_type(content_type: str | None) -> str:
    media_type = (content_type or "").split(";", 1)[0].lower().strip()
    return CONTENT_TYPE_SUFFIXES.get(media_type, ".webm")
