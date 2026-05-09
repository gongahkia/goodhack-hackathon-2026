from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from openai import AsyncOpenAI

from .config import Settings
from .data import educational_resources, grants_database
from .graph_queries import backtrace_sources
from .models import GraphSubset, Node, ReasoningLog

DEFAULT_ALLOWED_DOMAINS = ["gov.sg", "healthhub.sg", "aic.sg", "sgenable.sg", "moh.gov.sg", "parkinson.org"]


def build_memory_profile(graph: GraphSubset) -> dict[str, Any]:
    by_id = {node.id: node for node in graph.nodes}
    feedback_nodes = [node for node in graph.nodes if node.type == "caregiver_feedback"]
    by_status: Counter[str] = Counter()
    by_action_type: dict[str, Counter[str]] = defaultdict(Counter)
    scores_by_action_type: dict[str, list[int]] = defaultdict(list)
    steer_by_action_type: dict[str, Counter[str]] = defaultdict(Counter)
    edits: list[dict[str, Any]] = []

    for feedback in feedback_nodes:
        status = str(feedback.payload.get("status") or "edited")
        target_id = _uuid(feedback.payload.get("target_node_id"))
        target = by_id.get(target_id) if target_id else None
        action_type = str(target.payload.get("action_type") or target.type if target else "unknown")
        by_status[status] += 1
        by_action_type[action_type][status] += 1
        if isinstance(feedback.payload.get("usefulness_score"), int):
            scores_by_action_type[action_type].append(feedback.payload["usefulness_score"])
        if feedback.payload.get("steer"):
            steer_by_action_type[action_type][str(feedback.payload["steer"])] += 1
        if feedback.payload.get("payload_patch"):
            edits.append(
                {
                    "target_node_id": str(target.id) if target else str(target_id),
                    "title": target.payload.get("title") if target else None,
                    "fields": sorted(feedback.payload["payload_patch"].keys()),
                    "created_at": feedback.created_at.isoformat(),
                }
            )

    learned_preferences = []
    for action_type, counts in sorted(by_action_type.items()):
        approvals = counts.get("approved", 0)
        dismissals = counts.get("dismissed", 0)
        edits_count = counts.get("edited", 0)
        scores = scores_by_action_type.get(action_type, [])
        average_score = sum(scores) / len(scores) if scores else None
        if dismissals > approvals:
            learned_preferences.append(
                {
                    "kind": "downrank",
                    "action_type": action_type,
                    "reason": f"{dismissals} dismissed vs {approvals} approved",
                }
            )
        elif approvals > 0:
            learned_preferences.append(
                {
                    "kind": "reinforce",
                    "action_type": action_type,
                    "reason": f"{approvals} approved action{'s' if approvals != 1 else ''}",
                }
            )
        if average_score is not None and average_score <= 2.5:
            learned_preferences.append(
                {
                    "kind": "lower_confidence",
                    "action_type": action_type,
                    "reason": f"average usefulness score {average_score:.1f}/5",
                }
            )
        elif average_score is not None and average_score >= 4:
            learned_preferences.append(
                {
                    "kind": "high_value",
                    "action_type": action_type,
                    "reason": f"average usefulness score {average_score:.1f}/5",
                }
            )
        for steer, steer_count in Counter(steer_by_action_type.get(action_type, {})).most_common():
            learned_preferences.append(
                {
                    "kind": f"steer_{steer}",
                    "action_type": action_type,
                    "reason": f"{steer_count} caregiver steering signal{'s' if steer_count != 1 else ''}",
                }
            )
        if edits_count:
            learned_preferences.append(
                {
                    "kind": "adapt_format",
                    "action_type": action_type,
                    "reason": f"{edits_count} caregiver edit{'s' if edits_count != 1 else ''}",
                }
            )

    return {
        "feedback_count": len(feedback_nodes),
        "by_status": dict(by_status),
        "by_action_type": {key: dict(value) for key, value in by_action_type.items()},
        "average_scores": {key: round(sum(value) / len(value), 2) for key, value in scores_by_action_type.items() if value},
        "steering": {key: dict(value) for key, value in steer_by_action_type.items()},
        "learned_preferences": learned_preferences,
        "recent_edits": sorted(edits, key=lambda item: item["created_at"], reverse=True)[:5],
    }


