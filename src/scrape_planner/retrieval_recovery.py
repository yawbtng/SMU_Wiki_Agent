from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests

from .observability import append_event
from .storage import read_json, write_json


ANSWERABLE = "corpus_answerable"
NEEDS_WEB_RECOVERY = "needs_web_recovery"
UNANSWERABLE_AFTER_RECOVERY = "unanswerable_after_recovery"


@dataclass
class CorpusDocument:
    url: str
    title: str
    path: str
    text: str
    source: str
    links: list[str] = field(default_factory=list)


@dataclass
class Evidence:
    url: str
    title: str
    path: str
    snippet: str
    score: float
    source: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class RetrievalDecision:
    state: str
    question: str
    evidence: list[Evidence]
    closest: list[Evidence]
    recovery: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "question": self.question,
            "evidence": [asdict(item) for item in self.evidence],
            "closest": [asdict(item) for item in self.closest],
            "recovery": self.recovery,
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()
    path = parsed.path.rstrip("/") or "/"
    return parsed._replace(path=path, fragment="").geturl()


def _title_from_markdown(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
    return fallback


def _extract_markdown_links(text: str, base_url: str) -> list[str]:
    links: list[str] = []
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
        href = match.group(1).strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        links.append(_normalize_url(urljoin(base_url, href)))
    return list(dict.fromkeys(links))


def _load_manifest_docs(run_root: Path) -> list[CorpusDocument]:
    docs: list[CorpusDocument] = []
    seen_paths: set[str] = set()

    scrape_manifest = read_json(run_root / "scrape_manifest.json", [])
    for row in scrape_manifest if isinstance(scrape_manifest, list) else []:
        if not isinstance(row, dict) or str(row.get("status") or "").lower() != "success":
            continue
        path = Path(str(row.get("markdown_path") or ""))
        if not path.exists() or str(path) in seen_paths:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        url = str(row.get("url") or "")
        docs.append(
            CorpusDocument(
                url=url,
                title=_title_from_markdown(text, path.stem),
                path=str(path),
                text=text,
                source="raw_markdown",
                links=_extract_markdown_links(text, url),
            )
        )
        seen_paths.add(str(path))

    cleanup_manifest = read_json(run_root / "cleanup_manifest.json", [])
    for row in cleanup_manifest if isinstance(cleanup_manifest, list) else []:
        if not isinstance(row, dict) or str(row.get("status") or "").lower() != "cleaned":
            continue
        path = Path(str(row.get("cleaned_markdown_path") or ""))
        if not path.exists() or str(path) in seen_paths:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        url = str(row.get("url") or "")
        docs.append(
            CorpusDocument(
                url=url,
                title=str(row.get("title") or _title_from_markdown(text, path.stem)),
                path=str(path),
                text=text,
                source="cleaned_markdown",
                links=_extract_markdown_links(text, url),
            )
        )
        seen_paths.add(str(path))

    wiki_root = run_root / "wiki"
    if wiki_root.exists():
        for path in sorted(wiki_root.rglob("*.md")):
            if str(path) in seen_paths:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            docs.append(
                CorpusDocument(
                    url="",
                    title=_title_from_markdown(text, path.stem),
                    path=str(path),
                    text=text,
                    source="wiki",
                    links=_extract_markdown_links(text, ""),
                )
            )
            seen_paths.add(str(path))
    return docs


def load_corpus(run_root: Path) -> list[CorpusDocument]:
    return _load_manifest_docs(run_root)


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
}


def _terms(query: str) -> list[str]:
    terms = [item.lower() for item in re.findall(r"[A-Za-z][A-Za-z0-9&'-]{2,}", query)]
    return [item for item in terms if item not in _STOPWORDS]


def _phrases(query: str) -> list[str]:
    quoted = re.findall(r'"([^"]+)"', query)
    titleish = re.findall(r"\b[A-Z][A-Za-z0-9&'-]*(?:\s+[A-Z][A-Za-z0-9&'-]*)+\b", query)
    return [item.lower() for item in quoted + titleish if len(item.split()) >= 2]


