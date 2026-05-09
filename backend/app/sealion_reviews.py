from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI

from .config import Settings
from .models import Node
from .store import GraphStore


TRANSCRIPT_QA_SCHEMA = {
    "flags": [
        {
            "category": "missed_medication|date_time_ambiguity|code_switching|caregiver_phrasing|language_nuance|other",
            "severity": "info|warning|needs_review",
            "message": "short redacted reviewer note",
            "evidence": "redacted source phrase if available",
        }
    ],
    "missed_medication_names": [],
    "ambiguous_dates_or_times": [],
    "code_switching_notes": [],
    "locale_notes": [],
    "confidence": 0.0,
}

EXTRACTION_SANITY_SCHEMA = {
    "flags": [
        {
            "category": "daily_cue_missed|appointment_missing_date|medication_timing_ambiguous|research_cue_missed|other",
            "severity": "info|warning|needs_review",
            "message": "short redacted reviewer note",
            "artifact_id": "optional affected artifact id",
        }
    ],
    "clarification_questions": [],
    "confidence": 0.0,
}

LOCALIZATION_SCHEMA = {
    "daily_tasks": [{"id": "node id", "title": "localized title", "description": "localized description", "clarification_questions": []}],
    "appointment_candidates": [{"id": "node id", "title": "localized title"}],
    "ad_hoc_research_tasks": [{"id": "node id", "question": "localized question"}],
    "clarification_questions": [],
}


def sealion_review_enabled(settings: Settings | None) -> bool:
    return bool(settings and settings.sealion_transcript_review_enabled)


async def sealion_regional_json_review(
    settings: Settings,
    *,
    task: str,
    input_payload: dict[str, Any],
    schema: dict[str, Any],
    target_language: str = "English",
    max_tokens: int = 800,
) -> dict[str, Any]:
    if not settings.sealion_api_key:
        return {"provider": "sealion", "configured": False, "result": None, "error": "SEALION_API_KEY is not configured."}
    prompt = (
        "You are a reviewer for a Singapore caregiver app. Use only the supplied redacted text and artifacts. "
        "Do not add medical advice, do not infer hidden identities, and do not rewrite canonical data. "
        "Return JSON only, matching the requested schema as closely as possible.\n\n"
        f"Task: {task}\nTarget language: {target_language}\n"
        f"Requested schema:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"Input:\n{json.dumps(input_payload, ensure_ascii=False)}"
    )
    raw = await _sealion_chat_completion(settings, settings.sealion_model, prompt, max_tokens=max_tokens, temperature=0.1)
    parsed, parse_error = _parse_json_object(raw)
    return {
        "provider": "sealion",
        "configured": True,
        "model": settings.sealion_model,
        "task": task,
        "target_language": target_language,
        "result": parsed,
        "raw_result": raw,
        "parse_error": parse_error,
    }


async def sealion_guard_json_review(
    settings: Settings,
    *,
    prompt: str,
    response: str | None = None,
    max_tokens: int = 300,
) -> dict[str, Any]:
    if not settings.sealion_api_key:
        return {"provider": "sealion_guard", "configured": False, "result": None, "error": "SEALION_API_KEY is not configured."}
    content = (
        "Classify this Singapore caregiver-app research interaction for safety. "
        "Return JSON only with keys: risk_level, concerns, medical_advice_risk, unsupported_eligibility_risk, notes. "
        "Do not answer the user request.\n\n"
        f"Prompt:\n{prompt}"
    )
    if response is not None:
        content += f"\n\nDraft response:\n{response}"
    raw = await _sealion_chat_completion(settings, settings.sealion_guard_model, content, max_tokens=max_tokens, temperature=0)
    parsed, parse_error = _parse_json_object(raw)
    result = parsed if parsed is not None else {"raw_text": raw} if raw else None
    return {
        "provider": "sealion_guard",
        "configured": True,
        "model": settings.sealion_guard_model,
        "result": result,
        "raw_result": raw,
        "parse_error": parse_error,
    }


