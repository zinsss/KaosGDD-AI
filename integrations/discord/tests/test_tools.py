from __future__ import annotations

import base64
from datetime import date
from types import SimpleNamespace
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from kaos_governor.documents import PaperlessDocument, PaperlessSearchPage, PaperlessSearchResult, PaperlessTag
from kaos_governor.memos import Memo, MemoSearchPage, MemoSearchResult
from kaos_governor_discord.tools import BrainToolServer, ImagingSecondLookClient, ImagingSecondLookConfig


class FakeCalendarAdapter:
    def __init__(self) -> None:
        self.bootstrap_calls = []
        self.month_weather_calls = []
        self.tasks = [
            {"uid": "TASK-2", "summary": "No due", "status": "NEEDS-ACTION", "collection": "zin:tasks"},
            {
                "uid": "TASK-1",
                "summary": "Call mom",
                "due": "2026-08-14",
                "dueTime": "10:00",
                "status": "NEEDS-ACTION",
                "collection": "zin:tasks",
            },
            {"uid": "TASK-3", "summary": "Done", "due": "2026-08-14", "status": "COMPLETED"},
            {
                "uid": "TASK-4",
                "summary": "Done lately",
                "due": "2026-08-10",
                "status": "COMPLETED",
                "completed": "2026-08-15",
                "collection": "zin:tasks",
            },
        ]
        self.updated = []
        self.created = []
        self.created_events = []
        self.deleted = []

    def bootstrap(self, profile):
        self.bootstrap_calls.append(profile)
        return {
            "live": True,
            "collections": [
                {"id": "zin:tasks", "owner": "zin", "ownerLabel": "GDD_ZiN"},
                {"id": "family:events", "owner": "family", "ownerLabel": "Family"},
            ],
            "events": [
                {
                    "uid": "EVENT-1",
                    "summary": "Clinic",
                    "startDate": "2026-08-14",
                    "startTime": "10:50",
                    "collection": "family:events",
                },
                {"uid": "EVENT-2", "summary": "Tomorrow", "startDate": "2026-08-15"},
            ],
            "tasks": list(self.tasks),
        }

    def list_tasks(self, profile):
        self.bootstrap_calls.append(profile)
        return list(self.tasks)

    def month_weather(self, profile, *, start, end, city="pohang"):
        self.month_weather_calls.append((profile, start, end, city))
        return {
            "items": [
                {
                    "date": "2026-08-14",
                    "condition": "cloudy",
                    "minTemp": 23,
                    "maxTemp": 28,
                }
            ]
        }

    def update_task(self, profile, payload):
        self.updated.append((profile, dict(payload)))
        for index, task in enumerate(self.tasks):
            if task.get("uid") == payload.get("uid"):
                self.tasks[index] = {
                    **task,
                    "summary": payload.get("title", task.get("summary")),
                    "description": payload.get("memo", task.get("description", "")),
                    "due": payload.get("dueDate", task.get("due", "")),
                    "dueTime": payload.get("dueTime", task.get("dueTime", "")),
                    "priority": payload.get("priority", task.get("priority", "")),
                    "status": payload.get("status", task.get("status", "")),
                }
                return {"uid": task["uid"]}
        return {"uid": payload.get("uid", "")}

    def create_task(self, profile, payload):
        self.created.append((profile, dict(payload)))
        uid = f"TASK-CREATED-{len(self.created)}"
        self.tasks.append(
            {
                "uid": uid,
                "summary": payload.get("title", ""),
                "due": payload.get("dueDate", ""),
                "dueTime": payload.get("dueTime", ""),
                "status": "NEEDS-ACTION",
                "collection": payload.get("collectionId", "zin:tasks"),
            }
        )
        return {"uid": uid}

    def create_event(self, profile, payload):
        self.created_events.append((profile, dict(payload)))
        return {"uid": f"EVENT-CREATED-{len(self.created_events)}"}

    def delete_task(self, profile, uid, collection_id):
        self.deleted.append((profile, uid, collection_id))
        self.tasks = [task for task in self.tasks if task.get("uid") != uid]
        return {"uid": uid}


class FakeMemos:
    def __init__(self) -> None:
        self.config = SimpleNamespace(enabled=True)
        self.search_calls = []
        self.get_calls = []
        self.create_calls = []
        self.delete_calls = []
        self.update_calls = []

    def search(self, query, tags, limit):
        self.search_calls.append((query, tags, limit))
        memo = Memo("memos/42", "Secret body", ("server",), "created", "updated", "PRIVATE", True)
        if query == "many":
            other = Memo("memos/43", "Other body", ("server",), "created", "updated", "PRIVATE", False)
            return [MemoSearchResult(memo, "Search snippet"), MemoSearchResult(other, "Other snippet")]
        return [MemoSearchResult(memo, "Search snippet")]

    def search_page(self, query, tags, limit):
        results = tuple(self.search(query, tags, limit))
        return MemoSearchPage(query, tuple(tags or ()), results, 13, 213)

    def get(self, name):
        self.get_calls.append(name)
        return Memo(name, "Full memo body", ("server",), "created", "updated", "PRIVATE", False)

    def create(self, content):
        self.create_calls.append(content)
        return Memo("memos/new", content, (), "created", "updated", "PRIVATE", False)

    def update(self, name, content):
        self.update_calls.append((name, content))
        return Memo(name, content, ("server",), "created", "updated", "PRIVATE", False)

    def delete(self, name):
        self.delete_calls.append(name)


