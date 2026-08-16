import unittest

from kaos_brain.memo_intent import parse_memo_create, parse_memo_delete, parse_memo_edit


class MemoIntentTests(unittest.TestCase):
    def test_prefix_colon_create(self) -> None:
        request = parse_memo_create("메모해줘: 러스트데스크 설정은 100.94.208.16")
        assert request is not None
        self.assertEqual(request.content, "러스트데스크 설정은 100.94.208.16")

    def test_prefix_space_create(self) -> None:
        request = parse_memo_create("기록해줘 병원 와이파이 비밀번호 확인")
        assert request is not None
        self.assertEqual(request.content, "병원 와이파이 비밀번호 확인")

    def test_suffix_create(self) -> None:
        request = parse_memo_create("러스트데스크 설정은 100.94.208.16 메모에 저장해줘")
        assert request is not None
        self.assertEqual(request.content, "러스트데스크 설정은 100.94.208.16")

    def test_search_like_message_does_not_create(self) -> None:
        self.assertIsNone(parse_memo_create("메모에서 rustdesk 찾아줘"))

    def test_delete_memo_suffix(self) -> None:
        request = parse_memo_delete("러스트데스크 메모 삭제해줘")
        assert request is not None
        self.assertEqual(request.query, "러스트데스크")

    def test_delete_memo_status_suffix(self) -> None:
        request = parse_memo_delete("러스트데스크 메모 삭제했어요")
        assert request is not None
        self.assertEqual(request.query, "러스트데스크")

    def test_delete_memo_prefix(self) -> None:
        request = parse_memo_delete("메모 rustdesk 지워줘")
        assert request is not None
        self.assertEqual(request.query, "rustdesk")

    def test_task_delete_does_not_parse_as_memo_delete(self) -> None:
        self.assertIsNone(parse_memo_delete("러스트데스크 삭제해줘"))

    def test_edit_memo_with_colon_grammar(self) -> None:
        request = parse_memo_edit("메모 rustdesk 수정:\n# Rustdesk\nUse Tailscale.")
        assert request is not None
        self.assertEqual(request.query, "rustdesk")
        self.assertEqual(request.content, "# Rustdesk\nUse Tailscale.")

    def test_edit_memo_with_natural_suffix(self) -> None:
        request = parse_memo_edit("러스트데스크 메모를 새 설정으로 수정해줘")
        assert request is not None
        self.assertEqual(request.query, "러스트데스크")
        self.assertEqual(request.content, "새 설정")

    def test_edit_memo_requires_memo_word(self) -> None:
        self.assertIsNone(parse_memo_edit("rustdesk 수정: 새 설정"))

    def test_status_announcements_do_not_become_memo_commands(self) -> None:
        for content in (
            "메모 저장했어요",
            "메모를 새로 저장했어요",
            "메모 삭제했어요",
            "메모 수정했어요",
        ):
            with self.subTest(content=content):
                self.assertIsNone(parse_memo_create(content))
                self.assertIsNone(parse_memo_delete(content))
                self.assertIsNone(parse_memo_edit(content))


if __name__ == "__main__":
    unittest.main()
