from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigV1ValidationError(ValueError):
    """Raised when V1 config validation fails with field-level diagnostics."""


@dataclass(frozen=True)
class MaintenanceConfig:
    enabled: bool
    max_stale_pages: int


@dataclass(frozen=True)
class RetrievalConfig:
    top_k: int
    max_evidence_items: int


@dataclass(frozen=True)
class PdfConfig:
    max_pages_per_pdf: int
    max_pdf_mb: int


@dataclass(frozen=True)
class ZvecConfig:
    enabled: bool
    max_results: int


@dataclass(frozen=True)
class M001ConfigV1:
    maintenance: MaintenanceConfig
    retrieval: RetrievalConfig
    pdf: PdfConfig
    zvec: ZvecConfig


_REQUIRED_SECTIONS = ("maintenance", "retrieval", "pdf", "zvec")


def _expect_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigV1ValidationError(f"{path}: expected object")
    return value


def _expect_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigV1ValidationError(f"{path}: expected boolean")
    return value


def _expect_int(value: Any, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigV1ValidationError(f"{path}: expected integer")
    return value


def _bounded_int(value: Any, path: str, *, minimum: int, maximum: int) -> int:
    parsed = _expect_int(value, path)
    if parsed < minimum or parsed > maximum:
        raise ConfigV1ValidationError(
            f"{path}: expected {minimum} <= value <= {maximum}, got {parsed}"
        )
    return parsed


def _require_key(section: dict[str, Any], section_path: str, key: str) -> Any:
    if key not in section:
        raise ConfigV1ValidationError(f"{section_path}.{key}: missing required key")
    return section[key]


def parse_config_v1(payload: dict[str, Any]) -> M001ConfigV1:
    root = _expect_dict(payload, "$")

    for section_name in _REQUIRED_SECTIONS:
        if section_name not in root:
            raise ConfigV1ValidationError(f"$.{section_name}: missing required section")

    maintenance_raw = _expect_dict(root["maintenance"], "$.maintenance")
    retrieval_raw = _expect_dict(root["retrieval"], "$.retrieval")
    pdf_raw = _expect_dict(root["pdf"], "$.pdf")
    zvec_raw = _expect_dict(root["zvec"], "$.zvec")

    maintenance = MaintenanceConfig(
        enabled=_expect_bool(_require_key(maintenance_raw, "$.maintenance", "enabled"), "$.maintenance.enabled"),
        max_stale_pages=_bounded_int(
            _require_key(maintenance_raw, "$.maintenance", "max_stale_pages"),
            "$.maintenance.max_stale_pages",
            minimum=1,
            maximum=500,
        ),
    )

    retrieval = RetrievalConfig(
        top_k=_bounded_int(
            _require_key(retrieval_raw, "$.retrieval", "top_k"),
            "$.retrieval.top_k",
            minimum=1,
            maximum=50,
        ),
        max_evidence_items=_bounded_int(
            _require_key(retrieval_raw, "$.retrieval", "max_evidence_items"),
            "$.retrieval.max_evidence_items",
            minimum=1,
            maximum=20,
        ),
    )

    pdf = PdfConfig(
        max_pages_per_pdf=_bounded_int(
            _require_key(pdf_raw, "$.pdf", "max_pages_per_pdf"),
            "$.pdf.max_pages_per_pdf",
            minimum=1,
            maximum=200,
        ),
        max_pdf_mb=_bounded_int(
            _require_key(pdf_raw, "$.pdf", "max_pdf_mb"),
            "$.pdf.max_pdf_mb",
            minimum=1,
            maximum=100,
        ),
    )

    zvec = ZvecConfig(
        enabled=_expect_bool(_require_key(zvec_raw, "$.zvec", "enabled"), "$.zvec.enabled"),
        max_results=_bounded_int(
            _require_key(zvec_raw, "$.zvec", "max_results"),
            "$.zvec.max_results",
            minimum=1,
            maximum=20,
        ),
    )

    return M001ConfigV1(
        maintenance=maintenance,
        retrieval=retrieval,
        pdf=pdf,
        zvec=zvec,
    )


def load_config_v1(path: str | Path) -> M001ConfigV1:
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigV1ValidationError(f"$: config file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigV1ValidationError(f"$: invalid JSON ({exc.msg})") from exc

    if not isinstance(raw, dict):
        raise ConfigV1ValidationError("$: expected top-level object")
    return parse_config_v1(raw)