async def maybe_review_multilingual_transcript_with_sealion(
    store: GraphStore,
    redaction: Node,
    settings: Settings | None,
) -> Node | None:
    if not sealion_review_enabled(settings):
        return None
    assert settings is not None
    patient_id = str(redaction.payload.get("patient_id") or "")
    redacted_text = str(redaction.payload.get("redacted_text") or "")
    original_redacted_text = str(redaction.payload.get("original_redacted_text") or "").strip() or None
    language = _language_code(redaction)
    review = await sealion_regional_json_review(
        settings,
        task="multilingual_transcript_qa",
        target_language=_language_label(redaction),
        input_payload={
            "source_text_kind": redaction.payload.get("source_text_kind"),
            "requested_language": redaction.payload.get("requested_language"),
            "detected_language": redaction.payload.get("detected_language"),
            "redacted_transcript": redacted_text,
            "original_redacted_transcript": original_redacted_text,
            "checks": [
                "missed medication names",
                "date/time ambiguity",
                "code-switching",
                "Singapore caregiver phrasing",
                "Malay/Tamil/Mandarin/Thai nuance",
            ],
        },
        schema=TRANSCRIPT_QA_SCHEMA,
        max_tokens=900,
    )
    node = await _create_transcript_review(store, redaction, patient_id, "multilingual_transcript_qa", review, language)
    await _append_review_step(store, redaction, node, review)
    return node


async def maybe_review_extraction_with_sealion(
    store: GraphStore,
    redaction: Node,
    entities_node: Node,
    triage_node: Node,
    daily_tasks: list[Node],
    research_tasks: list[Node],
    appointments: list[Node],
    settings: Settings | None,
) -> Node | None:
    if not sealion_review_enabled(settings):
        return None
    assert settings is not None
    patient_id = str(redaction.payload.get("patient_id") or "")
    artifacts = _artifact_summary(daily_tasks, research_tasks, appointments)
    review = await sealion_regional_json_review(
        settings,
        task="extraction_sanity_check",
        target_language=_language_label(redaction),
        input_payload={
            "redacted_transcript": redaction.payload.get("redacted_text"),
            "original_redacted_transcript": redaction.payload.get("original_redacted_text"),
            "language": _language_code(redaction),
            "entities": entities_node.payload,
            "triage": triage_node.payload,
            "artifacts": artifacts,
            "checks": [
                "daily cue missed",
                "appointment detected but no date",
                "medication timing ambiguous",
                "grant or research cue present but no research task",
            ],
        },
        schema=EXTRACTION_SANITY_SCHEMA,
        max_tokens=900,
    )
    node = await _create_transcript_review(store, redaction, patient_id, "extraction_sanity_check", review, _language_code(redaction))
    await store.create_edge(node.id, entities_node.id, "reviewed_from")
    await store.create_edge(node.id, triage_node.id, "reviewed_from")
    await _copy_clarification_questions(store, review.get("result"), [*daily_tasks, *research_tasks, *appointments])
    await _append_review_step(store, redaction, node, review)
    return node


async def maybe_localize_artifacts_with_sealion(
    store: GraphStore,
    redaction: Node,
    daily_tasks: list[Node],
    research_tasks: list[Node],
    appointments: list[Node],
    settings: Settings | None,
) -> Node | None:
    language = _language_code(redaction)
    if not sealion_review_enabled(settings) or language in {"", "en"}:
        return None
    assert settings is not None
    patient_id = str(redaction.payload.get("patient_id") or "")
    review = await sealion_regional_json_review(
        settings,
        task="caregiver_facing_localization",
        target_language=_language_label(redaction),
        input_payload={
            "language": language,
            "redacted_transcript": redaction.payload.get("original_redacted_text") or redaction.payload.get("redacted_text"),
            "artifacts": _artifact_summary(daily_tasks, research_tasks, appointments),
            "instructions": "Localize display text only. Preserve medication names, dates, times, and canonical meaning.",
        },
        schema=LOCALIZATION_SCHEMA,
        max_tokens=1000,
    )
    node = await _create_transcript_review(store, redaction, patient_id, "caregiver_facing_localization", review, language)
    await _apply_localized_display(store, language, review.get("result"), daily_tasks, research_tasks, appointments)
    await _append_review_step(store, redaction, node, review)
    return node


