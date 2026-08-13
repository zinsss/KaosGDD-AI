import unittest
from io import BytesIO

from PIL import Image

from kaos_governor_discord.fax import faxable_attachment_name, image_to_pdf, rejection_message, safe_filename


class DiscordFaxTests(unittest.TestCase):
    def test_korean_archive_filename_is_preserved(self) -> None:
        self.assertEqual(safe_filename("../초2_문제집.pdf"), "초2_문제집.pdf")

    def test_image_attachment_name_preserves_stem_as_pdf(self) -> None:
        self.assertEqual(faxable_attachment_name("../처방전 사진.jpeg"), "처방전 사진.pdf")

    def test_image_attachment_converts_to_pdf(self) -> None:
        image = Image.new("RGBA", (40, 30), (120, 40, 80, 255))
        source = BytesIO()
        image.save(source, format="PNG")

        pdf = image_to_pdf(source.getvalue())

        self.assertTrue(pdf.startswith(b"%PDF-"))

    def test_rejection_explains_reply_contract(self) -> None:
        value = rejection_message(ValueError("reply_to_pdf_required"))
        self.assertIn("Reply directly to one PDF or image", value)


if __name__ == "__main__":
    unittest.main()
