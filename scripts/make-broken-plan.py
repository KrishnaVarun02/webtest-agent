#!/usr/bin/env python3
"""Create a reviewed plan with one deliberately wrong business assertion."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "generator" / "fixtures" / "approved-plan.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "generated" / "broken-approved-plan.json",
    )
    args = parser.parse_args()

    try:
        plan = json.loads(args.source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"unable to read approved plan: {exc}", file=sys.stderr)
        return 2

    broken = copy.deepcopy(plan)
    changed = 0
    for workflow in broken.get("workflows", []):
        for scenario in workflow.get("scenarios", []):
            if scenario.get("scenarioId") != "crud-positive":
                continue
            for assertion in scenario.get("assertions", []):
                if assertion.get("kind") == "value" and assertion.get("path") == "$.name":
                    assertion["expected"] = "INTENTIONALLY WRONG EXPECTATION"
                    assertion["evidence"] = "Deliberately broken by the failure-report demonstration."
                    changed += 1
    if changed != 1:
        print(f"expected to change exactly one assertion, changed {changed}", file=sys.stderr)
        return 3

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(broken, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
