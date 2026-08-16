from types import SimpleNamespace
import unittest

from kaos_brain.bot import BrainBot
from kaos_brain.governor_tools import GovernorToolError
from kaos_brain.tool_intent import ToolKind, ToolRequest


class FailingGovernorTools:
    async def fetch(self, request: ToolRequest):
        raise GovernorToolError("upstream exploded with details")


class BrainToolResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_governor_tools_uses_short_korean_message(self) -> None:
        brain = SimpleNamespace(governor_tools=None)

        reply, view = await BrainBot._answer_with_governor_tool(  # type: ignore[arg-type]
            brain,
            "오늘 뭐 있어?",
            ToolRequest(ToolKind.TODAY),
            actor_id=200,
        )

        self.assertEqual(reply, "Governor 연결이 아직 없어요.")
        self.assertIsNone(view)

    async def test_governor_tool_failure_hides_internal_error_details(self) -> None:
        brain = SimpleNamespace(governor_tools=FailingGovernorTools())

        with self.assertLogs("kaos_brain.bot", level="WARNING"):
            reply, view = await BrainBot._answer_with_governor_tool(  # type: ignore[arg-type]
                brain,
                "오늘 뭐 있어?",
                ToolRequest(ToolKind.TODAY),
                actor_id=200,
            )

        self.assertEqual(reply, "조회 실패했어요.")
        self.assertNotIn("upstream exploded", reply)
        self.assertIsNone(view)


if __name__ == "__main__":
    unittest.main()
