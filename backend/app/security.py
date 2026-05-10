from __future__ import annotations

import hmac
import re
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import HTTPException, Request

from .models import Node


RAW_DATA_REDACTION = "[redacted]"
SENSITIVE_FIELD_NAMES = {
    "raw_text",
    "normalized_english_text",
    "placeholder_map",
    "event_payload",
    "google_event_id",
    "html_link",
    "error",
    "raw_response",
    "content",
    "access_token",
    "refresh_token",
    "id_token",
}
SENSITIVE_NODE_TYPES = {"transcript", "pii_redaction", "calendar_write_request", "calendar_account"}


def key_matches(candidate: str | None, allowed: list[str | None]) -> bool:
    if not candidate:
        return False
    return any(bool(secret) and hmac.compare_digest(candidate, secret) for secret in allowed)


def require_pilot_security(settings: Any) -> None:
    env = str(getattr(settings, "app_env", "development")).lower()
    if env not in {"pilot", "production", "prod"}:
        return
    missing = []
    if not getattr(settings, "api_write_key", None):
        missing.append("API_WRITE_KEY")
    if not getattr(settings, "api_read_key", None):
        missing.append("API_READ_KEY")
    if not getattr(settings, "data_encryption_key", None):
        missing.append("DATA_ENCRYPTION_KEY")
    if missing:
        raise RuntimeError(f"{', '.join(missing)} must be configured when APP_ENV={settings.app_env}.")


def sanitize_public(value: Any) -> Any:
    if isinstance(value, Node):
        return sanitize_public(value.model_dump(mode="json"))
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        node_type = str(value.get("type") or "")
        for key, item in value.items():
            if key == "payload" and isinstance(item, dict):
                sanitized[key] = _sanitize_payload(item, node_type)
            elif key in SENSITIVE_FIELD_NAMES:
                sanitized[key] = RAW_DATA_REDACTION
            elif key == "steps" and isinstance(item, list):
                sanitized[key] = [_sanitize_reasoning_step(step) for step in item]
            else:
                sanitized[key] = sanitize_public(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_public(item) for item in value]
    return value


def sanitize_provider_error(exc: Exception | str) -> str:
    text = str(exc)
    text = re.sub(r"Bearer\s+[A-Za-z0-9._~+\-/=]+", "Bearer [redacted]", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-[redacted]", text)
    text = re.sub(r"(?i)(api[_ -]?key|access[_ -]?token|authorization)[=:]\s*[^,\s)]+", r"\1=[redacted]", text)
    return text[:500]


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        events = self._events[key]
        while events and events[0] <= now - window_seconds:
            events.popleft()
        if len(events) >= limit:
            raise HTTPException(429, "Too many requests. Try again later.")
        events.append(now)


def rate_limit_key(request: Request, operation: str) -> str:
    client = request.client.host if request.client else "unknown"
    api_key = request.headers.get("x-api-key") or request.headers.get("x-clinician-key") or "anonymous"
    return f"{operation}:{client}:{api_key[:12]}"


def vendor_allowed(settings: Any, vendor: str, purpose: str) -> bool:
    if not getattr(settings, "external_vendors_enabled", True):
        return False
    flag_name = f"vendor_{vendor.lower().replace('-', '_')}_enabled"
    if not getattr(settings, flag_name, True):
        return False
    allowed = getattr(settings, "vendor_allowed_purposes", "")
    if not allowed:
        return True
    allowed_pairs = {item.strip() for item in str(allowed).split(",") if item.strip()}
    return f"{vendor}:{purpose}" in allowed_pairs or f"{vendor}:*" in allowed_pairs


def vendor_blocked_response(vendor: str, purpose: str) -> dict[str, Any]:
    return {
        "provider": vendor,
        "configured": False,
        "results": [],
        "result": None,
        "error": f"Vendor '{vendor}' is disabled for purpose '{purpose}'.",
    }


def _sanitize_payload(payload: dict[str, Any], node_type: str) -> dict[str, Any]:
    return {
        key: (
            RAW_DATA_REDACTION
            if key in SENSITIVE_FIELD_NAMES or (node_type in SENSITIVE_NODE_TYPES and key in {"metadata", "normalization_metadata"})
            else sanitize_public(value)
        )
        for key, value in payload.items()
    }


def _sanitize_reasoning_step(step: Any) -> Any:
    if not isinstance(step, dict):
        return sanitize_public(step)
    return {
        key: RAW_DATA_REDACTION if key in SENSITIVE_FIELD_NAMES or key.endswith("_payload") else sanitize_public(value)
        for key, value in step.items()
    }
