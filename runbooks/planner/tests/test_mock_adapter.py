from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path

from kaos_runbook_planner import (
    MockAdapterError,
    MockLifecycleAdapter,
    RunbookPlanner,
)
from kaos_runbook_planner.planner import CATALOG_FILES


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TEST_UPDATE_PLAN_DIGEST = "sha256:" + "a" * 64


def parameters_for(operation: str) -> dict[str, object]:
    if operation in {"system.apply_updates", "containers.apply_update"}:
        return {"updatePlanDigest": TEST_UPDATE_PLAN_DIGEST}
    return {}


class MockLifecycleAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = RunbookPlanner(REPOSITORY_ROOT)
        self.adapter = MockLifecycleAdapter(self.planner)

    def test_all_catalog_operations_produce_nonexecuted_mock_receipts(self) -> None:
        for operation in CATALOG_FILES:
            with self.subTest(operation=operation):
                plan = self.planner.plan(operation, parameters_for(operation))
                receipt = self.adapter.simulate(plan)
                self.assertEqual(receipt["adapter"], "non-networked-mock")
                self.assertTrue(receipt["simulated"])
                self.assertFalse(receipt["executed"])
                self.assertFalse(receipt["productionWritesEnabled"])
                self.assertFalse(receipt["mockEvidence"]["realHostObserved"])
                self.assertEqual(receipt["mockEvidence"]["facts"], [])

    def test_read_only_plan_completes_only_a_simulated_lifecycle(self) -> None:
        receipt = self.adapter.simulate(self.planner.plan("system.status"))
        self.assertEqual(receipt["status"], "simulated-complete")
        self.assertEqual(receipt["verification"]["status"], "simulated-pass")
        self.assertEqual(
            [entry["state"] for entry in receipt["lifecycle"]],
            [
                "planned",
                "preflight-complete",
                "observation-simulated",
                "verification-complete",
            ],
        )

    def test_restart_stops_at_confirmation_without_action(self) -> None:
        receipt = self.adapter.simulate(self.planner.plan("service.restart"))
        self.assertEqual(receipt["status"], "confirmation-required")
        self.assertEqual(receipt["verification"]["status"], "not-run")
        self.assertEqual(receipt["lifecycle"][-1]["state"], "confirmation-required")
        self.assertEqual(
            receipt["auditRecord"]["result"], "no-action-confirmation-required"
        )
        self.assertFalse(receipt["executed"])

    def test_update_apply_plans_stop_at_confirmation_without_action(self) -> None:
        for operation in ("system.apply_updates", "containers.apply_update"):
            with self.subTest(operation=operation):
                plan = self.planner.plan(operation, parameters_for(operation))
                receipt = self.adapter.simulate(plan)
                self.assertEqual(receipt["status"], "confirmation-required")
                self.assertEqual(receipt["verification"]["status"], "not-run")
                self.assertFalse(receipt["executed"])

    def test_audit_record_has_every_catalog_required_field(self) -> None:
        plan = self.planner.plan("system.git_status")
        receipt = self.adapter.simulate(plan)
        self.assertEqual(
            set(receipt["auditRecord"]), set(plan["operationLog"]["fields"])
        )
        self.assertEqual(receipt["auditRecord"]["mode"], "dry-run-only")

    def test_safety_envelope_tampering_fails_closed(self) -> None:
        mutations = {
            "mode": "execute",
            "productionWritesEnabled": True,
            "executed": True,
            "operationId": "operation_not_dry_run",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                plan = self.planner.plan("system.status")
                plan[field] = value
                with self.assertRaises(MockAdapterError):
                    self.adapter.simulate(plan)

    def test_provenance_or_payload_tampering_fails_closed(self) -> None:
        mutations = (
            ("manifestDigest", "sha256:" + "0" * 64),
            ("catalogDigest", "sha256:" + "0" * 64),
            ("status", "approved"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                plan = self.planner.plan("system.logs_tail", {"lineCount": 25})
                plan[field] = value
                with self.assertRaisesRegex(MockAdapterError, "exactly match"):
                    self.adapter.simulate(plan)

        changed_parameters = deepcopy(
            self.planner.plan("system.logs_tail", {"lineCount": 25})
        )
        changed_parameters["parameters"]["lineCount"] = 26
        with self.assertRaisesRegex(MockAdapterError, "exactly match"):
            self.adapter.simulate(changed_parameters)

    def test_non_object_plan_fails_closed(self) -> None:
        with self.assertRaisesRegex(MockAdapterError, "JSON object"):
            self.adapter.simulate([])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
