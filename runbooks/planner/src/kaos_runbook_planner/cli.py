"""Command-line interface for inert runbook plan rendering."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .planner import CATALOG_FILES, PlanError, RunbookPlanner


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an allowlisted runbook and print a dry-run-only plan."
    )
    parser.add_argument("operation", choices=sorted(CATALOG_FILES))
    parser.add_argument(
        "--parameters-json",
        default="{}",
        help="JSON object containing only schema-declared parameter values.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        parameters = json.loads(args.parameters_json)
        if not isinstance(parameters, dict):
            raise PlanError("parameters must be a JSON object")
        plan = RunbookPlanner(_repository_root()).plan(args.operation, parameters)
    except (json.JSONDecodeError, PlanError) as exc:
        print(f"plan rejected: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
