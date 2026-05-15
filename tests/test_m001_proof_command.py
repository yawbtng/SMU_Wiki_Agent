from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "m001_proof.py"
CONFIG = REPO_ROOT / "configs" / "m001_v1.json"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "m001_proof"


class M001ProofCommandTests(unittest.TestCase):
    def _run(self, run_root: Path) -> tuple[subprocess.CompletedProcess[str], Path]:
        out_dir = Path(tempfile.mkdtemp(prefix="m001-proof-"))
        completed = subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--config",
                str(CONFIG),
                "--run-root",
                str(run_root),
                "--output-dir",
                str(out_dir),
            ],
            cwd=REPO_ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        return completed, out_dir

    def test_pass_fixture_returns_success_and_writes_reports(self) -> None:
        run_root = FIXTURES / "pass" / "run_root"
        completed, out_dir = self._run(run_root)

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)

        result_json = out_dir / "proof_result.json"
        result_md = out_dir / "proof_report.md"

        self.assertTrue(result_json.exists())
        self.assertTrue(result_md.exists())

        payload = json.loads(result_json.read_text(encoding="utf-8"))
        self.assertEqual(payload["overall_verdict"], "pass")
        check_ids = {row["check_id"] for row in payload["checks"]}
        self.assertEqual(check_ids, {"S03_STALE_PACKET", "S04_MAINTENANCE_ARTIFACTS", "S05_PDF_CONTRACTS"})

    def test_missing_artifact_fails_with_targeted_check_id(self) -> None:
        run_root = FIXTURES / "fail_missing" / "run_root"
        completed, out_dir = self._run(run_root)

        self.assertNotEqual(completed.returncode, 0)

        payload = json.loads((out_dir / "proof_result.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["overall_verdict"], "fail")
        s04 = next(row for row in payload["checks"] if row["check_id"] == "S04_MAINTENANCE_ARTIFACTS")
        self.assertEqual(s04["status"], "fail")
        self.assertEqual(s04["reason"], "missing_artifact")

    def test_malformed_pdf_chunk_fails_with_targeted_reason(self) -> None:
        run_root = FIXTURES / "fail_malformed" / "run_root"
        s03_src = FIXTURES / "pass" / "run_root" / "s03"
        s04_src = FIXTURES / "pass" / "run_root" / "s04"
        run_root_s03 = run_root / "s03"
        run_root_s04 = run_root / "s04"
        run_root_s03.mkdir(parents=True, exist_ok=True)
        run_root_s04.mkdir(parents=True, exist_ok=True)
        (run_root_s03 / "stale_packet.json").write_text((s03_src / "stale_packet.json").read_text(encoding="utf-8"), encoding="utf-8")

        import shutil

        if (run_root_s04 / "maintenance").exists():
            shutil.rmtree(run_root_s04 / "maintenance")
        shutil.copytree(s04_src / "maintenance", run_root_s04 / "maintenance")

        completed, out_dir = self._run(run_root)
        self.assertNotEqual(completed.returncode, 0)

        payload = json.loads((out_dir / "proof_result.json").read_text(encoding="utf-8"))
        s05 = next(row for row in payload["checks"] if row["check_id"] == "S05_PDF_CONTRACTS")
        self.assertEqual(s05["status"], "fail")
        self.assertEqual(s05["reason"], "missing_page_number")


if __name__ == "__main__":
    unittest.main()
