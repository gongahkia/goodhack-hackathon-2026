from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .models import Node
from .store import GraphStore


PATIENT_IDENTITY_NODE = "patient_identity"
KINSHIP_ALIASES = {
    "ah ma",
    "auntie",
    "aunty",
    "grandma",
    "grandmother",
    "ma",
    "mama",
    "mom",
    "mother",
    "mum",
    "mummy",
}
TITLE_PREFIXES = ("Mdm", "Madam", "Mrs", "Ms", "Miss")
TITLE_NAME_RE = re.compile(r"\b(?:Mdm|Madam|Mr|Mrs|Ms|Miss)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b")
LEE_LI_EQUIVALENTS = {"lee", "li"}


@dataclass(frozen=True)
class IdentityAlias:
    alias: str
    entity: str
    source: str
    confidence: float
    status: str = "approved"

    def model_dump(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "entity": self.entity,
            "source": self.source,
            "confidence": self.confidence,
            "status": self.status,
        }


async def ensure_patient_identity(
    store: GraphStore,
    patient_id: str,
    patient: dict[str, Any],
) -> Node:
    existing = await patient_identity(store, patient_id)
    aliases = _dedupe_aliases(
        [
            *_aliases_from_patient(patient),
            *(_alias_from_payload(item) for item in (existing.payload.get("aliases") if existing else []) or []),
        ]
    )
    payload = {
        "patient_id": patient_id,
        "canonical_name": patient.get("name"),
        "caregiver": patient.get("caregiver"),
        "aliases": [alias.model_dump() for alias in aliases],
    }
    if existing:
        updated = await store.update_node_payload(existing.id, payload, existing.status)
        return updated or existing
    return await store.create_node(PATIENT_IDENTITY_NODE, payload, "system", status="approved")


async def patient_identity(store: GraphStore, patient_id: str) -> Node | None:
    nodes = await store.list_nodes(patient_id, [PATIENT_IDENTITY_NODE])
    return nodes[0] if nodes else None


async def known_people_for_redaction(store: GraphStore, patient_id: str, patient: dict[str, Any]) -> list[str]:
    identity = await ensure_patient_identity(store, patient_id, patient)
    aliases = [
        str(item.get("alias") or "").strip()
        for item in identity.payload.get("aliases", [])
        if str(item.get("status") or "approved") == "approved" and str(item.get("alias") or "").strip()
    ]
    return sorted(set(aliases), key=len, reverse=True)


async def upsert_patient_alias(
    store: GraphStore,
    patient_id: str,
    patient: dict[str, Any],
    alias: str,
    entity: str = "patient",
    source: str = "user",
    confidence: float = 0.95,
    status: str = "approved",
) -> Node:
    identity = await ensure_patient_identity(store, patient_id, patient)
    normalized = _normalize_alias(alias)
    aliases = [
        _alias_from_payload(item)
        for item in identity.payload.get("aliases", [])
        if _normalize_alias(str(item.get("alias") or "")) != normalized
    ]
    aliases.append(IdentityAlias(alias.strip(), entity, source, confidence, status))
    payload = {**identity.payload, "aliases": [item.model_dump() for item in _dedupe_aliases(aliases)]}
    updated = await store.update_node_payload(identity.id, payload, "approved" if status == "approved" else "clarification_required")
    return updated or identity


async def learn_alias_candidates_from_transcript(
    store: GraphStore,
    transcript: Node,
    patient: dict[str, Any],
) -> Node | None:
    patient_id = str(transcript.payload.get("patient_id") or patient.get("patient_id") or "")
    if not patient_id:
        return None
    text = str(transcript.payload.get("raw_text") or "")
    if not text.strip():
        return None
    identity = await ensure_patient_identity(store, patient_id, patient)
    existing_aliases = {_normalize_alias(str(item.get("alias") or "")) for item in identity.payload.get("aliases", [])}
    candidates = [
        alias
        for alias in _candidate_aliases(text, patient)
        if _normalize_alias(alias.alias) not in existing_aliases
    ]
    if not candidates:
        return identity
    payload_aliases = [*identity.payload.get("aliases", []), *(candidate.model_dump() for candidate in candidates)]
    updated = await store.update_node_payload(identity.id, {"aliases": payload_aliases}, "clarification_required")
    return updated or identity


