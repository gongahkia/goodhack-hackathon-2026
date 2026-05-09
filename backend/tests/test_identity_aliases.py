import pytest

from app.identity import ensure_patient_identity, known_people_for_redaction, learn_alias_candidates_from_transcript
from app.store import MemoryGraphStore
from app.transcript_pipeline import redact_stored_transcript


@pytest.mark.asyncio
async def test_patient_identity_aliases_redact_titles_kinship_and_learn_reasonable_variants():
    store = MemoryGraphStore()
    patient = {
        "patient_id": "patient-1",
        "name": "Madam Li Tan Kia",
        "caregiver": "Daughter, Elaine",
    }
    transcript = await store.create_node(
        "transcript",
        {
            "patient_id": "patient-1",
            "raw_text": "Miss Lee needs Panadol before lunch every day. Mom has a doctor appointment on June 1 at 10am.",
        },
        "system",
        status="approved",
    )

    await learn_alias_candidates_from_transcript(store, transcript, patient)
    known_people = await known_people_for_redaction(store, "patient-1", patient)
    redaction = await redact_stored_transcript(store, transcript, known_people=known_people)

    identity = await ensure_patient_identity(store, "patient-1", patient)
    aliases = {item["alias"] for item in identity.payload["aliases"]}

    assert "Miss Lee" in aliases
    assert "mom" in aliases
    assert "Miss Lee" not in redaction.payload["redacted_text"]
    assert "Mom" not in redaction.payload["redacted_text"]
    assert "PERSON_" in redaction.payload["redacted_text"]
