from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from uuid import UUID

from .models import PatientSummary
from .store import GraphStore


PATIENT_ID = "mdm-tan"

PATIENT = PatientSummary(
    patient_id=PATIENT_ID,
    name="Mdm Tan Siew Lan",
    age=78,
    citizenship="Singapore Citizen",
    caregiver="Daughter, Elaine",
    living_arrangement="Lives with daughter in Toa Payoh",
    key_conditions=["Hypertension"],
)


def now_sgt_anchor() -> datetime:
    return datetime.now(ZoneInfo("Asia/Singapore")).replace(hour=9, minute=0, second=0, microsecond=0)


async def mirror_nehr_node(store: GraphStore, raw_id: UUID, patient_id: str, record_type: str, content: dict, recorded_at: datetime):
    return await store.create_node(
        type="nehr_record",
        payload={
            "patient_id": patient_id,
            "raw_id": str(raw_id),
            "record_type": record_type,
            "title": content.get("title") or content.get("diagnosis") or content.get("medication") or record_type.replace("_", " ").title(),
            "content": content,
            "recorded_at": recorded_at.isoformat(),
        },
        created_by="system",
        status="approved",
    )


async def seed_baseline(store: GraphStore) -> dict:
    await store.reset_demo()
    anchor = now_sgt_anchor()
    rows = [
        (
            "lab_result",
            {
                "title": "Routine bloodwork",
                "hbA1c": "5.8%",
                "ldl": "2.4 mmol/L",
                "creatinine": "78 umol/L",
                "notes": "Stable routine bloodwork from polyclinic chronic disease review.",
            },
            anchor - timedelta(days=182),
        ),
        (
            "prescription",
            {
                "title": "Hypertension prescription",
                "medication": "Amlodipine",
                "dose": "5 mg once every morning",
                "duration": "Long-term",
                "prescriber": "Toa Payoh Polyclinic",
            },
            anchor - timedelta(days=178),
        ),
    ]
    mirrored = []
    for record_type, content, recorded_at in rows:
        raw = await store.insert_nehr_raw(PATIENT_ID, record_type, content, recorded_at)
        node = await mirror_nehr_node(store, raw.id, PATIENT_ID, record_type, content, recorded_at)
        mirrored.append(node)
    return {"patient": PATIENT.model_dump(), "records_seeded": len(mirrored)}


async def ingest_trigger_records(store: GraphStore) -> dict:
    anchor = now_sgt_anchor()
    trigger_records = [
        (
            "diagnosis",
            {
                "title": "Early-stage Parkinson's disease diagnosis",
                "diagnosis": "Early-stage Parkinson's disease",
                "icd_hint": "G20",
                "doctor": "Neurology Clinic, Tan Tock Seng Hospital",
                "notes": "Mild bradykinesia and resting tremor. Independent in basic activities. Family advised to monitor gait and falls risk.",
            },
            anchor,
        ),
        (
            "prescription",
            {
                "title": "Initial Levodopa prescription",
                "medication": "Levodopa/Carbidopa",
                "dose": "100/25 mg three times daily after meals",
                "duration": "Review at next neurology appointment",
                "notes": "Counsel caregiver on adherence and timing.",
            },
            anchor,
        ),
        (
            "appointment",
            {
                "title": "Neurologist follow-up booking",
                "clinic": "Tan Tock Seng Hospital Neurology",
                "appointment_at": (anchor + timedelta(days=90)).replace(hour=2).isoformat(),
                "notes": "Review symptoms, medication response, and mobility.",
            },
            anchor,
        ),
    ]
    nodes = []
    raws = []
    for record_type, content, recorded_at in trigger_records:
        raw = await store.insert_nehr_raw(PATIENT_ID, record_type, content, recorded_at)
        node = await mirror_nehr_node(store, raw.id, PATIENT_ID, record_type, content, recorded_at)
        raws.append(raw)
        nodes.append(node)
    return {"trigger_record_id": str(nodes[0].id), "raw_ids": [str(row.id) for row in raws], "node_ids": [str(node.id) for node in nodes]}
