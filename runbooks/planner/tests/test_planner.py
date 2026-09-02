from __future__ import annotations

import ast
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from kaos_runbook_planner.planner import CATALOG_FILES, PlanError, RunbookPlanner


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class RunbookPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = RunbookPlanner(REPOSITORY_ROOT)

    def test_every_catalog_operation_produces_an_inert_plan(self) -> None:
        for operation in CATALOG_FILES:
            with self.subTest(operation=operation):
                plan = self.planner.plan(operation)
                self.assertEqual(plan["mode"], "dry-run-only")
                self.assertFalse(plan["productionWritesEnabled"])
                self.assertFalse(plan["executed"])
                self.assertTrue(plan["operationId"].startswith("dryrun_"))
                self.assertNotIn("command", json.dumps(plan).lower())

    def test_operation_id_is_stable_for_the_same_normalized_request(self) -> None:
        default_plan = self.planner.plan("system.logs_tail")
        explicit_plan = self.planner.plan("system.logs_tail", {"lineCount": 100})
        self.assertEqual(default_plan["operationId"], explicit_plan["operationId"])
        self.assertEqual(default_plan["parameters"], {"lineCount": 100})

    def test_unknown_operation_fails_closed(self) -> None:
        with self.assertRaisesRegex(PlanError, "not allowlisted"):
            self.planner.plan("system.shell")

    def test_extra_parameter_fails_closed(self) -> None:
        with self.assertRaisesRegex(PlanError, "not allowlisted"):
            self.planner.plan("system.status", {"command": "anything"})

    def test_parameter_type_and_bounds_fail_closed(self) -> None:
        rejected = (True, "100", 0, 201)
        for line_count in rejected:
            with self.subTest(line_count=line_count), self.assertRaises(PlanError):
                self.planner.plan("system.logs_tail", {"lineCount": line_count})

    def test_restart_remains_unexecuted_and_requires_confirmation(self) -> None:
        plan = self.planner.plan("service.restart")
        self.assertTrue(plan["action"]["wouldMutateSystem"])
        self.assertTrue(plan["confirmation"]["required"])
        self.assertEqual(
            plan["confirmation"]["state"], "required-before-future-execution"
        )
        self.assertFalse(plan["executed"])

    def test_modified_catalog_enabling_writes_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "runbooks" / "schema").mkdir(parents=True)
            (root / "runbooks" / "catalog").mkdir(parents=True)
            schema_source = REPOSITORY_ROOT / "runbooks" / "schema" / "runbook.schema.json"
            schema = json.loads(schema_source.read_text(encoding="utf-8"))
            (root / "runbooks" / "schema" / "runbook.schema.json").write_text(
                json.dumps(schema), encoding="utf-8"
            )
            source = REPOSITORY_ROOT / "runbooks" / "catalog" / "service.restart.json"
            unsafe = deepcopy(json.loads(source.read_text(encoding="utf-8")))
            unsafe["safety"]["productionWritesEnabled"] = True
            (root / "runbooks" / "catalog" / "service.restart.json").write_text(
                json.dumps(unsafe), encoding="utf-8"
            )
            unsafe_planner = RunbookPlanner(root)
            with self.assertRaisesRegex(PlanError, "catalog validation failed"):
                unsafe_planner.plan("service.restart")

    def test_planner_has_no_execution_or_network_imports(self) -> None:
        forbidden_imports = {
            "asyncio",
            "docker",
            "http",
            "os",
            "paramiko",
            "requests",
            "shlex",
            "socket",
            "subprocess",
            "urllib",
        }
        source_root = REPOSITORY_ROOT / "runbooks" / "planner" / "src"
        for path in source_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".", 1)[0])
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {"eval", "exec", "compile"})
            self.assertFalse(imported & forbidden_imports, path)


if __name__ == "__main__":
    unittest.main()
