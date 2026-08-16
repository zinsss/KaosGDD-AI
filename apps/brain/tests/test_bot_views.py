from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from kaos_brain.bot import (
    BrainDocumentSearchSelect,
    BrainDocumentSearchView,
    BrainMemoDeleteConfirmView,
    BrainMemoEditConfirmView,
    BrainMemoSearchSelect,
    BrainMemoSearchView,
)


class FakeGovernorTools:
    async def get_memo(self, name: str):
        return {"memo": {"name": name, "content": "# Rustdesk\nUse Tailscale."}}

    async def get_document(self, document_id: object):
        return {
            "document": {
                "id": document_id,
                "title": "Insurance receipt",
                "filename": "receipt.pdf",
                "correspondent": "Clinic",
            }
        }


class BrainBotViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_memo_search_select_opens_selected_memo_as_new_message(self) -> None:
        view = BrainMemoSearchView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            "rustdesk",
            [{"name": "memos/42", "snippet": "# Rustdesk", "tags": ["server"]}],
        )
        select = next(child for child in view.children if isinstance(child, BrainMemoSearchSelect))
        select._values = ["0"]
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await select.callback(interaction)  # type: ignore[arg-type]

        interaction.response.defer.assert_awaited_once()
        content = interaction.followup.send.await_args.args[0]
        self.assertEqual(content, "# Rustdesk\nUse Tailscale.")
        self.assertIn("view", interaction.followup.send.await_args.kwargs)

    async def test_document_search_select_opens_selected_document_as_new_message(self) -> None:
        view = BrainDocumentSearchView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            "보험",
            [{"id": 42, "title": "Insurance"}],
        )
        select = next(child for child in view.children if isinstance(child, BrainDocumentSearchSelect))
        select._values = ["0"]
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await select.callback(interaction)  # type: ignore[arg-type]

        interaction.response.defer.assert_awaited_once()
        content = interaction.followup.send.await_args.args[0]
        self.assertIn("## Documents search · 보험", content)
        self.assertIn("Insurance receipt", content)

    def test_memo_confirm_buttons_match_governor_labels(self) -> None:
        edit = BrainMemoEditConfirmView(FakeGovernorTools(), 200, "memos/42", "# Memo")  # type: ignore[arg-type]
        delete = BrainMemoDeleteConfirmView(FakeGovernorTools(), 200, "memos/42", "# Memo")  # type: ignore[arg-type]

        self.assertEqual([item.label for item in edit.children], ["Edit Memo", "Cancel"])
        self.assertEqual([item.label for item in delete.children], ["Delete Memo", "Cancel"])


if __name__ == "__main__":
    unittest.main()