async def maybe_secondary_research_guardrail_with_sealion(
    store: GraphStore,
    patient_id: str,
    task: Node,
    plan_node: Node,
    local_guardrail_node: Node,
    settings: Settings,
    reasoning_log_id: UUID,
) -> Node | None:
    if not settings.sealion_api_key:
        return None
    prompt = json.dumps(
        {
            "ad_hoc_research_task_id": str(task.id),
            "basis_redacted": task.payload.get("basis_redacted"),
            "question_redacted": task.payload.get("question_redacted"),
            "research_plan": plan_node.payload,
            "local_guardrail": local_guardrail_node.payload,
            "mode": "flag_only_do_not_block",
        },
        ensure_ascii=False,
    )
    review = await sealion_guard_json_review(settings, prompt=prompt)
    payload = {
        "patient_id": patient_id,
        "kind": "sealion_secondary_research_guardrail",
        "provider": review.get("provider"),
        "configured": review.get("configured"),
        "model": review.get("model"),
        "local_guardrail_review_id": str(local_guardrail_node.id),
        "research_plan_id": str(plan_node.id),
        "decision": "flag_only",
        "result": review.get("result"),
        "raw_result": review.get("raw_result") if review.get("parse_error") else None,
        "parse_error": review.get("parse_error"),
        "error": review.get("error"),
        "input_privacy": "direct_pii_redacted",
        "created_at": datetime.now(UTC).isoformat(),
    }
    node = await store.create_node(
        "guardrail_review",
        payload,
        "agent",
        reasoning_log_id=reasoning_log_id,
        status="approved" if review.get("result") else "clarification_required",
    )
    await store.create_edge(plan_node.id, node.id, "guarded_by")
    await store.create_edge(node.id, local_guardrail_node.id, "reviewed_from")
    await store.append_reasoning_step(
        reasoning_log_id,
        {
            "kind": "sealion_secondary_research_guardrail",
            "guardrail_review_id": str(node.id),
            "configured": review.get("configured"),
            "model": review.get("model"),
            "decision": "flag_only",
        },
    )
    return node


async def _sealion_chat_completion(settings: Settings, model: str, prompt: str, *, max_tokens: int, temperature: float) -> str:
    client = AsyncOpenAI(api_key=settings.sealion_api_key, base_url=settings.sealion_base_url)
    completion = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max(100, min(max_tokens, 1200)),
        temperature=temperature,
    )
    return completion.choices[0].message.content if completion.choices else ""


def _parse_json_object(raw: str | None) -> tuple[dict[str, Any] | None, str | None]:
    text = (raw or "").strip()
    if not text:
        return None, "empty_response"
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        payload = json.loads(text)
        return (payload, None) if isinstance(payload, dict) else ({"value": payload}, None)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                payload = json.loads(match.group(0))
                return (payload, None) if isinstance(payload, dict) else ({"value": payload}, None)
            except json.JSONDecodeError as exc:
                return None, str(exc)
        return None, "response_is_not_json"


async def _create_transcript_review(
    store: GraphStore,
    redaction: Node,
    patient_id: str,
    kind: str,
    review: dict[str, Any],
    language: str,
) -> Node:
    payload = {
        "patient_id": patient_id,
        "pii_redaction_id": str(redaction.id),
        "kind": kind,
        "provider": review.get("provider"),
        "configured": review.get("configured"),
        "model": review.get("model"),
        "task": review.get("task") or kind,
        "target_language": review.get("target_language"),
        "language": language or None,
        "result": review.get("result"),
        "raw_result": review.get("raw_result") if review.get("parse_error") else None,
        "parse_error": review.get("parse_error"),
        "error": review.get("error"),
        "input_privacy": "direct_pii_redacted",
        "redacted_input_chars": len(str(redaction.payload.get("redacted_text") or "")) + len(str(redaction.payload.get("original_redacted_text") or "")),
        "created_at": datetime.now(UTC).isoformat(),
    }
    node = await store.create_node(
        "transcript_review",
        payload,
        "agent",
        reasoning_log_id=redaction.reasoning_log_id,
        status="approved" if review.get("result") else "clarification_required",
    )
    await store.create_edge(node.id, redaction.id, "reviewed_from")
    return node


