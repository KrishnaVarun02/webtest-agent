"""Command line entry point for the deterministic generator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .generator import GenerationError, generate_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="webtest-generator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate", help="generate a Maven project from an approved plan")
    generate.add_argument("--plan", type=Path, required=True, help="approved plan JSON")
    generate.add_argument("--output-root", type=Path, required=True, help="parent directory for generated projects")
    generate.add_argument("--project-name", required=True, help="safe Maven/project directory name")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with args.plan.open("r", encoding="utf-8") as handle:
            plan = json.load(handle)
        if not isinstance(plan, dict):
            raise GenerationError("approved plan must be a JSON object")
        manifest = generate_project(plan, args.output_root, args.project_name)
    except (OSError, json.JSONDecodeError, GenerationError) as exc:
        print(f"generation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
