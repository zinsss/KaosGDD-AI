from datetime import date
import unittest

from kaos_brain.task_update_intent import parse_task_action, parse_task_create, parse_task_due_update
from kaos_brain.event_intent import parse_event_create


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

    def test_korean_tomorrow_create(self) -> None:
        request = parse_task_create("내일까지 엄마한테 전화해야돼", today=date(2026, 8, 14))
        assert request is not None
        self.assertEqual(request.title, "엄마한테 전화")
        self.assertEqual(request.due_date, "2026-08-15")
        self.assertEqual(request.due_time, "10:00")

    def test_korean_next_week_create(self) -> None:
        request = parse_task_create("다음주 월요일까지 영이 큐시미아 확인해야돼", today=date(2026, 8, 14))
        assert request is not None
        self.assertEqual(request.title, "영이 큐시미아 확인")
        self.assertEqual(request.due_date, "2026-08-17")

    def test_iso_date_create(self) -> None:
        request = parse_task_create("2026-08-20까지 보험 서류 준비해야돼", today=date(2026, 8, 14))
        assert request is not None
        self.assertEqual(request.title, "보험 서류 준비")
        self.assertEqual(request.due_date, "2026-08-20")

    def test_plain_message_does_not_create(self) -> None:
        self.assertIsNone(parse_task_create("내일 뭐 있어?", today=date(2026, 8, 14)))

    def test_korean_complete_action(self) -> None:
        request = parse_task_action("엄마 전화 완료")
        assert request is not None
        self.assertEqual(request.task_title, "엄마 전화")
        self.assertEqual(request.action, "complete")

    def test_korean_finished_action(self) -> None:
        request = parse_task_action("영이 큐시미아 끝냈어")
        assert request is not None
        self.assertEqual(request.task_title, "영이 큐시미아")
        self.assertEqual(request.action, "complete")

    def test_korean_delete_action(self) -> None:
        request = parse_task_action("보험 서류 삭제해줘")
        assert request is not None
        self.assertEqual(request.task_title, "보험 서류")
        self.assertEqual(request.action, "delete")

    def test_korean_reopen_action(self) -> None:
        request = parse_task_action("엄마 전화 완료 취소해줘")
        assert request is not None
        self.assertEqual(request.task_title, "엄마 전화")
        self.assertEqual(request.action, "reopen")

    def test_korean_reopen_action_with_restore_word(self) -> None:
        request = parse_task_action("영이 큐시미아 다시 살려줘")
        assert request is not None
        self.assertEqual(request.task_title, "영이 큐시미아")
        self.assertEqual(request.action, "reopen")

    def test_plain_message_does_not_action(self) -> None:
        self.assertIsNone(parse_task_action("오늘 뭐 있어?"))

    def test_korean_family_all_day_event_create(self) -> None:
        request = parse_event_create("08-15 엔소쿠료칸 종일일정으로 가족에 추가. 메모: 포항 조사리", today=date(2026, 8, 15))
        assert request is not None
        self.assertEqual(request.title, "엔소쿠료칸")
        self.assertEqual(request.start_date, "2026-08-15")
        self.assertEqual(request.end_date, "2026-08-15")
        self.assertTrue(request.all_day)
        self.assertEqual(request.profile, "family")
        self.assertEqual(request.memo, "포항 조사리")

    def test_event_create_rejects_invalid_date(self) -> None:
        self.assertIsNone(parse_event_create("13-40 이상한 일정으로 가족에 추가", today=date(2026, 8, 15)))


if __name__ == "__main__":
    unittest.main()