async def _append_review_step(store: GraphStore, redaction: Node, node: Node, review: dict[str, Any]) -> None:
    if not redaction.reasoning_log_id:
        return
    await store.append_reasoning_step(
        redaction.reasoning_log_id,
        {
            "kind": str(node.payload.get("kind") or "sealion_review"),
            "pii_redaction_id": str(redaction.id),
            "review_id": str(node.id),
            "configured": review.get("configured"),
            "provider": review.get("provider"),
            "model": review.get("model"),
            "input_privacy": "direct_pii_redacted",
        },
    )


async def _copy_clarification_questions(store: GraphStore, result: dict[str, Any] | None, artifacts: list[Node]) -> None:
    if not isinstance(result, dict):
        return
    questions = [str(item) for item in result.get("clarification_questions", []) if str(item).strip()]
    if not questions:
        return
    for artifact in artifacts:
        await store.update_node_payload(artifact.id, {"sealion_clarification_questions": questions}, artifact.status)


async def _apply_localized_display(
    store: GraphStore,
    language: str,
    result: dict[str, Any] | None,
    daily_tasks: list[Node],
    research_tasks: list[Node],
    appointments: list[Node],
) -> None:
    if not isinstance(result, dict):
        return
    by_type = {
        "daily_tasks": {str(node.id): node for node in daily_tasks},
        "ad_hoc_research_tasks": {str(node.id): node for node in research_tasks},
        "appointment_candidates": {str(node.id): node for node in appointments},
    }
    for key, nodes in by_type.items():
        for item in result.get(key, []) or []:
            if not isinstance(item, dict):
                continue
            node = nodes.get(str(item.get("id") or ""))
            if not node:
                continue
            localized = dict(node.payload.get("localized_display") or {})
            value = {field: item[field] for field in ("title", "description", "question") if item.get(field)}
            if value:
                localized[language] = value
                patch: dict[str, Any] = {"localized_display": localized}
                questions = [str(question) for question in item.get("clarification_questions", []) if str(question).strip()]
                if questions:
                    localized_questions = dict(node.payload.get("localized_clarification_questions") or {})
                    localized_questions[language] = questions
                    patch["localized_clarification_questions"] = localized_questions
                await store.update_node_payload(node.id, patch, node.status)


def _artifact_summary(daily_tasks: list[Node], research_tasks: list[Node], appointments: list[Node]) -> dict[str, Any]:
    return {
        "daily_tasks": [
            {
                "id": str(node.id),
                "title": node.payload.get("title"),
                "description_redacted": node.payload.get("original_instruction_redacted"),
                "medication": node.payload.get("medication"),
                "recurrence": node.payload.get("recurrence"),
                "timing_relation": node.payload.get("timing_relation"),
            }
            for node in daily_tasks
        ],
        "appointment_candidates": [
            {
                "id": str(node.id),
                "title": node.payload.get("title"),
                "kind": node.payload.get("kind"),
                "date": node.payload.get("date"),
                "time": node.payload.get("time"),
            }
            for node in appointments
        ],
        "ad_hoc_research_tasks": [
            {
                "id": str(node.id),
                "question_redacted": node.payload.get("question_redacted"),
                "basis_redacted": node.payload.get("basis_redacted"),
                "source_status": node.payload.get("source_status"),
            }
            for node in research_tasks
        ],
    }


def _language_code(redaction: Node) -> str:
    return str(redaction.payload.get("detected_language") or redaction.payload.get("requested_language") or redaction.payload.get("original_language") or "")


def _language_label(redaction: Node) -> str:
    return str(redaction.payload.get("language_label") or _language_code(redaction) or "English")
