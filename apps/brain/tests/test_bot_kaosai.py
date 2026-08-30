from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from kaos_brain.bot import BrainBot, _kaosai_planner_from_settings, _message_kst_date, parse_document_tag_suggestion
from kaos_brain.config import Settings
from kaos_brain.governor_tools import GovernorToolError
from kaos_brain.kaos_ai import DisabledKaosAIPlanner, KaosAIError, OpenClawKaosAIPlanner
from kaos_brain.tool_intent import ToolKind


BASE_ENV = {
    "DISCORD_BOT_TOKEN": "not-a-real-token",
    "DISCORD_GUILD_ID": "100",
    "DISCORD_ALLOWED_USER_IDS": "200",
    "DISCORD_BRAIN_CHANNEL_ID": "300",
    "KAOSAI_ENABLED": "true",
    "KAOSAI_PROVIDER": "openclaw",
    "KAOSAI_BASE_URL": "http://127.0.0.1:18789",
    "KAOSAI_API_TOKEN": "gateway-token",
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
        self.document_tag_calls = []
        self.document_tags = ("Clinic", "receipt")

    async def plan(self, user_text: str, *, context):
        self.calls.append((user_text, context))
        if self.error is not None:
            raise self.error
        if isinstance(self.plan_value, list):
            return self.plan_value.pop(0) if self.plan_value else None
        return self.plan_value

    async def suggest_document_tags(self, context):
        self.document_tag_calls.append(context)
        if self.error is not None:
            raise self.error
        return self.document_tags


class FakeGovernorTools:
    def __init__(self) -> None:
        self.fetch_calls = []
        self.task_create_calls = []
        self.task_due_calls = []
        self.event_create_calls = []
        self.memo_create_calls = []
        self.document_tag_context_calls = []
        self.document_tag_calls = []

    async def fetch(self, request):
        self.fetch_calls.append(request)
        return {"date": request.start or "2026-08-17", "events": [], "tasks": []}

    async def propose_task_create(self, request, *, actor_id: int, idempotency_key: str):
        self.task_create_calls.append((request, actor_id, idempotency_key))
        return {
            "confirmationId": "confirm-task-create",
            "task": {
                "title": request.title,
                "memo": request.memo,
                "due": request.due_date,
                "dueTime": request.due_time,
                "profile": request.profile,
                "collectionId": request.collection_id,
            },
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

    async def propose_event_create(self, request, *, actor_id: int, idempotency_key: str):
        self.event_create_calls.append((request, actor_id, idempotency_key))
        return {
            "confirmationId": "confirm-event-create",
            "event": {
                "title": request.title,
                "startDate": request.start_date,
                "endDate": request.end_date,
                "allDay": request.all_day,
                "memo": request.memo,
                "profile": request.profile,
            },
        }

    async def propose_memo_create(self, request, *, actor_id: int, idempotency_key: str):
        self.memo_create_calls.append((request, actor_id, idempotency_key))
        return {"confirmationId": "confirm-memo-create", "memo": {"content": request.content}}

    async def get_document_tag_context(self, document_id):
        self.document_tag_context_calls.append(document_id)
        return {
            "document": {"id": int(document_id), "title": "Receipt", "contentExcerpt": "Clinic receipt"},
            "availableTags": [{"id": 1, "name": "Clinic"}, {"id": 2, "name": "receipt"}],
        }

    async def propose_document_tags(self, request, *, actor_id: int, idempotency_key: str):
        self.document_tag_calls.append((request, actor_id, idempotency_key))
        return {"confirmationId": "confirm-document-tags", "document": {"title": "Receipt", "tags": list(request.tags)}}


class FailingGovernorTools(FakeGovernorTools):
    async def propose_task_create(self, request, *, actor_id: int, idempotency_key: str):
        raise GovernorToolError("boom")


class FakeReauth:
    def __init__(self) -> None:
        self.start_calls = 0
        self.callback_calls = []

    async def start(self):
        self.start_calls += 1
        return {"status": "waiting_for_callback", "oauthUrl": "https://auth.openai.com/oauth/authorize?state=test"}

    async def submit_callback(self, callback):
        self.callback_calls.append(callback)
        return {"status": "succeeded"}


def fake_message() -> SimpleNamespace:
    return SimpleNamespace(
        id=777,
        author=SimpleNamespace(id=200),
        channel=SimpleNamespace(id=300),
        created_at=datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc),
    )


class FakeTyping:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, traceback):
        return None


