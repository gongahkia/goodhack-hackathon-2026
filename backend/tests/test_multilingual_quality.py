import asyncio
import json
from datetime import date
from pathlib import Path

import pytest

from app.extraction import process_redacted_transcript
from app.quality import character_error_rate, extraction_accuracy, transcript_quality, word_error_rate
from app.store import MemoryGraphStore


async def _redaction(store: MemoryGraphStore, text: str, language: str):
    return await store.create_node(
        "pii_redaction",
        {
            "patient_id": "patient-1",
            "redacted_text": text,
            "placeholder_map": {"PERSON_1": "John"},
            "detected_language": language,
            "source_text_kind": "original",
        },
        "system",
        status="approved",
    )


def test_transcript_quality_uses_wer_for_word_spaced_languages_and_cer_for_mandarin():
    assert word_error_rate("John needs Panadol before lunch", "John needs Panadol lunch") == pytest.approx(0.2)
    assert character_error_rate("每天午餐前吃药", "每天午餐吃药") == pytest.approx(1 / 7)

    english = transcript_quality("John needs Panadol before lunch", "John needs Panadol lunch", "en")
    mandarin = transcript_quality("每天午餐前吃药", "每天午餐吃药", "zh")
    thai = transcript_quality("กินยาก่อนอาหารกลางวัน", "กินยาอาหารกลางวัน", "th")

    assert english["metric"] == "wer"
    assert english["passed"] is True
    assert mandarin["metric"] == "cer"
    assert mandarin["passed"] is True
    assert thai["metric"] == "cer"
    assert thai["passed"] is True


def test_multilingual_fixture_extraction_accuracy_scores_required_artifacts():
    store = MemoryGraphStore()
    redaction = asyncio.run(
        _redaction(
            store,
            "PERSON_1 perlu makan Panadol sebelum makan tengah hari setiap hari. Temu janji doktor pada 2026-06-01 at 10am. Doktor kata mungkin perlu kerusi roda, cari subsidi kerusi roda.",
            "ms",
        )
    )
    result = asyncio.run(process_redacted_transcript(store, redaction, reference_date=date(2026, 5, 9)))

    score = extraction_accuracy(
        result,
        {
            "buckets": ["daily_task", "appointment", "ad_hoc_research"],
            "daily_task": {"medication": "Panadol", "timing_relation": "before lunch", "recurrence": "daily"},
            "appointment": {"kind": "doctor", "date": "2026-06-01", "time": "10:00"},
            "research_task": True,
        },
    )

    assert score["passed"] is True
    assert score["score"] == 1
    assert all(score["checks"].values())


FIXTURE_PATH = Path(__file__).resolve().parents[2] / "data" / "multilingual_regression_fixtures.json"


@pytest.mark.parametrize("fixture", json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))
def test_multilingual_regression_fixture_corpus(fixture):
    store = MemoryGraphStore()
    redaction = asyncio.run(_redaction(store, fixture["text"], fixture["language"]))
    result = asyncio.run(process_redacted_transcript(store, redaction, reference_date=date(2026, 5, 9)))

    score = extraction_accuracy(result, fixture["expected"])

    assert score["passed"] is True, {"fixture": fixture["id"], "score": score, "result": result}
