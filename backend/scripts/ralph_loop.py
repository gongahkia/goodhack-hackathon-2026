from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Check:
    name: str
    args: list[str]


QUICK_CHECKS = [
    Check(
        "multilingual-pipeline",
        [
            "-m",
            "pytest",
            "-q",
            "tests/test_transcription_ingestion.py",
            "tests/test_extraction_triage.py",
            "tests/test_multilingual_quality.py",
            "tests/test_api_contracts.py",
        ],
    )
]
FULL_CHECKS = [
    *QUICK_CHECKS,
    Check("full-backend-suite", ["-m", "pytest", "-q"]),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run bounded robustness checks until the objective passes or a failure needs engineering work."
    )
    parser.add_argument("--max-iterations", type=int, default=1, help="Maximum loop attempts. Defaults to one deterministic pass.")
    parser.add_argument("--quick", action="store_true", help="Run only transcript/multilingual/API checks.")
    args = parser.parse_args()

    backend_root = Path(__file__).resolve().parents[1]
    checks = QUICK_CHECKS if args.quick else FULL_CHECKS
    max_iterations = max(1, args.max_iterations)

    for iteration in range(1, max_iterations + 1):
        print(f"robustness loop iteration {iteration}/{max_iterations}", flush=True)
        for check in checks:
            print(f"running {check.name}: {sys.executable} {' '.join(check.args)}", flush=True)
            completed = subprocess.run([sys.executable, *check.args], cwd=backend_root)
            if completed.returncode:
                print(f"{check.name} failed with exit code {completed.returncode}", flush=True)
                return completed.returncode
        print("all checks passed for this iteration", flush=True)

    print("objective checks passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
