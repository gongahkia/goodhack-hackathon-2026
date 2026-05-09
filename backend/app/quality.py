from __future__ import annotations

import re
from typing import Any


def word_error_rate(reference: str, hypothesis: str) -> float:
    reference_tokens = _word_tokens(reference)
    hypothesis_tokens = _word_tokens(hypothesis)
    if not reference_tokens:
        return 0.0 if not hypothesis_tokens else 1.0
    return _edit_distance(reference_tokens, hypothesis_tokens) / len(reference_tokens)


def character_error_rate(reference: str, hypothesis: str) -> float:
    reference_chars = [char for char in reference.strip() if not char.isspace()]
    hypothesis_chars = [char for char in hypothesis.strip() if not char.isspace()]
    if not reference_chars:
        return 0.0 if not hypothesis_chars else 1.0
    return _edit_distance(reference_chars, hypothesis_chars) / len(reference_chars)


def extraction_accuracy(result: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    triage = result.get("triage_decision", {}).get("payload", {})
    expected_buckets = set(expected.get("buckets", []))
    actual_buckets = set(triage.get("buckets", []))
    expected_daily = expected.get("daily_task", {})
    expected_appointment = expected.get("appointment", {})
    expected_research = bool(expected.get("research_task"))

    daily_payloads = [item.get("payload", {}) for item in result.get("daily_tasks", [])]
    appointment_payloads = [item.get("payload", {}) for item in result.get("appointment_candidates", [])]
    research_payloads = [item.get("payload", {}) for item in result.get("ad_hoc_research_tasks", [])]

    checks = {
        "buckets": expected_buckets <= actual_buckets,
        "daily_task_present": not expected_daily or bool(daily_payloads),
        "medication": not expected_daily.get("medication") or any(
            (payload.get("medication") or {}).get("name", "").lower() == str(expected_daily["medication"]).lower()
            for payload in daily_payloads
        ),
        "timing_relation": not expected_daily.get("timing_relation") or any(
            payload.get("timing_relation") == expected_daily["timing_relation"] for payload in daily_payloads
        ),
        "recurrence": not expected_daily.get("recurrence") or any(
            payload.get("recurrence") == expected_daily["recurrence"] for payload in daily_payloads
        ),
        "appointment": not expected_appointment or any(
            payload.get("kind") == expected_appointment.get("kind")
            and payload.get("date") == expected_appointment.get("date")
            and payload.get("time") == expected_appointment.get("time")
            for payload in appointment_payloads
        ),
        "research_task": not expected_research or bool(research_payloads),
        "privacy": not _contains_placeholder_leak(result),
    }
    passed = sum(1 for value in checks.values() if value)
    return {
        "passed": all(checks.values()),
        "score": round(passed / len(checks), 3),
        "checks": checks,
    }


def transcript_quality(reference: str, hypothesis: str, language: str) -> dict[str, Any]:
    metric = "cer" if language in {"zh", "th"} else "wer"
    error_rate = character_error_rate(reference, hypothesis) if metric == "cer" else word_error_rate(reference, hypothesis)
    return {
        "metric": metric,
        "error_rate": round(error_rate, 4),
        "passed": error_rate <= 0.25,
    }


def _word_tokens(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower(), flags=re.UNICODE)


def _edit_distance(left: list[Any], right: list[Any]) -> int:
    previous = list(range(len(right) + 1))
    for i, left_item in enumerate(left, start=1):
        current = [i]
        for j, right_item in enumerate(right, start=1):
            cost = 0 if left_item == right_item else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


def _contains_placeholder_leak(result: dict[str, Any]) -> bool:
    user_payloads = [
        *(item.get("payload", {}) for item in result.get("daily_tasks", [])),
        *(item.get("payload", {}) for item in result.get("appointment_candidates", [])),
        *(item.get("payload", {}) for item in result.get("ad_hoc_research_tasks", [])),
    ]
    return any(
        "PERSON_" in str(payload.get(key, ""))
        for payload in user_payloads
        for key in ("description", "basis", "question", "title")
    )
