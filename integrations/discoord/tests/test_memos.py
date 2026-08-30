from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from kaos_governor import GovernorOperations, MemoryDurableGovernorStore
from kaos_governor.memos import Memo, MemoMutationService, MemoSearchPage, MemoSearchResult
from kaosdiscoord.access import AccessPolicy
from kaosdiscoord.memos import (
    DiscordMemosCapture,
    MemosEditModal,
    MemosMoreView,
    MemosCreatePromptView,
    MemosDeletedView,
    MemosDeleteConfirmView,
    MemosOpenedView,
    MemosSearchSelect,
    MemosSearchView,
    memo_option_description,
    memo_option_label,
    parse_create_memo_message,
    render_memo_deleted,
    render_memo_opened,
)


class FakeMemos:
    def __init__(self) -> None:
        self.created = []
        self.updated = []
        self.deleted = []
        self.gets = []
        self.searches = []
        self.config = SimpleNamespace(max_results=20)
        self.memos = {}

    def create(self, content):
        self.created.append(content)
        memo = Memo("memos/42", content, ("태그",), "created", "updated", "PRIVATE", False)
        self.memos[memo.name] = memo
        return memo

    def update(self, name, content):
        self.updated.append((name, content))
        memo = Memo(name, content, ("태그",), "created", "updated2", "PRIVATE", False)
        self.memos[memo.name] = memo
        return memo

    def delete(self, name):
        self.deleted.append(name)
        self.memos.pop(name, None)
        return None

    def get(self, name):
        self.gets.append(name)
        return self.memos[name]

    def search(self, query, tags, limit):
        self.searches.append((query, tags, limit))
        content = "# Rustdesk Settings\n## For Tailscale\n- Relay server: 100.94.208.16\n@everyone"
        memo = Memo("memos/99", content, ("office",), "created", "updated", "PRIVATE", False)
        return [MemoSearchResult(memo, "Rustdesk Settings")]

    def search_page(self, query, tags, limit):
        self.searches.append((query, tags, limit))
        first = Memo(
            "memos/99",
            "# Rustdesk Settings\n## For Tailscale\n- Relay server: 100.94.208.16\n@everyone",
            ("office",),
            "created",
            "updated",
            "PRIVATE",
            False,
        )
        second = Memo(
            "memos/100",
            "## Rustdesk LAN\n- API server: blank",
            ("office",),
            "created",
            "updated",
            "PRIVATE",
            False,
        )
        return MemoSearchPage(
            query,
            (),
            (MemoSearchResult(first, "Rustdesk Settings"), MemoSearchResult(second, "Rustdesk LAN")),
            13,
            213,
        )


class FakeChannel:
    def __init__(self) -> None:
        self.id = 300
        self.sent = []

    async def send(self, *args, **kwargs):
        message = SimpleNamespace(id=900 + len(self.sent), delete=AsyncMock())
        self.sent.append((args, kwargs))
        return message


