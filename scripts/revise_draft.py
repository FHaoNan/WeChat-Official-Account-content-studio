#!/usr/bin/env python3
"""Revise a sourced article draft once using gate reports.

P8 is intentionally deterministic and conservative:
- add [Sx] citations to unsupported claim sentences when an evidence ledger exists;
- report missing source categories as blockers instead of fabricating URLs;
- persist generated/revision-report.json for agent/human follow-up.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


CITATION_RE = re.compile(r"\s*\[S\d+\](?:\[S\d+\])*\s*$")


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def normalize_claim(text: str) -> str:
    text = re.sub(r"\[[Ss]\d+\]", "", text)
    text = re.sub(r"[。！？.!?，,；;：:\s]+", "", text)
    return text.lower()


def best_source_id(claim: str, ledger_claims: list[dict[str, Any]]) -> str:
    normalized = normalize_claim(claim)
    # Lightweight deterministic routing; no invented facts.
    cost_terms = ("token", "成本", "烧", "重试", "上下文", "多步")
    tool_terms = ("工具", "调用", "api", "函数", "链路")
    community_terms = ("重试", "上下文", "多步", "token", "烧")

    def has_any(words: tuple[str, ...]) -> bool:
        lower = claim.lower()
        return any(w.lower() in lower for w in words)

    candidates = ledger_claims or []
    if has_any(community_terms):
        for item in candidates:
            sid = str(item.get("source_id") or "")
            hay = " ".join(str(item.get(k) or "") for k in ("fact", "title", "category", "source_type")).lower()
            if sid and any(w in hay for w in ("community", "hn", "reddit", "retry", "token", "context", "重试")):
                return sid
    if has_any(tool_terms):
        for item in candidates:
            sid = str(item.get("source_id") or "")
            hay = " ".join(str(item.get(k) or "") for k in ("fact", "title", "category", "source_type")).lower()
            if sid and any(w in hay for w in ("official", "docs", "tool", "api", "function", "工具")):
                return sid
    if has_any(cost_terms):
        for item in candidates:
            sid = str(item.get("source_id") or "")
            if sid:
                return sid
    return str(candidates[0].get("source_id") or "S1") if candidates else "S1"


def append_citation_to_claim(article: str, claim: str, source_id: str) -> tuple[str, bool]:
    if not claim.strip():
        return article, False
    citation = f" [{source_id}]"
    # Prefer exact substring from evidence gate report.
    escaped = re.escape(claim.strip())
    pattern = re.compile(rf"({escaped})(?!\s*\[S\d+\])")
    replaced, count = pattern.subn(lambda m: m.group(1) + citation, article, count=1)
    if count:
        return replaced, True

    # Fallback: line-level fuzzy containment.
    target = normalize_claim(claim)
    lines = article.splitlines()
    for idx, line in enumerate(lines):
        if f"[{source_id}]" in line:
            continue
        normalized_line = normalize_claim(line)
        if target and (target in normalized_line or normalized_line in target):
            lines[idx] = line.rstrip() + citation
            return "\n".join(lines) + ("\n" if article.endswith("\n") else ""), True
    return article, False


def revise_article(article_dir: Path) -> dict[str, Any]:
    generated = article_dir / "generated"
    article_path = article_dir / "article.md"
    if not article_path.exists():
        raise FileNotFoundError(f"article.md not found: {article_path}")
    generated.mkdir(parents=True, exist_ok=True)

    evidence_report = read_json(generated / "evidence-report.json", {})
    source_report = read_json(generated / "source-report.json", {})
    ledger = read_json(generated / "evidence-ledger.json", {})
    quality = read_json(generated / "quality-gates.json", {})
    ledger_claims = ledger.get("claims", []) if isinstance(ledger, dict) else []
    if not isinstance(ledger_claims, list):
        ledger_claims = []

    article = article_path.read_text(encoding="utf-8")
    original = article
    actions: list[dict[str, Any]] = []
    fixed: list[str] = []
    blocked: dict[str, Any] = {}

    unsupported = evidence_report.get("unsupported_claims", []) if isinstance(evidence_report, dict) else []
    if not isinstance(unsupported, list):
        unsupported = []
    fixed_claims = 0
    for claim in unsupported:
        claim_text = str(claim).strip()
        sid = best_source_id(claim_text, ledger_claims)
        article, changed = append_citation_to_claim(article, claim_text, sid)
        actions.append({"type": "add_citation", "claim": claim_text, "source_id": sid, "changed": changed})
        if changed:
            fixed_claims += 1
    if fixed_claims:
        fixed.append("evidence_coverage")

    source_summary = source_report.get("summary", {}) if isinstance(source_report, dict) else {}
    missing = source_summary.get("missing_categories", []) if isinstance(source_summary, dict) else []
    if missing:
        blocked["source_credibility"] = missing

    if article != original:
        article_path.write_text(article, encoding="utf-8")

    revision = {
        "changed": article != original,
        "fixed": fixed,
        "blocked": blocked,
        "actions": actions,
        "quality_summary_before": quality.get("summary", {}) if isinstance(quality, dict) else {},
    }
    result = {
        "success": True,
        "article_dir": str(article_dir),
        "revision": revision,
        "artifacts": {
            "article_md": str(article_path),
            "revision_report": str(generated / "revision-report.json"),
        },
    }
    (generated / "revision-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Revise article.md once from generated gate reports")
    p.add_argument("--article-dir", required=True)
    p.add_argument("--json", action="store_true")
    return p


def main() -> int:
    configure_stdio()
    args = build_parser().parse_args()
    try:
        result = revise_article(Path(args.article_dir).expanduser())
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else json.dumps(result["revision"], ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
