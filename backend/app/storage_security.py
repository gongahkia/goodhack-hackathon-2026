from __future__ import annotations

import base64
import hashlib
import json
from typing import Any


SENSITIVE_PAYLOAD_FIELDS = {
    "raw_text",
    "normalized_english_text",
    "placeholder_map",
    "event_payload",
    "error",
    "raw_response",
    "content",
}
ENCRYPTION_MARKER = "__encrypted__"


class FieldCrypto:
    def __init__(self, secret: str | None) -> None:
        self.secret = secret or None
        self._fernet = None
        if not self.secret:
            return
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:
            raise RuntimeError("Field encryption requires cryptography. Install backend requirements before enabling DATA_ENCRYPTION_KEY.") from exc
        digest = hashlib.sha256(self.secret.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    def encrypt_payload(self, value: Any) -> Any:
        if not self.enabled:
            return value
        return _walk_payload(value, self._encrypt_value)

    def decrypt_payload(self, value: Any) -> Any:
        if not self.enabled:
            return value
        return _walk_encrypted(value, self._decrypt_value)

    def _encrypt_value(self, value: Any) -> dict[str, str]:
        encoded = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        token = self._fernet.encrypt(encoded).decode("ascii")
        return {ENCRYPTION_MARKER: "fernet-v1", "value": token}

    def _decrypt_value(self, value: dict[str, str]) -> Any:
        token = str(value["value"]).encode("ascii")
        raw = self._fernet.decrypt(token)
        return json.loads(raw.decode("utf-8"))


def _walk_payload(value: Any, encrypt_fn) -> Any:
    if isinstance(value, dict):
        encrypted = {}
        for key, item in value.items():
            if key in SENSITIVE_PAYLOAD_FIELDS and item not in (None, "", {}, []):
                encrypted[key] = encrypt_fn(item)
            else:
                encrypted[key] = _walk_payload(item, encrypt_fn)
        return encrypted
    if isinstance(value, list):
        return [_walk_payload(item, encrypt_fn) for item in value]
    return value


def _walk_encrypted(value: Any, decrypt_fn) -> Any:
    if isinstance(value, dict):
        if value.get(ENCRYPTION_MARKER) == "fernet-v1" and "value" in value:
            return decrypt_fn(value)
        return {key: _walk_encrypted(item, decrypt_fn) for key, item in value.items()}
    if isinstance(value, list):
        return [_walk_encrypted(item, decrypt_fn) for item in value]
    return value
