#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from typing import Any


PRIMARY_DOMAINS = {
    "github.com",
    "arxiv.org",
    "openreview.net",
    "paperswithcode.com",
    "huggingface.co",
    "sec.gov",
}
PRIMARY_KEYWORDS = (
    "docs.",
    "/docs",
    "/documentation",
    "/blog/",
    "/research/",
    "/paper",
    "investor",
    "ir.",
    "earnings",
    "annual-report",
    "quarterly-results",
)
COMMUNITY_DOMAINS = {
    "x.com",
    "twitter.com",
    "reddit.com",
    "news.ycombinator.com",
    "youtube.com",
    "youtu.be",
}
MEDIA_DOMAINS = {
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "theinformation.com",
    "semianalysis.com",
    "stratechery.com",
    "technologyreview.com",
    "wired.com",
    "theverge.com",
    "techcrunch.com",
    "axios.com",
    "apnews.com",
    "economist.com",
}

REQUIRED_CATEGORIES = {
    "primary": "至少 1 个官方/GitHub/论文/财报来源",
    "community": "至少 1 个社区讨论来源：X / Reddit / HN / YouTube 官方访谈",
    "media_or_secondary": "至少 1 个英文主流媒体或强二手验证来源",
}


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def normalize_domain(url: str) -> str:
    parsed = urlparse(url.strip())
    domain = parsed.netloc.lower().split("@")[-1].split(":")[0]
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def domain_matches(domain: str, candidates: set[str]) -> bool:
    return any(domain == item or domain.endswith("." + item) for item in candidates)


def source_url(source: dict[str, Any]) -> str:
    for key in ("url", "link", "href", "source_url"):
        value = str(source.get(key) or "").strip()
        if value:
            return value
    return ""


def classify_source(source: dict[str, Any]) -> list[str]:
    url = source_url(source)
    declared = str(source.get("category") or source.get("source_type") or "").lower()
    domain = normalize_domain(url)
    haystack = " ".join(str(source.get(key) or "") for key in ("title", "note", "description", "publisher", "source_type", "category")).lower()
    categories: list[str] = []

    if declared in {"primary", "official", "official_docs", "github", "paper", "arxiv", "earnings", "filing", "financial_report"}:
        categories.append("primary")
    if declared in {"community", "x", "twitter", "reddit", "hn", "hackernews", "youtube", "interview"}:
        categories.append("community")
    if declared in {"media", "mainstream_media", "secondary", "strong_secondary", "analysis"}:
        categories.append("media_or_secondary")

    if domain_matches(domain, PRIMARY_DOMAINS) or any(token in url.lower() or token in domain for token in PRIMARY_KEYWORDS):
        categories.append("primary")
    if domain_matches(domain, COMMUNITY_DOMAINS):
        categories.append("community")
    if domain_matches(domain, MEDIA_DOMAINS):
        categories.append("media_or_secondary")
    if "official" in haystack and url.startswith(("http://", "https://")):
        categories.append("primary")
    if "youtube" in domain and ("interview" in haystack or "official" in haystack):
        categories.append("community")

    return sorted(set(categories))


def extract_markdown_sources(article_markdown: str) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    pattern = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
    for match in pattern.finditer(article_markdown):
        sources.append({"title": match.group(1).strip(), "url": match.group(2).strip(), "origin": "article.md"})
    bare_pattern = re.compile(r"(?<!\()https?://[^\s)\]}>,\"']+")
    seen = {item["url"] for item in sources}
    for match in bare_pattern.finditer(article_markdown):
        url = match.group(0).strip().rstrip("。.,，；;：:")
        if url not in seen:
            sources.append({"title": "bare_url", "url": url, "origin": "article.md"})
            seen.add(url)
    return sources


def load_sources_file(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("sources") or data.get("items") or []
    else:
        items = []
    sources: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            sources.append({"url": item, "origin": str(path)})
        elif isinstance(item, dict):
            copied = dict(item)
            copied.setdefault("origin", str(path))
            sources.append(copied)
    return sources


def collect_sources(article_dir: Path) -> list[dict[str, Any]]:
    candidates = [article_dir / "generated" / "sources.json", article_dir / "sources.json"]
    sources: list[dict[str, Any]] = []
    for path in candidates:
        if path.exists():
            try:
                sources.extend(load_sources_file(path))
            except Exception as exc:
                sources.append({"url": "", "title": f"invalid source file: {path}", "error": str(exc), "origin": str(path)})
    article_path = article_dir / "article.md"
    if article_path.exists():
        sources.extend(extract_markdown_sources(article_path.read_text(encoding="utf-8", errors="replace")))

    deduped: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for source in sources:
        url = source_url(source)
        key = url or f"{source.get('title')}::{source.get('origin')}"
        if key in seen_urls:
            continue
        seen_urls.add(key)
        deduped.append(source)
    return deduped


def build_report(article_dir: Path) -> dict[str, Any]:
    sources = collect_sources(article_dir)
    enriched: list[dict[str, Any]] = []
    category_counts = {key: 0 for key in REQUIRED_CATEGORIES}
    invalid_sources = 0

    for source in sources:
        url = source_url(source)
        categories = classify_source(source) if url else []
        if not url:
            invalid_sources += 1
        for category in categories:
            if category in category_counts:
                category_counts[category] += 1
        enriched.append({
            "title": source.get("title") or source.get("name") or "",
            "url": url,
            "domain": normalize_domain(url) if url else "",
            "categories": categories,
            "origin": source.get("origin", ""),
            "declared_type": source.get("source_type") or source.get("category") or "",
        })

    missing = [key for key, count in category_counts.items() if count < 1]
    checks = [
        {
            "name": key,
            "status": "pass" if key not in missing else "fail",
            "detail": REQUIRED_CATEGORIES[key],
            "count": category_counts[key],
        }
        for key in REQUIRED_CATEGORIES
    ]
    passed = not missing
    report = {
        "article_dir": str(article_dir),
        "policy": "domestic_hotspots_overseas_evidence: require primary + community + media_or_secondary",
        "requirements": REQUIRED_CATEGORIES,
        "checks": checks,
        "sources": enriched,
        "summary": {
            "passed": passed,
            "total_sources": len(enriched),
            "invalid_sources": invalid_sources,
            "categories": category_counts,
            "missing_categories": missing,
        },
    }
    return report


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="Check WeWrite source credibility minimum evidence mix.")
    parser.add_argument("--article-dir", required=True)
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args()

    article_dir = Path(args.article_dir).resolve()
    generated_dir = article_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(article_dir)
    report_path = generated_dir / "source-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        summary = report["summary"]
        status = "PASS" if summary["passed"] else "FAIL"
        missing = ", ".join(summary["missing_categories"])
        print(f"{status}: sources={summary['total_sources']} missing={missing or 'none'}")
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