def memory_instructions(memory: dict[str, Any]) -> list[str]:
    instructions = []
    for preference in memory.get("learned_preferences", []):
        kind = preference.get("kind")
        action_type = preference.get("action_type", "care action")
        reason = preference.get("reason", "caregiver feedback")
        if kind == "downrank":
            instructions.append(
                f"Down-rank low-risk {action_type} suggestions because {reason}. Do not suppress medication, falls-risk, appointment, or grant-deadline actions solely because of dismissals."
            )
        elif kind == "reinforce":
            instructions.append(f"Caregiver tends to accept {action_type} actions because {reason}; keep similar grounded suggestions concise and actionable.")
        elif kind == "adapt_format":
            instructions.append(f"Caregiver edited {action_type} actions because {reason}; prefer clearer wording and editable scheduling details.")
        elif kind == "lower_confidence":
            instructions.append(f"Treat future low-risk {action_type} suggestions as lower confidence because {reason}; ask for confirmation and keep wording modest.")
        elif kind == "high_value":
            instructions.append(f"Caregiver rated {action_type} suggestions highly because {reason}; continue surfacing similar grounded actions.")
        elif kind == "steer_more":
            instructions.append(f"Caregiver asked for more {action_type} suggestions; include similar grounded actions when evidence supports them.")
        elif kind == "steer_less":
            instructions.append(f"Caregiver asked for fewer {action_type} suggestions; reduce low-risk reminders unless they are clinically or financially important.")
        elif kind == "steer_simpler":
            instructions.append(f"Caregiver asked for simpler {action_type} suggestions; use shorter descriptions and clearer next steps.")
    return instructions


def build_care_plan_review(graph: GraphSubset, logs: list[ReasoningLog]) -> dict[str, Any]:
    now = datetime.now(UTC)
    actions = [node for node in graph.nodes if node.type == "scheduled_action" and node.status != "dismissed"]
    records = [node for node in graph.nodes if node.type == "nehr_record"]
    conditions = [node for node in graph.nodes if node.type == "inferred_condition"]
    pending = [node for node in actions if node.status == "pending_review"]
    upcoming = sorted(
        [node for node in actions if _parse_datetime(node.payload.get("start_at")) and _parse_datetime(node.payload.get("start_at")) >= now],
        key=lambda node: _parse_datetime(node.payload.get("start_at")) or now,
    )
    next_30 = [
        node
        for node in upcoming
        if (_parse_datetime(node.payload.get("start_at")) or now) <= now + timedelta(days=30)
    ]
    memory = build_memory_profile(graph)
    latest_log = logs[0] if logs else None

    narrative = [
        f"I rechecked {len(records)} source records and {len(conditions)} inferred condition{'s' if len(conditions) != 1 else ''}.",
        f"There are {len(pending)} care action{'s' if len(pending) != 1 else ''} still waiting for review.",
        f"{len(next_30)} active action{'s' if len(next_30) != 1 else ''} fall within the next 30 days.",
    ]
    if memory["learned_preferences"]:
        first = memory["learned_preferences"][0]
        narrative.append(f"Memory signal: {first['kind']} {first['action_type']} because {first['reason']}.")
    if latest_log and latest_log.conclusion:
        narrative.append(f"Latest reasoning conclusion: {latest_log.conclusion}")

    return {
        "generated_at": now.isoformat(),
        "record_count": len(records),
        "condition_count": len(conditions),
        "pending_review_count": len(pending),
        "upcoming_30_day_count": len(next_30),
        "next_actions": [_action_summary(node) for node in upcoming[:5]],
        "memory": memory,
        "memory_instructions": memory_instructions(memory),
        "narrative": narrative,
    }


async def search_verified_resources(query: str, settings: Settings, allowlist: list[str] | None = None) -> list[dict[str, Any]]:
    curated = _curated_resource_matches(query)
    domains = allowlist or DEFAULT_ALLOWED_DOMAINS
    live = await _live_search(query, settings, domains)
    return _dedupe_verified_results([*curated, *live])[:5]


async def search_verified_grants(query: str, settings: Settings, allowlist: list[str] | None = None) -> list[dict[str, Any]]:
    curated = _curated_grant_matches(query)
    domains = allowlist or DEFAULT_ALLOWED_DOMAINS
    live = await _live_search(f"{query} Singapore caregiver senior grant", settings, domains)
    return _dedupe_verified_results([*curated, *live])[:5]


