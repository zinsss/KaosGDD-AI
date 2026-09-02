from __future__ import annotations

import ast
import json
import shutil
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
                self.assertTrue(plan["manifestDigest"].startswith("sha256:"))
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
            self._copy_runbook_data(root)
            destination = root / "runbooks" / "catalog" / "service.restart.json"
            unsafe = deepcopy(json.loads(destination.read_text(encoding="utf-8")))
            unsafe["safety"]["productionWritesEnabled"] = True
            destination.write_text(json.dumps(unsafe), encoding="utf-8")
            with self.assertRaisesRegex(PlanError, "provenance check failed"):
                RunbookPlanner(root)

    def test_added_or_missing_catalog_file_is_rejected(self) -> None:
        for change in ("added", "missing"):
            with (
                self.subTest(change=change),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                root = Path(temporary_directory)
                self._copy_runbook_data(root)
                catalog = root / "runbooks" / "catalog"
                if change == "added":
                    (catalog / "unlisted.json").write_text("{}\n", encoding="utf-8")
                else:
                    (catalog / "system.status.json").unlink()
                with self.assertRaisesRegex(PlanError, "exactly match"):
                    RunbookPlanner(root)

    def test_stale_manifest_digest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._copy_runbook_data(root)
            manifest_path = root / "runbooks" / "catalog-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["catalog"]["system.status.json"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(PlanError, "provenance check failed"):
                RunbookPlanner(root)

    def test_manifest_digest_is_bound_into_operation_id(self) -> None:
        original = self.planner.plan("system.status")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._copy_runbook_data(root)
            manifest_path = root / "runbooks" / "catalog-manifest.json"
            manifest_path.write_text(
                manifest_path.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )
            changed = RunbookPlanner(root).plan("system.status")
        self.assertNotEqual(original["manifestDigest"], changed["manifestDigest"])
        self.assertNotEqual(original["operationId"], changed["operationId"])

    def test_modified_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._copy_runbook_data(root)
            schema_path = root / "runbooks" / "schema" / "runbook.schema.json"
            schema_path.write_text(
                schema_path.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(PlanError, "provenance check failed"):
                RunbookPlanner(root)

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

    @staticmethod
    def _copy_runbook_data(root: Path) -> None:
        destination = root / "runbooks"
        (destination / "schema").mkdir(parents=True)
        shutil.copy2(
            REPOSITORY_ROOT / "runbooks" / "catalog-manifest.json", destination
        )
        shutil.copytree(
            REPOSITORY_ROOT / "runbooks" / "catalog", destination / "catalog"
        )
        shutil.copytree(
            REPOSITORY_ROOT / "runbooks" / "schema",
            destination / "schema",
            dirs_exist_ok=True,
        )


if __name__ == "__main__":
    unittest.main()
