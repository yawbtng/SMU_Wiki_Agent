import json
import tempfile
import unittest
from pathlib import Path

from src.scrape_planner.runtime.state import RunStateStore
from src.scrape_planner.tracer_maintenance import run_tracer_maintenance_packet


class TestTracerMaintenanceContractAndWriters(unittest.TestCase):
    def test_valid_packet_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = {
                "job_id": "job-1",
                "target_page_id": "page.alpha",
                "target_page_path": "wiki/page-alpha.md",
                "stale_reason": "source_hash_changed",
                "source_hashes": {"src-1": "abc123"},
                "evidence_refs": [{"id": "ev1", "path": "sources/a.md", "snippet": "short excerpt"}],
            }
            result = run_tracer_maintenance_packet(root, payload)
            self.assertEqual(result["status"], "succeeded")

            job_root = root / "maintenance" / "job-1"
            self.assertTrue((job_root / "page.md").exists())
            self.assertTrue((job_root / "events.jsonl").exists())
            self.assertTrue((job_root / "source_usage.jsonl").exists())
            self.assertTrue((job_root / "result.json").exists())

            parsed = json.loads((job_root / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(parsed["status"], "succeeded")
            self.assertEqual(parsed["artifacts"]["source_map"], str(job_root / "source_map.json"))

    def test_malformed_packet_returns_failure_and_event(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = {
                "job_id": "job-bad",
                "target_page_id": "page.beta",
                "target_page_path": "wiki/page-beta.md",
                "stale_reason": "source_hash_changed",
                "source_hashes": {"src-2": "def456"},
                "evidence_refs": [{"id": "ev2", "raw_body": "this should be rejected"}],
            }
            result = run_tracer_maintenance_packet(root, payload)
            self.assertEqual(result["status"], "failed")
            self.assertIn("forbidden", result["error"]["message"])

            events = (root / "maintenance" / "job-bad" / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"event": "failed"', events)



class TestTracerMaintenanceExecutorE2E(unittest.TestCase):
    def test_executor_emits_full_artifact_chain_and_can_publish_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = {
                "job_id": "job-e2e-1",
                "target_page_id": "page.gamma",
                "target_page_path": "wiki/page-gamma.md",
                "stale_reason": "manual_revalidate",
                "source_hashes": {"src-9": "hash-999", "src-8": "hash-888"},
                "evidence_refs": [
                    {"id": "ev9", "path": "sources/c.md", "snippet": "bounded excerpt one"},
                    {"id": "ev8", "path": "sources/d.md", "snippet": "bounded excerpt two"},
                ],
            }

            result = run_tracer_maintenance_packet(root, payload)
            self.assertEqual(result["status"], "succeeded")

            job_root = root / "maintenance" / "job-e2e-1"
            expected_artifacts = {
                "page": job_root / "page.md",
                "events": job_root / "events.jsonl",
                "source_usage": job_root / "source_usage.jsonl",
                "source_map": job_root / "source_map.json",
            }
            for key, path in expected_artifacts.items():
                self.assertTrue(path.exists(), f"missing {key} artifact")
                self.assertEqual(result["artifacts"][key], str(path))

            self.assertTrue((job_root / "page_manifest.json").exists())
            self.assertTrue((job_root / "result.json").exists())

            source_usage_lines = (job_root / "source_usage.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(source_usage_lines), 2)
            for line in source_usage_lines:
                record = json.loads(line)
                self.assertNotIn("raw_body", record.get("source_ref", {}))
                self.assertIn("snippet", record.get("source_ref", {}))

            source_map = json.loads((job_root / "source_map.json").read_text(encoding="utf-8"))
            self.assertEqual(source_map["job_id"], "job-e2e-1")
            self.assertEqual([s["id"] for s in source_map["sources"]], ["src-8", "src-9"])

            events = [json.loads(line) for line in (job_root / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()]
            self.assertEqual(events[0]["event"], "started")
            self.assertEqual(events[-1]["event"], "succeeded")

            store = RunStateStore()
            site_id, run_id = "site-1", "run-1"
            store.set_status(site_id, run_id, {"state": "running", "job_id": "job-e2e-1"})
            store.push_event(site_id, run_id, {"event": "packet_succeeded", "job_id": "job-e2e-1"})
            store.set_pages(site_id, run_id, [{"id": "page.gamma", "path": "wiki/page-gamma.md"}])

            self.assertEqual(store.get_status(site_id, run_id).get("job_id"), "job-e2e-1")
            self.assertEqual(store.get_events(site_id, run_id)[0]["event"], "packet_succeeded")
            self.assertEqual(store.get_pages(site_id, run_id)[0]["id"], "page.gamma")


if __name__ == "__main__":
    unittest.main()
