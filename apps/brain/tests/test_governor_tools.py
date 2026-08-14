import unittest

from kaos_brain.governor_tools import render_tool_context
from kaos_brain.tool_intent import ToolKind, ToolRequest


class GovernorToolRenderingTests(unittest.TestCase):
    def test_render_today_context(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.TODAY),
            {
                "date": "2026-08-14",
                "weather": {"summary": "⛅️ 23-28℃"},
                "events": [{"title": "Clinic", "time": "10:00", "ownerLabel": "GDD_ZiN"}],
                "tasks": [{"title": "Call mom", "due": "2026-08-14", "dueTime": "10:00"}],
            },
        )
        self.assertIn("Today: 2026-08-14", context)
        self.assertIn("Weather: ⛅️ 23-28℃", context)
        self.assertIn("- 10:00 Clinic (GDD_ZiN)", context)
        self.assertIn("- Call mom - 2026-08-14 10:00", context)

    def test_render_empty_tasks_context(self) -> None:
        context = render_tool_context(ToolRequest(ToolKind.ACTIVE_TASKS), {"tasks": []})
        self.assertEqual(context, "Active tasks: none")


class GovernorToolClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_builds_today_route(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            async def _get(self, path: str, params: dict[str, str]):
                return {"path": path, "params": params}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.fetch(ToolRequest(ToolKind.TODAY))
        self.assertEqual(payload["path"], "/tools/today")
        self.assertEqual(payload["params"], {"profile": "main"})


if __name__ == "__main__":
    unittest.main()
