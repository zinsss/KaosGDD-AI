import unittest
from datetime import date

from kaos_brain.tool_intent import ToolKind, parse_tool_request


class ToolIntentTests(unittest.TestCase):
    def test_today_korean_request(self) -> None:
        request = parse_tool_request("오늘 뭐 있어?")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.TODAY)

    def test_today_task_request_uses_today_context(self) -> None:
        request = parse_tool_request("오늘 할 일 알려줘")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.TODAY)

    def test_today_schedule_request_uses_today_context(self) -> None:
        request = parse_tool_request("오늘 스케줄 알려줘")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.TODAY)

    def test_slash_month_day_request_uses_current_year_and_requested_day(self) -> None:
        request = parse_tool_request("8/26 보여줘", today=date(2026, 8, 26))
        assert request is not None
        self.assertEqual(request.kind, ToolKind.TODAY)
        self.assertEqual(request.start, "2026-08-26")

    def test_fullwidth_slash_month_day_request_uses_current_year_and_requested_day(self) -> None:
        request = parse_tool_request("8／26 보여줘", today=date(2026, 8, 25))
        assert request is not None
        self.assertEqual(request.kind, ToolKind.TODAY)
        self.assertEqual(request.start, "2026-08-26")

    def test_dot_month_day_request_uses_current_year_and_requested_day(self) -> None:
        request = parse_tool_request("8.26 보여줘", today=date(2026, 8, 25))
        assert request is not None
        self.assertEqual(request.kind, ToolKind.TODAY)
        self.assertEqual(request.start, "2026-08-26")

    def test_korean_month_day_request_uses_current_year_and_requested_day(self) -> None:
        request = parse_tool_request("8월 26일 보여줘", today=date(2026, 8, 25))
        assert request is not None
        self.assertEqual(request.kind, ToolKind.TODAY)
        self.assertEqual(request.start, "2026-08-26")

    def test_tomorrow_request_uses_today_context(self) -> None:
        request = parse_tool_request("내일 보여줘", today=date(2026, 8, 25))
        assert request is not None
        self.assertEqual(request.kind, ToolKind.TODAY)
        self.assertEqual(request.start, "2026-08-26")

    def test_weather_korean_request_uses_weather_context(self) -> None:
        request = parse_tool_request("지금 포항날씨는?")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.WEATHER)
        self.assertEqual(request.query, "포항")
        self.assertEqual(request.collection_id, "pohang")

    def test_weather_korean_location_sets_lookup_city(self) -> None:
        request = parse_tool_request("부산 날씨 알려줘")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.WEATHER)
        self.assertEqual(request.query, "부산")
        self.assertEqual(request.collection_id, "busan")

    def test_weather_overseas_location_sets_lookup_city(self) -> None:
        request = parse_tool_request("런던 날씨 알려줘")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.WEATHER)
        self.assertEqual(request.query, "런던")
        self.assertEqual(request.collection_id, "london")

    def test_weather_current_location_uses_default_city(self) -> None:
        request = parse_tool_request("여기 날씨는?")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.WEATHER)
        self.assertEqual(request.query, "")
        self.assertEqual(request.collection_id, "")

    def test_weather_unknown_location_is_not_treated_as_default(self) -> None:
        request = parse_tool_request("베를린 날씨 알려줘")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.WEATHER)
        self.assertEqual(request.query, "베를린")
        self.assertEqual(request.collection_id, "unsupported:베를린")

    def test_active_task_korean_request(self) -> None:
        request = parse_tool_request("뭐 해야 돼?")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.ACTIVE_TASKS)

    def test_active_task_compact_korean_request(self) -> None:
        request = parse_tool_request("내가 뭐 해야하지")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.ACTIVE_TASKS)

    def test_open_task_korean_request(self) -> None:
        request = parse_tool_request("남은 할 일 보여줘")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.ACTIVE_TASKS)

    def test_family_active_task_request_sets_profile(self) -> None:
        request = parse_tool_request("가족 할 일 보여줘")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.ACTIVE_TASKS)
        self.assertEqual(request.profile, "family")

    def test_supplies_active_request_sets_profile(self) -> None:
        request = parse_tool_request("비품 보여줘")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.ACTIVE_TASKS)
        self.assertEqual(request.profile, "supplies")

    def test_remaining_supplies_request_sets_profile(self) -> None:
        request = parse_tool_request("남은 비품 뭐야")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.ACTIVE_TASKS)
        self.assertEqual(request.profile, "supplies")

    def test_old_supplies_word_still_sets_profile(self) -> None:
        request = parse_tool_request("준비물 보여줘")
        assert request is not None
        self.assertEqual(request.profile, "supplies")

    def test_completed_task_korean_request_uses_recent_two_weeks(self) -> None:
        request = parse_tool_request("최근 2주 완료 할 일 보여줘", today=date(2026, 8, 15))
        assert request is not None
        self.assertEqual(request.kind, ToolKind.COMPLETED_TASKS)
        self.assertEqual(request.start, "2026-08-02")
        self.assertEqual(request.end, "2026-08-15")
        self.assertEqual(request.query, "")

    def test_completed_task_search_keeps_remaining_query(self) -> None:
        request = parse_tool_request("엄마 완료 할 일 찾아줘", today=date(2026, 8, 15))
        assert request is not None
        self.assertEqual(request.kind, ToolKind.COMPLETED_TASKS)
        self.assertEqual(request.query, "엄마")

    def test_family_completed_task_request_sets_profile(self) -> None:
        request = parse_tool_request("가족 완료 할 일 보여줘", today=date(2026, 8, 15))
        assert request is not None
        self.assertEqual(request.kind, ToolKind.COMPLETED_TASKS)
        self.assertEqual(request.profile, "family")
        self.assertEqual(request.query, "")

    def test_supplies_completed_task_request_sets_profile(self) -> None:
        request = parse_tool_request("비품 완료목록 보여줘", today=date(2026, 8, 15))
        assert request is not None
        self.assertEqual(request.kind, ToolKind.COMPLETED_TASKS)
        self.assertEqual(request.profile, "supplies")
        self.assertEqual(request.query, "")

    def test_memo_search_extracts_query(self) -> None:
        request = parse_tool_request("메모에서 rust desk 찾아줘")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.MEMO_SEARCH)
        self.assertEqual(request.query, "rust desk")

    def test_korean_memo_search_extracts_query(self) -> None:
        request = parse_tool_request("의무교육 메모 찾아줘")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.MEMO_SEARCH)
        self.assertEqual(request.query, "의무교육")

    def test_memo_show_extracts_query(self) -> None:
        request = parse_tool_request("rustdesk관련 메모 보여줘")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.MEMO_SEARCH)
        self.assertEqual(request.query, "rustdesk")

    def test_document_search_extracts_query(self) -> None:
        request = parse_tool_request("문서에서 보험 찾아줘")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.DOCUMENT_SEARCH)
        self.assertEqual(request.query, "보험")

    def test_document_search_keeps_multi_word_query(self) -> None:
        request = parse_tool_request("rust desk setup 문서 찾아줘")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.DOCUMENT_SEARCH)
        self.assertEqual(request.query, "rust desk setup")

    def test_dotdot_defaults_to_memo_search(self) -> None:
        request = parse_tool_request("..rust   desk setup")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.SEARCH_ALL)
        self.assertEqual(request.query, "rust desk setup")

    def test_dotdot_paperless_prefix_still_searches_everywhere(self) -> None:
        request = parse_tool_request("..paperless rust   desk setup")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.SEARCH_ALL)
        self.assertEqual(request.query, "rust desk setup")

    def test_dotdot_korean_document_prefix_still_searches_everywhere(self) -> None:
        request = parse_tool_request("..문서 보험")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.SEARCH_ALL)
        self.assertEqual(request.query, "보험")

    def test_dotdot_korean_paperless_prefix_still_searches_everywhere(self) -> None:
        request = parse_tool_request("..페이퍼리스 보험")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.SEARCH_ALL)
        self.assertEqual(request.query, "보험")

    def test_dotdot_memo_prefix_still_searches_everywhere(self) -> None:
        request = parse_tool_request("..메모 의무교육")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.SEARCH_ALL)
        self.assertEqual(request.query, "의무교육")

    def test_mutation_words_do_not_trigger_readonly_tool_lookup(self) -> None:
        self.assertIsNone(parse_tool_request("엄마 전화 할 일 추가해줘"))
        self.assertIsNone(parse_tool_request("영이 큐시미아 다음주 월요일까지로 수정"))

    def test_plain_chat_does_not_trigger_tool(self) -> None:
        self.assertIsNone(parse_tool_request("안녕"))


if __name__ == "__main__":
    unittest.main()
