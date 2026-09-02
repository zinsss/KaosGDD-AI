import json
import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from kaos_governor.fax import (
    FaxAction,
    FaxConfig,
    FaxError,
    FaxService,
    OfficeFaxConnectorClient,
    normalize_destination,
    parse_doneq,
    request_from_pdf,
)


class FaxTests(unittest.TestCase):
    def config(self, root: Path, *, baseline: bool = False) -> FaxConfig:
        return FaxConfig(
            enabled=True,
            message_intake=False,
            state_path=root / "state.json",
            queue_root=root / "queue",
            legacy_state_path=root / "queue" / "state.json",
            recvq=root / "hylafax" / "recvq",
            xferfaxlog=root / "hylafax" / "log" / "xferfaxlog",
            doneq=root / "hylafax" / "doneq",
            poll_seconds=5,
            minimum_file_age_seconds=0,
            max_pdf_bytes=1024,
            mark_existing_on_first_run=baseline,
            delete_source_on_success=True,
        )

    def request(self, **values):
        return request_from_pdf(
            destination=values.get("destination", "02-284-8302"),
            sender="discord:1",
            source_id=values.get("source_id", "discord:1:2:3:4"),
            filename=values.get("filename", "요청서.pdf"),
            pdf=values.get("pdf", b"%PDF-test"),
            max_bytes=1024,
        )

    def test_worker_owner_is_explicit_and_validated(self) -> None:
        config = FaxConfig.from_env({"FAX_LIFECYCLE_OWNER": "worker"})
        self.assertEqual(config.owner, "worker")
        with self.assertRaisesRegex(FaxError, "FAX_LIFECYCLE_OWNER"):
            FaxConfig.from_env({"FAX_LIFECYCLE_OWNER": "both"})

    def test_runtime_status_is_visible_to_a_separate_reader(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = FaxService(self.config(root))
            service.scan_actions()

            status = FaxService(self.config(root)).status()

        self.assertTrue(status["lastScanAt"])
        self.assertEqual(status["lastError"], "")
        self.assertEqual(status["owner"], "discord")

    def test_normalizes_domestic_and_country_code_numbers(self) -> None:
        self.assertEqual(normalize_destination("02-284-8302"), "022848302")
        self.assertEqual(normalize_destination("+82 2 284 8302"), "022848302")
        with self.assertRaises(FaxError):
            normalize_destination("1234")

    def test_submit_writes_bridge_manifest_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = FaxService(self.config(root))
            request = self.request()
            metadata = {"channelId": 10, "messageId": 20, "commandMessageId": 21}
            job, created = service.submit(request, metadata)
            duplicate, duplicate_created = service.submit(request, metadata)
            manifest = json.loads(
                (root / "queue" / "pending" / f"{job['jobId']}.json").read_text(encoding="utf-8")
            )

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(job["jobId"], duplicate["jobId"])
        self.assertEqual(manifest["pdfPath"], f"jobs/{job['jobId']}/document.pdf")
        self.assertEqual(manifest["destination"], "022848302")

    def test_connector_submit_uses_authenticated_http_contract(self) -> None:
        class Response:
            status = 202

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'{"status":"queued"}'

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = FaxConfig(
                **{
                    **self.config(root).__dict__,
                    "transport": "connector",
                    "connector_base_url": "http://office-fax:8098",
                    "connector_token": "not-a-real-token",
                }
            )
            urlopen = mock.Mock(return_value=Response())
            connector = OfficeFaxConnectorClient(config, urlopen=urlopen)

            result = connector.submit("job-1", self.request(), {"channelId": 10})

        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(result["status"], "queued")
        self.assertEqual(request.full_url, "http://office-fax:8098/v1/fax/jobs")
        self.assertEqual(request.get_header("Authorization"), "Bearer not-a-real-token")
        self.assertEqual(body["jobId"], "job-1")
        self.assertEqual(body["destination"], "022848302")
        self.assertEqual(body["pdfSha256"], self.request().pdf_sha256)
        self.assertIn("pdfBase64", body)

    def test_connector_transport_records_job_and_polls_status(self) -> None:
        class Connector:
            def __init__(self):
                self.submitted = []

            def submit(self, job_id, request, source_metadata):
                self.submitted.append((job_id, request, dict(source_metadata)))
                return {"status": "queued"}

            def job_status(self, job_id):
                return {
                    "status": "sent",
                    "hylafaxJobId": "42",
                    "completedAt": "2026-08-13T06:00:00Z",
                }

            def incoming_events(self):
                return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = FaxConfig(
                **{
                    **self.config(root).__dict__,
                    "transport": "connector",
                    "connector_base_url": "http://office-fax:8098",
                    "connector_token": "not-a-real-token",
                }
            )
            connector = Connector()
            service = FaxService(config, connector=connector)  # type: ignore[arg-type]
            service.scan_actions()
            job, created = service.submit(
                self.request(),
                {"channelId": 10, "messageId": 20, "commandMessageId": 21},
            )

            actions = service.scan_actions()

        self.assertTrue(created)
        self.assertEqual(job["status"], "queued")
        self.assertEqual(connector.submitted[0][0], job["jobId"])
        self.assertEqual(
            [action.kind for action in actions],
            ["notification", "notification", "notification", "cleanup"],
        )
        self.assertEqual(actions[2].content, "Fax successfully sent.")
        self.assertEqual(actions[-1].message_ids, (20, 21))

    def test_worker_owner_separates_discord_source_cleanup(self) -> None:
        class Connector:
            def submit(self, job_id, request, source_metadata):
                return {"status": "queued"}

            def job_status(self, job_id):
                return {
                    "status": "sent",
                    "hylafaxJobId": "42",
                    "completedAt": "2026-08-13T06:00:00Z",
                }

            def incoming_events(self):
                return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = FaxConfig(
                **{
                    **self.config(root).__dict__,
                    "message_intake": True,
                    "transport": "connector",
                    "connector_base_url": "http://office-fax:8098",
                    "connector_token": "not-a-real-token",
                    "owner": "worker",
                }
            )
            service = FaxService(config, connector=Connector())  # type: ignore[arg-type]
            service.submit(
                self.request(),
                {"channelId": 10, "messageId": 20, "commandMessageId": 21},
            )

            worker_actions = service.scan_actions()
            cleanup_actions = service.cleanup_actions()

        self.assertNotIn("cleanup", [action.kind for action in worker_actions])
        self.assertEqual([action.kind for action in cleanup_actions], ["cleanup"])
        self.assertEqual(cleanup_actions[0].message_ids, (20, 21))

    def test_recent_items_returns_outgoing_jobs_without_pdf_content(self) -> None:
        class Connector:
            def submit(self, job_id, request, source_metadata):
                return {"status": "sent", "hylafaxJobId": "42", "completedAt": "2026-08-13T06:00:00Z"}

            def job_status(self, job_id):
                return {"status": "sent", "hylafaxJobId": "42", "completedAt": "2026-08-13T06:00:00Z"}

            def incoming_events(self):
                return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = FaxConfig(
                **{
                    **self.config(root).__dict__,
                    "transport": "connector",
                    "connector_base_url": "http://office-fax:8098",
                    "connector_token": "not-a-real-token",
                }
            )
            service = FaxService(config, connector=Connector())  # type: ignore[arg-type]
            service.submit(self.request(filename="처방전.pdf"), {"channelId": 10, "messageId": 20})
            rows = service.recent_items()

        self.assertEqual(rows[0]["kind"], "fax")
        self.assertEqual(rows[0]["direction"], "outgoing")
        self.assertEqual(rows[0]["title"], "처방전.pdf")
        self.assertEqual(rows[0]["status"], "sent")
        self.assertEqual(rows[0]["destination"], "022848302")
        self.assertNotIn("pdf", {key.lower() for key in rows[0]})

    def test_failed_outgoing_job_can_be_acknowledged_for_ui_attention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.config(root)
            config.state_path.write_text(
                json.dumps(
                    {
                        "jobs": {
                            "failed-1": {
                                "status": "failed",
                                "destination": "05050750028",
                                "filename": "IMG_1074.pdf",
                                "error": "submission_failed",
                                "completedAt": "2026-09-02T10:00:00Z",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            service = FaxService(config)

            before = service.recent_items(limit=None)
            result = service.acknowledge_failed_job("failed-1")
            after = service.recent_items(limit=None)
            state = json.loads(config.state_path.read_text(encoding="utf-8"))

        self.assertFalse(before[0]["attentionAcknowledged"])
        self.assertEqual(result["attentionAcknowledged"], True)
        self.assertTrue(after[0]["attentionAcknowledged"])
        self.assertEqual(state["acknowledgedFailures"]["failed-1"]["error"], "submission_failed")

    def test_failed_job_ack_does_not_hide_changed_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.config(root)
            config.state_path.write_text(
                json.dumps(
                    {
                        "jobs": {
                            "failed-1": {
                                "status": "failed",
                                "destination": "05050750028",
                                "filename": "IMG_1074.pdf",
                                "error": "first_error",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            service = FaxService(config)
            service.acknowledge_failed_job("failed-1")
            state = json.loads(config.state_path.read_text(encoding="utf-8"))
            state["jobs"]["failed-1"]["error"] = "second_error"
            config.state_path.write_text(json.dumps(state), encoding="utf-8")

            row = FaxService(config).recent_items(limit=None)[0]

        self.assertFalse(row["attentionAcknowledged"])

    def test_connector_failed_job_can_recover_after_office_repair(self) -> None:
        class Connector:
            def __init__(self):
                self.status = {"status": "failed", "error": "fax_tiff_not_created"}

            def submit(self, job_id, request, source_metadata):
                return dict(self.status)

            def job_status(self, job_id):
                return dict(self.status)

            def incoming_events(self):
                return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = FaxConfig(
                **{
                    **self.config(root).__dict__,
                    "transport": "connector",
                    "connector_base_url": "http://office-fax:8098",
                    "connector_token": "not-a-real-token",
                }
            )
            connector = Connector()
            service = FaxService(config, connector=connector)  # type: ignore[arg-type]
            service.scan_actions()
            service.submit(
                self.request(),
                {"channelId": 10, "messageId": 20, "commandMessageId": 21},
            )
            for action in service.scan_actions():
                service.acknowledge(action)

            connector.status = {
                "status": "sent",
                "hylafaxJobId": "42",
                "completedAt": "2026-08-13T06:00:00Z",
            }
            actions = service.scan_actions()

        self.assertEqual([action.kind for action in actions], ["notification", "notification", "cleanup"])
        self.assertEqual(actions[0].content, "Sending fax.")
        self.assertEqual(actions[1].content, "Fax successfully sent.")
        self.assertEqual(actions[-1].message_ids, (20, 21))

    def test_connector_transport_delivers_incoming_pdf_events(self) -> None:
        class Connector:
            def incoming_events(self):
                return [
                    {
                        "eventId": "fax000000007.tif:4:1",
                        "filename": "2026-08-12-13:55_FROM_0547337787.pdf",
                        "remote": "0547337787",
                        "commid": "000000007",
                        "pages": "1",
                        "pdfBase64": "JVBERi1jb252ZXJ0ZWQ=",
                    }
                ]

            def job_status(self, job_id):
                return {"status": "queued"}

            def submit(self, job_id, request, source_metadata):
                return {"status": "queued"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = FaxConfig(
                **{
                    **self.config(root).__dict__,
                    "transport": "connector",
                    "connector_base_url": "http://office-fax:8098",
                    "connector_token": "not-a-real-token",
                }
            )
            service = FaxService(config, connector=Connector())  # type: ignore[arg-type]

            actions = service.scan_actions()
            service.acknowledge(actions[0])
            recent = service.recent_items()
            state_text = service.config.state_path.read_text(encoding="utf-8")

        self.assertEqual([action.kind for action in actions], ["archive"])
        self.assertEqual(actions[0].filename, "2026-08-12-13:55_FROM_0547337787.pdf")
        self.assertEqual(actions[0].content_bytes, b"%PDF-converted")
        self.assertEqual(recent[0]["kind"], "fax")
        self.assertEqual(recent[0]["direction"], "incoming")
        self.assertEqual(recent[0]["title"], "2026-08-12-13:55_FROM_0547337787.pdf")
        self.assertEqual(recent[0]["remote"], "0547337787")
        self.assertEqual(recent[0]["pages"], "1")
        self.assertNotIn("JVBERi1jb252ZXJ0ZWQ", state_text)

    def test_received_pdf_is_retained_for_authenticated_brain_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = FaxService(self.config(root))
            incoming = FaxAction(
                "incoming:archive:fax000000010.tif:308214:1787870178",
                "archive",
                filename="2026-08-28-07:32_FROM_07079664986.pdf",
                remote="07079664986",
                pages="1",
                received_at="2026-08-27T22:32:00Z",
            )
            record = service.store_incoming_document(incoming, b"%PDF-retained")
            service.acknowledge(incoming)
            payload = service.incoming_document(str(record["id"]))
            state_text = service.config.state_path.read_text(encoding="utf-8")

        self.assertEqual(payload["filename"], "2026-08-28-07:32_FROM_07079664986.pdf")
        self.assertEqual(base64.b64decode(str(payload["contentBase64"])), b"%PDF-retained")
        self.assertNotIn(base64.b64encode(b"%PDF-retained").decode("ascii"), state_text)

    def test_retained_pdf_reader_does_not_create_a_state_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fax_id = "a" * 32
            archive = root / "archive"
            archive.mkdir()
            (archive / f"{fax_id}.pdf").write_bytes(b"%PDF-read-only")
            (root / "state.json").write_text(
                json.dumps(
                    {
                        "incoming": {
                            fax_id: {
                                "filename": "received.pdf",
                                "documentPath": f"archive/{fax_id}.pdf",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            service = FaxService(self.config(root))

            document = service.incoming_document_bytes(fax_id)
            recent = service.recent_items(limit=None)

            self.assertEqual(document["content"], b"%PDF-read-only")
            self.assertTrue(recent[0]["hasDocument"])
            self.assertFalse((root / ".state.json.lock").exists())

    def test_retained_pdf_reader_rejects_paths_outside_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fax_id = "b" * 32
            (root / "outside.pdf").write_bytes(b"%PDF-outside")
            (root / "state.json").write_text(
                json.dumps(
                    {
                        "incoming": {
                            fax_id: {
                                "filename": "outside.pdf",
                                "documentPath": "outside.pdf",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            service = FaxService(self.config(root))

            with self.assertRaisesRegex(FaxError, "fax_document_not_found"):
                service.incoming_document_bytes(fax_id)

    def test_connector_token_can_be_loaded_from_secret_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / "token"
            token.write_text("secret-token\n", encoding="utf-8")

            config = FaxConfig.from_env(
                {
                    "FAX_TRANSPORT": "connector",
                    "FAX_CONNECTOR_BASE_URL": "http://office-fax:8098",
                    "FAX_CONNECTOR_TOKEN_FILE": str(token),
                }
            )

        self.assertEqual(config.transport, "connector")
        self.assertEqual(config.connector_token, "secret-token")

    def test_bridge_and_doneq_generate_lifecycle_archive_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = FaxService(self.config(root))
            service.scan_actions()  # Initialize an empty installation.
            job, _ = service.submit(
                self.request(),
                {"channelId": 10, "messageId": 20, "commandMessageId": 21},
            )
            result = root / "queue" / "results" / f"{job['jobId']}.json"
            result.parent.mkdir(parents=True)
            result.write_text(json.dumps({"status": "submitted", "hylafaxJobId": "42"}), encoding="utf-8")
            done = root / "hylafax" / "doneq" / "q42"
            done.parent.mkdir(parents=True)
            done.write_text("statuscode:0\nstate:7\nreturned:2\n", encoding="utf-8")

            actions = service.scan_actions()

        self.assertEqual(
            [action.kind for action in actions],
            ["notification", "notification", "notification", "archive", "cleanup"],
        )
        self.assertEqual(actions[2].content, "Fax successfully sent.")
        self.assertEqual(actions[-1].message_ids, (20, 21))

    def test_first_run_baselines_incoming_and_legacy_sent_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.config(root, baseline=True)
            config.recvq.mkdir(parents=True)
            (config.recvq / "fax000000007.tif").write_bytes(b"TIFF")
            document = config.queue_root / "jobs" / ("a" * 32) / "document.pdf"
            document.parent.mkdir(parents=True)
            document.write_bytes(b"%PDF-old")
            config.legacy_state_path.write_text(
                json.dumps(
                    {
                        "jobs": {
                            "a" * 32: {
                                "status": "sent",
                                "destination": "022848302",
                                "filename": "old.pdf",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            service = FaxService(config)

            first = service.scan_actions()
            second = service.scan_actions()
            delivered = service.status()["deliveredActions"]

        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertGreaterEqual(delivered, 5)

    def test_new_incoming_fax_carries_text_notification_for_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.config(root)
            service = FaxService(config)
            service.scan_actions()
            config.recvq.mkdir(parents=True)
            fax = config.recvq / "fax000000007.tif"
            fax.write_bytes(b"TIFF")
            config.xferfaxlog.parent.mkdir(parents=True)
            config.xferfaxlog.write_text(
                '08/12/26 13:55\tRECV\t000000007\tttyACM0\trecvq/fax000000007.tif\t""\tfax\t""\t"0547337787"\t9600\t1\n',
                encoding="utf-8",
            )

            actions = service.scan_actions()
            service.acknowledge(actions[0])
            recent = service.recent_items()

        self.assertEqual([action.kind for action in actions], ["archive"])
        self.assertEqual(actions[0].filename, "2026-08-12-13:55_FROM_0547337787.pdf")
        self.assertIn("Fax received.", actions[0].content)
        self.assertIn("Open #brain", actions[0].content)
        self.assertEqual(recent[0]["direction"], "incoming")
        self.assertEqual(recent[0]["remote"], "0547337787")
        self.assertEqual(recent[0]["pages"], "1")

    def test_doneq_compatibility_success_rule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q5"
            path.write_text("state:7\nreturned:2\n", encoding="utf-8")
            result = parse_doneq(path)
        self.assertTrue(result["sent"])


if __name__ == "__main__":
    unittest.main()
