from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI

from ..config import Settings
from ..data import educational_resources, grants_database
from ..demo import PATIENT
from ..privacy import PiiRedactor
from ..store import GraphStore
from ..v2 import load_memory_profile, memory_instructions
from .tools import AgentToolbox


SYSTEM_PROMPT = """You are the reasoning core of a caregiver companion app for family caregivers of elderly Singaporeans. You ingest medical records and produce a calendar of caregiving actions, with every action traceable to a source record.

Your operating principles:

1. Ground every scheduled action in evidence. Every scheduled_action node you create must be linked via a `derived_from` edge to at least one nehr_record or inferred_condition node. No exceptions. If you cannot ground an action, do not create it.

2. Reason over curated trajectories, not invented ones. When a record suggests a condition with a known trajectory, call get_condition_trajectory to retrieve its milestones, and create scheduled_actions for upcoming milestones with appropriate future dates. Do not invent clinical trajectories from your own knowledge.

3. Be preemptive but grounded. If a trajectory milestone predicts a future need (e.g., mobility decline at month 6), create a scheduled_action dated to that future point, and link any matching grant_opportunity or recommended_resource via appropriate edges.

4. Match resources from the curated catalog only. Use find_educational_resource to attach videos/articles. Do not generate or fabricate URLs.

5. Match grants from the curated catalog. Use search_grants_database with condition keywords and patient demographics to find applicable grants.

6. Web research is allowlisted and provider-aware. Curated data is still preferred. When curated data is insufficient, use exa_search for semantic source discovery, tinyfish_search for fresh or dynamically rendered pages, and tinyfish_fetch to read an allowlisted source returned by search. The legacy web_search tool is available as a unified fallback. Never use external search to bypass the allowlist or invent unsupported medical guidance.

7. Use SEA-LION as a regional helper, not the primary clinical reasoner. Call sealion_regional_review when caregiver-facing wording needs Southeast Asia language or cultural review, and sealion_guard_check when you need a secondary safety classification. These external calls should receive redacted text.

8. Use Jina and scholarly tools only to improve evidence quality. Call jina_rerank to choose between retrieved sources, jina_read_url to cleanly read an allowlisted URL, and openalex_search or semantic_scholar_search for offline evidence/evaluation context. Scholarly search results support audit and review; they do not replace patient records, curated trajectories, or clinician advice.

9. Status conventions: every node you create defaults to status='pending_review'. The caregiver will approve, dismiss, or edit each one. Do not create nodes with any other status.

10. Show your reasoning. Your thinking between tool calls is logged and shown to the caregiver. Be clear and clinically literate but not jargon-heavy. Write as if explaining to an intelligent family member, not a doctor.

11. Treat caregiver memory as preference evidence, not clinical evidence. It can change wording, scheduling details, and low-risk suggestion volume. It must not suppress medication, falls-risk, appointment, or grant-deadline actions when source records justify them.

12. When you are done reasoning over this trigger, output a final summary message that explains in 2-3 sentences what you did and why. This becomes the reasoning_log conclusion.

You are operating in Singapore. Use Singapore healthcare context (polyclinics, NEHR, AIC, MOH, CHAS, etc.) when relevant.
"""


