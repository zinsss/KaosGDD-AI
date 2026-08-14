import unittest

from kaos_brain.governor_tools import render_task_due_update_completed, render_task_due_update_proposal, render_tool_context
from kaos_brain.task_update_intent import TaskDueUpdateRequest
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

    def test_render_task_due_update_proposal(self) -> None:
        content = render_task_due_update_proposal(
            {"task": {"title": "Call mom", "oldDue": "2026-08-14", "oldDueTime": "10:00", "newDue": "2026-08-17", "newDueTime": "10:00"}}
        )
        self.assertIn("## Confirm task edit", content)
        self.assertIn("- task: Call mom", content)
        self.assertIn("- to: 2026-08-17 10:00", content)

    def test_render_task_due_update_completed(self) -> None:
        content = render_task_due_update_completed(
            {"task": {"title": "Call mom", "newDue": "2026-08-17", "newDueTime": "10:00"}}
        )
        self.assertEqual(content, "Task updated: Call mom -> 2026-08-17 10:00")


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

    async def test_propose_task_due_update_posts_contract(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            async def _post(self, path: str, payload: dict[str, str]):
                return {"path": path, "payload": payload}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.propose_task_due_update(
            TaskDueUpdateRequest("Call mom", "2026-08-17"),
            actor_id=994,
            idempotency_key="discord:1",
        )
        self.assertEqual(payload["path"], "/tools/tasks/update-due/proposals")
        self.assertEqual(payload["payload"]["taskTitle"], "Call mom")
        self.assertEqual(payload["payload"]["dueTime"], "10:00")


if __name__ == "__main__":
    unittest.main()
