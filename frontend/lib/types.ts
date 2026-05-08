export type NodeStatus = "pending_review" | "approved" | "dismissed" | "edited";

export type KgNode = {
  id: string;
  type: string;
  payload: Record<string, any>;
  created_by: "agent" | "system" | "user";
  created_at: string;
  reasoning_log_id?: string | null;
  status: NodeStatus;
};

export type KgEdge = {
  id: string;
  from_node: string;
  to_node: string;
  type: string;
  created_at: string;
};

export type ReasoningLog = {
  id: string;
  trigger: string;
  steps: Array<Record<string, any>>;
  conclusion?: string | null;
  created_at: string;
};

export type EventDetail = KgNode & {
  source_records: KgNode[];
  related_nodes: KgNode[];
  related_edges: KgEdge[];
  reasoning_log?: ReasoningLog | null;
};

export type PatientSummary = {
  patient_id: string;
  name: string;
  age: number;
  citizenship: string;
  caregiver: string;
  living_arrangement: string;
  key_conditions: string[];
};
