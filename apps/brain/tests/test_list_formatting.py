import unittest

from kaos_brain.list_formatting import page_status_label, page_window, range_summary


class ListFormattingTests(unittest.TestCase):
    def test_range_summary_uses_shared_list_shape(self) -> None:
        self.assertEqual(range_summary(1, 10, 26), "<1-10 of 26>")
        self.assertEqual(range_summary(11, 6, 26), "<11-16 of 26>")

    def test_range_summary_handles_empty_lists(self) -> None:
        self.assertEqual(range_summary(0, 0, 0), "<0 of 0>")
        self.assertEqual(range_summary(1, 0, 26), "<0 of 0>")

    def test_page_window_clamps_and_reports_page_state(self) -> None:
        window = page_window(list(range(26)), page=9, page_size=10)

        self.assertEqual(window.items, [20, 21, 22, 23, 24, 25])
        self.assertEqual(window.range_label, "<21-26 of 26>")
        self.assertEqual(window.page_label, "Page 3/3")

    def test_page_status_label_never_reports_zero_pages(self) -> None:
        self.assertEqual(page_status_label(0, 0), "Page 1/1")


if __name__ == "__main__":
    unittest.main()
