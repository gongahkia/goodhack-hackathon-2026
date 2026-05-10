from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
NRIC_RE = re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE)
SG_PHONE_RE = re.compile(r"(?<!\d)(?:\+65[\s-]?)?[689]\d{3}[\s-]?\d{4}(?!\d)")
GENERIC_PHONE_RE = re.compile(r"(?<!\d)(?:\+\d{1,3}[\s-]?)?(?:\d{3}[\s-]){2}\d{4}(?!\d)")
AGE_RE = re.compile(r"\b(age|aged)\s+(\d{1,3})\b", re.IGNORECASE)
TITLED_NAME_RE = re.compile(r"\b(?:Mdm|Madam|Mr|Mrs|Ms)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b")
CONTEXTUAL_NAME_RE = re.compile(r"\b([A-Z][a-z]{1,40})(?=\s+(?:aged|age|needs|need|must|should|may|might|has|had|will|takes|take|requires|require)\b)")
ADDRESS_HINT_RE = re.compile(r"\b(?:blk|block|unit|#\d|street|road|avenue|ave|lane|drive|postal|postcode)\b", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"\b[A-Z][A-Z_]*_\d+\b")
KINSHIP_MONTH_ALIAS_RE = re.compile(
    r"\b(?:aunt|auntie|aunty|uncle|ah ma|grandma|grandmother|mom|mum|mother|mama)\s+"
    r"(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|september|oct|october|nov|november|dec|december)\b",
    re.IGNORECASE,
)
NON_PERSON_CONTEXTUAL_NAMES = {
    "Panadol",
    "Paracetamol",
    "Insulin",
    "Metformin",
    "Aspirin",
    "HealthHub",
    "Singpass",
    "Jan",
    "January",
    "Feb",
    "February",
    "Mar",
    "March",
    "Apr",
    "April",
    "May",
    "Jun",
    "June",
    "Jul",
    "July",
    "Aug",
    "August",
    "Sep",
    "September",
    "Oct",
    "October",
    "Nov",
    "November",
    "Dec",
    "December",
}

KEY_CATEGORY = {
    "patient_name": "PATIENT",
    "nric": "NRIC",
    "fin": "NRIC",
    "phone": "PHONE",
    "mobile": "PHONE",
    "email": "EMAIL",
    "age": "AGE",
    "address": "ADDRESS",
    "postal_code": "ADDRESS",
}


