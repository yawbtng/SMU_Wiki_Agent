import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
