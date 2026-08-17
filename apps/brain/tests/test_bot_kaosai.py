from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from kaos_brain.bot import BrainBot, _kaosai_planner_from_settings
from kaos_brain.config import Settings
from kaos_brain.governor_tools import GovernorToolError
from kaos_brain.kaos_ai import DisabledKaosAIPlanner, KaosAIError, OpenClawKaosAIPlanner


BASE_ENV = {
    "DISCORD_BOT_TOKEN": "not-a-real-token",
    "DISCORD_GUILD_ID": "100",
    "DISCORD_ALLOWED_USER_IDS": "200",
    "DISCORD_BRAIN_CHANNEL_ID": "300",
    "KAOSAI_ENABLED": "true",
    "KAOSAI_PROVIDER": "openclaw",
    "KAOSAI_BASE_URL": "http://127.0.0.1:18789",
    "KAOSBRAIN_GOVERNOR_TOOLS_ENABLED": "true",
    "KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL": "http://100.78.124.43:8098",
    "KAOSBRAIN_SUPPLIES_COLLECTION_ID": "supplies:abc",
    "GOVERNOR_API_TOKEN": "token",
}


class FakeKaosAI:
    def __init__(self, plan=None, error: Exception | None = None) -> None:
        self.plan_value = plan
        self.error = error
        self.calls = []

    async def plan(self, user_text: str, *, context):
        self.calls.append((user_text, context))
        if self.error is not None:
            raise self.error
        return self.plan_value


class FakeGovernorTools:
    def __init__(self) -> None:
        self.fetch_calls = []
        self.task_create_calls = []
        self.task_due_calls = []
        self.memo_create_calls = []

    async def fetch(self, request):
        self.fetch_calls.append(request)
        return {"date": "2026-08-17", "events": [], "tasks": []}

    async def propose_task_create(self, request, *, actor_id: int, idempotency_key: str):
        self.task_create_calls.append((request, actor_id, idempotency_key))
        return {
            "confirmationId": "confirm-task-create",
            "task": {"title": request.title, "due": request.due_date, "dueTime": request.due_time},
        }

    async def propose_task_due_update(self, request, *, actor_id: int, idempotency_key: str):
        self.task_due_calls.append((request, actor_id, idempotency_key))
        return {
            "confirmationId": "confirm-task-due",
            "task": {
                "title": request.task_title,
                "oldDue": "",
                "oldDueTime": "",
                "newDue": request.due_date,
                "newDueTime": request.due_time,
            },
        }

    async def propose_memo_create(self, request, *, actor_id: int, idempotency_key: str):
        self.memo_create_calls.append((request, actor_id, idempotency_key))
        return {"confirmationId": "confirm-memo-create", "memo": {"content": request.content}}


class FailingGovernorTools(FakeGovernorTools):
    async def propose_task_create(self, request, *, actor_id: int, idempotency_key: str):
        raise GovernorToolError("boom")


def fake_message() -> SimpleNamespace:
    return SimpleNamespace(
        id=777,
        author=SimpleNamespace(id=200),
        channel=SimpleNamespace(id=300),
        created_at=datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc),
    )


