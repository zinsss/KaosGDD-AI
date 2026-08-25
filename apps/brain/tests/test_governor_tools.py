import unittest

from kaos_brain.governor_tools import (
    DocumentTagRequest,
    FAMILY_EVENT_MARKER,
    FAMILY_EVENT_SUFFIX,
    PERSONAL_EVENT_MARKER,
    document_display_title,
    document_public_url,
    memo_option_label,
    render_event_create_completed,
    render_event_create_proposal,
    render_memo_create_completed,
    render_memo_delete_completed,
    render_memo_deleted,
    render_memo_edit_completed,
    memo_option_description,
    memo_public_url,
    render_memo_opened,
    render_document_opened,
    render_document_tags_completed,
    render_document_tags_proposal,
    render_task_action_completed,
    render_task_create_completed,
    render_task_create_proposal,
    render_task_edit_completed,
    render_task_edit_proposal,
    render_task_due_update_completed,
    render_task_due_update_proposal,
    render_tool_context,
    TaskEditRequest,
)
from kaos_brain.event_intent import EventCreateRequest
from kaos_brain.task_update_intent import TaskActionRequest, TaskCreateRequest, TaskDueUpdateRequest
from kaos_brain.tool_intent import ToolKind, ToolRequest


class GovernorToolRenderingTests(unittest.TestCase):
    def test_event_markers_are_saved(self) -> None:
        self.assertEqual(PERSONAL_EVENT_MARKER, "𝘎𝘋𝘋𝙕𝘪𝙉")
        self.assertEqual(FAMILY_EVENT_MARKER, "𝘧𝘢𝘮𝘪𝘭𝘺")
        self.assertEqual(FAMILY_EVENT_SUFFIX, "  • 𝘧𝘢𝘮𝘪𝘭𝘺")

    def test_render_today_context(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.TODAY),
            {
                "date": "2026-08-14",
                "weather": {"summary": "⛅️ 23-28℃"},
                "events": [
                    {"title": "Clinic", "time": "10:00", "ownerLabel": "GDD_ZiN"},
                    {"title": "School", "time": "15:00", "ownerLabel": "Family"},
                ],
                "tasks": [{"title": "Call mom", "due": "2026-08-14", "dueTime": "10:00"}],
            },
        )
        self.assertIn("## 2026-08-14 · ⛅️ 23-28℃", context)
        self.assertIn("### 일정", context)
        self.assertIn("- 10:00 Clinic", context)
        self.assertIn("- 15:00 School  • 𝘧𝘢𝘮𝘪𝘭𝘺", context)
        self.assertNotIn("GDD_ZiN", context)
        self.assertIn("### 할 일", context)
        self.assertIn("- Call mom - 2026-08-14 10:00", context)

    def test_render_empty_today_context(self) -> None:
        context = render_tool_context(ToolRequest(ToolKind.TODAY), {"date": "2026-08-14", "events": [], "tasks": []})
        self.assertEqual(context, "## 2026-08-14\n- 없음")

    def test_render_weather_context(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.WEATHER, "포항"),
            {
                "date": "2026-08-14",
                "weather": {
                    "summary": "⛅️ 23-28℃",
                    "condition": "cloudy",
                    "precipitationProbability": 70,
                    "precipitationMm": 2.5,
                    "humidityPercent": 81,
                    "windSpeedKmh": 13.2,
                    "dayparts": [
                        {
                            "label": "Morning",
                            "glyph": "🌧️",
                            "minTemp": 23,
                            "maxTemp": 25,
                            "precipitationProbability": 80,
                            "precipitationMm": 1.2,
                            "humidityPercent": 88,
                            "windSpeedKmh": 11,
                        }
                    ],
                },
            },
        )
        self.assertEqual(
            context,
            "## 포항 날씨 • 2026-08-14\n"
            "- ⛅️ 23-28℃\n"
            "- 강수확률 70% · 강수량 2.5mm · 바람 13.2km/h\n"
            "### 시간대\n"
            "- 오전 🌧️ 23-25℃\n"
            "· 강수확률 80% · 강수량 1.2mm · 습도 88% · 바람 11km/h",
        )

    def test_render_empty_tasks_context(self) -> None:
        context = render_tool_context(ToolRequest(ToolKind.ACTIVE_TASKS), {"tasks": []})
        self.assertEqual(context, "## 할 일\n- 없음")

    def test_render_supplies_context_uses_scope_title_and_omits_empty_due(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="supplies"),
            {"profile": "supplies", "tasks": [{"title": "Soap"}]},
        )
        self.assertEqual(context, "## 비품\n- Soap")

    def test_render_completed_tasks_context(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.COMPLETED_TASKS, start="2026-08-02", end="2026-08-15"),
            {
                "from": "2026-08-02",
                "to": "2026-08-15",
                "tasks": [{"title": "Call mom", "completedDate": "2026-08-15"}],
            },
        )
        self.assertIn("## 완료한 할 일 · 2026-08-02 ~ 2026-08-15", context)
        self.assertIn("- Call mom - 2026-08-15", context)

    def test_render_empty_completed_supplies_context(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.COMPLETED_TASKS, profile="supplies", start="2026-08-02", end="2026-08-15"),
            {"profile": "supplies", "from": "2026-08-02", "to": "2026-08-15", "tasks": []},
        )
        self.assertEqual(context, "## 완료한 비품 · 2026-08-02 ~ 2026-08-15\n- 없음")

    def test_render_completed_supplies_context_omits_dates(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.COMPLETED_TASKS, profile="supplies", start="2026-08-02", end="2026-08-15"),
            {
                "profile": "supplies",
                "from": "2026-08-02",
                "to": "2026-08-15",
                "tasks": [{"title": "Soap", "completedDate": "2026-08-15"}],
            },
        )

        self.assertIn("## 완료한 비품 · 2026-08-02 ~ 2026-08-15", context)
        self.assertIn("- Soap", context)
        self.assertNotIn("- 2026-08-15", context)

    def test_render_family_tasks_context_uses_scope_title(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="family"),
            {"profile": "family", "tasks": [{"title": "Call mom", "due": "2026-08-17", "dueTime": "10:00"}]},
        )
        self.assertEqual(context, "## 가족 할 일\n- Call mom - 2026-08-17 10:00")

    def test_render_single_full_memo_context(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.MEMO_SEARCH, "rustdesk"),
            {
                "query": "rustdesk",
                "count": 1,
                "results": [{"name": "memos/42", "content": "# Rustdesk\nUse Tailscale.", "full": True}],
            },
        )
        self.assertIn("Searched..\n## rustdesk\n1 results in 1 memos", context)
        self.assertIn("### Rustdesk\n# Rustdesk\nUse Tailscale.", context)

    def test_render_multiple_memos_context_lists_titles(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.MEMO_SEARCH, "training"),
            {
                "query": "training",
                "resultCount": 2,
                "totalCount": 213,
                "results": [
                    {"name": "memos/1", "snippet": "# Online training\nID and password details " * 20, "tags": ["training"]},
                    {"name": "memos/2", "snippet": "Long mandatory training list " * 20, "tags": ["work"]},
                ],
            },
        )
        self.assertIn("Searched..\n## training\n2 results in 213 memos", context)
        self.assertIn("### Memos", context)
        self.assertIn("1. Online training", context)
        self.assertIn("2. Long mandatory training list", context)
        self.assertNotIn("#training", context)
        self.assertNotIn("#work", context)
        self.assertNotIn("Memos search:", context)

    def test_memo_option_description_stays_within_discord_limit(self) -> None:
        description = memo_option_description({"snippet": "x" * 200})
        self.assertLessEqual(len(description), 100)

    def test_memo_option_description_uses_no_tags_placeholder(self) -> None:
        self.assertEqual(memo_option_description({"snippet": "# Training note"}), "No tags")

    def test_memo_dropdown_uses_title_and_tags(self) -> None:
        item = {
            "name": "memos/abc",
            "snippet": "# Training note\nsecret body",
            "tags": ["education", "work"],
        }
        self.assertEqual(memo_option_label(item), "Training note")
        self.assertEqual(memo_option_description(item), "#education, #work")

    def test_memo_dropdown_prefers_search_payload_title(self) -> None:
        item = {
            "name": "memos/abc",
            "title": "Online training ID/PW",
            "snippet": "matched body text without the heading",
            "tags": ["education", "work"],
        }

        self.assertEqual(memo_option_label(item), "Online training ID/PW")
        self.assertEqual(memo_option_description(item), "#education, #work")

    def test_memo_dropdown_title_ignores_flattened_body_and_tags(self) -> None:
        item = {
            "name": "memos/abc",
            "title": "온라인 의무교육 ID/PW ## 미영샘 * GSEEK * pheco@example.com #의무교육",
            "snippet": "온라인 의무교육 ID/PW ## 미영샘 * GSEEK * pheco@example.com #의무교육",
            "tags": ["의무교육", "아이디", "직원"],
        }

        self.assertEqual(memo_option_label(item), "온라인 의무교육 ID/PW")
        self.assertEqual(memo_option_description(item), "#의무교육, #아이디, #직원")

    def test_memo_dropdown_title_ignores_flattened_bullet_body(self) -> None:
        item = {
            "name": "memos/abc",
            "title": "영해 선한 가정의학과의원 기본정보 * 사업자 등록 번호: 454-92-00293 * 주소: 경북 영덕군",
            "snippet": "영해 선한 가정의학과의원 기본정보 * 사업자 등록 번호: 454-92-00293 * 주소: 경북 영덕군",
            "tags": ["영해선한가정의학과", "기본정보", "YHSHFM"],
        }

        self.assertEqual(memo_option_label(item), "영해 선한 가정의학과의원 기본정보")
        self.assertEqual(memo_option_description(item), "#영해선한가정의학과, #기본정보, #YHSHFM")

    def test_memo_dropdown_prefers_h1_over_payload_title(self) -> None:
        item = {
            "name": "memos/abc",
            "title": "Fallback title",
            "snippet": "# H1 memo title\nmatched body text",
            "tags": ["education"],
        }

        self.assertEqual(memo_option_label(item), "H1 memo title")
        self.assertEqual(memo_option_description(item), "#education")

    def test_memo_dropdown_can_use_checklist_line_as_title(self) -> None:
        item = {"name": "memos/abc", "snippet": "- [ ] 마샬 스피커 2개"}

        self.assertEqual(memo_option_label(item), "마샬 스피커 2개")

    def test_render_opened_memo_uses_original_markdown(self) -> None:
        content = render_memo_opened(
            "training",
            {
                "name": "memos/abc",
                "content": "# Training note\n\n## Person\n\n- GSEEK\n  - user@example.com\n  - password",
                "tags": ["education"],
            },
        )
        self.assertEqual(
            content,
            "# Training note\n\n## Person\n\n- GSEEK\n  - user@example.com\n  - password",
        )

    def test_render_opened_memo_escapes_mentions(self) -> None:
        content = render_memo_opened("training", {"name": "memos/abc", "content": "# Training\n@everyone\n<@123>"})

        self.assertIn("@\u200beveryone", content)
        self.assertIn("<@\u200b123>", content)

    def test_render_deleted_memo_keeps_original_content(self) -> None:
        content = render_memo_deleted("# Training note\n\nBody", "2026-08-15 16:30 KST")
        self.assertEqual(content, "# Training note\n\nBody\n\nDeleted at 2026-08-15 16:30 KST")

    def test_memo_public_url_uses_memo_id(self) -> None:
        self.assertEqual(memo_public_url("https://memos.example", "memos/abc"), "https://memos.example/m/abc")
        self.assertEqual(memo_public_url("", "memos/abc"), "")

    def test_document_public_url_uses_document_id(self) -> None:
        self.assertEqual(
            document_public_url("https://paperless.example/", "42"),
            "https://paperless.example/documents/42/details",
        )
        self.assertEqual(document_public_url("", "42"), "")
        self.assertEqual(document_public_url("https://paperless.example", "bad"), "")

    def test_render_single_full_document_context(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.DOCUMENT_SEARCH, "rustdesk"),
            {
                "query": "rustdesk",
                "resultCount": 1,
                "totalCount": 12,
                "results": [
                    {
                        "id": 42,
                        "title": "Rustdesk setup",
                        "created": "2026-08-14T12:00:00Z",
                        "filename": "rustdesk.pdf",
                        "correspondent": "Clinic",
                        "full": True,
                    }
                ],
            },
        )
        self.assertIn("Searched..\n## rustdesk\n1 results in 12 documents", context)
        self.assertIn("Page 1 / 1", context)
        self.assertIn("- Rustdesk setup", context)
        self.assertNotIn("rustdesk.pdf", context)

    def test_render_opened_document_uses_title_as_header(self) -> None:
        content = render_document_opened(
            "insurance",
            {
                "id": 42,
                "title": "Insurance receipt",
                "created": "2026-08-14T12:00:00Z",
                "filename": "receipt.pdf",
                "correspondent": "Clinic",
                "url": "https://paperless.example/documents/42/details",
                "tags": ["medical", {"name": "receipt"}],
            },
        )

        self.assertEqual(
            content,
            "## Insurance receipt\n- #medical #receipt\n- document no `42`",
        )

    def test_document_display_title_uses_filename_only_as_fallback(self) -> None:
        self.assertEqual(document_display_title({"title": "보험 영수증", "filename": "scan.pdf"}), "보험 영수증")
        self.assertEqual(document_display_title({"filename": "scan.pdf"}), "scan.pdf")

    def test_render_document_tags_proposal_shows_ignored_ai_tags(self) -> None:
        content = render_document_tags_proposal(
            {
                "document": {"title": "Insurance receipt", "tags": ["medical", "receipt"]},
                "ignoredTags": ["made-up"],
            }
        )

        self.assertIn("## Confirm document tags", content)
        self.assertIn("- document: Insurance receipt", content)
        self.assertIn("- tags: #medical, #receipt", content)
        self.assertIn("- ignored: #made-up", content)
        self.assertEqual(render_document_tags_completed({}), "문서 태그 수정했어요.")

    def test_render_multiple_documents_context_uses_compact_summary(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.DOCUMENT_SEARCH, "insurance"),
            {
                "query": "insurance",
                "resultCount": 13,
                "totalCount": 213,
                "results": [
                    {
                        "id": 42,
                        "title": "Insurance receipt",
                        "created": "2026-08-14T12:00:00Z",
                        "filename": "receipt.pdf",
                        "correspondent": "Clinic",
                        "url": "https://paperless.example/documents/42/details",
                    },
                    {
                        "id": 43,
                        "title": "Insurance form",
                        "created": "2026-08-15T12:00:00Z",
                        "filename": "form.pdf",
                        "correspondent": "Clinic",
                    },
                ],
            },
        )
        self.assertIn("Searched..\n## insurance\n13 results in 213 documents", context)
        self.assertIn("Page 1 / 7", context)
        self.assertIn("- Insurance receipt", context)
        self.assertNotIn("[open]", context)
        self.assertIn("- Insurance form", context)
        self.assertNotIn("### Insurance receipt", context)
        self.assertNotIn("Document search:", context)

    def test_render_task_due_update_proposal(self) -> None:
        content = render_task_due_update_proposal(
            {"task": {"title": "Call mom", "oldDue": "2026-08-14", "oldDueTime": "10:00", "newDue": "2026-08-17", "newDueTime": "10:00"}}
        )
        self.assertIn("## Confirm task edit", content)
        self.assertIn("- task: Call mom", content)
        self.assertIn("- to: 2026-08-17 10:00", content)

    def test_render_task_due_update_completed(self) -> None:
        content = render_task_due_update_completed(
            {"task": {"title": "Call mom", "newDue": "2026-08-17", "newDueTime": "10:00"}}
        )
        self.assertEqual(content, "할 일 수정했어요.")

    def test_render_task_edit_proposal(self) -> None:
        content = render_task_edit_proposal(
            {
                "task": {
                    "oldTitle": "Call mom",
                    "title": "Call dad",
                    "oldDue": "2026-08-17",
                    "oldDueTime": "10:00",
                    "due": "2026-08-20",
                    "dueTime": "14:30",
                }
            }
        )

        self.assertIn("## Confirm task edit", content)
        self.assertIn("- from: Call mom", content)
        self.assertIn("- to: Call dad", content)
        self.assertIn("- due: 2026-08-17 10:00 -> 2026-08-20 14:30", content)

    def test_render_task_edit_completed(self) -> None:
        self.assertEqual(render_task_edit_completed({"task": {"title": "Call dad"}}), "할 일 수정했어요.")

    def test_render_task_create_completed(self) -> None:
        content = render_task_create_completed(
            {"task": {"title": "Call school", "due": "2026-08-17", "dueTime": "10:00"}}
        )
        self.assertEqual(content, "Task added.")

    def test_render_supplies_task_create_proposal_uses_supply_label(self) -> None:
        content = render_task_create_proposal(
            {"task": {"title": "토프라민", "profile": "supplies", "collectionId": "supplies:abc"}}
        )

        self.assertEqual(content, "Confirm New Supply\n## 토프라민")
        self.assertNotIn("New Task", content)
        self.assertNotIn("- task:", content)
        self.assertNotIn("- due:", content)

    def test_render_task_create_proposal_uses_title_headline_and_optional_due(self) -> None:
        content = render_task_create_proposal(
            {"task": {"title": "엄마한테 전화", "memo": "병원 끝나고", "due": "2026-08-18", "dueTime": "10:00"}}
        )

        self.assertEqual(content, "Confirm New Task\n## 엄마한테 전화\n- due: 2026-08-18 10:00\n- memo: 병원 끝나고")

    def test_render_supplies_task_completed_messages_use_supplies_label(self) -> None:
        payload = {"task": {"title": "Soap", "collectionId": "supplies:main"}}

        self.assertEqual(render_task_create_completed(payload), "Supply added.")
        self.assertEqual(render_task_edit_completed(payload), "비품 수정했어요.")
        self.assertEqual(render_task_action_completed({"task": {**payload["task"], "action": "delete"}}), "비품 삭제했어요.")
        self.assertEqual(render_task_action_completed({"task": {**payload["task"], "action": "complete"}}), "Soap을 구매했어요.")
        self.assertEqual(render_task_action_completed({"task": {**payload["task"], "action": "reopen"}}), "비품 다시 열었어요.")

    def test_render_task_complete_completed_uses_task_title(self) -> None:
        content = render_task_action_completed({"task": {"title": "Call school", "action": "complete"}})
        self.assertEqual(content, "Call school을 완료했어요.")

    def test_render_task_delete_completed(self) -> None:
        content = render_task_action_completed({"task": {"title": "Call school", "action": "delete"}})
        self.assertEqual(content, "할 일 삭제했어요.")

    def test_render_task_reopen_completed(self) -> None:
        content = render_task_action_completed({"task": {"title": "Call school", "action": "reopen"}})
        self.assertEqual(content, "할 일 다시 열었어요.")

    def test_render_event_create_messages(self) -> None:
        proposal = render_event_create_proposal(
            {
                "event": {
                    "title": "엔소쿠료칸",
                    "startDate": "2026-08-15",
                    "allDay": True,
                    "memo": "포항 조사리",
                }
            }
        )
        self.assertIn("## Confirm new event", proposal)
        self.assertIn("- event: 엔소쿠료칸", proposal)
        self.assertIn("- date: 2026-08-15", proposal)
        self.assertIn("- memo: 포항 조사리", proposal)
        self.assertEqual(render_event_create_completed({"event": {"uid": "EVENT-1"}}), "일정 저장했어요.")

    def test_render_memo_completion_messages(self) -> None:
        self.assertEqual(
            render_memo_create_completed({"memo": {"name": "memos/42"}}),
            "메모 저장했어요.",
        )
        self.assertEqual(
            render_memo_delete_completed({"memo": {"name": "memos/42"}}),
            "메모 삭제했어요.",
        )
        self.assertEqual(
            render_memo_edit_completed({"memo": {"name": "memos/42"}}),
            "메모 수정했어요.",
        )


class GovernorToolClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_builds_today_route(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            async def _get(self, path: str, params: dict[str, str]):
                return {"path": path, "params": params}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.fetch(ToolRequest(ToolKind.TODAY))
        self.assertEqual(payload["path"], "/tools/today")
        self.assertEqual(payload["params"], {"profile": "main"})

        dated_payload = await client.fetch(ToolRequest(ToolKind.TODAY, start="2026-08-26"))
        self.assertEqual(dated_payload["path"], "/tools/today")
        self.assertEqual(dated_payload["params"], {"profile": "main", "date": "2026-08-26"})

        weather = await client.fetch(ToolRequest(ToolKind.WEATHER, "부산", collection_id="busan"))
        self.assertEqual(weather["path"], "/tools/today")
        self.assertEqual(weather["params"], {"profile": "main", "city": "busan"})

        unsupported_weather = await client.fetch(ToolRequest(ToolKind.WEATHER, "베를린", collection_id="unsupported:베를린"))
        self.assertEqual(unsupported_weather["weatherLocationUnsupported"], "베를린")
        self.assertIn("부산", unsupported_weather["supportedWeatherLocations"])
        self.assertIn("런던", unsupported_weather["supportedWeatherLocations"])

        target_day = await client.today(day="2026-08-22")
        self.assertEqual(target_day["path"], "/tools/today")
        self.assertEqual(target_day["params"], {"profile": "main", "date": "2026-08-22"})

        week = await client.calendar_week(start="2026-08-22")
        self.assertEqual(week["path"], "/tools/calendar/week")
        self.assertEqual(week["params"], {"profile": "main", "days": "7", "date": "2026-08-22"})

        upcoming = await client.fetch(ToolRequest(ToolKind.UPCOMING_EVENTS))
        self.assertEqual(upcoming["path"], "/tools/events/upcoming")
        self.assertEqual(upcoming["params"], {"profile": "main", "days": "7"})

        month = await client.fetch(ToolRequest(ToolKind.CALENDAR_MONTH_IMAGE))
        self.assertEqual(month["path"], "/tools/calendar/month-image")
        self.assertEqual(month["params"], {"profile": "main"})

        september = await client.calendar_month_image(year=2026, month=9, today="2026-08-25")
        self.assertEqual(september["path"], "/tools/calendar/month-image")
        self.assertEqual(september["params"], {"profile": "main", "year": "2026", "month": "9", "date": "2026-08-25"})

        imports = await client.fetch(ToolRequest(ToolKind.RECENT_IMPORTS))
        self.assertEqual(imports["path"], "/tools/imports/recent")
        self.assertEqual(imports["params"], {"profile": "main"})

    async def test_fetch_single_memo_search_gets_full_body(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _get(self, path: str, params: dict[str, str]):
                self.calls.append((path, params))
                if path == "/tools/memos/search":
                    return {"query": "rustdesk", "count": 1, "results": [{"name": "memos/42", "snippet": "Rustdesk"}]}
                return {"memo": {"name": "memos/42", "content": "# Rustdesk\nUse Tailscale."}}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.fetch(ToolRequest(ToolKind.MEMO_SEARCH, "rustdesk"))
        self.assertEqual(
            client.calls,
            [
                ("/tools/memos/search", {"query": "rustdesk", "limit": "10"}),
                ("/tools/memos/42", {}),
            ],
        )
        self.assertEqual(payload["results"][0]["content"], "# Rustdesk\nUse Tailscale.")
        self.assertTrue(payload["results"][0]["full"])

    async def test_fetch_empty_memo_search_uses_list_route(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _get(self, path: str, params: dict[str, str]):
                self.calls.append((path, params))
                return {
                    "query": "",
                    "resultCount": 2,
                    "totalCount": 2,
                    "results": [
                        {"name": "memos/42", "snippet": "Rustdesk"},
                        {"name": "memos/43", "snippet": "Clinic"},
                    ],
                }

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.fetch(ToolRequest(ToolKind.MEMO_SEARCH, ""))
        self.assertEqual(client.calls, [("/tools/memos/list", {"limit": "10"})])
        self.assertEqual(payload["results"][0]["name"], "memos/42")

    async def test_fetch_completed_tasks_builds_filtered_route(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            async def _get(self, path: str, params: dict[str, str]):
                return {"path": path, "params": params}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.fetch(
            ToolRequest(ToolKind.COMPLETED_TASKS, "엄마", "2026-08-02", "2026-08-15")
        )
        self.assertEqual(payload["path"], "/tools/tasks/completed")
        self.assertEqual(
            payload["params"],
            {
                "profile": "main",
                "limit": "25",
                "query": "엄마",
                "from": "2026-08-02",
                "to": "2026-08-15",
            },
        )

    async def test_completed_tasks_accepts_custom_limit(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            async def _get(self, path: str, params: dict[str, str]):
                return {"path": path, "params": params}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.completed_tasks(ToolRequest(ToolKind.COMPLETED_TASKS, start="2026-08-01"), limit=250)

        self.assertEqual(payload["path"], "/tools/tasks/completed")
        self.assertEqual(payload["params"]["limit"], "250")
        self.assertEqual(payload["params"]["from"], "2026-08-01")

    async def test_fetch_supplies_active_tasks_adds_collection(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            async def _get(self, path: str, params: dict[str, str]):
                return {"path": path, "params": params}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
                supplies_collection_id="supplies:abc",
            )
        )
        payload = await client.fetch(ToolRequest(ToolKind.ACTIVE_TASKS, profile="supplies"))
        self.assertEqual(payload["path"], "/tools/tasks/active")
        self.assertEqual(payload["params"], {"profile": "supplies", "collectionId": "supplies:abc"})

    async def test_fetch_multi_memo_search_keeps_snippets_only(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _get(self, path: str, params: dict[str, str]):
                self.calls.append((path, params))
                return {
                    "query": "rustdesk",
                    "count": 2,
                    "results": [{"name": "memos/42", "snippet": "One"}, {"name": "memos/43", "snippet": "Two"}],
                }

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.fetch(ToolRequest(ToolKind.MEMO_SEARCH, "rustdesk"))
        self.assertEqual(client.calls, [("/tools/memos/search", {"query": "rustdesk", "limit": "10"})])
        self.assertNotIn("content", payload["results"][0])

    async def test_event_create_uses_request_profile(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _post(self, path: str, payload: dict[str, object]):
                self.calls.append((path, payload))
                return {"ok": True}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        await client.propose_event_create(
            EventCreateRequest(
                title="엔소쿠료칸",
                start_date="2026-08-15",
                end_date="2026-08-15",
                memo="포항 조사리",
                profile="family",
            ),
            actor_id=123,
            idempotency_key="k",
        )
        self.assertEqual(client.calls[0][0], "/tools/events/create/proposals")
        self.assertEqual(
            client.calls[0][1],
            {
                "actorId": "123",
                "idempotencyKey": "k",
                "profile": "family",
                "title": "엔소쿠료칸",
                "startDate": "2026-08-15",
                "endDate": "2026-08-15",
                "allDay": True,
                "memo": "포항 조사리",
            },
        )

    async def test_fetch_document_search_keeps_search_rows(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _get(self, path: str, params: dict[str, str]):
                self.calls.append((path, params))
                if path == "/tools/documents/search":
                    return {"query": "rustdesk", "resultCount": 1, "totalCount": 12, "results": [{"id": 42, "title": "Rustdesk"}]}
                return {"document": {"id": 42, "title": "Rustdesk setup", "filename": "rustdesk.pdf", "correspondent": "Clinic"}}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.fetch(ToolRequest(ToolKind.DOCUMENT_SEARCH, "rustdesk"))
        self.assertEqual(
            client.calls,
            [
                ("/tools/documents/search", {"query": "rustdesk", "limit": "10", "page": "1"}),
            ],
        )
        self.assertEqual(payload["results"][0]["title"], "Rustdesk")
        self.assertNotIn("full", payload["results"][0])

    async def test_fetch_multi_document_search_keeps_search_rows(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _get(self, path: str, params: dict[str, str]):
                self.calls.append((path, params))
                return {"query": "rustdesk", "resultCount": 2, "results": [{"id": 42, "title": "One"}, {"id": 43, "title": "Two"}]}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.fetch(ToolRequest(ToolKind.DOCUMENT_SEARCH, "rustdesk"))
        self.assertEqual(client.calls, [("/tools/documents/search", {"query": "rustdesk", "limit": "10", "page": "1"})])
        self.assertNotIn("full", payload["results"][0])

    async def test_fetch_empty_document_search_uses_list_route(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _get(self, path: str, params: dict[str, str]):
                self.calls.append((path, params))
                return {"query": "", "resultCount": 1, "results": [{"id": 42, "title": "One"}]}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.fetch(ToolRequest(ToolKind.DOCUMENT_SEARCH, ""))
        self.assertEqual(client.calls, [("/tools/documents/list", {"limit": "10", "page": "1"})])
        self.assertEqual(payload["results"][0]["title"], "One")

    async def test_document_list_page_uses_page_route_param(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _get(self, path: str, params: dict[str, str]):
                self.calls.append((path, params))
                return {"query": "", "resultCount": 26, "page": 2, "results": [{"id": 99, "title": "Two"}]}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.documents("", page=2)
        self.assertEqual(client.calls, [("/tools/documents/list", {"limit": "10", "page": "2"})])
        self.assertEqual(payload["page"], 2)

    async def test_document_search_page_uses_page_route_param(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _get(self, path: str, params: dict[str, str]):
                self.calls.append((path, params))
                return {"query": "rustdesk", "resultCount": 26, "page": 3, "results": [{"id": 99, "title": "Three"}]}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.documents("rustdesk", page=3)
        self.assertEqual(client.calls, [("/tools/documents/search", {"limit": "10", "page": "3", "query": "rustdesk"})])
        self.assertEqual(payload["page"], 3)

    async def test_propose_document_tags_posts_contract(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            async def _post(self, path: str, payload: dict[str, object]):
                return {"path": path, "payload": payload}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.propose_document_tags(
            DocumentTagRequest("42", ("medical", "receipt")),
            actor_id=994,
            idempotency_key="discord:1",
        )

        self.assertEqual(payload["path"], "/tools/documents/42/tags/proposals")
        self.assertEqual(payload["payload"]["actorId"], "994")
        self.assertEqual(payload["payload"]["idempotencyKey"], "discord:1")
        self.assertEqual(payload["payload"]["tags"], ["medical", "receipt"])

    async def test_get_document_tag_context_gets_contract(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            async def _get(self, path: str, params: dict[str, str]):
                return {"path": path, "params": params}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )

        payload = await client.get_document_tag_context("42")

        self.assertEqual(payload["path"], "/tools/documents/42/tag-context")
        self.assertEqual(payload["params"], {})

    async def test_propose_task_due_update_posts_contract(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            async def _post(self, path: str, payload: dict[str, str]):
                return {"path": path, "payload": payload}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.propose_task_due_update(
            TaskDueUpdateRequest("Call mom", "2026-08-17"),
            actor_id=994,
            idempotency_key="discord:1",
        )
        self.assertEqual(payload["path"], "/tools/tasks/update-due/proposals")
        self.assertEqual(payload["payload"]["taskTitle"], "Call mom")
        self.assertEqual(payload["payload"]["dueTime"], "10:00")

    async def test_task_create_omits_due_time_without_due_date(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            async def _post(self, path: str, payload: dict[str, str]):
                return {"path": path, "payload": payload}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )

        payload = await client.propose_task_create(
            TaskCreateRequest("오도리 문고리", "", "10:00", memo="문고리 사이즈 확인"),
            actor_id=994,
            idempotency_key="discord:1",
        )

        self.assertEqual(payload["path"], "/tools/tasks/create/proposals")
        self.assertEqual(payload["payload"]["title"], "오도리 문고리")
        self.assertEqual(payload["payload"]["memo"], "문고리 사이즈 확인")
        self.assertNotIn("dueDate", payload["payload"])
        self.assertNotIn("dueTime", payload["payload"])

    async def test_task_proposals_use_request_scope(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _post(self, path: str, payload: dict[str, str]):
                self.calls.append((path, payload))
                return {"ok": True}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
                supplies_collection_id="supplies:abc",
            )
        )
        await client.propose_task_create(
            TaskCreateRequest("Soap", "", "", profile="supplies"),
            actor_id=994,
            idempotency_key="discord:1",
        )
        await client.propose_task_action(
            TaskActionRequest("Soap", "reopen", profile="supplies", uid="SUPPLY-1"),
            actor_id=994,
            idempotency_key="discord:2",
        )
        await client.propose_task_edit(
            TaskEditRequest("Soap", "Hand soap", profile="supplies", uid="SUPPLY-1"),
            actor_id=994,
            idempotency_key="discord:3",
        )
        self.assertEqual(client.calls[0][1]["profile"], "supplies")
        self.assertEqual(client.calls[0][1]["collectionId"], "supplies:abc")
        self.assertNotIn("dueDate", client.calls[0][1])
        self.assertEqual(client.calls[1][1]["uid"], "SUPPLY-1")
        self.assertNotIn("dueTime", client.calls[0][1])
        self.assertEqual(client.calls[1][1]["profile"], "supplies")
        self.assertEqual(client.calls[1][1]["collectionId"], "supplies:abc")
        self.assertEqual(client.calls[2][0], "/tools/tasks/edit/proposals")
        self.assertEqual(client.calls[2][1]["profile"], "supplies")
        self.assertEqual(client.calls[2][1]["collectionId"], "supplies:abc")
        self.assertEqual(client.calls[2][1]["uid"], "SUPPLY-1")


if __name__ == "__main__":
    unittest.main()
