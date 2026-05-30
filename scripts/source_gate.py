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
    "primary": "至少 1 个一手来源：官方文档/GitHub/论文/财报/产品公告",
}
OPTIONAL_CATEGORIES = {
    "community": "可选：社区讨论来源仅用于用户反馈/争议线索，不作为重大事实单独依据",
    "media_or_secondary": "可选：英文主流媒体或强二手验证用于交叉验证，不要求硬凑齐",
}
ALL_CATEGORIES = {**REQUIRED_CATEGORIES, **OPTIONAL_CATEGORIES}


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


def source_snippet(source: dict[str, Any]) -> str:
    for key in ("snippet", "summary", "description", "quote", "note", "fact"):
        value = str(source.get(key) or "").strip()
        if value:
            return re.sub(r"\s+", " ", value)
    return ""


def explain_source(source: dict[str, Any], categories: list[str]) -> dict[str, str]:
    declared = str(source.get("source_type") or source.get("category") or "").lower()
    domain = normalize_domain(source_url(source))
    origin = str(source.get("origin") or "")
    title = str(source.get("title") or source.get("name") or domain or "该来源")

    if "primary" in categories and ("official" in declared or "docs" in domain or "/docs" in source_url(source)):
        why = f"{title} 是官方/文档类一手资料，适合确认产品边界、接口行为或技术机制。"
        supports = "产品或技术机制、部署方式、官方口径和可核验功能边界。"
        cannot = "不能单独证明用户反馈、商业采用规模或第三方评测结论。"
    elif "primary" in categories and ("github" in declared or domain.endswith("github.com")):
        why = f"{title} 是代码/开源实现资料，适合观察实现路径和工程约束。"
        supports = "实现路径、工程限制、依赖关系和开发者可复核的技术细节。"
        cannot = "不能单独证明商业采用规模、官方路线图或普通用户体验。"
    elif "primary" in categories and ("earnings" in declared or "investor" in domain):
        why = f"{title} 是财报/投资者关系资料，适合确认公司层面的收入、需求和产业叙事。"
        supports = "公司财务背景、产业需求、管理层公开口径和供需判断。"
        cannot = "不能单独证明底层技术机制、具体模型表现或用户体验。"
    elif "community" in categories:
        why = f"{title} 是社区/开发者讨论，适合捕捉真实使用摩擦和争议线索。"
        supports = "用户反馈、开发者痛点、使用摩擦和争议方向。"
        cannot = "不能单独证明重大事实、官方产品能力或产业规模。"
    elif "media_or_secondary" in categories:
        why = f"{title} 是媒体/强二手来源，适合提供产业背景和交叉验证。"
        supports = "产业背景、时间线、竞争格局和第三方交叉验证。"
        cannot = "不能单独证明底层机制、官方接口细节或未公开财务数字。"
    else:
        why = f"{title} 可作为辅助资料，但需要和一手来源交叉确认。"
        supports = "辅助背景和待核验线索。"
        cannot = "不能单独支撑关键事实判断。"

    if origin == "curated_fallback_after_search_empty":
        why += " 该来源来自搜索为空/受限后的 canonical fallback，后续最好用实时搜索结果补强。"
    return {"why_this_source": why, "what_it_supports": supports, "what_it_cannot_prove": cannot}


def extract_section_evidence(article_markdown: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in article_markdown.splitlines():
        heading_match = re.match(r"^##\s+(.+?)\s*$", line)
        if heading_match:
            current = {"heading": heading_match.group(1).strip(), "source_ids": []}
            sections.append(current)
            continue
        if current is None:
            continue
        for sid in re.findall(r"\[(S\d+)\]", line):
            if sid not in current["source_ids"]:
                current["source_ids"].append(sid)
    return sections


def fallback_audit(sources: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(sources)
    fallback = [source for source in sources if str(source.get("origin") or "") == "curated_fallback_after_search_empty"]
    count = len(fallback)
    ratio = round(count / total, 3) if total else 0.0
    if count == 0:
        recommendation = "未使用 fallback 来源。"
    elif ratio >= 0.5:
        recommendation = "fallback 来源占比较高；发布前建议用实时搜索或人工补证替换/补强关键证据。"
    else:
        recommendation = "少量 fallback 来源可作为稳定兜底，但关键判断仍建议人工补证。"
    return {"count": count, "total": total, "ratio": ratio, "status": "info", "recommendation": recommendation}


def build_report(article_dir: Path) -> dict[str, Any]:
    sources = collect_sources(article_dir)
    article_path = article_dir / "article.md"
    article_markdown = article_path.read_text(encoding="utf-8", errors="replace") if article_path.exists() else ""
    section_evidence = extract_section_evidence(article_markdown)
    sections_without_evidence = [item["heading"] for item in section_evidence if not item["source_ids"]]
    enriched: list[dict[str, Any]] = []
    category_counts = {key: 0 for key in ALL_CATEGORIES}
    invalid_sources = 0

    for index, source in enumerate(sources, 1):
        url = source_url(source)
        categories = classify_source(source) if url else []
        if not url:
            invalid_sources += 1
        for category in categories:
            if category in category_counts:
                category_counts[category] += 1
        snippet = source_snippet(source)
        explanation = explain_source(source, categories)
        source_id = str(source.get("source_id") or f"S{index}")
        assigned_sections = [section["heading"] for section in section_evidence if source_id in section["source_ids"]]
        item = {
            "source_id": source_id,
            "title": source.get("title") or source.get("name") or "",
            "url": url,
            "domain": normalize_domain(url) if url else "",
            "categories": categories,
            "origin": source.get("origin", ""),
            "declared_type": source.get("source_type") or source.get("category") or "",
            "assigned_sections": assigned_sections,
            **explanation,
        }
        if snippet:
            item["snippet"] = snippet
        enriched.append(item)

    required_missing = [key for key, count in category_counts.items() if key in REQUIRED_CATEGORIES and count < 1]
    checks = [
        {
            "name": key,
            "status": "pass" if key not in required_missing else "fail",
            "detail": REQUIRED_CATEGORIES[key],
            "count": category_counts[key],
            "required": True,
        }
        for key in REQUIRED_CATEGORIES
    ]
    checks.extend(
        {
            "name": key,
            "status": "info" if category_counts[key] < 1 else "pass",
            "detail": OPTIONAL_CATEGORIES[key],
            "count": category_counts[key],
            "required": False,
        }
        for key in OPTIONAL_CATEGORIES
    )
    passed = not required_missing
    report = {
        "article_dir": str(article_dir),
        "policy": "domestic_hotspots_overseas_evidence: first_hand_primary_required; community/media optional; article links not required",
        "requirements": REQUIRED_CATEGORIES,
        "optional_categories": OPTIONAL_CATEGORIES,
        "checks": checks,
        "sources": enriched,
        "section_evidence": section_evidence,
        "fallback_audit": fallback_audit(sources),
        "summary": {
            "passed": passed,
            "total_sources": len(enriched),
            "invalid_sources": invalid_sources,
            "categories": category_counts,
            "missing_categories": required_missing,
            "sections_without_evidence": sections_without_evidence,
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