def event_reasoning_narrative(event: Node, graph: GraphSubset, log: ReasoningLog | None) -> list[str]:
    sources = backtrace_sources(event, graph.nodes, graph.edges)
    source_titles = [source.payload.get("title") or source.payload.get("content", {}).get("title") for source in sources]
    action_type = event.payload.get("action_type") or "care action"
    narrative = [
        f"I am showing this {action_type} because it is linked back to {len(sources)} source record{'s' if len(sources) != 1 else ''}.",
    ]
    if source_titles:
        narrative.append(f"Evidence used: {', '.join(str(title) for title in source_titles if title)}.")
    if event.payload.get("start_at"):
        narrative.append(f"It is scheduled for {_human_datetime(event.payload['start_at'])}.")
    if event.payload.get("description"):
        narrative.append(str(event.payload["description"]))
    if log and log.conclusion:
        narrative.append(log.conclusion)
    return narrative


def normalize_scheduling_payload(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = dict(payload)
    action_type = str(next_payload.get("action_type") or "task")
    title = str(next_payload.get("title") or "")
    description = str(next_payload.get("description") or "")
    text = f"{title} {description}".lower()

    if not next_payload.get("timing_type"):
        if action_type in {"medication", "appointment"}:
            next_payload["timing_type"] = "fixed_time"
        elif action_type == "grant" or "deadline" in text or "apply" in text:
            next_payload["timing_type"] = "deadline"
        elif action_type in {"therapy", "task"}:
            next_payload["timing_type"] = "flexible_window"
        else:
            next_payload["timing_type"] = "movable"

    if not next_payload.get("urgency"):
        if action_type == "medication":
            next_payload["urgency"] = "clinical"
        elif action_type == "appointment":
            next_payload["urgency"] = "clinical"
        elif action_type == "grant":
            next_payload["urgency"] = "financial"
        else:
            next_payload["urgency"] = "routine"

    if not next_payload.get("estimated_effort_minutes"):
        next_payload["estimated_effort_minutes"] = _default_effort_minutes(action_type, text)

    if not next_payload.get("movable_window"):
        next_payload["movable_window"] = _default_movable_window(next_payload["timing_type"], action_type, next_payload.get("start_at"))

    if "rest_interrupt_allowed" not in next_payload:
        next_payload["rest_interrupt_allowed"] = next_payload["urgency"] in {"clinical", "financial"} and next_payload["timing_type"] in {"fixed_time", "deadline"}

    if not next_payload.get("scheduling_reason"):
        next_payload["scheduling_reason"] = _scheduling_reason(next_payload["timing_type"], action_type)

    return next_payload


def with_scheduling_metadata(node: Node) -> Node:
    if node.type != "scheduled_action":
        return node
    return node.model_copy(update={"payload": normalize_scheduling_payload(node.payload)})


def build_appointment_prep(event: Node, graph: GraphSubset) -> dict[str, Any] | None:
    if event.payload.get("action_type") != "appointment":
        return None
    sources = backtrace_sources(event, graph.nodes, graph.edges)
    source_text = " ".join(
        " ".join(
            [
                str(source.payload.get("title") or ""),
                str(source.payload.get("content", {}).get("notes") or ""),
                str(source.payload.get("content", {}).get("dose") or ""),
                str(source.payload.get("content", {}).get("medication") or ""),
            ]
        )
        for source in sources
    ).lower()
    condition_text = " ".join(str(node.payload.get("display_name") or node.payload.get("condition_key") or "") for node in graph.nodes if node.type == "inferred_condition").lower()
    has_parkinsons = "parkinson" in source_text or "parkinson" in condition_text or "parkinson" in str(event.payload.get("title", "")).lower()

    symptoms = ["Any new symptoms since the last visit", "Side effects, missed doses, or changes in daily routine"]
    medication_notes = ["Bring current medication list and timing pattern"]
    mobility_notes = ["Mention any near-falls, slower walking, tremor changes, or confidence changes"]
    questions = ["Ask what changes should trigger an earlier appointment", "Confirm next follow-up timing and who to contact if symptoms worsen"]
    long_term = ["Check whether any future equipment, therapy, or caregiver support planning should begin now"]
    recurring_concerns = _recurring_care_concerns(graph, event)
    previous_questions = _previous_clinician_questions(graph, event)
    unresolved_advice = _unresolved_advice(graph, event)
    revisit_next_time = ["Revisit any prior advice that has not turned into a scheduled care action yet"]

    if has_parkinsons:
        symptoms = ["Resting tremor changes", "Slowness or stiffness during daily activities", "Any freezing, shuffling, near-falls, or balance concerns"]
        medication_notes = ["Track Levodopa/Carbidopa timing after meals", "Note any nausea, dizziness, wearing-off, or missed doses"]
        mobility_notes = ["Share whether seated exercises are being completed", "Ask whether gait or falls assessment is needed before the next review"]
        questions = [
            "Should medication timing change if symptoms fluctuate?",
            "What falls-risk signs should the family watch for?",
            "Should physiotherapy continue at home or be escalated?",
        ]
        long_term = [
            "Discuss mobility aid readiness and whether an AIC SMF application may be needed later",
            "Ask when to reassess home safety, caregiver burden, and transport needs",
        ]
        recurring_concerns = list(dict.fromkeys([*recurring_concerns, "Medication timing after meals", "Falls and gait confidence", "Home exercise adherence"]))
        revisit_next_time = [
            "Confirm whether medication timing is still appropriate after meals",
            "Review whether mobility aid or home safety planning should move from forecast to action",
        ]

    return {
        "appointment_id": str(event.id),
        "generated_at": datetime.now(UTC).isoformat(),
        "title": event.payload.get("title"),
        "symptoms_to_mention": symptoms,
        "medication_notes": medication_notes,
        "therapy_mobility_notes": mobility_notes,
        "questions_for_clinician": questions,
        "long_term_concerns": long_term,
        "recurring_concerns": recurring_concerns[:5],
        "previous_questions": previous_questions[:5],
        "unresolved_advice": unresolved_advice[:5],
        "revisit_next_time": revisit_next_time[:5],
        "evidence": [_source_summary(source) for source in sources],
    }


def build_forecast(graph: GraphSubset) -> list[dict[str, Any]]:
    actions = [node for node in graph.nodes if node.type == "scheduled_action" and node.status != "dismissed"]
    forecast_actions = [
        action
        for action in actions
        if _is_forecast_action(action)
    ]
    return [_forecast_card(action, graph) for action in sorted(forecast_actions, key=lambda node: str(node.payload.get("start_at") or ""))]


def _is_forecast_action(action: Node) -> bool:
    title = str(action.payload.get("title") or "")
    description = str(action.payload.get("description") or "")
    text = f"{title} {description}".lower()
    future_date = _parse_datetime(action.payload.get("start_at"))
    support_keywords = ["grant", "fund", "subsid", "mobility", "wheelchair", "equipment", "home modification", "respite", "hospice"]
    return bool(
        action.payload.get("action_type") == "grant"
        or "apply" in text
        or future_date
        and future_date > datetime.now(UTC) + timedelta(days=45)
        and any(keyword in text for keyword in support_keywords)
    )


def _forecast_card(action: Node, graph: GraphSubset) -> dict[str, Any]:
    title = str(action.payload.get("title") or "Future care action")
    description = str(action.payload.get("description") or "")
    text = f"{title} {description}".lower()
    category = "care_service"
    if "grant" in text or "fund" in text or "subsid" in text:
        category = "grant"
    elif "mobility" in text or "wheelchair" in text or "aid" in text or "equipment" in text:
        category = "equipment"
    elif "home" in text or "modification" in text:
        category = "home_modification"
    elif "hospice" in text or "respite" in text:
        category = "care_service"

    sources = backtrace_sources(action, graph.nodes, graph.edges)
    grant = _related_grant(action, graph)
    target_date = action.payload.get("start_at")
    missing_documents = _missing_documents(category, action, grant)
    deadline_conflicts = _deadline_conflicts(action, graph)
    capacity = _capacity_signal(action, graph)
    timeline = [
        {"label": "Trigger", "detail": _first_source_title(sources) or "Care-plan trajectory identified a future need."},
        {"label": "Eligibility evidence", "detail": _eligibility_detail(grant, sources)},
        {"label": "Documents needed", "detail": ", ".join(missing_documents[:4]) if missing_documents else "No missing document signals yet."},
        {"label": "Prep steps", "detail": _prep_detail(category)},
        {"label": "Application window", "detail": f"Start by {_human_datetime(target_date)}." if target_date else "Review at the forecast checkpoint."},
        {"label": "Follow-up", "detail": "Recheck status after submission and update the care plan with any approval outcome."},
    ]
    return {
        "id": str(action.id),
        "title": title,
        "category": category,
        "status": action.status,
        "target_date": target_date,
        "summary": description,
        "agency": action.payload.get("agency") or (grant.payload.get("agency") if grant else None),
        "apply_url": action.payload.get("apply_url") or action.payload.get("url") or (grant.payload.get("url") if grant else None),
        "missing_documents": missing_documents,
        "deadline_conflicts": deadline_conflicts,
        "capacity": capacity,
        "timeline": timeline,
        "evidence": [_source_summary(source) for source in sources],
    }


def _recurring_care_concerns(graph: GraphSubset, event: Node) -> list[str]:
    terms = [
        str(node.payload.get("feedback_note") or node.payload.get("title") or node.payload.get("description") or "")
        for node in graph.nodes
        if node.type in {"caregiver_feedback", "scheduled_action", "nehr_record"}
    ]
    text = " ".join(terms).lower()
    concerns = []
    if "fall" in text or "gait" in text:
        concerns.append("Falls or gait changes have appeared in the care history")
    if "medication" in text or "levodopa" in text or "dose" in text:
        concerns.append("Medication timing or side effects should be checked")
    if "mobility" in text or "exercise" in text or "physio" in text:
        concerns.append("Mobility and therapy adherence should be reviewed")
    if event.payload.get("location"):
        concerns.append(f"Confirm logistics for {event.payload['location']}")
    return concerns or ["Check for changes since the previous appointment"]


def _previous_clinician_questions(graph: GraphSubset, event: Node) -> list[str]:
    feedback_questions = [
        str(node.payload.get("feedback_note"))
        for node in graph.nodes
        if node.type == "caregiver_feedback" and node.payload.get("feedback_note") and "?" in str(node.payload.get("feedback_note"))
    ]
    if feedback_questions:
        return feedback_questions
    if event.payload.get("action_type") == "appointment":
        return ["What symptoms or care needs should trigger an earlier review?"]
    return []


def _unresolved_advice(graph: GraphSubset, event: Node) -> list[str]:
    unresolved = []
    active_actions = [node for node in graph.nodes if node.type == "scheduled_action" and node.status != "dismissed"]
    if any(str(node.payload.get("title", "")).lower().find("exercise") >= 0 for node in active_actions):
        unresolved.append("Exercise routine is active; ask whether it should continue, change, or escalate.")
    if any(str(node.payload.get("title", "")).lower().find("mobility") >= 0 for node in active_actions):
        unresolved.append("Mobility support has been forecast; ask what evidence is needed before applying.")
    if event.status == "pending_review":
        unresolved.append("This appointment action is still pending caregiver review.")
    return unresolved


def _missing_documents(category: str, action: Node, grant: Node | None) -> list[str]:
    existing = " ".join(str(attachment.get("name", "")) for attachment in action.payload.get("attachments", []) if isinstance(attachment, dict)).lower()
    required_by_category = {
        "grant": ["NRIC or citizenship proof", "Clinical memo or diagnosis evidence", "Cost estimate or quotation", "Means-test or household income document"],
        "equipment": ["Clinical need note", "Mobility assessment", "Equipment quotation"],
        "home_modification": ["Home safety photos", "Clinical need note", "Contractor estimate"],
        "care_service": ["Referral note", "Care needs summary", "Caregiver contact details"],
    }
    required = required_by_category.get(category, required_by_category["care_service"])
    if grant and grant.payload.get("eligibility_hints"):
        required = [*required, "Eligibility evidence matching grant criteria"]
    return [item for item in required if not any(token in existing for token in item.lower().split()[:2])]


def _deadline_conflicts(action: Node, graph: GraphSubset) -> list[str]:
    start = _parse_datetime(action.payload.get("start_at"))
    if not start:
        return []
    same_week = [
        node
        for node in graph.nodes
        if node.type == "scheduled_action"
        and node.id != action.id
        and node.status != "dismissed"
        and (event_start := _parse_datetime(node.payload.get("start_at")))
        and abs((event_start - start).days) <= 3
    ]
    conflicts = []
    if len(same_week) >= 3:
        conflicts.append(f"{len(same_week)} other care actions fall within three days of this deadline.")
    if any(str(node.payload.get("action_type")) == "appointment" for node in same_week):
        conflicts.append("A clinician appointment is nearby; use it to gather missing evidence before applying.")
    return conflicts


def _capacity_signal(action: Node, graph: GraphSubset) -> dict[str, Any]:
    start = _parse_datetime(action.payload.get("start_at")) or datetime.now(UTC)
    week_start = start - timedelta(days=start.weekday())
    week_end = week_start + timedelta(days=7)
    weekly_actions = [
        node
        for node in graph.nodes
        if node.type == "scheduled_action"
        and node.status != "dismissed"
        and (event_start := _parse_datetime(node.payload.get("start_at")))
        and week_start <= event_start < week_end
    ]
    load = len(weekly_actions)
    risk = "low" if load <= 3 else "medium" if load <= 6 else "high"
    return {
        "weekly_action_count": load,
        "risk": risk,
        "note": "Keep the week manageable before adding applications or equipment visits." if risk != "low" else "Care workload looks manageable for this target week.",
    }


def _related_grant(action: Node, graph: GraphSubset) -> Node | None:
    by_id = {node.id: node for node in graph.nodes}
    for edge in graph.edges:
        if edge.from_node == action.id:
            target = by_id.get(edge.to_node)
            if target and target.type == "grant_opportunity":
                return target
    return next((node for node in graph.nodes if node.type == "grant_opportunity" and str(node.payload.get("name", "")).lower() in str(action.payload.get("title", "")).lower()), None)


def _source_summary(source: Node) -> dict[str, Any]:
    return {
        "id": str(source.id),
        "type": source.type,
        "title": source.payload.get("title") or source.payload.get("content", {}).get("title"),
        "recorded_at": source.payload.get("recorded_at"),
    }


def _first_source_title(sources: list[Node]) -> str | None:
    if not sources:
        return None
    return str(sources[0].payload.get("title") or sources[0].payload.get("content", {}).get("title") or "")


def _eligibility_detail(grant: Node | None, sources: list[Node]) -> str:
    if grant:
        hints = grant.payload.get("eligibility_hints") or []
        if hints:
            return ", ".join(str(hint) for hint in hints[:4])
    if sources:
        return "Evidence is linked to source health records and inferred condition trajectory."
    return "Eligibility evidence should be reviewed before application."


def _prep_detail(category: str) -> str:
    if category == "equipment":
        return "Prepare diagnosis evidence, mobility notes, caregiver observations, and device quotes if needed."
    if category == "grant":
        return "Prepare identity details, citizenship/age evidence, clinical notes, and any supporting cost documents."
    if category == "home_modification":
        return "Prepare home safety notes, photos, clinical need evidence, and contractor or equipment estimates."
    return "Prepare clinical notes, care needs, caregiver capacity, and service-provider requirements."


def _default_effort_minutes(action_type: str, text: str) -> int:
    if action_type == "medication":
        return 5
    if action_type == "therapy":
        return 20
    if action_type == "appointment":
        return 90
    if action_type == "grant":
        return 45
    if "document" in text or "apply" in text:
        return 45
    return 20


def _default_movable_window(timing_type: str, action_type: str, start_at: Any) -> dict[str, str] | None:
    if timing_type == "fixed_time":
        return None
    try:
        start = datetime.fromisoformat(str(start_at).replace("Z", "+00:00")) if start_at else None
    except ValueError:
        start = None
    if start is None:
        return {"start": "09:00", "end": "18:00"}
    local_hour = start.hour
    if action_type == "therapy" or local_hour < 12:
        return {"start": "08:00", "end": "12:00"}
    if local_hour >= 18:
        return {"start": "18:00", "end": "21:00"}
    return {"start": "09:00", "end": "17:00"}


def _scheduling_reason(timing_type: str, action_type: str) -> str:
    if timing_type == "fixed_time":
        if action_type == "medication":
            return "Medication keeps its prescribed timing unless the caregiver edits it."
        if action_type == "appointment":
            return "Appointment time comes from the clinic booking and should only move through rescheduling."
        return "This action has a fixed clinical or logistical time."
    if timing_type == "deadline":
        return "Deadline-based actions can move earlier, but should not move past the target date."
    if timing_type == "flexible_window":
        return "This action can move inside the caregiver-approved care window."
    return "This action is movable unless the caregiver marks it fixed."


async def _verify_live_results_with_openai(results: list[dict[str, Any]], settings: Settings, query: str) -> list[dict[str, Any]]:
    if not results or not settings.live_search_llm_verification or settings.use_scripted_agent:
        return results
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.responses.create(
            model=settings.openai_model,
            instructions=(
                "You verify healthcare support search results for a caregiver app. "
                "Return compact JSON only: {\"decisions\":[{\"url\":\"...\",\"status\":\"safe_to_show|needs_review|reject\",\"reason\":\"...\"}]}. "
                "Prefer official, relevant, current sources. Reject unrelated or unsafe medical claims."
            ),
            input=json.dumps({"query": query, "results": results}, default=str),
            max_output_tokens=500,
        )
        payload = json.loads(getattr(response, "output_text", "") or "{}")
        decisions = {item.get("url"): item for item in payload.get("decisions", []) if isinstance(item, dict)}
    except Exception:
        return [{**result, "secondary_verification": "failed_open"} for result in results]

    verified = []
    for result in results:
        decision = decisions.get(result.get("url"))
        if not decision:
            verified.append({**result, "secondary_verification": "not_returned"})
            continue
        status = decision.get("status")
        if status == "reject":
            continue
        verified.append(
            {
                **result,
                "verification_status": status if status in {"safe_to_show", "needs_review"} else result.get("verification_status", "needs_review"),
                "secondary_verification": "openai",
                "reason": str(decision.get("reason") or result.get("reason") or "Verified by secondary model."),
            }
        )
    return verified


async def _exa_search(query: str, api_key: str, allowlist: list[str]) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": api_key},
            json={"query": query, "includeDomains": allowlist, "numResults": 5},
        )
        response.raise_for_status()
        data = response.json()
    results = []
    for item in data.get("results", []):
        result = verify_live_result(
            {
                "title": item.get("title") or "Untitled source",
                "source": _source_from_url(item.get("url")),
                "url": item.get("url"),
                "snippet": str(item.get("text") or item.get("snippet") or "")[:400],
                "published_at": item.get("publishedDate") or item.get("published_at"),
            },
            allowlist,
        )
        if result["verification_status"] != "reject":
            results.append(result)
    return results


