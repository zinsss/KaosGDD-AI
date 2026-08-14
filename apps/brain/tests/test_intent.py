import unittest

from kaos_brain.intent import Route, parse_request


class IntentTests(unittest.TestCase):
    def test_empty_message_is_ignored(self) -> None:
        self.assertIsNone(parse_request("   "))

    def test_plain_text_routes_to_chat(self) -> None:
        request = parse_request("안녕")
        assert request is not None
        self.assertEqual(request.route, Route.CHAT)
        self.assertEqual(request.text, "안녕")

    def test_deep_prefix_routes_to_deep_model(self) -> None:
        request = parse_request("deep: migration risk 정리")
        assert request is not None
        self.assertEqual(request.route, Route.DEEP)
        self.assertEqual(request.text, "migration risk 정리")

    def test_korean_deep_prefix_routes_to_deep_model(self) -> None:
        request = parse_request("생각: 오늘 할 일 우선순위")
        assert request is not None
        self.assertEqual(request.route, Route.DEEP)
        self.assertEqual(request.text, "오늘 할 일 우선순위")


if __name__ == "__main__":
    unittest.main()
