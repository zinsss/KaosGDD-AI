from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import unittest

from aiohttp.test_utils import TestClient, TestServer
from kaos_governor.documents import PaperlessSearchPage, PaperlessSearchResult
from kaos_governor.memos import Memo, MemoSearchResult
from kaos_governor_discord.tools import BrainToolServer


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
        ]
        self.updated = []
        self.created = []
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
                    "due": payload.get("dueDate", task.get("due", "")),
                    "dueTime": payload.get("dueTime", task.get("dueTime", "")),
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

    def delete_task(self, profile, uid, collection_id):
        self.deleted.append((profile, uid, collection_id))
        self.tasks = [task for task in self.tasks if task.get("uid") != uid]
        return {"uid": uid}


class FakeMemos:
    def __init__(self) -> None:
        self.config = SimpleNamespace(enabled=True)
        self.search_calls = []
        self.get_calls = []

    def search(self, query, tags, limit):
        self.search_calls.append((query, tags, limit))
        memo = Memo("memos/42", "Secret body", ("server",), "created", "updated", "PRIVATE", True)
        return [MemoSearchResult(memo, "Search snippet")]

    def get(self, name):
        self.get_calls.append(name)
        return Memo(name, "Full memo body", ("server",), "created", "updated", "PRIVATE", False)


class FakePaperless:
    def __init__(self) -> None:
        self.search_calls = []

    def search_page(self, query, *, limit):
        self.search_calls.append((query, limit))
        return PaperlessSearchPage(
            query,
            (PaperlessSearchResult(42, "Rustdesk setup", "2026-08-14", "rustdesk.pdf"),),
            1,
            12,
        )


class BrainToolServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.calendar = FakeCalendarAdapter()
        self.memos = FakeMemos()
        self.paperless = FakePaperless()
        server = BrainToolServer(
            "127.0.0.1",
            8098,
            governor_api_token="governor-secret",
            calendar_adapter=self.calendar,  # type: ignore[arg-type]
            memos=self.memos,  # type: ignore[arg-type]
            paperless=self.paperless,  # type: ignore[arg-type]
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

    async def test_memos_search_returns_snippets_only(self) -> None:
        response = await self.client.get(
            "/tools/memos/search?query=rust%20desk&tag=server&limit=3",
            headers=self.headers(),
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["results"][0]["name"], "memos/42")
        self.assertNotIn("content", payload["results"][0])
        self.assertEqual(self.memos.search_calls, [("rust desk", ["server"], 3)])

    async def test_memo_get_returns_full_content(self) -> None:
        response = await self.client.get("/tools/memos/42", headers=self.headers())

        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["memo"]["content"], "Full memo body")
        self.assertEqual(self.memos.get_calls, ["memos/42"])

    async def test_document_search_returns_paperless_results(self) -> None:
        response = await self.client.get("/tools/documents/search?query=rust%20desk", headers=self.headers())

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["source"], "paperless-live")
        self.assertEqual(payload["results"][0]["title"], "Rustdesk setup")
        self.assertEqual(self.paperless.search_calls, [("rust desk", 5)])

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
