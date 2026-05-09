from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx

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
    if not settings.exa_api_key:
        return curated
    live = await _exa_search(query, settings.exa_api_key, allowlist or DEFAULT_ALLOWED_DOMAINS)
    return _dedupe_verified_results([*live, *curated])[:5]


async def search_verified_grants(query: str, settings: Settings, allowlist: list[str] | None = None) -> list[dict[str, Any]]:
    curated = _curated_grant_matches(query)
    if not settings.exa_api_key:
        return curated
    live = await _exa_search(f"{query} Singapore caregiver senior grant", settings.exa_api_key, allowlist or DEFAULT_ALLOWED_DOMAINS)
    return _dedupe_verified_results([*live, *curated])[:5]


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
    reason = "Allowed source domain and usable title/snippet." if status == "safe_to_show" else "Rejected because source is missing, incomplete, or outside the allowlist."
    return {
        "title": result.get("title") or "Untitled source",
        "source": result.get("source") or _source_from_url(url),
        "url": url or None,
        "snippet": result.get("snippet") or "",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "verification_status": status,
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
