#!/usr/bin/env python3
"""Research overseas sources for a selected Token Burner topic.

P4 bridge: takes a selected topic / overseas_evidence_plan, searches or reads a
fixture of search results, classifies candidate URLs with the same policy as
source_gate.py, and emits a real sources.json that can feed
`toolkit/cli.py draft-from-topic`.

The script never fabricates URLs. If the required source mix is not found it
fails closed by default; use --allow-incomplete only for exploratory runs.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from source_gate import REQUIRED_CATEGORIES, classify_source, source_url  # noqa: E402

SEARCH_DOMAINS_BY_TYPE = {
    "official_docs": "official docs documentation release notes",
    "official": "official docs documentation release notes",
    "github": "site:github.com OR site:huggingface.co",
    "github_or_paper": "site:github.com OR site:arxiv.org OR site:openreview.net OR site:huggingface.co",
    "paper": "site:arxiv.org OR site:openreview.net paper",
    "arxiv": "site:arxiv.org",
    "earnings": "earnings transcript investor relations annual report sec filing",
    "filing": "site:sec.gov filing annual report",
    "community": "site:x.com OR site:reddit.com OR site:news.ycombinator.com OR site:youtube.com",
    "mainstream_media": "site:reuters.com OR site:bloomberg.com OR site:ft.com OR site:wsj.com OR site:theinformation.com OR site:technologyreview.com",
    "media": "site:reuters.com OR site:bloomberg.com OR site:ft.com OR site:wsj.com",
}

SOURCE_TYPE_NORMALIZATION = {
    "official": "official_docs",
    "official_docs": "official_docs",
    "docs": "official_docs",
    "github": "github",
    "github_or_paper": "github_or_paper",
    "paper": "paper",
    "arxiv": "paper",
    "earnings": "earnings",
    "filing": "filing",
    "community": "community",
    "x": "community",
    "twitter": "community",
    "reddit": "community",
    "hn": "community",
    "hackernews": "community",
    "youtube": "community",
    "mainstream_media": "mainstream_media",
    "media": "mainstream_media",
    "secondary": "mainstream_media",
    "strong_secondary": "mainstream_media",
}


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def select_topic(payload: dict[str, Any], index: int | None = None) -> dict[str, Any]:
    topics = payload.get("topics")
    if isinstance(topics, list) and topics:
        if index is None:
            topic = next((item for item in topics if isinstance(item, dict) and item.get("auto_write_allowed", True)), topics[0])
        else:
            if index < 0 or index >= len(topics):
                raise IndexError(f"--topic-index out of range: {index}")
            topic = topics[index]
    else:
        topic = payload.get("topic", payload)
    if not isinstance(topic, dict):
        raise ValueError("selected topic must be an object")
    return topic


def topic_title(topic: dict[str, Any]) -> str:
    raw_hotspot = topic.get("hotspot")
    hotspot: dict[str, Any] = raw_hotspot if isinstance(raw_hotspot, dict) else {}
    return str(
        topic.get("recommended_title")
        or topic.get("proposed_title")
        or topic.get("title")
        or hotspot.get("title")
        or "AI topic"
    ).strip()


def normalize_source_type(value: str) -> str:
    key = value.strip().lower().replace("-", "_")
    return SOURCE_TYPE_NORMALIZATION.get(key, key or "unknown")


def evidence_plan(topic: dict[str, Any]) -> list[dict[str, str]]:
    plans: list[Any] = []
    raw_llm_review = topic.get("llm_review")
    llm_review: dict[str, Any] = raw_llm_review if isinstance(raw_llm_review, dict) else {}
    raw_llm_plan = llm_review.get("overseas_evidence_plan")
    if isinstance(raw_llm_plan, list):
        plans.extend(raw_llm_plan)
    raw_topic_plan = topic.get("overseas_evidence_plan")
    if isinstance(raw_topic_plan, list):
        plans.extend(raw_topic_plan)
    raw_overseas = topic.get("overseas_evidence")
    overseas: dict[str, Any] = raw_overseas if isinstance(raw_overseas, dict) else {}
    raw_directions = overseas.get("directions")
    directions = raw_directions if isinstance(raw_directions, list) else []
    for direction in directions:
        text = str(direction).strip()
        if text:
            plans.append({"source_type": infer_source_type_from_text(text), "query": text})

    normalized: list[dict[str, str]] = []
    for item in plans:
        if isinstance(item, str):
            normalized.append({"source_type": infer_source_type_from_text(item), "query": item})
        elif isinstance(item, dict):
            query = str(item.get("query") or item.get("search_query") or item.get("direction") or "").strip()
            source_type = normalize_source_type(str(item.get("source_type") or item.get("category") or infer_source_type_from_text(query)))
            if query:
                normalized.append({"source_type": source_type, "query": query})
    if not normalized:
        title = topic_title(topic)
        normalized = [
            {"source_type": "official_docs", "query": f"{title} official documentation release notes"},
            {"source_type": "community", "query": f"{title} discussion Hacker News Reddit X"},
            {"source_type": "mainstream_media", "query": f"{title} Reuters Bloomberg technology"},
        ]
    return dedupe_plans(normalized)


def infer_source_type_from_text(text: str) -> str:
    lower = text.lower()
    if any(token in lower for token in ["github", "arxiv", "paper", "论文", "huggingface", "openreview"]):
        return "github_or_paper"
    if any(token in lower for token in ["official", "docs", "documentation", "release notes", "官方", "文档"]):
        return "official_docs"
    if any(token in lower for token in ["reddit", "hacker", "hn", "x.com", "twitter", "youtube", "社区"]):
        return "community"
    if any(token in lower for token in ["reuters", "bloomberg", "wsj", "ft.com", "the verge", "媒体", "英文媒体"]):
        return "mainstream_media"
    if any(token in lower for token in ["earnings", "investor", "sec", "annual report", "财报"]):
        return "earnings"
    return "unknown"


def dedupe_plans(plans: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    output = []
    for plan in plans:
        key = (plan["source_type"], plan["query"])
        if key in seen:
            continue
        seen.add(key)
        output.append(plan)
    return output


def existing_sources(topic: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = topic.get("sources") or payload.get("sources") or []
    sources = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                sources.append({"url": item, "origin": "topic"})
            elif isinstance(item, dict):
                copied = dict(item)
                copied.setdefault("origin", "topic")
                sources.append(copied)
    return sources


def load_search_fixture(path: Path) -> list[dict[str, Any]]:
    data = load_json(path)
    results: list[Any]
    if isinstance(data, list):
        results = data
    elif isinstance(data, dict):
        if isinstance(data.get("results"), list):
            results = data["results"]
        elif isinstance(data.get("queries"), dict):
            results = []
            for query, items in data["queries"].items():
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            copied = dict(item)
                            copied.setdefault("query", query)
                            results.append(copied)
        else:
            results = []
    else:
        results = []
    normalized = []
    for item in results:
        if isinstance(item, str):
            normalized.append({"url": item, "origin": "search_fixture"})
        elif isinstance(item, dict):
            copied = dict(item)
            copied.setdefault("origin", "search_fixture")
            normalized.append(copied)
    return normalized


def search_duckduckgo(query: str, limit: int, timeout: float) -> list[dict[str, Any]]:
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 research_sources.py"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
    matches = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, flags=re.I | re.S)
    results = []
    for href, raw_title in matches[:limit]:
        resolved = unwrap_duckduckgo_url(html.unescape(href))
        title = re.sub(r"<[^>]+>", "", raw_title)
        title = html.unescape(re.sub(r"\s+", " ", title)).strip()
        if resolved.startswith(("http://", "https://")):
            results.append({"title": title, "url": resolved, "query": query, "origin": "duckduckgo"})
    return results


def unwrap_duckduckgo_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("uddg"):
            return query["uddg"][0]
    if value.startswith("//duckduckgo.com/l/"):
        return unwrap_duckduckgo_url("https:" + value)
    return value


def query_matches_result(plan_query: str, result: dict[str, Any]) -> bool:
    result_query = str(result.get("query") or "").strip()
    if not result_query:
        return True
    if result_query == plan_query:
        return True
    return result_query.lower() in plan_query.lower() or plan_query.lower() in result_query.lower()


def candidate_sources(payload: dict[str, Any], topic: dict[str, Any], plans: list[dict[str, str]], args: argparse.Namespace) -> list[dict[str, Any]]:
    candidates = existing_sources(topic, payload)
    fixture_results = load_search_fixture(Path(args.search_fixture)) if args.search_fixture else []
    for plan in plans:
        query = plan["query"]
        search_query = augment_query(query, plan["source_type"])
        if fixture_results:
            results = [item for item in fixture_results if query_matches_result(query, item) or query_matches_result(search_query, item)]
        elif args.no_network:
            results = []
        else:
            try:
                results = search_duckduckgo(search_query, args.per_query_limit, args.timeout_seconds)
            except Exception as exc:
                results = [{"title": f"search failed: {query}", "url": "", "error": str(exc), "query": query, "origin": "duckduckgo"}]
        for result in results[: args.per_query_limit]:
            source = dict(result)
            source.setdefault("source_type", plan["source_type"])
            source.setdefault("research_query", query)
            source.setdefault("search_query", search_query)
            candidates.append(source)
    return dedupe_sources(candidates)


def augment_query(query: str, source_type: str) -> str:
    suffix = SEARCH_DOMAINS_BY_TYPE.get(source_type, "")
    if not suffix or any(token in query.lower() for token in ["site:", "official", "github", "arxiv", "reuters", "bloomberg", "reddit", "ycombinator"]):
        return query
    return f"{query} {suffix}"


def dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output = []
    for source in sources:
        url = source_url(source)
        if not url or not url.startswith(("http://", "https://")):
            continue
        key = canonical_url(url)
        if key in seen:
            continue
        seen.add(key)
        copied = dict(source)
        copied["url"] = url
        output.append(copied)
    return output


def canonical_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


def enrich_and_score_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for idx, source in enumerate(sources):
        copied = dict(source)
        categories = classify_source(copied)
        copied["categories"] = categories
        copied["credibility_score"] = source_score(copied, idx)
        enriched.append(copied)
    enriched.sort(key=lambda item: item.get("credibility_score", 0), reverse=True)
    return enriched


def source_score(source: dict[str, Any], index: int) -> int:
    categories = classify_source(source)
    score = 10 - min(index, 5)
    if "primary" in categories:
        score += 5
    if "media_or_secondary" in categories:
        score += 4
    if "community" in categories:
        score += 3
    declared = normalize_source_type(str(source.get("source_type") or ""))
    if declared in {"official_docs", "github_or_paper", "github", "paper", "earnings"} and "primary" in categories:
        score += 2
    if declared == "community" and "community" in categories:
        score += 2
    if declared == "mainstream_media" and "media_or_secondary" in categories:
        score += 2
    return score


def build_summary(sources: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {key: 0 for key in REQUIRED_CATEGORIES}
    for source in sources:
        for category in source.get("categories") or classify_source(source):
            if category in counts:
                counts[category] += 1
    missing = [key for key, count in counts.items() if count < 1]
    return {
        "passed": not missing,
        "total_sources": len(sources),
        "categories": counts,
        "missing_categories": missing,
    }


def update_topic_payload(payload: dict[str, Any], selected_topic: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    updated = json.loads(json.dumps(payload, ensure_ascii=False))
    clean_sources = clean_sources_for_manifest(sources)
    topics = updated.get("topics")
    if isinstance(topics, list):
        for topic in topics:
            if isinstance(topic, dict) and same_topic(topic, selected_topic):
                topic["sources"] = clean_sources
                topic["research_sources"] = {"status": "complete", "count": len(clean_sources)}
                break
    elif isinstance(updated.get("topic"), dict):
        updated["topic"]["sources"] = clean_sources
        updated["topic"]["research_sources"] = {"status": "complete", "count": len(clean_sources)}
    else:
        updated["sources"] = clean_sources
        updated["research_sources"] = {"status": "complete", "count": len(clean_sources)}
    return updated


def same_topic(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return topic_title(a) == topic_title(b) or a.get("hotspot") == b.get("hotspot")


def clean_sources_for_manifest(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean = []
    for source in sources:
        item = {
            "title": str(source.get("title") or source.get("name") or source_url(source)).strip(),
            "url": source_url(source),
            "source_type": normalize_source_type(str(source.get("source_type") or source.get("category") or "")),
            "categories": source.get("categories") or classify_source(source),
            "research_query": source.get("research_query") or source.get("query") or "",
            "origin": source.get("origin") or "",
        }
        clean.append(item)
    return clean


def build_report(topic: dict[str, Any], plans: list[dict[str, str]], sources: list[dict[str, Any]]) -> dict[str, Any]:
    summary = build_summary(sources)
    return {
        "policy": "国内热点发现，海外信息补证；sources must satisfy source_gate required mix",
        "topic_title": topic_title(topic),
        "evidence_plan": plans,
        "summary": summary,
        "sources": clean_sources_for_manifest(sources),
    }


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="Research real overseas sources for a selected WeWrite topic.")
    parser.add_argument("--topic-file", required=True, help="Topic JSON from select_ai_topics.py or LLM rerank")
    parser.add_argument("--topic-index", type=int, default=None, help="Index inside topics[]; default picks first auto-writeable topic")
    parser.add_argument("--search-fixture", default="", help="Deterministic search results fixture for tests/offline use")
    parser.add_argument("--output", default="", help="Write sources manifest JSON; default: <topic-dir>/sources.json not inferred")
    parser.add_argument("--topic-output", default="", help="Write topic JSON with selected topic.sources populated")
    parser.add_argument("--report-output", default="", help="Write full research report JSON")
    parser.add_argument("--per-query-limit", type=int, default=6)
    parser.add_argument("--max-sources", type=int, default=12)
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    parser.add_argument("--no-network", action="store_true", help="Do not call web search; use topic/fixture sources only")
    parser.add_argument("--allow-incomplete", action="store_true", help="Return 0 even when required source categories are missing")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args()

    payload = load_json(Path(args.topic_file))
    if not isinstance(payload, dict):
        raise ValueError("--topic-file must contain a JSON object")
    topic = select_topic(payload, args.topic_index)
    plans = evidence_plan(topic)
    candidates = candidate_sources(payload, topic, plans, args)
    sources = enrich_and_score_sources(candidates)[: max(1, args.max_sources)]
    report = build_report(topic, plans, sources)

    if args.output:
        write_json(Path(args.output), {"sources": report["sources"]})
    if args.topic_output:
        write_json(Path(args.topic_output), update_topic_payload(payload, topic, sources))
    if args.report_output:
        write_json(Path(args.report_output), report)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        summary = report["summary"]
        status = "PASS" if summary["passed"] else "FAIL"
        print(f"{status}: sources={summary['total_sources']} missing={','.join(summary['missing_categories']) or 'none'}")

    return 0 if report["summary"]["passed"] or args.allow_incomplete else 1


if __name__ == "__main__":
    raise SystemExit(main())