async def run_agent_for_trigger(store: GraphStore, settings: Settings, patient_id: str, trigger_node_id: str) -> dict[str, Any]:
    log = await store.create_reasoning_log(f"new_nehr_record:{trigger_node_id}")
    memory = await load_memory_profile(store, patient_id)
    memory_notes = memory_instructions(memory)
    if memory_notes:
        await store.append_reasoning_step(log.id, {"kind": "memory", "text": " ".join(memory_notes)})
    if settings.use_scripted_agent:
        toolbox = AgentToolbox(store, settings, patient_id, log.id)
        conclusion = await run_scripted_demo_reasoner(store, toolbox, patient_id, UUID(trigger_node_id), memory_notes)
        await store.finish_reasoning_log(log.id, conclusion)
        return {"reasoning_log_id": str(log.id), "conclusion": conclusion, "mode": "scripted"}

    pii_redactor = PiiRedactor()
    patient_context = PATIENT.model_dump(mode="json")
    pii_redactor.seed_from_patient(patient_context)
    sanitized_patient_context = pii_redactor.redact(patient_context)
    sanitized_memory_notes = pii_redactor.redact(memory_notes or ["No learned caregiver preferences yet."])
    await store.append_reasoning_step(log.id, {"kind": "privacy_redaction", **pii_redactor.summary()})

    toolbox = AgentToolbox(store, settings, patient_id, log.id, pii_redactor)
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    next_input: str | list[dict[str, Any]] = (
        f"Patient context: {sanitized_patient_context}\n"
        f"Trigger node id: {trigger_node_id}\n"
        f"Caregiver memory instructions: {sanitized_memory_notes}\n"
        "Reason over this new record and create the v1 caregiving graph updates."
    )
    previous_response_id: str | None = None
    conclusion = ""
    for _ in range(8):
        request: dict[str, Any] = {
            "model": settings.openai_model,
            "instructions": SYSTEM_PROMPT,
            "input": next_input,
            "tools": toolbox.tool_specs(),
            "max_output_tokens": 1600,
        }
        if previous_response_id:
            request["previous_response_id"] = previous_response_id
        response = await client.responses.create(**request)
        previous_response_id = response.id
        tool_results: list[dict[str, str]] = []
        tool_used = False
        response_text = getattr(response, "output_text", "") or ""

        for item in response.output:
            item_type = getattr(item, "type", None)
            if item_type == "message":
                text = _extract_response_text(item)
                if text:
                    conclusion = text
                    await store.append_reasoning_step(log.id, {"kind": "thought", "text": text})
            if item_type == "function_call":
                tool_used = True
                args = json.loads(item.arguments or "{}")
                await store.append_reasoning_step(log.id, {"kind": "tool_call", "tool": item.name, "input": pii_redactor.redact(args)})
                result = await toolbox.call(item.name, args)
                tool_results.append(
                    {
                        "type": "function_call_output",
                        "call_id": item.call_id,
                        "output": json.dumps(result, default=str),
                    }
                )
        if tool_results:
            next_input = tool_results
        if not tool_used:
            if not conclusion and response_text:
                conclusion = response_text
                await store.append_reasoning_step(log.id, {"kind": "thought", "text": response_text})
            break
    rejections = await toolbox.finalize()
    if rejections:
        conclusion = "Some scheduled actions were rejected because they lacked required provenance. The remaining graph updates are grounded."
    await store.finish_reasoning_log(log.id, conclusion)
    return {"reasoning_log_id": str(log.id), "conclusion": conclusion, "mode": "openai"}


def _extract_response_text(message: Any) -> str:
    chunks: list[str] = []
    for content in getattr(message, "content", []) or []:
        text = getattr(content, "text", None)
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip()