class DiscordMemosCaptureTests(unittest.IsolatedAsyncioTestCase):
    def make_message(self, content: str, *, channel_id: int = 300):
        channel = FakeChannel()
        channel.id = channel_id
        message = SimpleNamespace(
            id=500,
            content=content,
            guild=SimpleNamespace(id=100),
            channel=channel,
            author=SimpleNamespace(id=200, bot=False),
            delete=AsyncMock(),
            reply=AsyncMock(),
        )
        return message

    async def test_plain_message_is_deleted_without_creating_memo(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            confirmation_delete_after=1,
        )
        message = self.make_message("메모 내용\n#태그")

        handled = await capture.handle_message(message)  # type: ignore[arg-type]

        self.assertTrue(handled)
        self.assertEqual(service.created, [])
        message.delete.assert_awaited_once()
        self.assertEqual(message.channel.sent, [])
        self.assertEqual(capture.status()["acceptedCount"], 0)

    async def test_triple_plus_message_creates_memo_then_deletes_original(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            confirmation_delete_after=1,
        )
        message = self.make_message("+++\n### 메모 내용\n#태그")

        handled = await capture.handle_message(message)  # type: ignore[arg-type]

        self.assertTrue(handled)
        self.assertEqual(service.created, ["### 메모 내용\n#태그"])
        message.delete.assert_awaited_once()
        self.assertEqual(message.channel.sent[0][0], ("Saved to Memos: memos/42",))
        self.assertEqual(message.channel.sent[0][1]["delete_after"], 1)
        self.assertEqual(capture.status()["acceptedCount"], 1)

    async def test_direct_create_uses_governed_actor_and_durable_fingerprint(self) -> None:
        service = FakeMemos()
        store = MemoryDurableGovernorStore()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            operations=GovernorOperations(store),
            memo_mutations=MemoMutationService(service),  # type: ignore[arg-type]
        )

        memo = await capture.create_memo(
            "private body",
            actor_id="200",
            idempotency_key="discord-message:500",
        )

        self.assertEqual(memo.name, "memos/42")
        self.assertEqual(service.created, ["private body"])
        audit = store.audit_records()
        operation = store.get_operation(audit[0].operation_id)
        assert operation is not None
        self.assertEqual(operation.actor.actor_id, "200")
        self.assertEqual(operation.actor.scope, "personal")
        self.assertEqual(operation.tool_name, "memos")
        self.assertEqual(operation.operation_type, "create")
        self.assertEqual(operation.status, "completed")
        self.assertNotIn("content", operation.parameters)
        self.assertEqual(operation.parameters["contentFingerprint"]["bytes"], 12)
        self.assertEqual([record.outcome for record in audit], ["accepted", "completed"])

    async def test_direct_create_replay_does_not_repeat_memos_write(self) -> None:
        service = FakeMemos()
        store = MemoryDurableGovernorStore()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            operations=GovernorOperations(store),
            memo_mutations=MemoMutationService(service),  # type: ignore[arg-type]
        )

        first = await capture.create_memo(
            "private body",
            actor_id="200",
            idempotency_key="discord-message:500",
        )
        replay = await capture.create_memo(
            "private body",
            actor_id="200",
            idempotency_key="discord-message:500",
        )

        self.assertEqual(first.name, replay.name)
        self.assertEqual(service.created, ["private body"])
        self.assertEqual(service.gets, ["memos/42"])
        self.assertEqual(len(store.audit_records()), 2)

    async def test_direct_edit_and_delete_use_governed_operations(self) -> None:
        service = FakeMemos()
        original = service.create("# Original")
        service.created.clear()
        store = MemoryDurableGovernorStore()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            operations=GovernorOperations(store),
            memo_mutations=MemoMutationService(service),  # type: ignore[arg-type]
        )

        updated = await capture.update_memo(
            original.name,
            "# Updated",
            actor_id="200",
            idempotency_key="discord-interaction:501",
        )
        await capture.delete_memo(
            original.name,
            actor_id="200",
            idempotency_key="discord-interaction:502",
        )

        self.assertEqual(updated.content, "# Updated")
        self.assertEqual(service.updated, [("memos/42", "# Updated")])
        self.assertEqual(service.deleted, ["memos/42"])
        operation_ids = list(dict.fromkeys(record.operation_id for record in store.audit_records()))
        operations = [store.get_operation(operation_id) for operation_id in operation_ids]
        self.assertEqual(
            [operation.operation_type for operation in operations if operation],
            ["edit", "delete"],
        )
        self.assertTrue(
            all("content" not in operation.parameters for operation in operations if operation)
        )
        self.assertEqual(
            [record.outcome for record in store.audit_records()],
            ["accepted", "completed", "accepted", "completed"],
        )

    async def test_triple_plus_only_posts_modal_button_prompt(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )
        message = self.make_message("+++")

        handled = await capture.handle_message(message)  # type: ignore[arg-type]

        self.assertTrue(handled)
        self.assertEqual(service.created, [])
        message.delete.assert_awaited_once()
        self.assertEqual(message.channel.sent[0][0], ("## Memos\n- Add memo",))
        self.assertIsInstance(message.channel.sent[0][1]["view"], MemosCreatePromptView)

    async def test_dotdot_message_searches_memos_then_deletes_original(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            search_result_delete_after=0,
        )
        message = self.make_message("..printer")

        handled = await capture.handle_message(message)  # type: ignore[arg-type]

        self.assertTrue(handled)
        self.assertEqual(service.created, [])
        self.assertEqual(service.searches, [("printer", None, 20)])
        message.delete.assert_awaited_once()
        content = message.channel.sent[0][0][0]
        self.assertIn("Searched..", content)
        self.assertIn("## printer", content)
        self.assertIn("13 results in 213 memos", content)
        self.assertIn("view", message.channel.sent[0][1])

    async def test_multi_result_search_message_is_temporary(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            search_result_delete_after=1800,
        )
        message = self.make_message("..printer")

        self.assertTrue(await capture.handle_message(message))  # type: ignore[arg-type]

        self.assertEqual(capture.status()["searchResultDeleteAfterSeconds"], 1800)
        self.assertEqual(capture._temporary_search_messages, {900})

    async def test_opened_single_search_result_is_not_temporary(self) -> None:
        class OneResultMemos(FakeMemos):
            def search_page(self, query, tags, limit):
                self.searches.append((query, tags, limit))
                memo = Memo("memos/99", "# Rustdesk Settings", (), "created", "updated", "PRIVATE", False)
                return MemoSearchPage(query, (), (MemoSearchResult(memo, "Rustdesk Settings"),), 1, 213)

        service = OneResultMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            search_result_delete_after=1800,
        )
        message = self.make_message("..rustdesk")

        self.assertTrue(await capture.handle_message(message))  # type: ignore[arg-type]

        self.assertEqual(capture._temporary_search_messages, set())

    async def test_single_search_result_opens_with_close_and_more_buttons(self) -> None:
        class OneResultMemos(FakeMemos):
            def search_page(self, query, tags, limit):
                self.searches.append((query, tags, limit))
                memo = Memo("memos/99", "# Rustdesk Settings", (), "created", "updated", "PRIVATE", False)
                return MemoSearchPage(query, (), (MemoSearchResult(memo, "Rustdesk Settings"),), 1, 213)

        service = OneResultMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            search_result_delete_after=0,
        )
        message = self.make_message("..rustdesk")

        self.assertTrue(await capture.handle_message(message))  # type: ignore[arg-type]

        view = message.channel.sent[0][1]["view"]
        self.assertIsInstance(view, MemosOpenedView)
        self.assertEqual([item.label for item in view.children], ["Close", "More..."])

    def test_search_dropdown_uses_title_and_tags_only(self) -> None:
        memo = Memo(
            "memos/99",
            "# Rustdesk Settings\n## For Tailscale\n- Relay server: 100.94.208.16",
            ("server", "rustdesk"),
            "",
            "",
            "PRIVATE",
            False,
        )
        result = MemoSearchResult(memo, "Relay server: 100.94.208.16")

        self.assertEqual(memo_option_label(result), "Rustdesk Settings")
        self.assertEqual(memo_option_description(result), "#server, #rustdesk")

    async def test_dotdot_message_normalizes_multi_term_memos_search(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )
        message = self.make_message("..rust   desk setup")

        self.assertTrue(await capture.handle_message(message))  # type: ignore[arg-type]

        self.assertEqual(service.searches, [("rust desk setup", None, 20)])
        content = message.channel.sent[0][0][0]
        self.assertIn("## rust desk setup", content)

    async def test_other_channels_are_ignored(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )

        self.assertFalse(await capture.handle_message(self.make_message("memo", channel_id=301)))  # type: ignore[arg-type]
        self.assertEqual(service.created, [])

    def test_opened_memo_renders_body_as_markdown_and_escapes_mentions(self) -> None:
        memo = Memo(
            "memos/99",
            "# Rustdesk Settings\n## For Tailscale\n- Relay server: 100.94.208.16\n@everyone",
            (),
            "",
            "",
            "PRIVATE",
            False,
        )
        content = render_memo_opened("rustdesk", MemoSearchResult(memo, "Rustdesk Settings"))

        self.assertIn("# Rustdesk Settings\n## For Tailscale", content)
        self.assertIn("- Relay server: 100.94.208.16", content)
        self.assertIn("@\u200beveryone", content)

    async def test_search_select_opens_selected_memo_as_new_message(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )
        page = service.search_page("rustdesk", None, 20)
        select = MemosSearchSelect(page, capture)
        select._values = ["1"]
        interaction = SimpleNamespace(
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
            message=SimpleNamespace(id=900, delete=AsyncMock()),
        )
        capture._temporary_search_messages.add(900)

        await select.callback(interaction)  # type: ignore[arg-type]

        interaction.response.defer.assert_awaited_once()
        content = interaction.followup.send.await_args.kwargs["content"]
        self.assertIn("## Rustdesk LAN", content)
        self.assertIsInstance(interaction.followup.send.await_args.kwargs["view"], MemosOpenedView)
        interaction.message.delete.assert_awaited_once()
        self.assertEqual(capture._temporary_search_messages, set())

    async def test_search_view_clears_controls_on_timeout(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )
        page = service.search_page("rustdesk", None, 20)
        view = MemosSearchView(page, capture)
        message = SimpleNamespace(id=901, edit=AsyncMock())
        view.bind_message(message)  # type: ignore[arg-type]

        await view.on_timeout()

        message.edit.assert_awaited_once()

    async def test_opened_memo_more_button_reveals_edit_and_delete_buttons(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )
        memo = Memo("memos/99", "# Memo", (), "created", "updated", "PRIVATE", False)
        view = MemosOpenedView(capture, "memo", memo)
        interaction = SimpleNamespace(
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(edit_message=AsyncMock()),
        )

        await view.children[1].callback(interaction)  # type: ignore[arg-type,union-attr]

        more_view = interaction.response.edit_message.await_args.kwargs["view"]
        self.assertIsInstance(more_view, MemosMoreView)
        self.assertEqual([item.label for item in more_view.children], ["Close", "Edit", "Delete"])

    async def test_opened_memo_delete_flow_marks_message_deleted_with_undo(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )
        memo = Memo("memos/99", "# Memo", (), "created", "updated", "PRIVATE", False)
        view = MemosDeleteConfirmView(capture, "memo", memo)
        message = SimpleNamespace(edit=AsyncMock())
        interaction = SimpleNamespace(
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
            message=message,
        )

        await view.children[1].callback(interaction)  # type: ignore[arg-type,union-attr]

        self.assertEqual(service.deleted, ["memos/99"])
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        content = message.edit.await_args.kwargs["content"]
        self.assertIn("# Memo", content)
        self.assertIn("Deleted at ", content)
        self.assertIsInstance(message.edit.await_args.kwargs["view"], MemosDeletedView)

    async def test_opened_memo_edit_button_asks_for_confirmation(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )
        memo = Memo("memos/99", "# Memo\nBody", (), "created", "updated", "PRIVATE", False)
        view = MemosMoreView(capture, "memo", memo)
        interaction = SimpleNamespace(
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(edit_message=AsyncMock()),
        )

        await view.children[1].callback(interaction)  # type: ignore[arg-type,union-attr]

        confirm_view = interaction.response.edit_message.await_args.kwargs["view"]
        self.assertEqual([item.label for item in confirm_view.children], ["Cancel", "Edit Memo"])

    async def test_edit_confirm_button_opens_prefilled_modal(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )
        memo = Memo("memos/99", "# Memo\nBody", (), "created", "updated", "PRIVATE", False)
        more_view = MemosMoreView(capture, "memo", memo)
        confirm_interaction = SimpleNamespace(
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(edit_message=AsyncMock()),
        )
        await more_view.children[1].callback(confirm_interaction)  # type: ignore[arg-type,union-attr]
        confirm_view = confirm_interaction.response.edit_message.await_args.kwargs["view"]
        modal_interaction = SimpleNamespace(
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(send_modal=AsyncMock()),
        )

        await confirm_view.children[1].callback(modal_interaction)  # type: ignore[arg-type,union-attr]

        modal = modal_interaction.response.send_modal.await_args.args[0]
        self.assertIsInstance(modal, MemosEditModal)
        self.assertEqual(modal.content.default, "# Memo\nBody")

    async def test_deleted_memo_undo_recreates_memo_and_restores_message(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )
        memo = Memo("memos/99", "# Memo", (), "created", "updated", "PRIVATE", False)
        view = MemosDeletedView(capture, "memo", memo)
        message = SimpleNamespace(edit=AsyncMock())
        interaction = SimpleNamespace(
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
            message=message,
        )

        await view.children[0].callback(interaction)  # type: ignore[arg-type,union-attr]

        self.assertEqual(service.created, ["# Memo"])
        self.assertIn("# Memo", message.edit.await_args.kwargs["content"])
        self.assertIsInstance(message.edit.await_args.kwargs["view"], MemosOpenedView)

    def test_deleted_memo_renders_original_content_and_timestamp(self) -> None:
        memo = Memo("memos/99", "# Memo\nBody", (), "created", "updated", "PRIVATE", False)

        content = render_memo_deleted(memo)

        self.assertIn("# Memo\nBody", content)
        self.assertIn("Deleted at ", content)

    async def test_update_memo_uses_service_contract(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )

        memo = await capture.update_memo("memos/99", "# Updated")

        self.assertEqual(memo.content, "# Updated")
        self.assertEqual(service.updated, [("memos/99", "# Updated")])
        self.assertEqual(capture.last_error, "")

    def test_parse_create_memo_message_requires_triple_plus_marker(self) -> None:
        self.assertEqual(parse_create_memo_message("+++"), "")
        self.assertEqual(parse_create_memo_message("+++\n# Title\nBody"), "# Title\nBody")
        self.assertEqual(parse_create_memo_message("  +++  \n# Title"), "# Title")
        self.assertIsNone(parse_create_memo_message("plain memo"))
        self.assertIsNone(parse_create_memo_message("+++ # Title"))


if __name__ == "__main__":
    unittest.main()
