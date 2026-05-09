from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from .models import Node
from .store import GraphStore


class ConsentRecordCreate(BaseModel):
    purpose: str = Field(min_length=1, max_length=120)
    notice_version: str = Field(default="pilot.v1", max_length=80)
    channel: str = Field(default="api", max_length=80)
    granted: bool = True


class DataSubjectRequestCreate(BaseModel):
    request_type: str = Field(pattern="^(access|export|correction|deletion|withdrawal)$")
    requester: str = Field(default="caregiver", max_length=120)
    details: str | None = Field(default=None, max_length=2000)


class PrivacyIncidentCreate(BaseModel):
    summary: str = Field(min_length=1, max_length=500)
    affected_data_categories: list[str] = Field(default_factory=list, max_length=20)
    affected_user_count: int | None = Field(default=None, ge=0)
    discovered_at: datetime | None = None
    assessed_at: datetime | None = None
    status: str = Field(default="open", max_length=80)


async def record_consent(
    store: GraphStore,
    patient_id: str,
    purpose: str,
    notice_version: str = "pilot.v1",
    channel: str = "api",
    granted: bool = True,
) -> Node:
    return await store.create_node(
        "consent_record",
        {
            "patient_id": patient_id,
            "purpose": purpose,
            "notice_version": notice_version,
            "channel": channel,
            "granted": granted,
            "recorded_at": datetime.now(UTC).isoformat(),
        },
        "user",
        status="approved" if granted else "dismissed",
    )


async def record_processing_activity(
    store: GraphStore,
    patient_id: str,
    purpose: str,
    data_categories: list[str],
    source_node_id: str | None = None,
    vendor: str | None = None,
    transfer_region: str | None = None,
) -> Node:
    return await store.create_node(
        "processing_activity",
        {
            "patient_id": patient_id,
            "purpose": purpose,
            "data_categories": data_categories,
            "source_node_id": source_node_id,
            "vendor": vendor,
            "transfer_region": transfer_region,
            "recorded_at": datetime.now(UTC).isoformat(),
        },
        "system",
        status="approved",
    )


async def create_data_subject_request(store: GraphStore, patient_id: str, request: DataSubjectRequestCreate) -> Node:
    return await store.create_node(
        "data_subject_request",
        {
            "patient_id": patient_id,
            **request.model_dump(mode="json"),
            "status": "received",
            "received_at": datetime.now(UTC).isoformat(),
        },
        "user",
        status="pending_review",
    )


async def create_privacy_incident(store: GraphStore, incident: PrivacyIncidentCreate) -> Node:
    discovered_at = incident.discovered_at or datetime.now(UTC)
    assessed_at = incident.assessed_at
    payload = {
        **incident.model_dump(mode="json"),
        "discovered_at": discovered_at.isoformat(),
        "assessed_at": assessed_at.isoformat() if assessed_at else None,
        "singapore_pdpa_assessment_expected_by": (discovered_at + timedelta(days=30)).isoformat(),
        "singapore_pdpc_notify_by": (assessed_at + timedelta(days=3)).isoformat() if assessed_at else None,
        "regional_72h_notify_by": (assessed_at + timedelta(hours=72)).isoformat() if assessed_at else None,
        "notifiable_assessment": "pending" if not assessed_at else "requires_review",
    }
    return await store.create_node("privacy_incident", payload, "system", status="pending_review")


async def purge_expired_sensitive_data(store: GraphStore, patient_id: str, settings: Any, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    raw_days = int(getattr(settings, "raw_transcript_retention_days", 30))
    placeholder_days = int(getattr(settings, "placeholder_map_retention_days", 30))
    audit_days = int(getattr(settings, "audit_log_retention_days", 365))
    purged_nodes: list[str] = []

    for node in await store.list_nodes(patient_id):
        age_days = (current - node.created_at.astimezone(UTC)).days
        patch: dict[str, Any] = {}
        if node.type == "transcript" and age_days >= raw_days:
            patch.update({"raw_text": None, "normalized_english_text": None, "retention_status": "raw_transcript_purged"})
        if node.type == "pii_redaction" and age_days >= placeholder_days:
            patch.update({"placeholder_map": {}, "retention_status": "placeholder_map_purged"})
        if node.type == "calendar_write_request" and age_days >= audit_days:
            patch.update({"event_payload": None, "error": None, "retention_status": "calendar_payload_purged"})
        if not patch:
            continue
        await store.update_node_payload(node.id, {**patch, "retention_purged_at": current.isoformat()}, node.status)
        tombstone = await store.create_node(
            "retention_tombstone",
            {
                "patient_id": patient_id,
                "source_node_id": str(node.id),
                "source_node_type": node.type,
                "purged_fields": sorted(patch),
                "purged_at": current.isoformat(),
            },
            "system",
            status="approved",
        )
        await store.create_edge(tombstone.id, node.id, "retention_applied")
        purged_nodes.append(str(node.id))

    return {"purged_node_ids": purged_nodes, "purged_count": len(purged_nodes)}
