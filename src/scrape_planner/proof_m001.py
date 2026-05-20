from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config_v1 import M001ConfigV1


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    status: str
    reason: str
    details: dict[str, Any]
    timestamp: str


@dataclass(frozen=True)
class ProofResult:
    run_root: str
    generated_at: str
    checks: list[CheckResult]
    overall_verdict: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fail(check_id: str, reason: str, details: dict[str, Any]) -> CheckResult:
    return CheckResult(check_id=check_id, status="fail", reason=reason, details=details, timestamp=_now_iso())


def _pass(check_id: str, reason: str, details: dict[str, Any]) -> CheckResult:
    return CheckResult(check_id=check_id, status="pass", reason=reason, details=details, timestamp=_now_iso())


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def check_s03_stale_packet(run_root: Path, config: M001ConfigV1) -> CheckResult:
    check_id = "S03_STALE_PACKET"
    stale_packet = run_root / "s03" / "stale_packet.json"
    if not stale_packet.exists():
        return _fail(check_id, "missing_artifact", {"path": str(stale_packet)})

    try:
        payload = _read_json(stale_packet)
    except Exception as exc:
        return _fail(check_id, "invalid_json", {"path": str(stale_packet), "error": str(exc)})

    if not isinstance(payload, dict):
        return _fail(check_id, "malformed_packet", {"path": str(stale_packet), "expected": "object"})

    reason = payload.get("reason")
    if reason != "source_hash_changed":
        return _fail(
            check_id,
            "reason_mismatch",
            {"path": str(stale_packet), "expected": "source_hash_changed", "actual": reason},
        )

    evidence = payload.get("evidence_refs")
    if not isinstance(evidence, list):
        return _fail(check_id, "malformed_evidence_refs", {"path": str(stale_packet), "expected": "list"})

    if len(evidence) > config.retrieval.max_evidence_items:
        return _fail(
            check_id,
            "evidence_refs_exceeds_bound",
            {
                "path": str(stale_packet),
                "count": len(evidence),
                "max_allowed": config.retrieval.max_evidence_items,
            },
        )

    return _pass(check_id, "source_hash_changed", {"path": str(stale_packet), "evidence_count": len(evidence)})


def check_s04_maintenance_artifacts(run_root: Path) -> CheckResult:
    check_id = "S04_MAINTENANCE_ARTIFACTS"
    job_root = run_root / "s04" / "maintenance" / "job-001"

    required = [
        "page.md",
        "manifest.json",
        "source_map.json",
        "source_usage.json",
        "events.jsonl",
        "result.json",
        "handoff.md",
    ]
    missing = [name for name in required if not (job_root / name).exists()]
    if missing:
        return _fail(check_id, "missing_artifact", {"job_root": str(job_root), "missing": missing})

    return _pass(check_id, "all_artifacts_present", {"job_root": str(job_root), "artifacts": required})


def check_s05_pdf_contracts(run_root: Path) -> CheckResult:
    check_id = "S05_PDF_CONTRACTS"
    chunks_path = run_root / "s05" / "pdf_chunks.jsonl"
    quarantine_path = run_root / "s05" / "pdf_quarantine.jsonl"

    if not chunks_path.exists():
        return _fail(check_id, "missing_artifact", {"path": str(chunks_path)})
    if not quarantine_path.exists():
        return _fail(check_id, "missing_artifact", {"path": str(quarantine_path)})

    try:
        chunks = _read_jsonl(chunks_path)
    except Exception as exc:
        return _fail(check_id, "invalid_jsonl", {"path": str(chunks_path), "error": str(exc)})

    for idx, row in enumerate(chunks):
        if not isinstance(row, dict) or "page_number" not in row:
            return _fail(
                check_id,
                "missing_page_number",
                {"path": str(chunks_path), "row_index": idx},
            )

    try:
        quarantined = _read_jsonl(quarantine_path)
    except Exception as exc:
        return _fail(check_id, "invalid_jsonl", {"path": str(quarantine_path), "error": str(exc)})

    for idx, row in enumerate(quarantined):
        if not isinstance(row, dict):
            return _fail(check_id, "malformed_quarantine_row", {"path": str(quarantine_path), "row_index": idx})
        if row.get("reason") != "unsupported_content_type":
            return _fail(
                check_id,
                "quarantine_reason_mismatch",
                {
                    "path": str(quarantine_path),
                    "row_index": idx,
                    "expected": "unsupported_content_type",
                    "actual": row.get("reason"),
                },
            )

    return _pass(
        check_id,
        "pdf_contracts_valid",
        {
            "chunks_path": str(chunks_path),
            "chunk_count": len(chunks),
            "quarantine_path": str(quarantine_path),
            "quarantine_count": len(quarantined),
        },
    )


def run_proof(run_root: Path, config: M001ConfigV1) -> ProofResult:
    checks = [
        check_s03_stale_packet(run_root, config),
        check_s04_maintenance_artifacts(run_root),
        check_s05_pdf_contracts(run_root),
    ]
    verdict = "pass" if all(check.status == "pass" for check in checks) else "fail"
    return ProofResult(run_root=str(run_root), generated_at=_now_iso(), checks=checks, overall_verdict=verdict)


def proof_result_to_json(result: ProofResult) -> dict[str, Any]:
    return {
        "run_root": result.run_root,
        "generated_at": result.generated_at,
        "overall_verdict": result.overall_verdict,
        "checks": [asdict(check) for check in result.checks],
    }


def proof_result_to_markdown(result: ProofResult) -> str:
    lines = [
        "# M001 Proof Report",
        "",
        f"- Run root: `{result.run_root}`",
        f"- Generated at: `{result.generated_at}`",
        f"- Overall verdict: **{result.overall_verdict.upper()}**",
        "",
        "| Check ID | Status | Reason | Timestamp |",
        "|---|---|---|---|",
    ]
    for check in result.checks:
        lines.append(
            f"| `{check.check_id}` | {check.status} | `{check.reason}` | `{check.timestamp}` |"
        )

    lines.append("")
    lines.append("## Details")
    lines.append("")
    for check in result.checks:
        lines.append(f"### {check.check_id}")
        lines.append("")
        lines.append(f"- Status: `{check.status}`")
        lines.append(f"- Reason: `{check.reason}`")
        lines.append(f"- Timestamp: `{check.timestamp}`")
        lines.append("- Details:")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(check.details, indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)
