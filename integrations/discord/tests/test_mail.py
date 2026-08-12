import unittest

from kaos_governor.mail import Attachment, MailMessage
from kaos_governor_discord.mail import render_mail_summary, safe_attachment_filename


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
        self.assertIn("## Naver Mail", rendered)
        self.assertIn("**Folder**", rendered)
        self.assertIn("> First line", rendered)
        self.assertIn("- Attachment: notice.pdf", rendered)
        self.assertNotIn("@everyone", rendered)
        self.assertNotIn("**Sender**", rendered)

    def test_attachment_filename_is_reduced_to_safe_basename(self) -> None:
        attachment = Attachment("../folder/notice\n.pdf", "application/pdf", b"pdf")
        self.assertEqual(safe_attachment_filename(attachment), "notice.pdf")


if __name__ == "__main__":
    unittest.main()
