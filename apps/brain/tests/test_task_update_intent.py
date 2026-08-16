from datetime import date
import unittest

from kaos_brain.task_update_intent import parse_task_action, parse_task_create, parse_task_edit, parse_task_due_update
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

    def test_korean_month_day_update_with_afternoon_time(self) -> None:
        request = parse_task_due_update("엄마 전화 8월 20일 오후 3시까지로 수정", today=date(2026, 8, 14))
        assert request is not None
        self.assertEqual(request.task_title, "엄마 전화")
        self.assertEqual(request.due_date, "2026-08-20")
        self.assertEqual(request.due_time, "15:00")

    def test_short_month_day_rolls_to_next_year_when_past(self) -> None:
        request = parse_task_due_update("보험 서류 08-01까지로 수정", today=date(2026, 8, 14))
        assert request is not None
        self.assertEqual(request.due_date, "2027-08-01")

    def test_family_task_update_sets_profile(self) -> None:
        request = parse_task_due_update("가족 엄마 전화 기한 내일로 변경", today=date(2026, 8, 14))
        assert request is not None
        self.assertEqual(request.task_title, "엄마 전화")
        self.assertEqual(request.profile, "family")

    def test_iso_date_update(self) -> None:
        request = parse_task_due_update("보험 서류 마감일을 2026-08-20로 수정", today=date(2026, 8, 14))
        assert request is not None
        self.assertEqual(request.task_title, "보험 서류")
        self.assertEqual(request.due_date, "2026-08-20")

    def test_plain_message_does_not_update(self) -> None:
        self.assertIsNone(parse_task_due_update("오늘 뭐 있어?", today=date(2026, 8, 14)))

    def test_title_edit_intent(self) -> None:
        request = parse_task_edit("엄마 전화 제목을 아빠 전화로 수정")
        assert request is not None
        self.assertEqual(request.task_title, "엄마 전화")
        self.assertEqual(request.title, "아빠 전화")
        self.assertEqual(request.memo, "")

    def test_memo_edit_intent(self) -> None:
        request = parse_task_edit("영이 큐시미아 메모를 약 남은 개수 확인으로 변경")
        assert request is not None
        self.assertEqual(request.task_title, "영이 큐시미아")
        self.assertEqual(request.title, "영이 큐시미아")
        self.assertEqual(request.memo, "약 남은 개수 확인")

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

    def test_family_task_create_sets_profile(self) -> None:
        request = parse_task_create("가족 내일까지 엄마한테 전화해야돼", today=date(2026, 8, 14))
        assert request is not None
        self.assertEqual(request.title, "엄마한테 전화")
        self.assertEqual(request.profile, "family")

    def test_explicit_task_create_without_due(self) -> None:
        request = parse_task_create("엄마 전화 할 일 추가해줘", today=date(2026, 8, 14))
        assert request is not None
        self.assertEqual(request.title, "엄마 전화")
        self.assertEqual(request.due_date, "")
        self.assertEqual(request.due_time, "")

    def test_supplies_create_without_due_date(self) -> None:
        request = parse_task_create("준비물 비누 추가해줘", today=date(2026, 8, 14))
        assert request is not None
        self.assertEqual(request.title, "비누")
        self.assertEqual(request.due_date, "")
        self.assertEqual(request.due_time, "")
        self.assertEqual(request.profile, "supplies")

    def test_iso_date_create(self) -> None:
        request = parse_task_create("2026-08-20까지 보험 서류 준비해야돼", today=date(2026, 8, 14))
        assert request is not None
        self.assertEqual(request.title, "보험 서류 준비")
        self.assertEqual(request.due_date, "2026-08-20")

    def test_korean_date_time_create(self) -> None:
        request = parse_task_create("8월 20일 오전 9시까지 보험 서류 준비해야돼", today=date(2026, 8, 14))
        assert request is not None
        self.assertEqual(request.title, "보험 서류 준비")
        self.assertEqual(request.due_date, "2026-08-20")
        self.assertEqual(request.due_time, "09:00")

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

    def test_supplies_reopen_action_sets_profile(self) -> None:
        request = parse_task_action("준비물 비누 다시 살려줘")
        assert request is not None
        self.assertEqual(request.task_title, "비누")
        self.assertEqual(request.action, "reopen")
        self.assertEqual(request.profile, "supplies")

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
