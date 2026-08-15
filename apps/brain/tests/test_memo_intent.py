import unittest

from kaos_brain.memo_intent import parse_memo_create


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


if __name__ == "__main__":
    unittest.main()
