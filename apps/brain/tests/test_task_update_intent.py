from datetime import date
import unittest

from kaos_brain.task_update_intent import parse_task_due_update


class TaskUpdateIntentTests(unittest.TestCase):
    def test_korean_next_week_monday_update(self) -> None:
        request = parse_task_due_update("영이 큐시미아 다음주 월요일까지로 편집", today=date(2026, 8, 14))
        assert request is not None
        self.assertEqual(request.task_title, "영이 큐시미아")
        self.assertEqual(request.due_date, "2026-08-17")
        self.assertEqual(request.due_time, "10:00")

    def test_korean_tomorrow_update(self) -> None:
        request = parse_task_due_update("엄마 전화 기한 내일로 변경", today=date(2026, 8, 14))
        assert request is not None
        self.assertEqual(request.task_title, "엄마 전화")
        self.assertEqual(request.due_date, "2026-08-15")

    def test_iso_date_update(self) -> None:
        request = parse_task_due_update("보험 서류 마감일을 2026-08-20로 수정", today=date(2026, 8, 14))
        assert request is not None
        self.assertEqual(request.task_title, "보험 서류")
        self.assertEqual(request.due_date, "2026-08-20")

    def test_plain_message_does_not_update(self) -> None:
        self.assertIsNone(parse_task_due_update("오늘 뭐 있어?", today=date(2026, 8, 14)))


if __name__ == "__main__":
    unittest.main()
