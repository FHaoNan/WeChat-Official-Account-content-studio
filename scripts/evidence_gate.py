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
    total_claims = len(unsupported) + len(CITATION_RE.findall(text))
    passed = len(unsupported) == 0
    return {
        "summary": {
            "passed": passed,
            "total_claims": total_claims,
            "supported": total_claims - len(unsupported),
            "unsupported": len(unsupported),
        },
        "unsupported_claims": unsupported,
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
