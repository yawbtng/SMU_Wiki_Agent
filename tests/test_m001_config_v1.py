import json
import tempfile
import unittest
from pathlib import Path

from src.scrape_planner.config_v1 import (
    ConfigV1ValidationError,
    load_config_v1,
    parse_config_v1,
)


class TestM001ConfigV1(unittest.TestCase):
    def _valid_payload(self):
        return {
            "maintenance": {"enabled": True, "max_stale_pages": 100},
            "retrieval": {"top_k": 5, "max_evidence_items": 8},
            "pdf": {"max_pages_per_pdf": 50, "max_pdf_mb": 20},
            "zvec": {"enabled": True, "max_results": 5},
        }

    def test_parse_valid_config(self):
        config = parse_config_v1(self._valid_payload())
        self.assertEqual(config.retrieval.top_k, 5)
        self.assertEqual(config.pdf.max_pdf_mb, 20)
        self.assertTrue(config.maintenance.enabled)

    def test_missing_required_section(self):
        payload = self._valid_payload()
        payload.pop("pdf")
        with self.assertRaises(ConfigV1ValidationError) as ctx:
            parse_config_v1(payload)
        self.assertIn("$.pdf: missing required section", str(ctx.exception))

    def test_missing_required_key(self):
        payload = self._valid_payload()
        payload["retrieval"].pop("top_k")
        with self.assertRaises(ConfigV1ValidationError) as ctx:
            parse_config_v1(payload)
        self.assertIn("$.retrieval.top_k: missing required key", str(ctx.exception))

    def test_invalid_bound(self):
        payload = self._valid_payload()
        payload["pdf"]["max_pages_per_pdf"] = 500
        with self.assertRaises(ConfigV1ValidationError) as ctx:
            parse_config_v1(payload)
        self.assertIn("$.pdf.max_pages_per_pdf", str(ctx.exception))

    def test_load_config_v1_from_file(self):
        payload = self._valid_payload()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m001_v1.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            cfg = load_config_v1(path)
            self.assertEqual(cfg.zvec.max_results, 5)


if __name__ == "__main__":
    unittest.main()
