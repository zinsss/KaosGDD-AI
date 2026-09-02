"""Validate catalog entries and produce inert normalized operation plans."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator


CATALOG_FILES = {
    "service.restart": "service.restart.json",
    "system.disk_status": "system.disk_status.json",
    "system.git_status": "system.git_status.json",
    "system.logs_tail": "system.logs_tail.json",
    "system.status": "system.status.json",
}


class PlanError(ValueError):
    """A request or catalog entry failed closed."""


class RunbookPlanner:
    """Create plans without contacting or changing any managed system."""

    def __init__(self, repository_root: Path) -> None:
        self._repository_root = repository_root.resolve()
        self._catalog_root = self._repository_root / "runbooks" / "catalog"
        schema_path = self._repository_root / "runbooks" / "schema" / "runbook.schema.json"
        schema = self._load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)

    def plan(self, operation: str, parameters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return a deterministic dry-run plan for one allowlisted operation."""
        filename = CATALOG_FILES.get(operation)
        if filename is None:
            raise PlanError(f"operation is not allowlisted: {operation!r}")

        runbook = self._load_json(self._catalog_root / filename)
        self._validate_runbook(runbook, expected_operation=operation)
        normalized_parameters = self._normalize_parameters(runbook, parameters or {})

        identity = {
            "contractVersion": runbook["contractVersion"],
            "runbookVersion": runbook["runbookVersion"],
            "operation": runbook["operation"],
            "host": runbook["host"],
            "target": runbook["target"],
            "parameters": normalized_parameters,
        }
        identity_json = self._canonical_json(identity)
        runbook_json = self._canonical_json(runbook)

        return {
            "planVersion": "1.0",
            "operationId": f"dryrun_{hashlib.sha256(identity_json).hexdigest()[:24]}",
            "status": "planned",
            "mode": "dry-run-only",
            "productionWritesEnabled": False,
            "executed": False,
            "catalogDigest": f"sha256:{hashlib.sha256(runbook_json).hexdigest()}",
            "operation": runbook["operation"],
            "runbookVersion": runbook["runbookVersion"],
            "host": deepcopy(runbook["host"]),
            "target": deepcopy(runbook["target"]),
            "action": deepcopy(runbook["action"]),
            "parameters": normalized_parameters,
            "preflight": deepcopy(runbook["preflight"]),
            "confirmation": {
                **deepcopy(runbook["confirmation"]),
                "state": (
                    "required-before-future-execution"
                    if runbook["confirmation"]["required"]
                    else "not-required-for-read-only-observation"
                ),
            },
            "verification": deepcopy(runbook["verification"]),
            "rollback": deepcopy(runbook["rollback"]),
            "operationLog": deepcopy(runbook["operationLog"]),
        }

    def _validate_runbook(self, runbook: Any, *, expected_operation: str) -> None:
        errors = sorted(self._validator.iter_errors(runbook), key=lambda error: list(error.path))
        if errors:
            location = ".".join(str(part) for part in errors[0].path) or "<root>"
            raise PlanError(f"catalog validation failed at {location}: {errors[0].message}")
        if runbook["operation"] != expected_operation:
            raise PlanError("catalog filename and operation do not match")
        if runbook["safety"] != {
            "executionMode": "dry-run-only",
            "productionWritesEnabled": False,
        }:
            raise PlanError("catalog safety boundary is not dry-run-only")

    @staticmethod
    def _normalize_parameters(
        runbook: Mapping[str, Any], requested: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(requested, Mapping):
            raise PlanError("parameters must be a JSON object")

        specifications = {
            specification["name"]: specification
            for specification in runbook["parameters"]["allowed"]
        }
        unknown = sorted(set(requested) - set(specifications))
        if unknown:
            raise PlanError(f"parameters are not allowlisted: {', '.join(unknown)}")

        normalized: dict[str, Any] = {}
        for name, specification in specifications.items():
            if name in requested:
                value = requested[name]
            elif "default" in specification:
                value = specification["default"]
            elif specification["required"]:
                raise PlanError(f"required parameter is missing: {name}")
            else:
                continue

            RunbookPlanner._validate_parameter(name, value, specification)
            normalized[name] = value
        return normalized

    @staticmethod
    def _validate_parameter(name: str, value: Any, specification: Mapping[str, Any]) -> None:
        expected_type = specification["type"]
        if expected_type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise PlanError(f"parameter {name} must be an integer")
            if "minimum" in specification and value < specification["minimum"]:
                raise PlanError(f"parameter {name} is below its minimum")
            if "maximum" in specification and value > specification["maximum"]:
                raise PlanError(f"parameter {name} exceeds its maximum")
        elif expected_type == "string":
            if not isinstance(value, str):
                raise PlanError(f"parameter {name} must be a string")
        else:
            raise PlanError(f"catalog declares unsupported parameter type: {expected_type}")

        if "enum" in specification and value not in specification["enum"]:
            raise PlanError(f"parameter {name} is not an allowed value")

    @staticmethod
    def _canonical_json(value: Any) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _load_json(path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PlanError(f"unable to load repository runbook data: {path.name}") from exc
