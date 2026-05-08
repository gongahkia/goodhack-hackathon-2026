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
]

EdgeType = Literal["derived_from", "triggers", "recommends", "applies_to", "feedback_on"]
CreatedBy = Literal["agent", "system", "user"]
NodeStatus = Literal["pending_review", "approved", "dismissed", "edited"]


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


class NodeEdit(BaseModel):
    payload: dict[str, Any]
    status: NodeStatus = "edited"