def approved_patient_aliases(patient: dict[str, Any]) -> list[str]:
    return [alias.alias for alias in _aliases_from_patient(patient)]


def _aliases_from_patient(patient: dict[str, Any]) -> list[IdentityAlias]:
    name = str(patient.get("name") or "").strip()
    aliases: list[IdentityAlias] = []
    if name:
        aliases.extend(IdentityAlias(alias, "patient", "patient_profile", 0.99) for alias in _name_variants(name))
    aliases.extend(IdentityAlias(alias, "patient", "kinship_default", 0.72) for alias in sorted(KINSHIP_ALIASES))
    return _dedupe_aliases(aliases)


def _candidate_aliases(text: str, patient: dict[str, Any]) -> list[IdentityAlias]:
    patient_name = str(patient.get("name") or "")
    patient_surnames = _surname_equivalents(patient_name)
    candidates: list[IdentityAlias] = []
    for match in TITLE_NAME_RE.finditer(text):
        raw = match.group(0)
        raw_surnames = _surname_equivalents(raw)
        if raw_surnames & patient_surnames:
            confidence = 0.86 if _normalize_alias(raw) not in {_normalize_alias(item.alias) for item in _aliases_from_patient(patient)} else 0.99
            candidates.append(IdentityAlias(raw, "patient", "transcript_title_name", confidence, "approved" if confidence >= 0.85 else "pending_review"))
    for alias in KINSHIP_ALIASES:
        if re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE):
            candidates.append(IdentityAlias(alias, "patient", "transcript_kinship_term", 0.72))
    return _dedupe_aliases(candidates)


def _name_variants(name: str) -> set[str]:
    stripped = re.sub(r"^(Mdm|Madam|Mr|Mrs|Ms|Miss)\.?\s+", "", name, flags=re.IGNORECASE).strip()
    parts = stripped.split()
    surname = parts[0] if parts else ""
    variants = {name, stripped}
    if surname:
        for prefix in TITLE_PREFIXES:
            variants.add(f"{prefix} {surname}")
    return {variant for variant in variants if len(variant) >= 2}


def _surname_equivalents(name: str) -> set[str]:
    stripped = re.sub(r"^(Mdm|Madam|Mr|Mrs|Ms|Miss)\.?\s+", "", name, flags=re.IGNORECASE).strip()
    surname = stripped.split()[0].lower() if stripped.split() else ""
    if surname in LEE_LI_EQUIVALENTS:
        return set(LEE_LI_EQUIVALENTS)
    return {surname} if surname else set()


def _alias_from_payload(payload: Any) -> IdentityAlias:
    if not isinstance(payload, dict):
        return IdentityAlias(str(payload), "patient", "legacy", 0.5, "pending_review")
    return IdentityAlias(
        alias=str(payload.get("alias") or ""),
        entity=str(payload.get("entity") or "patient"),
        source=str(payload.get("source") or "stored"),
        confidence=float(payload.get("confidence") or 0.5),
        status=str(payload.get("status") or "approved"),
    )


def _dedupe_aliases(aliases: list[IdentityAlias]) -> list[IdentityAlias]:
    by_key: dict[str, IdentityAlias] = {}
    for alias in aliases:
        if not alias.alias.strip():
            continue
        key = _normalize_alias(alias.alias)
        existing = by_key.get(key)
        if not existing or alias.confidence > existing.confidence or existing.status != "approved" and alias.status == "approved":
            by_key[key] = alias
    return sorted(by_key.values(), key=lambda item: (-item.confidence, item.alias.lower()))


def _normalize_alias(alias: str) -> str:
    return re.sub(r"\s+", " ", alias.strip().lower().replace(".", ""))
