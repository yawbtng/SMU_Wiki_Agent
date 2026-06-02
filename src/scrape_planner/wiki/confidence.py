from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

from .leadership import extract_leadership_from_evidence
from .query_intent import is_person_lookup_query

DEFAULT_MIN_SCORE_FUSED = 0.4
DEFAULT_MIN_GAP_FUSED = 0.05
DEFAULT_MIN_SCORE_RERANKED = 0.5
DEFAULT_MIN_GAP_RERANKED = 0.05


@dataclass(frozen=True)
class ConfidenceDecision:
    confident: bool
    decision: str
    reasons: list[str]
    min_score: float
    min_gap: float
    top_score: float
    top_two_gap: float
    citation_present: bool
    scoring_mode: str
    gated_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def confidence_thresholds_for_mode(mode: str) -> tuple[float, float]:
    if mode == "reranked":
        return (
            _float_env("RAG_CONFIDENCE_MIN_SCORE_RERANKED", DEFAULT_MIN_SCORE_RERANKED),
            _float_env("RAG_CONFIDENCE_MIN_GAP_RERANKED", DEFAULT_MIN_GAP_RERANKED),
        )
    return (
        _float_env("RAG_CONFIDENCE_MIN_SCORE_FUSED", DEFAULT_MIN_SCORE_FUSED),
        _float_env("RAG_CONFIDENCE_MIN_GAP_FUSED", DEFAULT_MIN_GAP_FUSED),
    )


def assess_confidence(
    result: dict[str, Any],
    *,
    question: str | None = None,
    min_score: float | None = None,
    min_gap: float | None = None,
) -> dict[str, Any]:
    evidence = result.get("evidence") if isinstance(result.get("evidence"), list) else []
    if question and is_person_lookup_query(question):
        leadership = extract_leadership_from_evidence(question, evidence)
        if leadership and leadership.confidence >= 0.8:
            return ConfidenceDecision(
                confident=True,
                decision="confident",
                reasons=["leadership_entity_match", "status_ok", "citation_present"],
                min_score=0.0,
                min_gap=0.0,
                top_score=1.0,
                top_two_gap=1.0,
                citation_present=any(_has_citation(item) for item in evidence if isinstance(item, dict)),
                scoring_mode=_detect_scoring_mode(evidence, result),
                gated_score=1.0,
            ).to_dict()
    scoring_mode = _detect_scoring_mode(evidence, result)
    score_threshold, gap_threshold = confidence_thresholds_for_mode(scoring_mode)
    if min_score is not None:
        score_threshold = min_score
    if min_gap is not None:
        gap_threshold = min_gap

    top_score, second_score = _mode_aware_scores(evidence, scoring_mode)
    gap = top_score - second_score if evidence else 0.0
    citation_present = any(_has_citation(item) for item in evidence if isinstance(item, dict))

    checks = {
        "status_ok": str(result.get("status") or "") == "ok",
        "top_score_ok": top_score >= score_threshold,
        "citation_present": citation_present,
        "top_two_gap_ok": gap >= gap_threshold,
    }
    reasons = [name for name, ok in checks.items() if ok]
    reasons.extend(f"missing_{name}" for name, ok in checks.items() if not ok)
    confident = all(checks.values())
    return ConfidenceDecision(
        confident=confident,
        decision="confident" if confident else "not_confident",
        reasons=reasons,
        min_score=score_threshold,
        min_gap=gap_threshold,
        top_score=round(top_score, 6),
        top_two_gap=round(gap, 6),
        citation_present=citation_present,
        scoring_mode=scoring_mode,
        gated_score=round(top_score, 6),
    ).to_dict()


def _detect_scoring_mode(evidence: list[Any], result: dict[str, Any]) -> str:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    retrieval = metadata.get("retrieval") if isinstance(metadata.get("retrieval"), dict) else {}
    if str(retrieval.get("reranker") or "").strip():
        return "reranked"
    for item in evidence:
        if not isinstance(item, dict):
            continue
        scores = item.get("scores") if isinstance(item.get("scores"), dict) else {}
        reasons = item.get("ranking_reasons") if isinstance(item.get("ranking_reasons"), list) else []
        if float(scores.get("model_rerank") or 0.0) > 0.0 or "openrouter_rerank" in reasons:
            return "reranked"
    return "fused"


def _mode_aware_scores(evidence: list[Any], scoring_mode: str) -> tuple[float, float]:
    if not evidence:
        return 0.0, 0.0
    if scoring_mode == "reranked":
        values = [_rerank_score(item) for item in evidence if isinstance(item, dict)]
        values = [value for value in values if value > 0.0] or [0.0]
        top = values[0] if values else 0.0
        second = values[1] if len(values) > 1 else 0.0
        return top, second
    fused_values = [_fused_score(item) for item in evidence if isinstance(item, dict)]
    if not fused_values:
        return 0.0, 0.0
    max_score = max(fused_values) or 1.0
    normalized = [value / max_score for value in fused_values]
    top = normalized[0]
    second = normalized[1] if len(normalized) > 1 else 0.0
    return top, second


def _rerank_score(item: dict[str, Any]) -> float:
    scores = item.get("scores") if isinstance(item.get("scores"), dict) else {}
    try:
        return float(scores.get("model_rerank") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _fused_score(item: dict[str, Any]) -> float:
    scores = item.get("scores") if isinstance(item.get("scores"), dict) else {}
    for key in ("combined", "retrieval_vector", "bm25", "lexical"):
        try:
            value = float(scores.get(key) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value:
            return value
    return 0.0


def _has_citation(item: dict[str, Any]) -> bool:
    if str(item.get("source_id") or "") and item.get("source_kind") != "wiki":
        return True
    source_ids = item.get("source_ids")
    if isinstance(source_ids, list) and any(str(value).strip() for value in source_ids):
        return True
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    if str(metadata.get("original_url") or metadata.get("original_path") or "").strip():
        return True
    provenance = metadata.get("provenance") if isinstance(metadata.get("provenance"), dict) else {}
    return bool(str(provenance.get("url") or provenance.get("source_url") or "").strip())


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default