async def _live_search(query: str, settings: Settings, allowlist: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if settings.exa_api_key:
        try:
            results = await _exa_search(query, settings.exa_api_key, allowlist)
            if results:
                return await _verify_live_results_with_openai(results, settings, query)
        except httpx.HTTPError:
            pass
    if settings.tinyfish_api_key:
        try:
            results = await _tinyfish_search(query, settings.tinyfish_api_key, allowlist)
            return await _verify_live_results_with_openai(results, settings, query)
        except httpx.HTTPError:
            return []
    return []


async def _tinyfish_search(query: str, api_key: str, allowlist: list[str]) -> list[dict[str, Any]]:
    scoped_query = f"{query} " + " OR ".join(f"site:{domain}" for domain in allowlist)
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get(
            "https://api.search.tinyfish.ai",
            headers={"X-API-Key": api_key},
            params={"query": scoped_query, "location": "SG", "language": "en"},
        )
        response.raise_for_status()
        data = response.json()
    results = []
    for item in data.get("results", [])[:5]:
        result = verify_live_result(
            {
                "title": item.get("title") or "Untitled source",
                "source": item.get("site_name") or _source_from_url(item.get("url")),
                "url": item.get("url"),
                "snippet": str(item.get("snippet") or "")[:400],
                "published_at": item.get("published_at") or item.get("date"),
            },
            allowlist,
        )
        if result["verification_status"] != "reject":
            results.append(result)
    return results


def verify_live_result(result: dict[str, Any], allowlist: list[str] | None = None) -> dict[str, Any]:
    domains = allowlist or DEFAULT_ALLOWED_DOMAINS
    url = str(result.get("url") or "")
    domain = _domain(url)
    allowed = bool(domain) and any(domain == allowed or domain.endswith(f".{allowed}") for allowed in domains)
    status = "safe_to_show" if allowed and result.get("title") and result.get("snippet") else "reject"
    recency_status = _recency_status(result.get("published_at"))
    reason = (
        f"Allowed source domain, usable title/snippet, recency {recency_status}."
        if status == "safe_to_show"
        else "Rejected because source is missing, incomplete, or outside the allowlist."
    )
    return {
        "title": result.get("title") or "Untitled source",
        "source": result.get("source") or _source_from_url(url),
        "url": url or None,
        "snippet": result.get("snippet") or "",
        "published_at": result.get("published_at"),
        "retrieved_at": datetime.now(UTC).isoformat(),
        "verification_status": status,
        "recency_status": recency_status,
        "secondary_verification": result.get("secondary_verification") or "not_run",
        "reason": reason,
    }


def build_calendar_ics(events: list[Node], calendar_name: str) -> str:
    now = _ics_datetime(datetime.now(UTC))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Caregiver Companion//Care Plan//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escape(calendar_name)}",
        "X-WR-TIMEZONE:Asia/Singapore",
    ]
    for event in sorted(events, key=lambda node: str(node.payload.get("start_at") or "")):
        start = _parse_datetime(event.payload.get("start_at"))
        if not start:
            continue
        end = _parse_datetime(event.payload.get("end_at")) or start + timedelta(minutes=30)
        description = event.payload.get("description") or ""
        if event.status:
            description = f"{description}\nStatus: {event.status}".strip()
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{event.id}@caregiver-companion",
                f"DTSTAMP:{now}",
                f"DTSTART:{_ics_datetime(start)}",
                f"DTEND:{_ics_datetime(end)}",
                f"SUMMARY:{_ics_escape(str(event.payload.get('title') or 'Care action'))}",
                f"DESCRIPTION:{_ics_escape(description)}",
                f"CATEGORIES:{_ics_escape(str(event.payload.get('action_type') or 'care'))}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _curated_resource_matches(query: str) -> list[dict[str, Any]]:
    terms = set(query.lower().replace("_", " ").split())
    results = []
    for resource in educational_resources():
        text = " ".join(
            [
                resource.get("title", ""),
                resource.get("topic", ""),
                resource.get("condition", ""),
                " ".join(resource.get("tags", [])),
            ]
        ).lower()
        if terms and not any(term in text for term in terms):
            continue
        verified = verify_live_result(
            {
                "title": resource.get("title"),
                "source": resource.get("source", "Curated catalog"),
                "url": resource.get("url") or ("https://www.healthhub.sg/" if resource.get("source") == "HealthHub" else "https://www.parkinson.org/"),
                "snippet": resource.get("summary") or resource.get("topic") or "Curated caregiver education resource.",
            }
        )
        if verified["verification_status"] != "reject":
            results.append(verified)
        elif resource.get("source") == "HealthHub":
            results.append(
                verify_live_result(
                    {
                        "title": resource.get("title"),
                        "source": resource.get("source", "Curated catalog"),
                        "url": "https://www.healthhub.sg/",
                        "snippet": resource.get("summary") or resource.get("topic") or "Curated caregiver education resource.",
                    }
                )
            )
    return results[:5]


