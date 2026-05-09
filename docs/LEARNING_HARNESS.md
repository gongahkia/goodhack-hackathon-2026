# Learning Harness

The backend improves API-call behavior through context engineering and evaluation records, not model training.

## What Exists

The learning harness can:

- build compact runtime context from caregiver feedback, memory profiles, and model evaluations
- record model evaluation outcomes for extraction, triage, scheduling, research, and synthesis behavior
- create prompt candidates for human review
- keep learning artifacts in the graph for auditability

## What Does Not Happen

The backend does not:

- export datasets for later model training
- fine-tune a model
- run RLHF or RLAIF loops
- optimize or deploy prompts automatically
- edit its own source code
- include raw transcripts or placeholder maps in learning context

Prompt candidates are stored with:

```json
{
  "deployment_status": "pending_human_review",
  "autonomous_activation_allowed": false
}
```

## API

Inspect compact learning context:

```bash
curl -s http://127.0.0.1:8000/learning/context \
  -H "X-API-Key: $API_WRITE_KEY" | jq
```

Create a model evaluation:

```bash
curl -s -X POST http://127.0.0.1:8000/learning/model-evaluations \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_WRITE_KEY" \
  -d '{
    "component": "triage",
    "input_node_ids": ["NODE_UUID"],
    "outcome": "fail",
    "scores": {"specificity": 0.4},
    "failure_tags": ["unwanted_research"],
    "recommended_follow_up": "Block research for simple medication reminders."
  }' | jq
```

Create a prompt candidate:

```bash
curl -s -X POST http://127.0.0.1:8000/learning/prompt-candidates \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_WRITE_KEY" \
  -d '{
    "component": "triage",
    "current_prompt_version": "triage.v1",
    "proposed_prompt": "Classify simple medication reminders as daily tasks only.",
    "rationale": "Evaluation showed speculative research should stay blocked.",
    "source_model_evaluation_id": "MODEL_EVALUATION_UUID"
  }' | jq
```

## Graph Artifacts

Learning nodes:

- `model_evaluation`
- `prompt_candidate`

Learning edges:

- `evaluates`
- `candidate_from`

These make it possible to trace a prompt candidate back to a reviewed model behavior without creating a training dataset export.