def _window_snippet(text: str, terms: Iterable[str], *, size: int = 420) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""
    lowered = compact.lower()
    positions = [lowered.find(term.lower()) for term in terms if term and lowered.find(term.lower()) >= 0]
    start = max(min(positions) - 140, 0) if positions else 0
    snippet = compact[start : start + size].strip()
    return snippet


def _score_doc(query: str, doc: CorpusDocument) -> tuple[float, list[str]]:
    terms = _terms(query)
    phrases = _phrases(query)
    haystacks = {
        "title": doc.title.lower(),
        "url": doc.url.lower(),
        "path": doc.path.lower(),
        "body": doc.text.lower(),
    }
    score = 0.0
    reasons: list[str] = []
    for term in terms:
        body_count = haystacks["body"].count(term)
        if body_count:
            score += min(body_count, 6) * 1.0
            reasons.append(f"body:{term}")
        if term in haystacks["title"]:
            score += 4.0
            reasons.append(f"title:{term}")
        if term in haystacks["url"]:
            score += 3.0
            reasons.append(f"url:{term}")
        if term in haystacks["path"]:
            score += 1.5
            reasons.append(f"path:{term}")
    for phrase in phrases:
        if phrase in haystacks["body"]:
            score += 8.0
            reasons.append(f"phrase:{phrase}")
        if phrase in haystacks["title"] or phrase in haystacks["url"]:
            score += 6.0
            reasons.append(f"field_phrase:{phrase}")
    return score, list(dict.fromkeys(reasons))


def _supports_answer(question: str, evidence: Evidence) -> bool:
    blob = f"{evidence.title}\n{evidence.url}\n{evidence.snippet}".lower()
    terms = _terms(question)
    if not terms:
        return bool(evidence.snippet)
    critical = [
        term
        for term in terms
        if term
        in {
            "director",
            "chair",
            "deadline",
            "tuition",
            "cost",
            "fee",
            "fees",
            "admission",
            "admissions",
            "requirement",
            "requirements",
            "contact",
            "email",
            "phone",
        }
    ]
    if critical and not all(term in blob for term in critical):
        return False
    phrases = _phrases(question)
    important_phrases = [phrase for phrase in phrases if len(phrase.split()) >= 2]
    if important_phrases and not any(phrase in blob for phrase in important_phrases):
        return False
    matched = sum(1 for term in terms if term in blob)
    return matched / max(len(terms), 1) >= 0.5


def _same_unit(a: str, b: str) -> bool:
    if not a or not b:
        return False
    pa = [part for part in urlparse(a).path.split("/") if part]
    pb = [part for part in urlparse(b).path.split("/") if part]
    return len(pa) >= 3 and len(pb) >= 3 and pa[:3] == pb[:3]


def _graph_expand(scored: list[Evidence], docs: list[CorpusDocument], *, max_extra: int) -> list[Evidence]:
    if not scored or max_extra <= 0:
        return []
    by_url = {_normalize_url(doc.url): doc for doc in docs if doc.url}
    seed_urls = [_normalize_url(item.url) for item in scored if item.url]
    extra: list[Evidence] = []
    seen = {item.path for item in scored}
    for seed_url in seed_urls[:3]:
        seed_doc = by_url.get(seed_url)
        candidate_urls = set(seed_doc.links if seed_doc else [])
        candidate_urls.update(url for url in by_url if _same_unit(seed_url, url))
        for url in candidate_urls:
            doc = by_url.get(_normalize_url(url))
            if not doc or doc.path in seen:
                continue
            extra.append(
                Evidence(
                    url=doc.url,
                    title=doc.title,
                    path=doc.path,
                    snippet=_window_snippet(doc.text, _terms(doc.title)),
                    score=1.0,
                    source=f"{doc.source}:graph_expand",
                    reasons=["linked_or_same_unit"],
                )
            )
            seen.add(doc.path)
            if len(extra) >= max_extra:
                return extra
    return extra


