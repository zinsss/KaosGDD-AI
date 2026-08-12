import unittest

from kaos_governor_discord.fax import rejection_message, safe_filename


class DiscordFaxTests(unittest.TestCase):
    def test_korean_archive_filename_is_preserved(self) -> None:
        self.assertEqual(safe_filename("../초2_문제집.pdf"), "초2_문제집.pdf")

    def test_rejection_explains_reply_contract(self) -> None:
        value = rejection_message(ValueError("reply_to_pdf_required"))
        self.assertIn("Reply directly to one PDF", value)


if __name__ == "__main__":
    unittest.main()