def fake_discord_message(content: str) -> SimpleNamespace:
    message = fake_message()
    message.content = content
    message.guild = SimpleNamespace(id=100)
    message.author.bot = False
    message.mentions = []
    message.channel.typing = lambda: FakeTyping()
    message.channel.send = AsyncMock()
    message.delete = AsyncMock()
    message.reply = AsyncMock()
    return message


class BrainBotKaosAITests(unittest.IsolatedAsyncioTestCase):
    def brain(self, plan, *, governor_tools=None, error: Exception | None = None, env=None) -> BrainBot:
        bot = object.__new__(BrainBot)
        bot.settings = Settings.from_env({**BASE_ENV, **(env or {})})
        bot.kaosai = FakeKaosAI(plan, error)
        bot.governor_tools = governor_tools or FakeGovernorTools()
        bot.reauth = None
        bot._connection = SimpleNamespace(user=None)
        return bot

    def test_kaosai_planner_factory_uses_openclaw_only_when_enabled(self) -> None:
        disabled = _kaosai_planner_from_settings(Settings.from_env({**BASE_ENV, "KAOSAI_ENABLED": "false"}))
        enabled = _kaosai_planner_from_settings(Settings.from_env(BASE_ENV))

        self.assertIsInstance(disabled, DisabledKaosAIPlanner)
        self.assertIsInstance(enabled, OpenClawKaosAIPlanner)

    def test_parse_document_tag_suggestion_requires_explicit_tag_request(self) -> None:
        self.assertEqual(parse_document_tag_suggestion("문서 42 태그 추천"), "42")
        self.assertEqual(parse_document_tag_suggestion("document 42 tag suggest"), "42")
        self.assertEqual(parse_document_tag_suggestion("문서 42 보여줘"), "")

    async def test_document_tag_suggestion_uses_ai_context_then_governor_confirmation(self) -> None:
        governor_tools = FakeGovernorTools()
        brain = self.brain(None, governor_tools=governor_tools)
        message = fake_discord_message("문서 42 태그 추천")

        await BrainBot.on_message(brain, message)  # type: ignore[arg-type]

        self.assertEqual(governor_tools.document_tag_context_calls, ["42"])
        self.assertEqual(brain.kaosai.document_tag_calls[0]["document"]["title"], "Receipt")
        request, actor_id, idempotency_key = governor_tools.document_tag_calls[0]
        self.assertEqual(request.document_id, "42")
        self.assertEqual(request.tags, ("Clinic", "receipt"))
        self.assertEqual(actor_id, 200)
        self.assertEqual(idempotency_key, "discord:777:document-tags")
        self.assertIn("## Confirm document tags", message.reply.await_args.args[0])

    async def test_kaosai_reauth_command_starts_local_agent(self) -> None:
        brain = self.brain(None)
        brain.reauth = FakeReauth()
        message = fake_discord_message("ai:reauth")

        await BrainBot.on_message(brain, message)  # type: ignore[arg-type]

        self.assertEqual(brain.reauth.start_calls, 1)
        reply = message.reply.await_args.args[0]
        self.assertIn("## KaosAI login renewal", reply)
        self.assertIn("https://auth.openai.com/oauth/authorize", reply)

    async def test_rrr_command_reposts_active_control_message(self) -> None:
        brain = self.brain(None)
        brain._reload_active_control_from_message = AsyncMock()  # type: ignore[method-assign]
        message = fake_discord_message("/rrr")

        await BrainBot.on_message(brain, message)  # type: ignore[arg-type]

        brain._reload_active_control_from_message.assert_awaited_once_with(message)
        self.assertEqual(brain.kaosai.calls, [])
        message.reply.assert_not_awaited()

    async def test_dotdot_search_bypasses_kaosai_and_searches_governor_tools(self) -> None:
        tools = FakeGovernorTools()
        brain = self.brain({"intent": "clarify", "parameters": {"question": "무엇을 찾을까요?"}}, governor_tools=tools)
        message = fake_discord_message("..통관")

        await BrainBot.on_message(brain, message)  # type: ignore[arg-type]

        self.assertEqual(brain.kaosai.calls, [])
        self.assertEqual([request.kind for request in tools.fetch_calls], [ToolKind.MEMO_SEARCH, ToolKind.DOCUMENT_SEARCH])
        self.assertTrue(all(request.query == "통관" for request in tools.fetch_calls))
        self.assertIn("Searched..\n## 통관", message.reply.await_args.args[0])

    async def test_kaosai_reauth_callback_is_deleted_and_submitted(self) -> None:
        brain = self.brain(None)
        brain.reauth = FakeReauth()
        callback = "http://localhost:1455/auth/callback?code=ac_secret.value&state=test"
        message = fake_discord_message(callback)

        await BrainBot.on_message(brain, message)  # type: ignore[arg-type]

        message.delete.assert_awaited_once()
        self.assertEqual(brain.reauth.callback_calls, [callback])
        self.assertEqual(message.channel.send.await_args.args[0], "KaosAI login renewed.")
        self.assertIn("allowed_mentions", message.channel.send.await_args.kwargs)

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

    async def test_event_date_clarification_answer_creates_event(self) -> None:
        tools = FakeGovernorTools()
        brain = self.brain(
            [{"intent": "clarify", "scope": "personal", "parameters": {"question": "미영샘 월차 일정을 등록할 날짜가 언제인가요?"}}],
            governor_tools=tools,
            env={"KAOSAI_CHAT_ENABLED": "true"},
        )
        first = fake_discord_message("일정, 미영샘 월차")
        second = fake_discord_message("오늘")
        second.id = 778

        await BrainBot.on_message(brain, first)  # type: ignore[arg-type]
        await BrainBot.on_message(brain, second)  # type: ignore[arg-type]

        self.assertIn("날짜가 언제", first.reply.await_args.args[0])
        self.assertEqual(brain.kaosai.calls, [])
        request, actor_id, idempotency_key = tools.event_create_calls[0]
        self.assertEqual(request.title, "미영샘 월차")
        self.assertEqual(request.start_date, "2026-08-17")
        self.assertTrue(request.all_day)
        self.assertEqual(actor_id, 200)
        self.assertEqual(idempotency_key, "discord:778")
        self.assertIn("Confirm new event", second.reply.await_args.args[0])
        self.assertIn("- calendar: 𝘎𝘋𝘋𝙕𝘪𝙉", second.reply.await_args.args[0])

    async def test_kaosai_diagnostic_shows_plan_and_guard_without_governor_call(self) -> None:
        tools = FakeGovernorTools()
        brain = self.brain(
            {
                "intent": "task.create",
                "scope": "personal",
                "parameters": {"title": "엄마한테 전화", "memo": "병원 끝나고", "dueDate": "2026-08-18"},
            },
            governor_tools=tools,
        )

        reply = await BrainBot._render_kaosai_diagnostic(  # type: ignore[arg-type]
            brain,
            "내일까지 엄마한테 전화해야돼",
            message=fake_message(),
        )

        self.assertIn("## KaosAI plan", reply)
        self.assertIn("intent: task.create", reply)
        self.assertIn("kind: governor_proposal", reply)
        self.assertIn("confirmation: required", reply)
        self.assertIn("- title: 엄마한테 전화", reply)
        self.assertIn("- due: 2026-08-18 10:00", reply)
        self.assertIn("- execution: skipped", reply)
        self.assertNotIn("```json", reply)
        self.assertEqual(tools.fetch_calls, [])
        self.assertEqual(tools.task_create_calls, [])

    async def test_kaosai_dry_run_intercepts_chat_before_governor_proposal(self) -> None:
        tools = FakeGovernorTools()
        brain = self.brain(
            {
                "intent": "task.create",
                "scope": "personal",
                "parameters": {"title": "엄마한테 전화", "memo": "병원 끝나고", "dueDate": "2026-08-18"},
            },
            governor_tools=tools,
            env={"KAOSAI_DRY_RUN_ENABLED": "true"},
        )
        message = fake_discord_message("내일까지 엄마한테 전화해야돼")

        await BrainBot.on_message(brain, message)  # type: ignore[arg-type]

        message.reply.assert_awaited_once()
        reply = message.reply.await_args.args[0]
        self.assertIn("## KaosAI plan", reply)
        self.assertIn("intent: task.create", reply)
        self.assertIn("- execution: skipped", reply)
        self.assertEqual(tools.task_create_calls, [])
        self.assertEqual(tools.task_due_calls, [])

    async def test_reported_korean_make_task_uses_create_not_active_list(self) -> None:
        tools = FakeGovernorTools()
        brain = self.brain(None, governor_tools=tools)
        message = fake_discord_message("전염병신고 할일 만들어줘")

        await BrainBot.on_message(brain, message)  # type: ignore[arg-type]

        request, actor_id, idempotency_key = tools.task_create_calls[0]
        self.assertEqual(request.title, "전염병신고")
        self.assertEqual(request.due_date, "")
        self.assertEqual(actor_id, 200)
        self.assertEqual(idempotency_key, "discord:777")
        self.assertEqual(tools.fetch_calls, [])
        self.assertIn("Confirm New Task", message.reply.await_args.args[0])

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
        self.assertIn("## KaosAI rejected", reply)
        self.assertIn("reason: `intent_not_allowed`", reply)
        self.assertIn("intent: shell.run", reply)
        self.assertIn("- execution: skipped", reply)
        self.assertNotIn("command", reply)

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

    async def test_kaosai_today_plan_preserves_requested_date(self) -> None:
        tools = FakeGovernorTools()
        brain = self.brain(
            {"intent": "today.get", "scope": "personal", "parameters": {"date": "2026-08-26"}},
            governor_tools=tools,
        )

        reply, view = await BrainBot._answer_with_kaosai_plan(  # type: ignore[arg-type]
            brain,
            "8/26 보여줘",
            message=fake_message(),
        )

        self.assertEqual(reply, "## 2026-08-26\n- 없음")
        self.assertIsNone(view)
        self.assertEqual(tools.fetch_calls[0].start, "2026-08-26")

    def test_message_kst_date_treats_naive_discord_time_as_utc(self) -> None:
        message = fake_message()
        message.created_at = datetime(2026, 8, 25, 15, 3)

        self.assertEqual(_message_kst_date(message).isoformat(), "2026-08-26")

    async def test_kaosai_mutation_plan_uses_guard_and_governor_proposal(self) -> None:
        tools = FakeGovernorTools()
        brain = self.brain(
            {
                "intent": "task.create",
                "scope": "personal",
                "parameters": {"title": "엄마한테 전화", "memo": "병원 끝나고", "dueDate": "2026-08-18"},
            },
            governor_tools=tools,
        )

        reply, view = await BrainBot._answer_with_kaosai_plan(  # type: ignore[arg-type]
            brain,
            "내일까지 엄마한테 전화해야돼",
            message=fake_message(),
        )

        self.assertIn("Confirm New Task", reply)
        self.assertIn("## 엄마한테 전화", reply)
        self.assertIn("- due: 2026-08-18 10:00", reply)
        self.assertIn("- memo: 병원 끝나고", reply)
        self.assertIsNotNone(view)
        request, actor_id, idempotency_key = tools.task_create_calls[0]
        self.assertEqual(request.memo, "병원 끝나고")
        self.assertEqual(request.due_time, "10:00")
        self.assertEqual(actor_id, 200)
        self.assertEqual(idempotency_key, "discord:777")

    async def test_kaosai_family_task_plan_shows_family_list(self) -> None:
        tools = FakeGovernorTools()
        brain = self.brain(
            {
                "intent": "task.create",
                "scope": "family",
                "parameters": {"title": "로운이 준비물", "dueDate": "2026-08-26"},
            },
            governor_tools=tools,
        )

        reply, view = await BrainBot._answer_with_kaosai_plan(  # type: ignore[arg-type]
            brain,
            "가족 할일 로운이 준비물",
            message=fake_message(),
        )

        self.assertIn("Confirm New Task", reply)
        self.assertIn("- list: 𝘧𝘢𝘮𝘪𝘭𝘺", reply)
        self.assertIsNotNone(view)
        request, _, _ = tools.task_create_calls[0]
        self.assertEqual(request.profile, "family")

    async def test_kaosai_supplies_plan_strips_due_before_governor(self) -> None:
        tools = FakeGovernorTools()
        brain = self.brain(
            {
                "intent": "task.create",
                "scope": "supplies",
                "parameters": {"title": "휴지", "memo": "코스트코", "dueDate": "2026-08-18", "dueTime": "14:00"},
            },
            governor_tools=tools,
        )

        reply, _ = await BrainBot._answer_with_kaosai_plan(  # type: ignore[arg-type]
            brain,
            "휴지 비품 추가",
            message=fake_message(),
        )

        request, _, _ = tools.task_create_calls[0]
        self.assertIn("Confirm New Supply", reply)
        self.assertIn("## 휴지", reply)
        self.assertIn("- memo: 코스트코", reply)
        self.assertNotIn("- task: 휴지", reply)
        self.assertNotIn("- due:", reply)
        self.assertEqual(request.profile, "supplies")
        self.assertEqual(request.memo, "코스트코")
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
