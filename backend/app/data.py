from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from .config import get_settings


def _read_json(filename: str) -> Any:
    path = get_settings().data_dir / filename
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache
def condition_trajectories() -> dict[str, Any]:
    return _read_json("condition_trajectories.json")


@lru_cache
def grants_database() -> list[dict[str, Any]]:
    return _read_json("grants_singapore.json")


@lru_cache
def educational_resources() -> list[dict[str, Any]]:
    return _read_json("educational_resources.json")
