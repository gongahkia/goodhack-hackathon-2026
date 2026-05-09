from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from .config import Settings


class TranscriptionError(RuntimeError):
    status_code = 500


class TranscriptionUnavailable(TranscriptionError):
    status_code = 503


class TranscriptionInputError(TranscriptionError):
    status_code = 400


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    provider: str
    model: str
    language: str | None = None
    metadata: dict[str, Any] | None = None

    def model_dump(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "language": self.language,
            "metadata": self.metadata or {},
        }


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

    provider = settings.transcription_provider.lower().strip()
    errors: list[str] = []
    if provider in {"local", "auto", "mlx", "mlx-whisper"}:
        try:
            return await _transcribe_locally(audio, content_type, settings)
        except TranscriptionUnavailable as exc:
            errors.append(str(exc))
            if provider not in {"auto"}:
                raise

    if provider in {"openai", "openai-api"}:
        return await _transcribe_with_openai(audio, content_type, settings)

    if provider in {"groq", "auto"}:
        try:
            return await _transcribe_with_groq(audio, content_type, settings)
        except TranscriptionUnavailable as exc:
            errors.append(str(exc))
            raise TranscriptionUnavailable(" ".join(errors) if errors else str(exc)) from exc

    raise TranscriptionUnavailable(
        f"Unknown transcription provider '{settings.transcription_provider}'. Use 'local', 'openai', 'groq', or 'auto'."
    )


async def _transcribe_locally(audio: bytes, content_type: str | None, settings: Settings) -> TranscriptionResult:
    backend = settings.local_transcription_backend.lower().strip()
    errors: list[str] = []
    if backend in {"auto", "mlx", "mlx-whisper"}:
        try:
            return await _transcribe_with_mlx_whisper(audio, content_type, settings)
        except TranscriptionUnavailable as exc:
            errors.append(str(exc))
            if backend != "auto":
                raise
    if backend in {"auto", "faster", "faster-whisper", "cpu"}:
        try:
            return await _transcribe_with_faster_whisper(audio, content_type, settings)
        except TranscriptionUnavailable as exc:
            errors.append(str(exc))
            raise TranscriptionUnavailable(" ".join(errors) if errors else str(exc)) from exc
    raise TranscriptionUnavailable(
        f"Unknown local transcription backend '{settings.local_transcription_backend}'. Use 'auto', 'mlx-whisper', or 'faster-whisper'."
    )


async def _transcribe_with_mlx_whisper(audio: bytes, content_type: str | None, settings: Settings) -> TranscriptionResult:
    return await asyncio.to_thread(_run_mlx_whisper, audio, content_type, settings)


def _run_mlx_whisper(audio: bytes, content_type: str | None, settings: Settings) -> TranscriptionResult:
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
        if settings.transcription_language:
            kwargs["language"] = settings.transcription_language
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
        language=settings.transcription_language or None,
    )


async def _transcribe_with_faster_whisper(audio: bytes, content_type: str | None, settings: Settings) -> TranscriptionResult:
    return await asyncio.to_thread(_run_faster_whisper, audio, content_type, settings)


def _run_faster_whisper(audio: bytes, content_type: str | None, settings: Settings) -> TranscriptionResult:
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
            language=settings.transcription_language or None,
            beam_size=5,
            vad_filter=True,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
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
        language=settings.transcription_language or None,
    )


@lru_cache(maxsize=2)
def _faster_whisper_model(model_name: str, compute_type: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_name, device="cpu", compute_type=compute_type)


async def _transcribe_with_groq(audio: bytes, content_type: str | None, settings: Settings) -> TranscriptionResult:
    if not settings.groq_api_key:
        raise TranscriptionUnavailable("Groq transcription requires GROQ_API_KEY.")

    suffix = _suffix_for_content_type(content_type)
    files = {"file": (f"recording{suffix}", audio, content_type or "application/octet-stream")}
    data = {
        "model": settings.groq_transcription_model,
        "response_format": "json",
        "temperature": "0",
    }
    if settings.transcription_language:
        data["language"] = settings.transcription_language

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
        raise TranscriptionUnavailable(f"Groq transcription failed: {exc}") from exc

    payload = response.json()
    text = str(payload.get("text", "")).strip()
    if not text:
        raise TranscriptionInputError("No speech was detected in the audio.")
    return TranscriptionResult(
        text=text,
        provider="groq",
        model=settings.groq_transcription_model,
        language=settings.transcription_language or None,
        metadata=_transcription_metadata(payload),
    )


async def _transcribe_with_openai(audio: bytes, content_type: str | None, settings: Settings) -> TranscriptionResult:
    if not settings.openai_api_key:
        raise TranscriptionUnavailable("OpenAI transcription requires OPENAI_API_KEY.")

    suffix = _suffix_for_content_type(content_type)
    files = {"file": (f"recording{suffix}", audio, content_type or "application/octet-stream")}
    data = {
        "model": settings.openai_transcription_model,
        "response_format": "json",
        "temperature": "0",
    }
    if settings.transcription_language:
        data["language"] = settings.transcription_language

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
        raise TranscriptionUnavailable(f"OpenAI transcription failed: {detail}") from exc
    except httpx.HTTPError as exc:
        raise TranscriptionUnavailable(f"OpenAI transcription failed: {exc}") from exc

    payload = response.json()
    text = str(payload.get("text", "")).strip()
    if not text:
        raise TranscriptionInputError("No speech was detected in the audio.")
    return TranscriptionResult(
        text=text,
        provider="openai",
        model=settings.openai_transcription_model,
        language=payload.get("language") or settings.transcription_language or None,
        metadata=_transcription_metadata(payload),
    )


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
