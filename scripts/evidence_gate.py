#!/usr/bin/env python3
"""Evidence gate: check that key claims in article.md have [S1] style citations.

This gate is conservative: it only flags obvious unsupported judgment sentences.
It does not attempt to parse natural language perfectly; the goal is to catch
gross cases where the writer forgot to attach evidence.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


CLAIM_PATTERNS = re.compile(
    r"(因为|所以|导致|造成|会|是|会烧|成本|token|调用|重试|上下文|工具链|可靠性|推理|部署)",
    re.IGNORECASE,
)

CITATION_RE = re.compile(r"\[S\d+\]")
SOURCE_ID_RE = re.compile(r"\[(S\d+)\]")


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def find_article(article_dir: Path) -> Path:
    md = article_dir / "article.md"
    if md.exists():
        return md
    raise FileNotFoundError(f"article.md not found under {article_dir}")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_source_map(article_dir: Path) -> dict[str, dict[str, Any]]:
    generated = article_dir / "generated"
    source_map: dict[str, dict[str, Any]] = {}
    ledger = load_json(generated / "evidence-ledger.json", {})
    claims = ledger.get("claims", []) if isinstance(ledger, dict) else []
    if isinstance(claims, list):
        for item in claims:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("source_id") or "").strip()
            if sid:
                source_map[sid] = dict(item)

    sources_payload = load_json(generated / "sources.json", {})
    raw_sources = sources_payload.get("sources", sources_payload) if isinstance(sources_payload, dict) else sources_payload
    if isinstance(raw_sources, list):
        for index, item in enumerate(raw_sources, 1):
            if not isinstance(item, dict):
                continue
            sid = str(item.get("source_id") or f"S{index}").strip()
            merged = dict(item)
            if sid in source_map:
                merged = {**merged, **source_map[sid]}
            source_map[sid] = merged
    return source_map


def clean_sentence(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:240]


def citation_sentences(text: str) -> list[dict[str, Any]]:
    audits: list[dict[str, Any]] = []
    paragraphs = re.split(r"\n\s*\n", text)
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph or paragraph.lstrip().startswith(("#", "```", "|")):
            continue
        if not CITATION_RE.search(paragraph):
            continue
        if paragraph.lstrip().startswith("- [S"):
            # The evidence-chain bullet is already the source fact itself; P21 audits
            # article claims that cite evidence, not the ledger display rows.
            continue
        source_ids = []
        for sid in SOURCE_ID_RE.findall(paragraph):
            if sid not in source_ids:
                source_ids.append(sid)
        claim = clean_sentence(SOURCE_ID_RE.sub("", paragraph).strip(" -*。."))
        if claim:
            audits.append({"claim": claim, "source_ids": source_ids})
    return audits


def source_text(source: dict[str, Any]) -> str:
    parts = []
    for key in ("fact", "snippet", "summary", "description", "quote", "note", "title", "source_type", "category"):
        value = str(source.get(key) or "").strip()
        if value:
            parts.append(value)
    return " ".join(parts).lower()


def claim_tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}|[\u4e00-\u9fff]{2,}", text.lower()))
    # Add common bilingual bridges used by this workbench so Chinese article claims
    # can be compared with English source snippets without pretending to translate.
    bridges = {
        "工具": {"tool", "tools", "function", "functions", "api", "apis"},
        "调用": {"call", "calls", "calling", "function", "functions", "api", "apis"},
        "推理": {"inference", "serving"},
        "成本": {"cost", "costs"},
        "可靠性": {"reliability", "reliable"},
        "部署": {"deploy", "deploying", "deployment"},
        "芯片": {"chip", "chips", "gpu", "hardware"},
        "模型": {"model", "models"},
    }
    expanded = set(tokens)
    for cn, en_words in bridges.items():
        if cn in text:
            expanded.update(en_words)
    return expanded


def classify_support(claim: str, source_ids: list[str], source_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not source_ids:
        return {
            "support_level": "indirect",
            "support_reason": "该判断没有可解析的 [Sx] 来源锚点，需要人工复核。",
            "needs_human_review": True,
        }
    missing = [sid for sid in source_ids if sid not in source_map]
    if missing:
        return {
            "support_level": "indirect",
            "support_reason": f"未找到 {', '.join(missing)} 对应的来源记录，无法判断证据强度。",
            "needs_human_review": True,
        }

    levels: list[str] = []
    reasons: list[str] = []
    claim_terms = claim_tokens(claim)
    for sid in source_ids:
        source = source_map[sid]
        source_type = str(source.get("source_type") or source.get("category") or "").lower()
        haystack = source_text(source)
        overlap = claim_terms & claim_tokens(haystack)
        if "mainstream_media" in source_type or "media" in source_type:
            levels.append("background")
            reasons.append(f"{sid} 是媒体/强二手来源，适合提供产业背景或交叉验证，不能单独证明关键机制。")
        elif "community" in source_type or "reddit" in haystack or "hacker news" in haystack:
            levels.append("background")
            reasons.append(f"{sid} 是社区反馈来源，适合说明使用摩擦，不能单独证明事实边界。")
        elif "earnings" in source_type or "investor" in haystack:
            levels.append("background")
            reasons.append(f"{sid} 是财报/投资者关系来源，适合说明公司和产业背景。")
        elif "official" in source_type or "docs" in source_type or "github" in source_type or "paper" in source_type:
            if overlap:
                levels.append("direct")
                reasons.append(f"{sid} 是 {source_type or 'primary'} 一手来源，且与判断存在关键词重合：{', '.join(sorted(overlap)[:5])}。")
            else:
                levels.append("indirect")
                reasons.append(f"{sid} 是 {source_type or 'primary'} 一手来源，但与该句关键词重合较少，需要确认引用是否贴合。")
        else:
            if overlap:
                levels.append("indirect")
                reasons.append(f"{sid} 与该句存在关键词重合：{', '.join(sorted(overlap)[:5])}，但来源类型边界不够明确。")
            else:
                levels.append("indirect")
                reasons.append(f"{sid} 来源类型不明确且关键词重合较少，需要人工复核。")

    if "direct" in levels:
        level = "direct"
    elif "indirect" in levels:
        level = "indirect"
    else:
        level = "background"
    return {
        "support_level": level,
        "support_reason": " ".join(reasons),
        "needs_human_review": level != "direct",
    }


def extract_claim_sentences(text: str) -> list[str]:
    claims = []
    paragraphs = re.split(r"\n\s*\n", text)
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        # Evidence next to a claim may be at the end of the same paragraph, so
        # treat the whole paragraph as covered when it contains [S1]-style refs.
        if CITATION_RE.search(paragraph):
            continue
        cleaned = "\n".join(
            line for line in paragraph.splitlines()
            if not line.lstrip().startswith(("#", "- [S", "- "))
        ).strip()
        if not cleaned:
            continue
        sentences = re.split(r"[。！？\.\!\?]\s*", cleaned)
        for s in sentences:
            s = s.strip()
            if len(s) < 8:
                continue
            if CLAIM_PATTERNS.search(s):
                claims.append(s[:120])
    return claims


def run_evidence_gate(article_dir: Path) -> dict[str, Any]:
    article_path = find_article(article_dir)
    text = article_path.read_text(encoding="utf-8")
    unsupported = extract_claim_sentences(text)
    source_map = load_source_map(article_dir)
    claim_audits = []
    support_levels = {"direct": 0, "indirect": 0, "background": 0}
    needs_human_review = 0
    for audit in citation_sentences(text):
        classified = classify_support(audit["claim"], audit["source_ids"], source_map)
        enriched = {**audit, **classified}
        claim_audits.append(enriched)
        level = enriched["support_level"]
        support_levels[level] = support_levels.get(level, 0) + 1
        if enriched.get("needs_human_review"):
            needs_human_review += 1
    total_claims = len(unsupported) + len(claim_audits)
    passed = len(unsupported) == 0
    return {
        "summary": {
            "passed": passed,
            "total_claims": total_claims,
            "supported": len(claim_audits),
            "unsupported": len(unsupported),
            "support_levels": support_levels,
            "needs_human_review": needs_human_review,
        },
        "unsupported_claims": unsupported,
        "claim_audits": claim_audits,
        "article_path": str(article_path),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--article-dir", required=True)
    p.add_argument("--output", default=None)
    p.add_argument("--json", action="store_true")
    return p


def main() -> int:
    configure_stdio()
    args = build_parser().parse_args()
    try:
        result = run_evidence_gate(Path(args.article_dir))
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(result["summary"], ensure_ascii=False))
        return 0 if result["summary"]["passed"] else 1
    except Exception as exc:
        err = {"success": False, "error": str(exc)}
        print(json.dumps(err, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
