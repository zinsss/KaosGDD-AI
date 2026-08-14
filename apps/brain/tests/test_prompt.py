import unittest

from kaos_brain.intent import Route
from kaos_brain.prompt import ROUTER_SYSTEM_PROMPT, system_prompt


class PromptTests(unittest.TestCase):
    def test_chat_prompt_preserves_authority_boundary(self) -> None:
        prompt = system_prompt(Route.CHAT)
        self.assertIn("not the source of truth", prompt)
        self.assertIn("Do not emit JSON tool calls", prompt)

    def test_deep_prompt_is_advisory(self) -> None:
        prompt = system_prompt(Route.DEEP)
        self.assertIn("advisory only", prompt)
        self.assertIn("suitable for Discord", prompt)

    def test_router_prompt_only_allows_route_words(self) -> None:
        self.assertIn("answer or deep", ROUTER_SYSTEM_PROMPT)
        self.assertIn("Do not emit JSON", ROUTER_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
