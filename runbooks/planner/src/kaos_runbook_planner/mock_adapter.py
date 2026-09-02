"""Non-networked lifecycle simulation for normalized dry-run plans."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .planner import PlanError, RunbookPlanner


class MockAdapterError(ValueError):
    """A plan was not safe or authentic enough to simulate."""


class MockLifecycleAdapter:
    """Simulate lifecycle state without observing or changing a real host."""

    def __init__(self, planner: RunbookPlanner) -> None:
        self._planner = planner

    def simulate(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Return a deterministic in-memory receipt for an authentic inert plan."""
        self._validate_safety_envelope(plan)
        try:
            trusted_plan = self._planner.plan(plan["operation"], plan["parameters"])
        except (KeyError, PlanError) as exc:
            raise MockAdapterError("plan cannot be re-derived from the trusted catalog") from exc
        if plan != trusted_plan:
            raise MockAdapterError("plan does not exactly match the trusted normalized plan")

        confirmation_required = trusted_plan["confirmation"]["required"]
        lifecycle = [
            self._state("planned", "accepted authentic dry-run plan"),
            self._state("preflight-complete", "simulated all declared preflight checks"),
        ]

        if confirmation_required:
            status = "confirmation-required"
            lifecycle.append(
                self._state(
                    "confirmation-required",
                    "no confirmation accepted and no action taken",
                )
            )
            verification = {
                "status": "not-run",
                "reason": "mock lifecycle stops before a confirmation-gated action",
            }
            result = "no-action-confirmation-required"
        else:
            status = "simulated-complete"
            lifecycle.extend(
                [
                    self._state(
                        "observation-simulated",
                        "returned deterministic mock evidence only",
                    ),
                    self._state(
                        "verification-complete",
                        "simulated all declared verification checks",
                    ),
                ]
            )
            verification = {
                "status": "simulated-pass",
                "checks": deepcopy(trusted_plan["verification"]["checks"]),
            }
            result = "simulated-read-only-complete"

        return {
            "receiptVersion": "1.0",
            "adapter": "non-networked-mock",
            "status": status,
            "simulated": True,
            "executed": False,
            "productionWritesEnabled": False,
            "operationId": trusted_plan["operationId"],
            "operation": trusted_plan["operation"],
            "host": deepcopy(trusted_plan["host"]),
            "target": deepcopy(trusted_plan["target"]),
            "manifestDigest": trusted_plan["manifestDigest"],
            "catalogDigest": trusted_plan["catalogDigest"],
            "lifecycle": lifecycle,
            "mockEvidence": {
                "source": "deterministic-test-fixture",
                "realHostObserved": False,
                "facts": [],
            },
            "verification": verification,
            "auditRecord": {
                "timestamp": "1970-01-01T00:00:00Z",
                "actor": "mock:test-actor",
                "operationId": trusted_plan["operationId"],
                "operation": trusted_plan["operation"],
                "host": trusted_plan["host"]["id"],
                "target": trusted_plan["target"]["id"],
                "mode": "dry-run-only",
                "result": result,
                "evidence": "deterministic mock evidence; no host contacted",
            },
        }

    @staticmethod
    def _validate_safety_envelope(plan: Any) -> None:
        if not isinstance(plan, dict):
            raise MockAdapterError("plan must be a normalized JSON object")
        if plan.get("mode") != "dry-run-only":
            raise MockAdapterError("plan mode is not dry-run-only")
        if plan.get("productionWritesEnabled") is not False:
            raise MockAdapterError("plan does not disable production writes")
        if plan.get("executed") is not False:
            raise MockAdapterError("plan claims execution")
        operation_id = plan.get("operationId")
        if not isinstance(operation_id, str) or not operation_id.startswith("dryrun_"):
            raise MockAdapterError("plan operation ID is not a dry-run identity")

    @staticmethod
    def _state(name: str, evidence: str) -> dict[str, str]:
        return {"state": name, "evidence": evidence}
