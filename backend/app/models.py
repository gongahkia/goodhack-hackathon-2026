from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


NodeType = Literal[
    "nehr_record",
    "inferred_condition",
    "scheduled_action",
    "recommended_resource",
    "grant_opportunity",
    "caregiver_feedback",
    "caregiver_note",
    "care_intent",
    "research_note",
    "decision_forecast",
    "memory_profile",
    "human_evaluation",
]

EdgeType = Literal[
    "derived_from",
    "triggers",
    "recommends",
    "applies_to",
    "feedback_on",
    "extracted_from",
    "clarifies",
    "researches",
    "scheduled_from",
    "evaluates",
]
CreatedBy = Literal["agent", "system", "user"]
NodeStatus = Literal["pending_review", "approved", "dismissed", "edited", "clarification_required"]


class Node(BaseModel):
    id: UUID
    type: NodeType
    payload: dict[str, Any]
    created_by: CreatedBy
    created_at: datetime
    reasoning_log_id: UUID | None = None
    status: NodeStatus = "pending_review"


class Edge(BaseModel):
    id: UUID
    from_node: UUID
    to_node: UUID
    type: EdgeType
    created_at: datetime


class ReasoningLog(BaseModel):
    id: UUID
    trigger: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    conclusion: str | None = None
    created_at: datetime


class NehrRecordRaw(BaseModel):
    id: UUID
    patient_id: str
    record_type: str
    content: dict[str, Any]
    recorded_at: datetime
    ingested_at: datetime


class GraphSubset(BaseModel):
    nodes: list[Node]
    edges: list[Edge]


class PatientSummary(BaseModel):
    patient_id: str
    name: str
    age: int
    citizenship: str
    caregiver: str
    living_arrangement: str
    key_conditions: list[str]


class StatusUpdate(BaseModel):
    status: NodeStatus
    usefulness_score: int | None = Field(default=None, ge=1, le=5)
    feedback_note: str | None = None
    steer: str | None = None


class NodeEdit(BaseModel):
    payload: dict[str, Any]
    status: NodeStatus = "edited"


class CaregiverNoteCreate(BaseModel):
    text: str
    recorded_at: datetime | None = None


class ClarificationUpdate(BaseModel):
    answer: str
    payload_patch: dict[str, Any] = Field(default_factory=dict)


class HumanEvaluationCreate(BaseModel):
    action_id: UUID
    reviewer_role: str = "clinician"
    provenance_score: int = Field(ge=1, le=5)
    reasoning_score: int = Field(ge=1, le=5)
    appropriateness_score: int = Field(ge=1, le=5)
    burden_score: int = Field(ge=1, le=5)
    notes: str | None = None