def _curated_grant_matches(query: str) -> list[dict[str, Any]]:
    terms = set(query.lower().replace("_", " ").split())
    results = []
    for grant in grants_database():
        text = " ".join(
            [
                grant.get("name", ""),
                grant.get("summary", ""),
                grant.get("description", ""),
                " ".join(grant.get("applicable_conditions", [])),
                " ".join(grant.get("eligibility_hints", [])),
            ]
        ).lower()
        if terms and not any(term in text for term in terms):
            continue
        verified = verify_live_result(
            {
                "title": grant.get("name"),
                "source": grant.get("agency", "Curated grant catalog"),
                "url": grant.get("url") or "https://www.aic.sg/",
                "snippet": grant.get("summary") or grant.get("description") or "Curated Singapore support scheme.",
            }
        )
        if verified["verification_status"] != "reject":
            results.append(verified)
    return results[:5]


def _dedupe_verified_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for result in results:
        key = result.get("url") or result.get("title")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def _action_summary(node: Node) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "title": node.payload.get("title"),
        "action_type": node.payload.get("action_type"),
        "start_at": node.payload.get("start_at"),
        "status": node.status,
    }


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _recency_status(value: Any) -> str:
    published = _parse_datetime(value)
    if not published:
        return "unknown"
    age = datetime.now(UTC) - published
    if age <= timedelta(days=365):
        return "current"
    if age <= timedelta(days=1095):
        return "aging"
    return "old"


def _ics_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def _human_datetime(value: Any) -> str:
    parsed = _parse_datetime(value)
    if not parsed:
        return str(value)
    return parsed.astimezone(UTC).strftime("%d %b %Y, %H:%M UTC")


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _source_from_url(url: Any) -> str:
    domain = _domain(str(url or ""))
    return domain or "Unknown source"
