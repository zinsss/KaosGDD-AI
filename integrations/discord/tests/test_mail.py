import unittest

from kaos_governor.mail import Attachment, MailMessage
from kaos_governor_discord.mail import (
    render_attachment_label,
    render_mail_summary,
    safe_attachment_filename,
    transport_attachment_filename,
)


class MailRenderingTests(unittest.TestCase):
    def test_discord_summary_uses_markdown_and_escapes_mail_content(self) -> None:
        mail = MailMessage(
            mailbox="각종공문/영덕군보건소",
            uid=3,
            sender="**Sender** @everyone <sender@example.test>",
            subject="_Notice_",
            preview="First line\nSecond line",
            attachments=(Attachment("notice.pdf", "application/pdf", b"pdf"),),
            received_at="2026-08-12 15:30 KST",
        )
        rendered = render_mail_summary(mail, 20 * 1024 * 1024)
        self.assertTrue(rendered.startswith("## Naver Mail\n**Folder** 각종공문/영덕군보건소"))
        self.assertIn("**From** \\*\\*Sender\\*\\* @\u200beveryone sender@example.test", rendered)
        self.assertIn("**Date** 2026-08-12 15:30 KST", rendered)
        self.assertIn("### \\_Notice\\_", rendered)
        self.assertIn("***Attachment:***\n- notice.pdf", rendered)
        self.assertIn("First line\nSecond line", rendered)
        self.assertNotIn("> First line", rendered)
        self.assertNotIn("Fetched read-only", rendered)
        self.assertNotIn("**Subject**", rendered)
        self.assertNotIn("@everyone", rendered)
        self.assertNotIn("**Sender**", rendered)

    def test_attachment_filename_is_reduced_to_safe_basename(self) -> None:
        attachment = Attachment("../folder/notice\n.pdf", "application/pdf", b"pdf")
        self.assertEqual(safe_attachment_filename(attachment), "notice.pdf")

    def test_korean_filename_is_visible_with_an_ascii_transport_name(self) -> None:
        attachment = Attachment("예방접종 안내문.pdf", "application/pdf", b"pdf")
        self.assertEqual(safe_attachment_filename(attachment), "예방접종 안내문.pdf")
        self.assertEqual(transport_attachment_filename(attachment), "naver-attachment.pdf")
        self.assertEqual(render_attachment_label(attachment), "**Attachment** · 예방접종 안내문.pdf")

    def test_attachment_label_escapes_markdown_and_mentions(self) -> None:
        attachment = Attachment("**notice** @everyone.pdf", "application/pdf", b"pdf")
        rendered = render_attachment_label(attachment)
        self.assertNotIn("@everyone", rendered)
        self.assertNotIn("**notice**", rendered)
        self.assertEqual(transport_attachment_filename(attachment), "notice-everyone.pdf")


if __name__ == "__main__":
    unittest.main()