class BrainBotKaosAITests(unittest.IsolatedAsyncioTestCase):
    def brain(self, plan, *, governor_tools=None, error: Exception | None = None) -> BrainBot:
        bot = object.__new__(BrainBot)
        bot.settings = Settings.from_env(BASE_ENV)
        bot.kaosai = FakeKaosAI(plan, error)
        bot.governor_tools = governor_tools or FakeGovernorTools()
        return bot

    def test_kaosai_planner_factory_uses_openclaw_only_when_enabled(self) -> None:
        disabled = _kaosai_planner_from_settings(Settings.from_env({**BASE_ENV, "KAOSAI_ENABLED": "false"}))
        enabled = _kaosai_planner_from_settings(Settings.from_env(BASE_ENV))

        self.assertIsInstance(disabled, DisabledKaosAIPlanner)
        self.assertIsInstance(enabled, OpenClawKaosAIPlanner)

    async def test_kaosai_clarify_plan_returns_question_without_governor(self) -> None:
        brain = self.brain({"intent": "clarify", "scope": "personal", "parameters": {"question": "어떤 메모인가요?"}})

        reply, view = await BrainBot._answer_with_kaosai_plan(  # type: ignore[arg-type]
            brain,
            "그 메모 수정해줘",
            message=fake_message(),
        )

        self.assertEqual(reply, "어떤 메모인가요?")
        self.assertIsNone(view)
        self.assertEqual(brain.governor_tools.fetch_calls, [])

    async def test_kaosai_diagnostic_shows_plan_and_guard_without_governor_call(self) -> None:
        tools = FakeGovernorTools()
        brain = self.brain(
            {
                "intent": "task.create",
                "scope": "personal",
                "parameters": {"title": "엄마한테 전화", "dueDate": "2026-08-18"},
            },
            governor_tools=tools,
        )

        reply = await BrainBot._render_kaosai_diagnostic(  # type: ignore[arg-type]
            brain,
            "내일까지 엄마한테 전화해야돼",
            message=fake_message(),
        )

        self.assertIn("## KaosAI diagnostic", reply)
        self.assertIn('"intent": "task.create"', reply)
        self.assertIn("- guard: accepted `governor_proposal`", reply)
        self.assertIn("- execution: skipped", reply)
        self.assertEqual(tools.fetch_calls, [])
        self.assertEqual(tools.task_create_calls, [])

    async def test_kaosai_diagnostic_reports_planner_and_guard_failures(self) -> None:
        planner_failed = self.brain(None, error=KaosAIError("nope"))
        reply = await BrainBot._render_kaosai_diagnostic(  # type: ignore[arg-type]
            planner_failed,
            "hello",
            message=fake_message(),
        )
        self.assertEqual(reply, "## KaosAI diagnostic\n- planner: failed `nope`")

        guard_rejected = self.brain({"intent": "shell.run", "scope": "personal", "parameters": {"command": "id"}})
        reply = await BrainBot._render_kaosai_diagnostic(  # type: ignore[arg-type]
            guard_rejected,
            "run id",
            message=fake_message(),
        )
        self.assertIn("- guard: rejected `intent_not_allowed`", reply)

    async def test_kaosai_readonly_plan_uses_governor_tool_path(self) -> None:
        tools = FakeGovernorTools()
        brain = self.brain({"intent": "today.get", "scope": "personal", "parameters": {}}, governor_tools=tools)

        reply, view = await BrainBot._answer_with_kaosai_plan(  # type: ignore[arg-type]
            brain,
            "오늘 뭐 있어?",
            message=fake_message(),
        )

        self.assertEqual(reply, "## 2026-08-17\n- 없음")
        self.assertIsNone(view)
        self.assertEqual(len(tools.fetch_calls), 1)

    async def test_kaosai_mutation_plan_uses_guard_and_governor_proposal(self) -> None:
        tools = FakeGovernorTools()
        brain = self.brain(
            {
                "intent": "task.create",
                "scope": "personal",
                "parameters": {"title": "엄마한테 전화", "dueDate": "2026-08-18"},
            },
            governor_tools=tools,
        )

        reply, view = await BrainBot._answer_with_kaosai_plan(  # type: ignore[arg-type]
            brain,
            "내일까지 엄마한테 전화해야돼",
            message=fake_message(),
        )

        self.assertIn("## Confirm new task", reply)
        self.assertIn("- task: 엄마한테 전화", reply)
        self.assertIsNotNone(view)
        request, actor_id, idempotency_key = tools.task_create_calls[0]
        self.assertEqual(request.due_time, "10:00")
        self.assertEqual(actor_id, 200)
        self.assertEqual(idempotency_key, "discord:777")

    async def test_kaosai_supplies_plan_strips_due_before_governor(self) -> None:
        tools = FakeGovernorTools()
        brain = self.brain(
            {
                "intent": "task.create",
                "scope": "supplies",
                "parameters": {"title": "휴지", "dueDate": "2026-08-18", "dueTime": "14:00"},
            },
            governor_tools=tools,
        )

        reply, _ = await BrainBot._answer_with_kaosai_plan(  # type: ignore[arg-type]
            brain,
            "휴지 비품 추가",
            message=fake_message(),
        )

        request, _, _ = tools.task_create_calls[0]
        self.assertIn("- task: 휴지", reply)
        self.assertEqual(request.profile, "supplies")
        self.assertEqual(request.collection_id, "supplies:abc")
        self.assertEqual(request.due_date, "")
        self.assertEqual(request.due_time, "")

    async def test_kaosai_planner_or_guard_failure_falls_back(self) -> None:
        planner_failed = self.brain(None, error=KaosAIError("nope"))
        self.assertIsNone(
            await BrainBot._answer_with_kaosai_plan(  # type: ignore[arg-type]
                planner_failed,
                "hello",
                message=fake_message(),
            )
        )

        guard_rejected = self.brain({"intent": "shell.run", "scope": "personal", "parameters": {"command": "id"}})
        self.assertIsNone(
            await BrainBot._answer_with_kaosai_plan(  # type: ignore[arg-type]
                guard_rejected,
                "run id",
                message=fake_message(),
            )
        )

    async def test_governor_failure_returns_short_message(self) -> None:
        brain = self.brain(
            {
                "intent": "task.create",
                "scope": "personal",
                "parameters": {"title": "엄마한테 전화", "dueDate": "2026-08-18"},
            },
            governor_tools=FailingGovernorTools(),
        )

        reply, view = await BrainBot._answer_with_kaosai_plan(  # type: ignore[arg-type]
            brain,
            "내일까지 엄마한테 전화해야돼",
            message=fake_message(),
        )

        self.assertEqual(reply, "요청 처리 실패했어요.")
        self.assertIsNone(view)


if __name__ == "__main__":
    unittest.main()