class FakePaperless:
    def __init__(self) -> None:
        self.search_calls = []
        self.get_calls = []
        self.update_calls = []
        self.existing_tag_calls = []

    def search_page(self, query, *, limit):
        self.search_calls.append((query, limit))
        return PaperlessSearchPage(
            query,
            (PaperlessSearchResult(42, "Rustdesk setup", "2026-08-14", "rustdesk.pdf"),),
            1,
            12,
        )

    def get(self, document_id):
        self.get_calls.append(document_id)
        return PaperlessDocument(
            42,
            "Rustdesk setup detail",
            "2026-08-14",
            "rustdesk.pdf",
            "Clinic",
            "Full OCR body",
            (7,),
        )

    def metadata_proposal(self, document_id, *, title="", tags=()):
        document = self.get(document_id)
        return {
            "document": document.as_dict(),
            "proposal": {
                "id": document.document_id,
                "oldTitle": document.title,
                "title": title or document.title,
                "tags": list(tags),
            },
        }

    def existing_tag_names(self, names):
        self.existing_tag_calls.append(tuple(names))
        known = {"server": "server", "rustdesk": "rustdesk", "clinic": "Clinic"}
        return tuple(known[name.casefold()] for name in names if name.casefold() in known)

    def list_tags(self):
        return (PaperlessTag(7, "server"), PaperlessTag(8, "Clinic"), PaperlessTag(9, "receipt"))

    def update_metadata(self, document_id, *, title, tags=()):
        self.update_calls.append((document_id, title, tuple(tags)))
        return PaperlessDocument(
            int(document_id),
            title,
            "2026-08-14",
            "rustdesk.pdf",
            "Clinic",
            "Full OCR body",
            (8, 9),
        )


def _second_look_payload(request_id: str) -> dict:
    return {
        "source": "kaosaio",
        "requestId": request_id,
        "studyInstanceUid": "1.2.3",
        "seriesInstanceUid": "1.2.3.4",
        "sopInstanceUid": "1.2.3.4.5",
        "modality": "DX",
        "bodyPart": "CHEST",
        "viewPosition": "PA",
        "aiDomain": "cxr",
        "images": [{"format": "png", "contentBase64": base64.b64encode(b"png").decode("ascii")}],
        "question": "눈에 띄는 이상 소견이나 놓치기 쉬운 포인트를 체크해주세요.",
        "safety": {
            "temporary": True,
            "storedInAioReports": False,
            "dicomMetadataSent": False,
            "orthancReadOnly": True,
            "dicomModified": False,
            "pacsFinalReport": False,
            "renderedPreview": True,
            "burnedInAnnotationsPossible": True,
            "disclaimer": "KaosAIO Opinion...",
        },
    }


class BrainToolServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.calendar = FakeCalendarAdapter()
        self.memos = FakeMemos()
        self.paperless = FakePaperless()
        self.calendar_refresh_count = 0

        async def refresh_calendar_surfaces() -> None:
            self.calendar_refresh_count += 1

        server = BrainToolServer(
            "127.0.0.1",
            8098,
            governor_api_token="governor-secret",
            calendar_adapter=self.calendar,  # type: ignore[arg-type]
            memos=self.memos,  # type: ignore[arg-type]
            paperless=self.paperless,  # type: ignore[arg-type]
            calendar_refresh_callback=refresh_calendar_surfaces,
            today_provider=lambda: date(2026, 8, 14),
        )
        self.client = TestClient(TestServer(server.application()))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()

    def headers(self):
        return {"Authorization": "Bearer governor-secret"}

    async def test_tools_require_bearer_token(self) -> None:
        response = await self.client.get("/tools/today")

        self.assertEqual(response.status, 401)
        self.assertEqual((await response.json())["error"], "governor_api_unauthorized")

    async def test_imaging_second_look_accepts_kaosaio_temporary_preview(self) -> None:
        response = await self.client.post(
            "/tools/imaging/second-look",
            headers=self.headers(),
            json={
                "source": "kaosaio",
                "requestId": "kaosaio-second-look-1",
                "studyInstanceUid": "1.2.3",
                "seriesInstanceUid": "1.2.3.4",
                "sopInstanceUid": "1.2.3.4.5",
                "modality": "DX",
                "bodyPart": "CHEST",
                "viewPosition": "PA",
                "aiDomain": "cxr",
                "images": [{"format": "png", "contentBase64": base64.b64encode(b"png").decode("ascii")}],
                "question": "눈에 띄는 이상 소견이나 놓치기 쉬운 포인트를 체크해주세요.",
                "safety": {
                    "temporary": True,
                    "storedInAioReports": False,
                    "dicomMetadataSent": False,
                    "orthancReadOnly": True,
                    "dicomModified": False,
                    "pacsFinalReport": False,
                    "renderedPreview": True,
                    "burnedInAnnotationsPossible": True,
                    "disclaimer": "KaosAIO Opinion...",
                },
            },
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertTrue(payload["jobId"].startswith("imaging_"))
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["result"]["model"], "not-connected")
        self.assertIn("AI 보조 검토", payload["result"]["disclaimer"])

    async def test_imaging_second_look_rejects_unsafe_request(self) -> None:
        response = await self.client.post(
            "/tools/imaging/second-look",
            headers=self.headers(),
            json={
                "source": "kaosaio",
                "requestId": "kaosaio-second-look-2",
                "modality": "DX",
                "aiDomain": "cxr",
                "images": [{"format": "png", "contentBase64": base64.b64encode(b"png").decode("ascii")}],
                "question": "check",
                "safety": {
                    "temporary": True,
                    "storedInAioReports": True,
                    "dicomMetadataSent": False,
                    "orthancReadOnly": True,
                    "dicomModified": False,
                    "pacsFinalReport": False,
                    "renderedPreview": True,
                },
            },
        )

        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"], "imaging_second_look_safety_rejected")

    async def test_imaging_second_look_forwards_to_configured_provider(self) -> None:
        provider_requests = []

        async def provider(request):
            provider_requests.append(await request.json())
            self.assertEqual(request.headers.get("Authorization"), "Bearer imaging-token")
            return web.json_response(
                {
                    "status": "completed",
                    "result": {
                        "summary": "검토 완료",
                        "checklist": ["폐야 확인"],
                        "cautions": ["최종 판단은 진료자가 합니다."],
                        "recommendation": "임상 소견과 대조",
                        "model": "qwen2.5vl",
                        "fallback": {"from": "kaosai", "to": "ollama"},
                    },
                }
            )

        app = web.Application()
        app.router.add_post("/imaging/second-look", provider)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            server = BrainToolServer(
                "127.0.0.1",
                8098,
                governor_api_token="governor-secret",
                calendar_adapter=self.calendar,  # type: ignore[arg-type]
                memos=self.memos,  # type: ignore[arg-type]
                paperless=self.paperless,  # type: ignore[arg-type]
                imaging_second_look=ImagingSecondLookClient(
                    ImagingSecondLookConfig(
                        url=f"http://127.0.0.1:{port}/imaging/second-look",
                        token="imaging-token",
                    )
                ),
            )
            client = TestClient(TestServer(server.application()))
            await client.start_server()
            try:
                response = await client.post(
                    "/tools/imaging/second-look",
                    headers=self.headers(),
                    json=_second_look_payload("kaosaio-second-look-forwarded"),
                )
                self.assertEqual(response.status, 200)
                payload = await response.json()
                self.assertEqual(payload["status"], "completed")
                self.assertEqual(payload["result"]["summary"], "검토 완료")
                self.assertEqual(payload["result"]["model"], "qwen2.5vl")
                self.assertEqual(payload["result"]["fallback"], {"from": "kaosai", "to": "ollama"})
                self.assertEqual(len(provider_requests), 1)
            finally:
                await client.close()
        finally:
            await runner.cleanup()

    async def test_today_returns_events_due_tasks_and_weather(self) -> None:
        response = await self.client.get("/tools/today?profile=main", headers=self.headers())

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["date"], "2026-08-14")
        self.assertEqual(payload["events"][0]["title"], "Clinic")
        self.assertEqual(payload["tasks"][0]["title"], "Call mom")
        self.assertEqual(payload["weather"]["summary"], "⛅️ 23-28℃")
        self.assertEqual(self.calendar.month_weather_calls, [("main", "2026-08-14", "2026-08-14", "pohang")])

    async def test_active_tasks_returns_sorted_non_completed_tasks(self) -> None:
        response = await self.client.get("/tools/tasks/active?profile=main", headers=self.headers())

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual([item["uid"] for item in payload["tasks"]], ["TASK-1", "TASK-2"])

    async def test_completed_tasks_returns_completed_tasks_in_date_window(self) -> None:
        response = await self.client.get(
            "/tools/tasks/completed?profile=main&from=2026-08-15&to=2026-08-15",
            headers=self.headers(),
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["tasks"][0]["uid"], "TASK-4")
        self.assertEqual(payload["tasks"][0]["completedDate"], "2026-08-15")
        self.assertEqual(payload["tasks"][0]["completedDateSource"], "completed")

    async def test_completed_tasks_can_search_title(self) -> None:
        response = await self.client.get(
            "/tools/tasks/completed?profile=main&query=lately",
            headers=self.headers(),
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual([item["uid"] for item in payload["tasks"]], ["TASK-4"])

    async def test_memos_search_returns_snippets_only(self) -> None:
        response = await self.client.get(
            "/tools/memos/search?query=rust%20desk&tag=server&limit=3",
            headers=self.headers(),
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["results"][0]["name"], "memos/42")
        self.assertEqual(payload["results"][0]["title"], "Secret body")
        self.assertNotIn("content", payload["results"][0])
        self.assertEqual(payload["resultCount"], 13)
        self.assertEqual(payload["totalCount"], 213)
        self.assertEqual(self.memos.search_calls, [("rust desk", ["server"], 3)])

    async def test_memo_get_returns_full_content(self) -> None:
        response = await self.client.get("/tools/memos/42", headers=self.headers())

        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["memo"]["content"], "Full memo body")
        self.assertEqual(self.memos.get_calls, ["memos/42"])

    async def test_memo_create_proposal_requires_confirmation_before_write(self) -> None:
        response = await self.client.post(
            "/tools/memos/create/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-memo-1",
                "content": "# Rustdesk\nUse Tailscale.",
            },
        )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertTrue(payload["confirmationId"].startswith("conf_"))
        self.assertEqual(payload["memo"]["content"], "# Rustdesk\nUse Tailscale.")
        self.assertEqual(self.memos.create_calls, [])

    async def test_memo_create_approval_creates_memo(self) -> None:
        proposal = await self.client.post(
            "/tools/memos/create/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-memo-2",
                "content": "# Rustdesk\nUse Tailscale.",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["source"], "memos-live")
        self.assertEqual(payload["memo"]["name"], "memos/new")
        self.assertEqual(self.memos.create_calls, ["# Rustdesk\nUse Tailscale."])
        self.assertEqual(self.calendar_refresh_count, 0)

    async def test_memo_create_approval_rejects_wrong_actor(self) -> None:
        proposal = await self.client.post(
            "/tools/memos/create/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-memo-3",
                "content": "Secret memo",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "111"},
        )

        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"], "confirmation_actor_mismatch")
        self.assertEqual(self.memos.create_calls, [])

    async def test_memo_delete_proposal_requires_confirmation_before_write(self) -> None:
        response = await self.client.post(
            "/tools/memos/delete/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-memo-delete-1",
                "query": "rustdesk",
            },
        )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertTrue(payload["confirmationId"].startswith("conf_"))
        self.assertEqual(payload["memo"]["name"], "memos/42")
        self.assertEqual(payload["memo"]["content"], "Full memo body")
        self.assertEqual(self.memos.delete_calls, [])

    async def test_memo_delete_proposal_can_target_exact_name(self) -> None:
        response = await self.client.post(
            "/tools/memos/delete/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-memo-delete-by-name-1",
                "name": "memos/42",
            },
        )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertEqual(payload["memo"]["name"], "memos/42")
        self.assertEqual(self.memos.search_calls, [])
        self.assertEqual(self.memos.get_calls, ["memos/42"])
        self.assertEqual(self.memos.delete_calls, [])

    async def test_memo_delete_approval_deletes_memo(self) -> None:
        proposal = await self.client.post(
            "/tools/memos/delete/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-memo-delete-2",
                "query": "rustdesk",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["source"], "memos-live")
        self.assertEqual(payload["memo"]["name"], "memos/42")
        self.assertEqual(payload["memo"]["action"], "delete")
        self.assertEqual(self.memos.delete_calls, ["memos/42"])

    async def test_memo_delete_approval_rejects_wrong_actor(self) -> None:
        proposal = await self.client.post(
            "/tools/memos/delete/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-memo-delete-3",
                "query": "rustdesk",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "111"},
        )

        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"], "confirmation_actor_mismatch")
        self.assertEqual(self.memos.delete_calls, [])

    async def test_memo_delete_rejects_ambiguous_match(self) -> None:
        response = await self.client.post(
            "/tools/memos/delete/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-memo-delete-4",
                "query": "many",
            },
        )

        self.assertEqual(response.status, 409)
        payload = await response.json()
        self.assertEqual(payload["error"], "memo_match_ambiguous")
        self.assertEqual(len(payload["matches"]), 2)
        self.assertEqual(self.memos.delete_calls, [])

    async def test_memo_edit_proposal_requires_confirmation_before_write(self) -> None:
        response = await self.client.post(
            "/tools/memos/edit/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-memo-edit-1",
                "query": "rustdesk",
                "content": "# Rustdesk\nUpdated body",
            },
        )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertTrue(payload["confirmationId"].startswith("conf_"))
        self.assertEqual(payload["memo"]["name"], "memos/42")
        self.assertEqual(payload["memo"]["oldContent"], "Full memo body")
        self.assertEqual(payload["memo"]["newContent"], "# Rustdesk\nUpdated body")
        self.assertEqual(self.memos.update_calls, [])

    async def test_memo_edit_proposal_can_target_exact_name(self) -> None:
        response = await self.client.post(
            "/tools/memos/edit/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-memo-edit-by-name-1",
                "name": "memos/42",
                "content": "# Rustdesk\nUpdated body",
            },
        )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertEqual(payload["memo"]["name"], "memos/42")
        self.assertEqual(payload["memo"]["oldContent"], "Full memo body")
        self.assertEqual(payload["memo"]["newContent"], "# Rustdesk\nUpdated body")
        self.assertEqual(self.memos.search_calls, [])
        self.assertEqual(self.memos.get_calls, ["memos/42"])
        self.assertEqual(self.memos.update_calls, [])

    async def test_memo_edit_approval_updates_memo(self) -> None:
        proposal = await self.client.post(
            "/tools/memos/edit/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-memo-edit-2",
                "query": "rustdesk",
                "content": "# Rustdesk\nUpdated body",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["source"], "memos-live")
        self.assertEqual(payload["memo"]["name"], "memos/42")
        self.assertEqual(payload["memo"]["action"], "edit")
        self.assertEqual(payload["memo"]["content"], "# Rustdesk\nUpdated body")
        self.assertEqual(self.memos.update_calls, [("memos/42", "# Rustdesk\nUpdated body")])

    async def test_memo_edit_approval_rejects_wrong_actor(self) -> None:
        proposal = await self.client.post(
            "/tools/memos/edit/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-memo-edit-3",
                "query": "rustdesk",
                "content": "# Rustdesk\nUpdated body",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "111"},
        )

        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"], "confirmation_actor_mismatch")
        self.assertEqual(self.memos.update_calls, [])

    async def test_memo_edit_rejects_ambiguous_match(self) -> None:
        response = await self.client.post(
            "/tools/memos/edit/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-memo-edit-4",
                "query": "many",
                "content": "Updated body",
            },
        )

        self.assertEqual(response.status, 409)
        payload = await response.json()
        self.assertEqual(payload["error"], "memo_match_ambiguous")
        self.assertEqual(len(payload["matches"]), 2)
        self.assertEqual(self.memos.update_calls, [])

    async def test_document_search_returns_paperless_results(self) -> None:
        response = await self.client.get("/tools/documents/search?query=rust%20desk", headers=self.headers())

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["source"], "paperless-live")
        self.assertEqual(payload["results"][0]["title"], "Rustdesk setup")
        self.assertEqual(self.paperless.search_calls, [("rust desk", 5)])

    async def test_document_get_returns_paperless_document(self) -> None:
        response = await self.client.get("/tools/documents/42", headers=self.headers())

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["source"], "paperless-live")
        self.assertEqual(payload["document"]["id"], 42)
        self.assertEqual(payload["document"]["title"], "Rustdesk setup detail")
        self.assertEqual(payload["document"]["content"], "Full OCR body")
        self.assertEqual(payload["document"]["tagIds"], [7])
        self.assertEqual(self.paperless.get_calls, ["42"])

    async def test_document_tag_context_returns_excerpt_and_existing_tags(self) -> None:
        response = await self.client.get("/tools/documents/42/tag-context", headers=self.headers())

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["source"], "paperless-live")
        self.assertEqual(payload["document"]["id"], 42)
        self.assertEqual(payload["document"]["contentExcerpt"], "Full OCR body")
        self.assertEqual(payload["document"]["contentLength"], 13)
        self.assertNotIn("content", payload["document"])
        self.assertEqual(payload["availableTags"], [{"id": 7, "name": "server"}, {"id": 8, "name": "Clinic"}, {"id": 9, "name": "receipt"}])

    async def test_document_metadata_proposal_requires_confirmation_before_write(self) -> None:
        response = await self.client.post(
            "/tools/documents/42/metadata/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "document-metadata-1",
                "title": "Rustdesk Settings",
                "tags": ["server", "#rustdesk", "server"],
            },
        )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertTrue(payload["confirmationId"].startswith("conf_"))
        self.assertEqual(payload["source"], "paperless-live")
        self.assertEqual(payload["document"]["oldTitle"], "Rustdesk setup detail")
        self.assertEqual(payload["document"]["title"], "Rustdesk Settings")
        self.assertEqual(payload["document"]["tags"], ["server", "rustdesk"])
        self.assertEqual(self.paperless.update_calls, [])

    async def test_document_metadata_approval_updates_paperless(self) -> None:
        proposal = await self.client.post(
            "/tools/documents/42/metadata/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "document-metadata-2",
                "title": "Rustdesk Settings",
                "tags": ["server", "rustdesk"],
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["source"], "paperless-live")
        self.assertEqual(payload["document"]["title"], "Rustdesk Settings")
        self.assertEqual(self.paperless.update_calls, [(42, "Rustdesk Settings", ("server", "rustdesk"))])
        self.assertEqual(self.calendar_refresh_count, 0)

    async def test_document_metadata_approval_rejects_wrong_actor(self) -> None:
        proposal = await self.client.post(
            "/tools/documents/42/metadata/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "document-metadata-3",
                "title": "Rustdesk Settings",
                "tags": ["server"],
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "111"},
        )

        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"], "confirmation_actor_mismatch")
        self.assertEqual(self.paperless.update_calls, [])

    async def test_document_tag_proposal_keeps_new_tags_for_confirmation(self) -> None:
        response = await self.client.post(
            "/tools/documents/42/tags/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "document-tags-1",
                "tags": ["server", "new-ai-tag", "#Clinic"],
            },
        )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertTrue(payload["confirmationId"].startswith("conf_"))
        self.assertEqual(payload["document"]["tags"], ["server", "new-ai-tag", "Clinic"])
        self.assertEqual(payload["suggestedTags"], ["server", "new-ai-tag", "Clinic"])
        self.assertEqual(payload["ignoredTags"], [])
        self.assertEqual(self.paperless.existing_tag_calls, [])
        self.assertEqual(self.paperless.update_calls, [])

    async def test_document_tag_proposal_accepts_all_new_tags_for_confirmation(self) -> None:
        response = await self.client.post(
            "/tools/documents/42/tags/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "document-tags-2",
                "tags": ["made-up"],
            },
        )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertEqual(payload["document"]["tags"], ["made-up"])
        self.assertEqual(payload["ignoredTags"], [])
        self.assertEqual(self.paperless.update_calls, [])

    async def test_task_due_update_proposal_requires_confirmation_before_write(self) -> None:
        response = await self.client.post(
            "/tools/tasks/update-due/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-1",
                "profile": "main",
                "taskTitle": "Call mom",
                "dueDate": "2026-08-17",
                "dueTime": "10:00",
            },
        )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertTrue(payload["confirmationId"].startswith("conf_"))
        self.assertEqual(payload["task"]["title"], "Call mom")
        self.assertEqual(payload["task"]["newDue"], "2026-08-17")
        self.assertEqual(self.calendar.updated, [])

    async def test_task_due_update_approval_updates_calendar_task(self) -> None:
        proposal = await self.client.post(
            "/tools/tasks/update-due/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-2",
                "profile": "main",
                "taskTitle": "Call mom",
                "dueDate": "2026-08-17",
                "dueTime": "10:00",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(self.calendar.updated[0][0], "main")
        self.assertEqual(self.calendar.updated[0][1]["uid"], "TASK-1")
        self.assertEqual(self.calendar.updated[0][1]["dueDate"], "2026-08-17")
        self.assertEqual(self.calendar_refresh_count, 1)

    async def test_task_due_update_approval_rejects_wrong_actor(self) -> None:
        proposal = await self.client.post(
            "/tools/tasks/update-due/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-3",
                "profile": "main",
                "taskTitle": "Call mom",
                "dueDate": "2026-08-17",
                "dueTime": "10:00",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "111"},
        )

        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"], "confirmation_actor_mismatch")
        self.assertEqual(self.calendar.updated, [])

    async def test_task_due_update_rejects_ambiguous_match(self) -> None:
        self.calendar.tasks.append(
            {
                "uid": "TASK-4",
                "summary": "Call mom again",
                "due": "2026-08-15",
                "status": "NEEDS-ACTION",
                "collection": "zin:tasks",
            }
        )

        response = await self.client.post(
            "/tools/tasks/update-due/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-4",
                "profile": "main",
                "taskTitle": "Call mom",
                "dueDate": "2026-08-17",
                "dueTime": "10:00",
            },
        )

        self.assertEqual(response.status, 201)

        response = await self.client.post(
            "/tools/tasks/update-due/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-5",
                "profile": "main",
                "taskTitle": "mom",
                "dueDate": "2026-08-17",
                "dueTime": "10:00",
            },
        )

        self.assertEqual(response.status, 409)
        self.assertEqual((await response.json())["error"], "task_match_ambiguous")

    async def test_task_edit_proposal_requires_confirmation_before_write(self) -> None:
        response = await self.client.post(
            "/tools/tasks/edit/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-edit-1",
                "profile": "main",
                "uid": "TASK-1",
                "taskTitle": "Call mom",
                "title": "Call dad",
                "memo": "monthly",
                "dueDate": "2026-08-20",
                "dueTime": "14:30",
                "priority": "1",
            },
        )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertTrue(payload["confirmationId"].startswith("conf_"))
        self.assertEqual(payload["task"]["oldTitle"], "Call mom")
        self.assertEqual(payload["task"]["title"], "Call dad")
        self.assertEqual(self.calendar.updated, [])

    async def test_task_edit_approval_updates_calendar_task(self) -> None:
        proposal = await self.client.post(
            "/tools/tasks/edit/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-edit-2",
                "profile": "main",
                "uid": "TASK-1",
                "taskTitle": "Call mom",
                "title": "Call dad",
                "memo": "monthly",
                "dueDate": "2026-08-20",
                "dueTime": "14:30",
                "priority": "1",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["task"]["action"], "edit")
        self.assertEqual(self.calendar.updated[0][0], "main")
        self.assertEqual(self.calendar.updated[0][1]["uid"], "TASK-1")
        self.assertEqual(self.calendar.updated[0][1]["title"], "Call dad")
        self.assertEqual(self.calendar.updated[0][1]["memo"], "monthly")
        self.assertEqual(self.calendar.updated[0][1]["dueDate"], "2026-08-20")
        self.assertEqual(self.calendar.updated[0][1]["dueTime"], "14:30")
        self.assertEqual(self.calendar.updated[0][1]["priority"], "1")
        self.assertEqual(self.calendar_refresh_count, 1)

    async def test_task_edit_strips_supplies_due_dates(self) -> None:
        self.calendar.tasks.append(
            {
                "uid": "SUPPLY-1",
                "summary": "Soap",
                "due": "2026-08-17",
                "dueTime": "10:00",
                "status": "NEEDS-ACTION",
                "collection": "supplies:abc",
            }
        )
        proposal = await self.client.post(
            "/tools/tasks/edit/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-edit-supply-1",
                "profile": "supplies",
                "collectionId": "supplies:abc",
                "uid": "SUPPLY-1",
                "taskTitle": "Soap",
                "title": "Hand soap",
                "memo": "bath",
                "dueDate": "2026-08-20",
                "dueTime": "14:30",
                "priority": "1",
            },
        )
        self.assertEqual(proposal.status, 201)
        proposal_payload = await proposal.json()
        self.assertEqual(proposal_payload["task"]["due"], "")
        confirmation_id = proposal_payload["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(self.calendar.updated[0][1]["title"], "Hand soap")
        self.assertEqual(self.calendar.updated[0][1]["dueDate"], "")
        self.assertEqual(self.calendar.updated[0][1]["dueTime"], "")
        self.assertEqual(self.calendar.updated[0][1]["priority"], "")

    async def test_task_create_proposal_requires_confirmation_before_write(self) -> None:
        response = await self.client.post(
            "/tools/tasks/create/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-create-1",
                "profile": "main",
                "title": "Call school",
                "dueDate": "2026-08-17",
                "dueTime": "10:00",
            },
        )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertTrue(payload["confirmationId"].startswith("conf_"))
        self.assertEqual(payload["task"]["title"], "Call school")
        self.assertEqual(payload["task"]["due"], "2026-08-17")
        self.assertEqual(self.calendar.created, [])

    async def test_task_create_approval_creates_calendar_task(self) -> None:
        proposal = await self.client.post(
            "/tools/tasks/create/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-create-2",
                "profile": "main",
                "title": "Call school",
                "dueDate": "2026-08-17",
                "dueTime": "10:00",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["task"]["uid"], "TASK-CREATED-1")
        self.assertEqual(self.calendar.created[0][0], "main")
        self.assertEqual(self.calendar.created[0][1]["title"], "Call school")
        self.assertEqual(self.calendar.created[0][1]["dueDate"], "2026-08-17")
        self.assertEqual(self.calendar_refresh_count, 1)

    async def test_task_create_allows_personal_task_without_due_date(self) -> None:
        proposal = await self.client.post(
            "/tools/tasks/create/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-create-no-due-1",
                "profile": "main",
                "title": "오도리 문고리",
            },
        )
        self.assertEqual(proposal.status, 201)
        proposal_payload = await proposal.json()
        self.assertEqual(proposal_payload["task"]["title"], "오도리 문고리")
        self.assertEqual(proposal_payload["task"]["due"], "")
        self.assertEqual(proposal_payload["task"]["dueTime"], "")
        confirmation_id = proposal_payload["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(self.calendar.created[0][0], "main")
        self.assertEqual(self.calendar.created[0][1]["title"], "오도리 문고리")
        self.assertEqual(self.calendar.created[0][1]["dueDate"], "")
        self.assertEqual(self.calendar.created[0][1]["dueTime"], "")

    async def test_task_create_approval_preserves_collection_id(self) -> None:
        proposal = await self.client.post(
            "/tools/tasks/create/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-create-supplies-1",
                "profile": "supplies",
                "collectionId": "supplies:abc",
                "title": "Toothpaste",
            },
        )
        self.assertEqual(proposal.status, 201)
        proposal_payload = await proposal.json()
        self.assertEqual(proposal_payload["task"]["collectionId"], "supplies:abc")
        self.assertEqual(proposal_payload["task"]["due"], "")
        confirmation_id = proposal_payload["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(self.calendar.created[0][0], "supplies")
        self.assertEqual(self.calendar.created[0][1]["collectionId"], "supplies:abc")
        self.assertEqual(self.calendar.created[0][1]["dueDate"], "")
        self.assertEqual(self.calendar_refresh_count, 1)

    async def test_task_create_strips_supplies_due_dates(self) -> None:
        proposal = await self.client.post(
            "/tools/tasks/create/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-create-supplies-2",
                "profile": "supplies",
                "collectionId": "supplies:abc",
                "title": "Toothbrush",
                "dueDate": "2026-08-17",
                "dueTime": "10:00",
            },
        )
        self.assertEqual(proposal.status, 201)
        proposal_payload = await proposal.json()
        self.assertEqual(proposal_payload["task"]["due"], "")
        self.assertEqual(proposal_payload["task"]["dueTime"], "")
        confirmation_id = proposal_payload["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(self.calendar.created[0][1]["collectionId"], "supplies:abc")
        self.assertEqual(self.calendar.created[0][1]["dueDate"], "")
        self.assertEqual(self.calendar.created[0][1]["dueTime"], "")

    async def test_task_due_update_rejects_supplies_collection(self) -> None:
        response = await self.client.post(
            "/tools/tasks/update-due/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-supplies-due-1",
                "profile": "supplies",
                "collectionId": "supplies:abc",
                "taskTitle": "Soap",
                "dueDate": "2026-08-17",
                "dueTime": "10:00",
            },
        )

        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"], "supplies_due_not_allowed")

    async def test_task_create_approval_rejects_wrong_actor(self) -> None:
        proposal = await self.client.post(
            "/tools/tasks/create/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-create-3",
                "profile": "main",
                "title": "Call school",
                "dueDate": "2026-08-17",
                "dueTime": "10:00",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "111"},
        )

        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"], "confirmation_actor_mismatch")
        self.assertEqual(self.calendar.created, [])

    async def test_event_create_proposal_requires_confirmation_before_write(self) -> None:
        response = await self.client.post(
            "/tools/events/create/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-event-create-1",
                "profile": "family",
                "title": "엔소쿠료칸",
                "startDate": "2026-08-15",
                "endDate": "2026-08-15",
                "allDay": True,
                "memo": "포항 조사리",
                "collectionId": "family:events",
            },
        )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertTrue(payload["confirmationId"].startswith("conf_"))
        self.assertEqual(payload["event"]["title"], "엔소쿠료칸")
        self.assertEqual(payload["event"]["startDate"], "2026-08-15")
        self.assertEqual(payload["event"]["memo"], "포항 조사리")
        self.assertEqual(payload["event"]["collectionId"], "family:events")
        self.assertEqual(self.calendar.created_events, [])

    async def test_event_create_approval_creates_family_event(self) -> None:
        proposal = await self.client.post(
            "/tools/events/create/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-event-create-2",
                "profile": "family",
                "title": "엔소쿠료칸",
                "startDate": "2026-08-15",
                "endDate": "2026-08-15",
                "allDay": True,
                "memo": "포항 조사리",
                "collectionId": "family:events",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["event"]["uid"], "EVENT-CREATED-1")
        self.assertEqual(self.calendar.created_events[0][0], "family")
        self.assertEqual(
            self.calendar.created_events[0][1],
            {
                "title": "엔소쿠료칸",
                "startDate": "2026-08-15",
                "endDate": "2026-08-15",
                "allDay": True,
                "memo": "포항 조사리",
                "collectionId": "family:events",
            },
        )
        self.assertEqual(self.calendar_refresh_count, 1)

    async def test_task_complete_proposal_requires_confirmation_before_write(self) -> None:
        response = await self.client.post(
            "/tools/tasks/action/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-complete-1",
                "profile": "main",
                "taskTitle": "Call mom",
                "action": "complete",
            },
        )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertEqual(payload["task"]["title"], "Call mom")
        self.assertEqual(payload["task"]["action"], "complete")
        self.assertEqual(self.calendar.updated, [])

    async def test_task_complete_approval_marks_task_completed(self) -> None:
        proposal = await self.client.post(
            "/tools/tasks/action/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-complete-2",
                "profile": "main",
                "taskTitle": "Call mom",
                "action": "complete",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["task"]["action"], "complete")
        self.assertEqual(self.calendar.updated[0][1]["uid"], "TASK-1")
        self.assertEqual(self.calendar.updated[0][1]["status"], "COMPLETED")
        self.assertEqual(self.calendar_refresh_count, 1)

    async def test_task_action_filters_by_collection_id(self) -> None:
        self.calendar.tasks.append(
            {
                "uid": "SUPPLY-1",
                "summary": "Soap",
                "status": "NEEDS-ACTION",
                "collection": "supplies:abc",
            }
        )
        proposal = await self.client.post(
            "/tools/tasks/action/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-complete-supplies-1",
                "profile": "supplies",
                "collectionId": "supplies:abc",
                "taskTitle": "Soap",
                "action": "complete",
            },
        )
        self.assertEqual(proposal.status, 201)
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(self.calendar.updated[0][0], "supplies")
        self.assertEqual(self.calendar.updated[0][1]["uid"], "SUPPLY-1")
        self.assertEqual(self.calendar.updated[0][1]["collectionId"], "supplies:abc")

    async def test_task_delete_approval_deletes_calendar_task(self) -> None:
        proposal = await self.client.post(
            "/tools/tasks/action/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-delete-1",
                "profile": "main",
                "taskTitle": "Call mom",
                "action": "delete",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["task"]["action"], "delete")
        self.assertEqual(self.calendar.deleted, [("main", "TASK-1", "zin:tasks")])
        self.assertEqual(self.calendar_refresh_count, 1)

    async def test_task_reopen_proposal_matches_completed_tasks_only(self) -> None:
        response = await self.client.post(
            "/tools/tasks/action/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-reopen-1",
                "profile": "main",
                "taskTitle": "Done lately",
                "action": "reopen",
            },
        )

        self.assertEqual(response.status, 201)
        payload = await response.json()
        self.assertEqual(payload["task"]["title"], "Done lately")
        self.assertEqual(payload["task"]["action"], "reopen")
        self.assertEqual(self.calendar.updated, [])

    async def test_task_reopen_approval_marks_task_needs_action(self) -> None:
        proposal = await self.client.post(
            "/tools/tasks/action/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-reopen-2",
                "profile": "main",
                "taskTitle": "Done lately",
                "action": "reopen",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "994579996960104529"},
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["task"]["action"], "reopen")
        self.assertEqual(self.calendar.updated[0][1]["uid"], "TASK-4")
        self.assertEqual(self.calendar.updated[0][1]["status"], "NEEDS-ACTION")

    async def test_task_action_approval_rejects_wrong_actor(self) -> None:
        proposal = await self.client.post(
            "/tools/tasks/action/proposals",
            headers=self.headers(),
            json={
                "actorId": "994579996960104529",
                "idempotencyKey": "discord-message-complete-3",
                "profile": "main",
                "taskTitle": "Call mom",
                "action": "complete",
            },
        )
        confirmation_id = (await proposal.json())["confirmationId"]

        response = await self.client.post(
            f"/tools/confirmations/{confirmation_id}/approve",
            headers=self.headers(),
            json={"actorId": "111"},
        )

        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"], "confirmation_actor_mismatch")
        self.assertEqual(self.calendar.updated, [])


if __name__ == "__main__":
    unittest.main()
