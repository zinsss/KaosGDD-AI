"""Validate catalog entries and produce inert normalized operation plans."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator


CATALOG_FILES = {
    "containers.apply_update": "containers.apply_update.json",
    "containers.check_updates": "containers.check_updates.json",
    "containers.plan_update": "containers.plan_update.json",
    "service.restart": "service.restart.json",
    "system.apply_updates": "system.apply_updates.json",
    "system.check_updates": "system.check_updates.json",
    "system.disk_status": "system.disk_status.json",
    "system.git_status": "system.git_status.json",
    "system.logs_tail": "system.logs_tail.json",
    "system.plan_updates": "system.plan_updates.json",
    "system.status": "system.status.json",
}


class PlanError(ValueError):
    """A request or catalog entry failed closed."""


class RunbookPlanner:
    """Create plans without contacting or changing any managed system."""

    def __init__(self, repository_root: Path) -> None:
        self._repository_root = repository_root.resolve()
        self._runbooks_root = self._repository_root / "runbooks"
        self._catalog_root = self._repository_root / "runbooks" / "catalog"
        manifest_path = self._runbooks_root / "catalog-manifest.json"
        manifest_bytes, manifest = self._load_json_bytes(manifest_path)
        self._validate_manifest(manifest)
        self._manifest_digest = f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}"

        schema_path = self._runbooks_root / manifest["schema"]["path"]
        schema_bytes, schema = self._load_json_bytes(schema_path)
        self._verify_digest(
            schema_bytes, manifest["schema"]["digest"], "runbook schema"
        )
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)
        self._verify_catalog(manifest["catalog"])
        self._catalog_digests = deepcopy(manifest["catalog"])

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
            "manifestDigest": self._manifest_digest,
            "catalogDigest": f"sha256:{self._catalog_digests[filename]}",
            "operation": runbook["operation"],
            "host": runbook["host"],
            "target": runbook["target"],
            "parameters": normalized_parameters,
        }
        identity_json = self._canonical_json(identity)

        return {
            "planVersion": "1.0",
            "operationId": f"dryrun_{hashlib.sha256(identity_json).hexdigest()[:24]}",
            "status": "planned",
            "mode": "dry-run-only",
            "productionWritesEnabled": False,
            "executed": False,
            "manifestDigest": self._manifest_digest,
            "catalogDigest": f"sha256:{self._catalog_digests[filename]}",
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

    def _validate_manifest(self, manifest: Any) -> None:
        if not isinstance(manifest, dict) or set(manifest) != {
            "manifestVersion",
            "algorithm",
            "schema",
            "catalog",
        }:
            raise PlanError("catalog manifest has an invalid top-level contract")
        if manifest["manifestVersion"] != "1.0" or manifest["algorithm"] != "sha256":
            raise PlanError("catalog manifest version or algorithm is unsupported")
        schema_entry = manifest["schema"]
        if (
            not isinstance(schema_entry, dict)
            or set(schema_entry) != {"path", "digest"}
            or schema_entry["path"] != "schema/runbook.schema.json"
        ):
            raise PlanError("catalog manifest schema entry is invalid")
        self._validate_digest(schema_entry["digest"], "schema")
        if not isinstance(manifest["catalog"], dict):
            raise PlanError("catalog manifest entries must be an object")
        expected_files = set(CATALOG_FILES.values())
        if set(manifest["catalog"]) != expected_files:
            raise PlanError("catalog manifest does not match the operation allowlist")
        for filename, digest in manifest["catalog"].items():
            if Path(filename).name != filename:
                raise PlanError("catalog manifest filenames must be plain filenames")
            self._validate_digest(digest, filename)

    def _verify_catalog(self, expected_digests: Mapping[str, str]) -> None:
        actual_files = {
            path.name for path in self._catalog_root.glob("*.json") if path.is_file()
        }
        if actual_files != set(expected_digests):
            raise PlanError("catalog files do not exactly match the committed manifest")
        for filename, expected_digest in expected_digests.items():
            try:
                content = (self._catalog_root / filename).read_bytes()
            except OSError as exc:
                raise PlanError(f"unable to load repository runbook data: {filename}") from exc
            self._verify_digest(content, expected_digest, filename)

    @staticmethod
    def _validate_digest(digest: Any, label: str) -> None:
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise PlanError(f"catalog manifest digest is invalid for {label}")

    @staticmethod
    def _verify_digest(content: bytes, expected_digest: str, label: str) -> None:
        actual_digest = hashlib.sha256(content).hexdigest()
        if actual_digest != expected_digest:
            raise PlanError(f"repository provenance check failed for {label}")

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
            if "minLength" in specification and len(value) < specification["minLength"]:
                raise PlanError(f"parameter {name} is shorter than its minimum length")
            if "maxLength" in specification and len(value) > specification["maxLength"]:
                raise PlanError(f"parameter {name} exceeds its maximum length")
            if "pattern" in specification and re.fullmatch(
                specification["pattern"], value
            ) is None:
                raise PlanError(f"parameter {name} does not match its required format")
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
        return RunbookPlanner._load_json_bytes(path)[1]

    @staticmethod
    def _load_json_bytes(path: Path) -> tuple[bytes, Any]:
        try:
            content = path.read_bytes()
            return content, json.loads(content)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PlanError(f"unable to load repository runbook data: {path.name}") from exc