def retrieve_from_corpus(
    question: str,
    run_root: Path,
    *,
    top_k: int = 8,
    answer_threshold: float = 10.0,
    graph_expand: bool = True,
) -> RetrievalDecision:
    docs = load_corpus(run_root)
    scored: list[Evidence] = []
    for doc in docs:
        score, reasons = _score_doc(question, doc)
        if score <= 0:
            continue
        scored.append(
            Evidence(
                url=doc.url,
                title=doc.title,
                path=doc.path,
                snippet=_window_snippet(doc.text, _terms(question) + _phrases(question)),
                score=round(score, 3),
                source=doc.source,
                reasons=reasons[:12],
            )
        )
    scored.sort(key=lambda item: item.score, reverse=True)
    closest = scored[:top_k]
    if graph_expand:
        closest = (closest + _graph_expand(closest, docs, max_extra=max(0, top_k - len(closest))))[:top_k]
    evidence = [item for item in closest if item.score >= answer_threshold and _supports_answer(question, item)]
    return RetrievalDecision(
        state=ANSWERABLE if evidence else NEEDS_WEB_RECOVERY,
        question=question,
        evidence=evidence,
        closest=closest,
    )


def _ollama_embed(text: str, *, model: str, base_url: str) -> list[float]:
    resp = requests.post(f"{base_url.rstrip('/')}/api/embeddings", json={"model": model, "prompt": text}, timeout=120)
    if resp.status_code == 404:
        resp = requests.post(f"{base_url.rstrip('/')}/api/embed", json={"model": model, "input": text}, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    if "embedding" in data:
        return [float(v) for v in data["embedding"]]
    embeddings = data.get("embeddings") or []
    if embeddings:
        return [float(v) for v in embeddings[0]]
    raise RuntimeError("Ollama returned no embedding")


def query_zvec(
    question: str,
    *,
    db_path: Path,
    top_k: int = 8,
    model: str = "nomic-embed-text:latest",
    ollama_base_url: str = "http://localhost:11434",
) -> list[Evidence]:
    import zvec

    collection = zvec.open(path=str(db_path)) if hasattr(zvec, "open") else zvec.create_and_open(path=str(db_path), schema=None)
    vector = _ollama_embed(question, model=model, base_url=ollama_base_url)
    result = collection.query(vectors=zvec.VectorQuery(field_name="embedding", vector=vector), topk=int(top_k))
    evidence: list[Evidence] = []
    for item in result or []:
        doc = getattr(item, "doc", item)
        raw_score = getattr(item, "score", 0.0)
        fields = getattr(doc, "fields", {}) or {}
        text = str(fields.get("text") or "")
        evidence.append(
            Evidence(
                url=str(fields.get("url") or ""),
                title=str(fields.get("title") or ""),
                path=str(fields.get("path") or ""),
                snippet=_window_snippet(text, _terms(question) + _phrases(question)),
                score=float(raw_score or 0.0),
                source="zvec_embedding",
                reasons=["semantic_match"],
            )
        )
    return evidence


def retrieve_with_zvec(
    question: str,
    run_root: Path,
    *,
    zvec_db_path: Path,
    top_k: int = 8,
    answer_threshold: float = 10.0,
    zvec_model: str = "nomic-embed-text:latest",
    ollama_base_url: str = "http://localhost:11434",
) -> RetrievalDecision:
    semantic = query_zvec(
        question,
        db_path=zvec_db_path,
        top_k=top_k,
        model=zvec_model,
        ollama_base_url=ollama_base_url,
    )
    corpus = retrieve_from_corpus(question, run_root, top_k=top_k, answer_threshold=answer_threshold)
    if not semantic:
        return corpus

    docs_by_path = {doc.path: doc for doc in load_corpus(run_root)}
    boosted: list[Evidence] = []
    for item in semantic:
        doc = docs_by_path.get(item.path)
        if doc is None:
            boosted.append(item)
            continue
        keyword_score, reasons = _score_doc(question, doc)
        boosted.append(
            Evidence(
                url=item.url,
                title=item.title or doc.title,
                path=item.path,
                snippet=item.snippet or _window_snippet(doc.text, _terms(question) + _phrases(question)),
                score=round(keyword_score + 3.0, 3),
                source="zvec_embedding+fielded",
                reasons=(item.reasons + reasons)[:12],
            )
        )
    merged = boosted + [item for item in corpus.closest if item.path not in {row.path for row in boosted}]
    merged.sort(key=lambda item: item.score, reverse=True)
    closest = merged[:top_k]
    evidence = [item for item in closest if item.score >= answer_threshold and _supports_answer(question, item)]
    return RetrievalDecision(
        state=ANSWERABLE if evidence else NEEDS_WEB_RECOVERY,
        question=question,
        evidence=evidence,
        closest=closest,
    )


def _domain_from_run(run_root: Path) -> str | None:
    docs = load_corpus(run_root)
    for doc in docs:
        host = urlparse(doc.url).netloc
        if host:
            return host
    return None


def tavily_search(
    question: str,
    *,
    tavily_api_key: str,
    include_domains: list[str] | None = None,
    max_results: int = 5,
) -> tuple[list[dict[str, Any]], int]:
    query = question
    if include_domains:
        query = f"{question} " + " ".join(f"site:{domain}" for domain in include_domains)
    t0 = time.perf_counter()
    resp = requests.post(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {tavily_api_key}", "Content-Type": "application/json"},
        json={
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_domains": include_domains or [],
            "include_answer": False,
            "include_raw_content": False,
        },
        timeout=60,
    )
    resp.raise_for_status()
    latency_ms = int((time.perf_counter() - t0) * 1000)
    results = resp.json().get("results") or []
    return [row for row in results if isinstance(row, dict) and row.get("url")], latency_ms


def tavily_extract_urls(
    urls: list[str],
    *,
    tavily_api_key: str,
    extract_depth: str = "basic",
) -> tuple[list[dict[str, Any]], int]:
    if not urls:
        return [], 0
    t0 = time.perf_counter()
    resp = requests.post(
        "https://api.tavily.com/extract",
        headers={"Authorization": f"Bearer {tavily_api_key}", "Content-Type": "application/json"},
        json={
            "urls": urls,
            "extract_depth": extract_depth,
            "format": "markdown",
            "include_images": False,
            "include_favicon": False,
        },
        timeout=90,
    )
    resp.raise_for_status()
    latency_ms = int((time.perf_counter() - t0) * 1000)
    return [row for row in resp.json().get("results", []) if isinstance(row, dict)], latency_ms


def index_recovered_pages(run_root: Path, extracted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    markdown_dir = run_root / "markdown"
    metadata_dir = run_root / "metadata"
    markdown_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    scrape_manifest = read_json(run_root / "scrape_manifest.json", [])
    if not isinstance(scrape_manifest, list):
        scrape_manifest = []
    by_url = {str(row.get("url") or ""): dict(row) for row in scrape_manifest if isinstance(row, dict)}
    indexed: list[dict[str, Any]] = []
    for row in extracted:
        url = str(row.get("url") or "").strip()
        content = str(row.get("raw_content") or "").strip()
        if not url or not content:
            continue
        slug = _slug(url)
        md_path = markdown_dir / f"tavily_{slug}.md"
        meta_path = metadata_dir / f"tavily_{slug}.json"
        md_path.write_text(content, encoding="utf-8")
        write_json(
            meta_path,
            {
                "url": url,
                "fetch_mode": "tavily_search_recovery",
                "indexed_at": _utc_now_iso(),
                "score": row.get("score"),
            },
        )
        page = by_url.get(url, {})
        page.update(
            {
                "url": url,
                "status": "success",
                "fetch_mode": "tavily_search_recovery",
                "failure_reason": None,
                "markdown_path": str(md_path),
                "metadata_path": str(meta_path),
                "raw_html_path": page.get("raw_html_path"),
                "text_length": len(content),
                "finished_at": _utc_now_iso(),
            }
        )
        by_url[url] = page
        indexed.append(page)
    write_json(run_root / "scrape_manifest.json", list(by_url.values()))
    return indexed


def reindex_zvec(
    run_root: Path,
    *,
    db_path: Path | None = None,
    model: str = "nomic-embed-text:latest",
    ollama_base_url: str = "http://localhost:11434",
) -> dict[str, Any]:
    script = Path(__file__).resolve().parents[2] / "scripts" / "zvec_index_run.py"
    cmd = [
        sys.executable,
        str(script),
        str(run_root),
        "--model",
        model,
        "--ollama",
        ollama_base_url,
    ]
    if db_path is not None:
        cmd.extend(["--db", str(db_path)])
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return {"stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}


def answer_with_recovery(
    question: str,
    run_root: Path,
    *,
    tavily_api_key: str | None = None,
    include_domains: list[str] | None = None,
    top_k: int = 8,
    answer_threshold: float = 10.0,
    max_web_results: int = 5,
    reindex_after_recovery: bool = False,
    zvec_db_path: Path | None = None,
    zvec_model: str = "nomic-embed-text:latest",
    ollama_base_url: str = "http://localhost:11434",
) -> RetrievalDecision:
    if zvec_db_path is not None and zvec_db_path.exists():
        first = retrieve_with_zvec(
            question,
            run_root,
            zvec_db_path=zvec_db_path,
            top_k=top_k,
            answer_threshold=answer_threshold,
            zvec_model=zvec_model,
            ollama_base_url=ollama_base_url,
        )
    else:
        first = retrieve_from_corpus(question, run_root, top_k=top_k, answer_threshold=answer_threshold)
    if first.state == ANSWERABLE or not tavily_api_key:
        return first

    domains = include_domains if include_domains is not None else []
    if not domains:
        inferred = _domain_from_run(run_root)
        if inferred:
            domains = [inferred]

    search_results, search_latency_ms = tavily_search(
        question,
        tavily_api_key=tavily_api_key,
        include_domains=domains,
        max_results=max_web_results,
    )
    urls = [str(row["url"]) for row in search_results[:max_web_results]]
    extracted, extract_latency_ms = tavily_extract_urls(urls, tavily_api_key=tavily_api_key)
    indexed = index_recovered_pages(run_root, extracted)
    recovery: dict[str, Any] = {
        "searched": True,
        "domains": domains,
        "search_results": len(search_results),
        "extract_results": len(extracted),
        "indexed_pages": len(indexed),
        "urls": urls,
    }
    append_event(
        run_root,
        {
            "provider": "tavily",
            "operation": "answer_recovery_search_extract",
            "status": "success",
            "question": question,
            "search_results": len(search_results),
            "extract_results": len(extracted),
            "indexed_pages": len(indexed),
            "latency_ms": search_latency_ms + extract_latency_ms,
        },
    )
    if reindex_after_recovery and indexed:
        try:
            recovery["zvec_reindex"] = reindex_zvec(
                run_root,
                db_path=zvec_db_path,
                model=zvec_model,
                ollama_base_url=ollama_base_url,
            )
        except Exception as exc:
            recovery["zvec_reindex_error"] = str(exc)

    if zvec_db_path is not None and zvec_db_path.exists():
        second = retrieve_with_zvec(
            question,
            run_root,
            zvec_db_path=zvec_db_path,
            top_k=top_k,
            answer_threshold=answer_threshold,
            zvec_model=zvec_model,
            ollama_base_url=ollama_base_url,
        )
    else:
        second = retrieve_from_corpus(question, run_root, top_k=top_k, answer_threshold=answer_threshold)
    second.recovery = recovery
    if second.state != ANSWERABLE:
        second.state = UNANSWERABLE_AFTER_RECOVERY
    return second
