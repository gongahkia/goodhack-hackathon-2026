from __future__ import annotations

from .models import PatientSummary


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