async def run_scripted_demo_reasoner(store: GraphStore, toolbox: AgentToolbox, patient_id: str, trigger_node_id: UUID, memory_notes: list[str] | None = None) -> str:
    graph = await store.graph_subset(patient_id)
    diagnosis = next((node for node in graph.nodes if node.id == trigger_node_id), None)
    if not diagnosis:
        raise ValueError("Trigger node not found")
    related_records = [
        node for node in graph.nodes if node.type == "nehr_record" and node.payload.get("recorded_at") == diagnosis.payload.get("recorded_at")
    ]
    prescription = next((node for node in related_records if node.payload.get("record_type") == "prescription"), diagnosis)
    appointment = next((node for node in related_records if node.payload.get("record_type") == "appointment"), diagnosis)
    therapy_downranked = any("low-risk therapy" in note or "therapy suggestions" in note for note in (memory_notes or []))

    await store.append_reasoning_step(
        toolbox.reasoning_log_id,
        {
            "kind": "thought",
            "text": "The new diagnosis identifies early-stage Parkinson's disease, so I will use the curated Parkinson's trajectory rather than inventing a progression.",
        },
    )
    if memory_notes:
        await store.append_reasoning_step(
            toolbox.reasoning_log_id,
            {
                "kind": "memory",
                "text": "I checked caregiver feedback memory before creating actions. " + " ".join(memory_notes),
            },
        )
    trajectory = await toolbox.get_condition_trajectory("parkinsons_early_stage")
    await store.append_reasoning_step(toolbox.reasoning_log_id, {"kind": "tool_call", "tool": "get_condition_trajectory", "input": {"condition_key": "parkinsons_early_stage"}})
    await store.append_reasoning_step(toolbox.reasoning_log_id, {"kind": "tool_result", "tool": "get_condition_trajectory", "result": trajectory})

    condition = await store.create_node(
        "inferred_condition",
        {
            "patient_id": patient_id,
            "condition_key": "parkinsons_early_stage",
            "display_name": trajectory["display_name"],
            "confidence": "high",
            "basis": "Neurology diagnosis record explicitly states early-stage Parkinson's disease.",
        },
        "agent",
        toolbox.reasoning_log_id,
    )
    await store.create_edge(condition.id, diagnosis.id, "derived_from")

    start = datetime.now(ZoneInfo("Asia/Singapore")).replace(hour=0, minute=0, second=0, microsecond=0)
    medication = await _grounded_action(
        store,
        toolbox,
        prescription.id,
        {
            "patient_id": patient_id,
            "title": "Levodopa after meals",
            "description": "Give Levodopa/Carbidopa 100/25 mg three times daily after meals and watch timing consistency.",
            "action_type": "medication",
            "start_at": (start + timedelta(hours=8)).isoformat(),
            "end_at": (start + timedelta(hours=8, minutes=20)).isoformat(),
            "recurrence": "Daily after breakfast, lunch, and dinner",
        },
    )
    await store.create_edge(condition.id, medication.id, "triggers")

    resource = next(item for item in educational_resources() if item["id"] == "parkinsons_physio_seated_exercises")
    resource_node = await store.create_node("recommended_resource", {"patient_id": patient_id, **resource}, "agent", toolbox.reasoning_log_id)
    physio = await _grounded_action(
        store,
        toolbox,
        diagnosis.id,
        {
            "patient_id": patient_id,
            "title": "Optional seated Parkinson's exercise" if therapy_downranked else "Daily seated Parkinson's exercise",
            "description": (
                "Optional low-risk movement prompt: keep this concise because the caregiver previously dismissed similar therapy suggestions."
                if therapy_downranked
                else "Start a short seated exercise routine to maintain mobility and confidence while symptoms are mild."
            ),
            "action_type": "therapy",
            "start_at": (start + timedelta(hours=10)).isoformat(),
            "end_at": (start + timedelta(hours=10, minutes=20)).isoformat(),
            "recurrence": "Daily",
        },
    )
    await store.create_edge(condition.id, physio.id, "triggers")
    await store.create_edge(physio.id, resource_node.id, "recommends")

    follow_up_at = appointment.payload["content"]["appointment_at"]
    follow_up = await _grounded_action(
        store,
        toolbox,
        appointment.id,
        {
            "patient_id": patient_id,
            "title": "Neurologist follow-up",
            "description": "Review symptoms, medication response, gait changes, and falls risk with the neurology team.",
            "action_type": "appointment",
            "start_at": follow_up_at,
            "end_at": (datetime.fromisoformat(follow_up_at) + timedelta(hours=1)).isoformat(),
            "location": "Tan Tock Seng Hospital Neurology",
            "scheduling_url": "https://www.ttsh.com.sg/Patients-and-Visitors/Your-Clinic-Visit/Pages/Appointments.aspx",
        },
    )
    await store.create_edge(condition.id, follow_up.id, "triggers")

    grant = next(item for item in grants_database() if item["id"] == "aic_seniors_mobility_enabling_fund")
    grant_node = await store.create_node("grant_opportunity", {"patient_id": patient_id, **grant}, "agent", toolbox.reasoning_log_id)
    await store.create_edge(grant_node.id, condition.id, "applies_to")
    grant_task = await _grounded_action(
        store,
        toolbox,
        condition.id,
        {
            "patient_id": patient_id,
            "title": "Apply for Seniors' Mobility and Enabling Fund",
            "description": "At the 6-month mobility checkpoint, check whether Mdm Tan needs mobility aids and prepare an AIC SMF application if eligible.",
            "action_type": "grant",
            "start_at": (start + timedelta(days=182, hours=9)).isoformat(),
            "end_at": (start + timedelta(days=182, hours=10)).isoformat(),
            "agency": "Agency for Integrated Care",
        },
    )
    await store.create_edge(condition.id, grant_task.id, "triggers")
    await store.create_edge(grant_task.id, grant_node.id, "applies_to")

    await store.append_reasoning_step(
        toolbox.reasoning_log_id,
        {
            "kind": "thought",
            "text": "I created immediate medication, exercise, and follow-up actions, then added a 6-month SMF grant checkpoint because the curated Parkinson's trajectory flags mobility assessment at that point.",
        },
    )
    return (
        "I matched the new neurology record to the curated early-stage Parkinson's trajectory and created grounded care actions for medication, daily exercise, and follow-up. "
        "I also added a 6-month AIC Seniors' Mobility and Enabling Fund checkpoint because the trajectory predicts mobility assessment needs at that milestone."
        + (" I adjusted the low-risk therapy suggestion based on caregiver feedback memory." if therapy_downranked else "")
    )


async def _grounded_action(store: GraphStore, toolbox: AgentToolbox, source_id: UUID, payload: dict[str, Any]):
    node_id = UUID((await toolbox.create_node("scheduled_action", payload))["node_id"])
    await toolbox.create_edge(str(node_id), str(source_id), "derived_from")
    node = await store.get_node(node_id)
    if not node:
        raise RuntimeError("Grounded scheduled action was not persisted")
    return node
