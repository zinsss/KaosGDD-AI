import unittest

from kaosdiscoord.markdown import (
    MarkdownField,
    MarkdownMessage,
    MarkdownMessageTooLong,
    escape_text,
)


class MarkdownMessageTests(unittest.TestCase):
    def test_renders_discord_markdown_structure(self) -> None:
        message = MarkdownMessage(
            title="Fax received",
            summary="A new document is ready.",
            fields=(MarkdownField("From", "054-123-4567"),),
            bullets=("2 pages", "PDF archived"),
            quote="Line one\nLine two",
            footer="KaosGovernor",
        ).render()
        self.assertIn("## Fax received", message)
        self.assertIn("**From**", message)
        self.assertIn("- 2 pages", message)
        self.assertIn("> Line one", message)
        self.assertIn("-# KaosGovernor", message)

    def test_escapes_dynamic_markdown_and_mentions(self) -> None:
        escaped = escape_text("**urgent** @everyone")
        self.assertNotIn("**urgent**", escaped)
        self.assertNotIn("@everyone", escaped)

    def test_rejects_messages_over_discord_limit(self) -> None:
        with self.assertRaises(MarkdownMessageTooLong):
            MarkdownMessage(title="Long", summary="x" * 2_000).render()


if __name__ == "__main__":
    unittest.main()
