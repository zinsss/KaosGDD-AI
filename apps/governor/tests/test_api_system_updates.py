from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import ast
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from kaos_governor import api, system_updates


NOW = datetime(2026, 9, 2, 3, 0, tzinfo=timezone.utc)


def report_bytes(**overrides: object) -> bytes:
    payload: dict[str, object] = {
        "collectedAt": "2026-09-02T02:30:00Z",
        "reports": [
            {
                "target": {"name": "kaosgdd", "mode": "local"},
                "ok": True,
                "facts": {
                    "hostname": "kaosgdd",
                    "os_updates": "12",
                    "docker_package_updates": "2",
                    "reboot_required": "no",
                    "docker_running": "8",
                    "docker_unhealthy": "0",
                    "docker_exited": "1",
                    "docker_image_updates": "not checked; requires explicit pull",
                    "untrusted_extra": "must not be returned",
                },
            }
        ],
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


class CaptureHandler(api.Handler):
    def __init__(self, path: str, headers: dict[str, str]) -> None:
        self.path = path
        self.headers = dict(headers)
        self.rfile = BytesIO()
        self.wfile = BytesIO()
        self.status = 0

    def send_response(self, code: int, message: str | None = None) -> None:
        self.status = code

    def send_header(self, keyword: str, value: str) -> None:
        return None

    def end_headers(self) -> None:
        return None


class SystemUpdatesApiTests(unittest.TestCase):
    def test_parser_returns_only_normalized_fresh_h3_fields(self) -> None:
        result = system_updates.parse_system_updates(report_bytes(), now=NOW)

        self.assertTrue(result["readOnly"])
        self.assertEqual(result["host"], "kaosgdd")
        self.assertEqual(result["ageSeconds"], 1_800)
        self.assertEqual(result["updates"]["routinePackageCount"], 12)
        self.assertEqual(result["updates"]["dockerEnginePackageCount"], 2)
        self.assertEqual(result["updates"]["containerImageStatus"], "not-checked")
        self.assertNotIn("untrusted_extra", json.dumps(result))
        self.assertLess(len(json.dumps(result).encode("utf-8")), 2_048)

    def test_reader_uses_only_the_fixed_report_path(self) -> None:
        with patch.object(
            type(system_updates.MAINTENANCE_REPORT_PATH),
            "read_bytes",
            autospec=True,
            return_value=report_bytes(),
        ) as read_bytes:
            result = system_updates.read_system_updates(now=NOW)

        self.assertTrue(result["readOnly"])
        read_bytes.assert_called_once_with(system_updates.MAINTENANCE_REPORT_PATH)

    def test_parser_rejects_invalid_size_age_target_and_counts(self) -> None:
        invalid_payloads = [b"", b"not-json", b"[]"]
        for content in invalid_payloads:
            with self.subTest(content=content), self.assertRaises(
                system_updates.SystemUpdatesError
            ):
                system_updates.parse_system_updates(content, now=NOW)

        with self.assertRaisesRegex(system_updates.SystemUpdatesError, "too_large"):
            system_updates.parse_system_updates(
                b"x" * (system_updates.MAX_REPORT_BYTES + 1), now=NOW
            )
        with self.assertRaisesRegex(system_updates.SystemUpdatesError, "stale"):
            system_updates.parse_system_updates(
                report_bytes(collectedAt="2026-08-30T00:00:00Z"), now=NOW
            )

        base = json.loads(report_bytes())
        for reports in ([], base["reports"] * 2):
            with self.subTest(reports=reports), self.assertRaisesRegex(
                system_updates.SystemUpdatesError, "target_invalid"
            ):
                system_updates.parse_system_updates(
                    report_bytes(reports=reports), now=NOW
                )

        payload = json.loads(report_bytes())
        payload["reports"][0]["facts"]["os_updates"] = "unknown"
        with self.assertRaisesRegex(system_updates.SystemUpdatesError, "count_invalid"):
            system_updates.parse_system_updates(
                json.dumps(payload).encode("utf-8"), now=NOW
            )

    def test_payload_rejects_family_and_wraps_read_only_status(self) -> None:
        with self.assertRaisesRegex(
            system_updates.SystemUpdatesError, "main_profile_required"
        ):
            api.system_updates_payload("family")

        with patch.object(
            api,
            "read_system_updates",
            return_value={"readOnly": True, "host": "kaosgdd"},
        ):
            payload = api.system_updates_payload("main")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["readOnly"])
        self.assertEqual(payload["profile"], "main")

    def test_handler_requires_personal_cloudflare_access(self) -> None:
        handler = CaptureHandler(
            "/api/system/updates", {"Host": "family.kaosgdd.net"}
        )
        with (
            patch.object(
                api.memos_relay,
                "verify_cloudflare_access",
                return_value=("family", "family@example.com"),
            ),
            patch.object(api, "system_updates_payload") as read_updates,
        ):
            handler.do_GET()

        self.assertEqual(handler.status, 404)
        self.assertEqual(
            json.loads(handler.wfile.getvalue())["error"], "main_profile_required"
        )
        read_updates.assert_not_called()

    def test_handler_returns_stable_errors_without_report_content_or_path(self) -> None:
        handler = CaptureHandler(
            "/api/system/updates", {"Host": "kaosgdd.net"}
        )
        with (
            patch.object(
                api.memos_relay,
                "verify_cloudflare_access",
                return_value=("personal", "zin@example.com"),
            ),
            patch.object(
                api,
                "system_updates_payload",
                side_effect=system_updates.SystemUpdatesError(
                    "system_updates_stale"
                ),
            ),
        ):
            handler.do_GET()

        body = handler.wfile.getvalue()
        self.assertEqual(handler.status, 503)
        self.assertEqual(json.loads(body)["error"], "system_updates_stale")
        self.assertLess(len(body), 256)
        self.assertNotIn(b"/data/", body)

    def test_handler_returns_normalized_status_after_personal_access(self) -> None:
        handler = CaptureHandler(
            "/api/system/updates", {"Host": "kaosgdd.net"}
        )
        with (
            patch.object(
                api.memos_relay,
                "verify_cloudflare_access",
                return_value=("personal", "zin@example.com"),
            ),
            patch.object(
                api,
                "system_updates_payload",
                return_value={"ok": True, "readOnly": True},
            ) as read_updates,
        ):
            handler.do_GET()

        self.assertEqual(handler.status, 200)
        self.assertTrue(json.loads(handler.wfile.getvalue())["readOnly"])
        read_updates.assert_called_once_with("main")

    def test_runtime_adapter_has_no_execution_or_network_imports(self) -> None:
        path = Path(system_updates.__file__ or "")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        forbidden = {
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
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        self.assertFalse(imported & forbidden)


if __name__ == "__main__":
    unittest.main()