@dataclass
class PiiRedactor:
    redact_age: bool = True
    contextual_person_names: bool = False
    seed_identifiers: dict[str, str] = field(default_factory=dict)
    _value_to_placeholder: dict[str, str] = field(default_factory=dict)
    _placeholder_to_value: dict[str, str] = field(default_factory=dict)
    _category_counts: Counter[str] = field(default_factory=Counter)
    _placeholder_counts: Counter[str] = field(default_factory=Counter)

    def seed_from_patient(self, patient: dict[str, Any]) -> None:
        name = str(patient.get("name") or "").strip()
        if name:
            for variant in _name_variants(name):
                self.seed_identifiers[variant] = "PATIENT"
        patient_id = str(patient.get("patient_id") or "").strip()
        if patient_id:
            self.seed_identifiers[patient_id] = "PATIENT_ID"
        caregiver = str(patient.get("caregiver") or "").strip()
        if caregiver:
            for variant in _caregiver_name_variants(caregiver):
                self.seed_identifiers[variant] = "CAREGIVER"

    def redact(self, value: Any) -> Any:
        return self._redact_value(value, path=())

    def restore_placeholders(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self.restore_placeholders(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.restore_placeholders(item) for item in value]
        if isinstance(value, str):
            restored = value
            for placeholder, raw in sorted(self._placeholder_to_value.items(), key=lambda item: len(item[0]), reverse=True):
                restored = restored.replace(placeholder, raw)
            return restored
        return value

    def summary(self) -> dict[str, Any]:
        return {
            "redaction_ran": True,
            "detected_categories": sorted(self._category_counts),
            "placeholder_counts": dict(self._placeholder_counts),
            "placeholder_total": sum(self._placeholder_counts.values()),
        }

    def placeholder_map(self) -> dict[str, str]:
        return dict(self._placeholder_to_value)

    def _redact_value(self, value: Any, path: tuple[str, ...]) -> Any:
        key = path[-1].lower() if path else ""
        if isinstance(value, dict):
            return {item_key: self._redact_value(item_value, (*path, str(item_key))) for item_key, item_value in value.items()}
        if isinstance(value, list):
            return [self._redact_value(item, path) for item in value]
        if value is None:
            return None
        if key == "name" and any(part.lower().startswith("patient") for part in path):
            return self._placeholder(str(value), "PATIENT")
        if key == "age" and not self.redact_age:
            return value
        if key in KEY_CATEGORY:
            return self._placeholder(str(value), KEY_CATEGORY[key])
        if "address" in key or "postal" in key:
            return self._placeholder(str(value), "ADDRESS")
        if key == "caregiver":
            return self._redact_text_preserving_role(str(value))
        if isinstance(value, str):
            return self._redact_text(value)
        return value

    def _redact_text_preserving_role(self, text: str) -> str:
        if "," in text:
            role, rest = text.split(",", 1)
            return f"{role},{self._redact_text(rest)}"
        return self._redact_text(text)

    def _redact_text(self, text: str) -> str:
        redacted = text
        for raw, category in sorted(self.seed_identifiers.items(), key=lambda item: len(item[0]), reverse=True):
            if raw and not _is_kinship_month_alias(raw):
                redacted = re.sub(re.escape(raw), lambda match, item_category=category: self._placeholder(match.group(0), item_category), redacted, flags=re.IGNORECASE)
        redacted = EMAIL_RE.sub(lambda match: self._placeholder(match.group(0), "EMAIL"), redacted)
        redacted = NRIC_RE.sub(lambda match: self._placeholder(match.group(0), "NRIC"), redacted)
        redacted = SG_PHONE_RE.sub(lambda match: self._placeholder(match.group(0), "PHONE"), redacted)
        redacted = GENERIC_PHONE_RE.sub(lambda match: self._placeholder(match.group(0), "PHONE"), redacted)
        if self.redact_age:
            redacted = AGE_RE.sub(lambda match: f"{match.group(1)} {self._placeholder(match.group(2), 'AGE')}", redacted)
        redacted = TITLED_NAME_RE.sub(lambda match: self._placeholder(match.group(0), "PERSON"), redacted)
        if self.contextual_person_names:
            redacted = CONTEXTUAL_NAME_RE.sub(lambda match: self._placeholder(match.group(1), "PERSON") if match.group(1) not in NON_PERSON_CONTEXTUAL_NAMES else match.group(1), redacted)
        if ADDRESS_HINT_RE.search(redacted):
            redacted = _redact_address_fragments(redacted, self)
        return redacted

    def _placeholder(self, raw: str, category: str) -> str:
        if raw in self._value_to_placeholder:
            return self._value_to_placeholder[raw]
        existing = next((placeholder for value, placeholder in self._value_to_placeholder.items() if value.lower() == raw.lower()), None)
        if existing:
            self._value_to_placeholder[raw] = existing
            return existing
        self._category_counts[category] += 1
        placeholder = f"{category}_{self._category_counts[category]}"
        self._value_to_placeholder[raw] = placeholder
        self._placeholder_to_value[placeholder] = raw
        self._placeholder_counts[category] += 1
        return placeholder


def redact_for_openai(value: Any, patient: dict[str, Any] | None = None) -> tuple[Any, PiiRedactor]:
    redactor = PiiRedactor()
    if patient:
        redactor.seed_from_patient(patient)
    return redactor.redact(value), redactor


def redact_transcript_direct_pii(text: str, known_people: list[str] | None = None) -> dict[str, Any]:
    redactor = PiiRedactor(redact_age=False, contextual_person_names=True)
    for person in known_people or []:
        if person.strip():
            redactor.seed_identifiers[person.strip()] = "PERSON"
    redacted_text = redactor.redact(text)
    return {
        "raw_text": text,
        "redacted_text": redacted_text,
        "placeholder_map": redactor.placeholder_map(),
        "privacy": redactor.summary(),
    }


def rehydrate_placeholders(value: Any, placeholder_map: dict[str, str]) -> Any:
    unknown = sorted(_unknown_placeholders(value, set(placeholder_map)))
    if unknown:
        raise ValueError(f"Unknown placeholder reference(s): {', '.join(unknown)}")
    return _replace_placeholders(value, placeholder_map)


def sanitize_audit_payload(value: Any, patient: dict[str, Any]) -> dict[str, Any]:
    redactor = PiiRedactor()
    redactor.seed_from_patient(patient)
    redacted = redactor.redact(value)
    if isinstance(redacted, dict):
        redacted["audit_privacy"] = redactor.summary()
        return redacted
    return {"value": redacted, "audit_privacy": redactor.summary()}


def _unknown_placeholders(value: Any, known: set[str]) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(_unknown_placeholders(item, known) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_unknown_placeholders(item, known) for item in value)) if value else set()
    if isinstance(value, str):
        return {placeholder for placeholder in PLACEHOLDER_RE.findall(value) if placeholder not in known}
    return set()


def _replace_placeholders(value: Any, placeholder_map: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _replace_placeholders(item, placeholder_map) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_placeholders(item, placeholder_map) for item in value]
    if isinstance(value, str):
        restored = value
        for placeholder, raw in sorted(placeholder_map.items(), key=lambda item: len(item[0]), reverse=True):
            restored = restored.replace(placeholder, raw)
        return restored
    return value


def _name_variants(name: str) -> set[str]:
    variants = {name}
    stripped = re.sub(r"^(Mdm|Madam|Mr|Mrs|Ms)\.?\s+", "", name, flags=re.IGNORECASE).strip()
    if stripped and stripped != name:
        variants.add(stripped)
        first = stripped.split()[0]
        title = name.split()[0]
        variants.add(f"{title} {first}")
    return {variant for variant in variants if len(variant) >= 3}


def _caregiver_name_variants(caregiver: str) -> set[str]:
    pieces = [piece.strip() for piece in re.split(r"[,/]", caregiver) if piece.strip()]
    roles = {"daughter", "son", "wife", "husband", "spouse", "caregiver", "helper", "granddaughter", "grandson"}
    return {piece for piece in pieces if piece.lower() not in roles and len(piece) >= 3}


def _redact_address_fragments(text: str, redactor: PiiRedactor) -> str:
    patterns = [
        re.compile(r"\b(?:blk|block)\s+\d+[A-Za-z]?(?:\s+[A-Za-z0-9 #\-]+)?", re.IGNORECASE),
        re.compile(r"#\d{1,3}-\d{1,4}", re.IGNORECASE),
        re.compile(r"\b\d{6}\b"),
    ]
    redacted = text
    for pattern in patterns:
        redacted = pattern.sub(lambda match: redactor._placeholder(match.group(0), "ADDRESS"), redacted)
    return redacted


def _is_kinship_month_alias(value: str) -> bool:
    return bool(KINSHIP_MONTH_ALIAS_RE.fullmatch(value.strip()))
