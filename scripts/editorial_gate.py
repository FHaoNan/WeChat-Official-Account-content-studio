#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


INTERNAL_TERM_PATTERNS: list[tuple[str, str]] = [
    (r"\bofficial_docs\b", "official_docs"),
    (r"\bgithub_or_paper\b", "github_or_paper"),
    (r"\binternal evidence ledger\b", "internal evidence ledger"),
    (r"\bevidence ledger\b", "evidence ledger"),
    (r"\bsource gate\b", "source gate"),
    (r"\bevidence gate\b", "evidence gate"),
    (r"需要在后续深读", "需要在后续深读"),
    (r"补充更精确的原文摘录", "补充更精确的原文摘录"),
    (r"阻塞发布", "阻塞发布"),
    (r"本选题的\s*[^\s，。；、]*\s*证据", "本选题的 X 证据"),
]

TITLE_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "芯片": ["芯片", "算力", "半导体", "GPU", "NPU", "推理卡", "国产"],
    "算力": ["算力", "芯片", "GPU", "推理", "训练", "集群"],
    "模型": ["模型", "LLM", "大模型", "参数", "推理", "训练"],
    "Agent": ["Agent", "智能体", "工具调用", "上下文", "重试", "token"],
    "token": ["token", "Token", "上下文", "成本", "推理", "调用"],
    "Claude": ["Claude", "Anthropic", "模型", "Agent"],
    "ChatGPT": ["ChatGPT", "OpenAI", "模型", "Agent"],
    "MCP": ["MCP", "工具", "协议", "Agent", "上下文"],
}

GENERIC_TEMPLATE_TERMS = ["Agent", "token", "工具调用", "上下文", "失败重试", "可靠性"]


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def make_check(name: str, status: str, detail: str, *, data: object | None = None) -> dict[str, Any]:
    check: dict[str, Any] = {"name": name, "status": status, "detail": detail}
    if data is not None:
        check["data"] = data
    return check


def strip_markdown_title(markdown: str) -> str:
    lines = markdown.splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("# "))


def check_internal_workflow_terms(markdown: str) -> dict:
    hits: list[dict[str, object]] = []
    for pattern, label in INTERNAL_TERM_PATTERNS:
        for match in re.finditer(pattern, markdown, flags=re.IGNORECASE):
            start = max(0, match.start() - 32)
            end = min(len(markdown), match.end() + 32)
            hits.append({"term": label, "excerpt": re.sub(r"\s+", " ", markdown[start:end]).strip()})
    if hits:
        labels = []
        for hit in hits:
            term = str(hit["term"])
            if term not in labels:
                labels.append(term)
        return make_check(
            "internal_workflow_terms",
            "fail",
            "正文泄漏内部工作流术语: " + ", ".join(labels[:10]),
            data={"hits": hits},
        )
    return make_check("internal_workflow_terms", "pass", "正文无内部工作流术语泄漏")


def check_evidence_chain_public_language(markdown: str) -> dict:
    evidence_section = ""
    match = re.search(r"##\s*证据链(?P<body>.*?)(?:\n##\s+|\Z)", markdown, flags=re.S)
    if match:
        evidence_section = match.group("body")
    if not evidence_section:
        return make_check("evidence_chain_public_language", "pass", "未发现单独证据链章节或无需读者化检查")
    bad_phrases = ["需要在后续深读", "本选题的", "证据，需要", "internal", "ledger", "阻塞发布"]
    hits = [phrase for phrase in bad_phrases if phrase.lower() in evidence_section.lower()]
    if hits:
        return make_check("evidence_chain_public_language", "fail", "证据链仍像内部笔记: " + ", ".join(hits), data={"hits": hits})
    return make_check("evidence_chain_public_language", "pass", "证据链语言面向读者")


def title_anchor_terms(title: str) -> list[str]:
    anchors: list[str] = []
    for key, related in TITLE_TOPIC_KEYWORDS.items():
        if key.lower() in title.lower():
            for term in related:
                if term not in anchors:
                    anchors.append(term)
    return anchors


def check_title_body_alignment(title: str, markdown: str) -> dict:
    body = strip_markdown_title(markdown)
    anchors = title_anchor_terms(title)
    if not anchors:
        return make_check("title_body_alignment", "pass", "标题无强主题锚点，跳过错位启发式", data={"anchors": []})
    matched = [term for term in anchors if body.lower().count(term.lower()) >= (2 if len(term) <= 2 else 1)]
    generic_hits = [term for term in GENERIC_TEMPLATE_TERMS if body.lower().count(term.lower()) >= 2]
    ok = bool(matched)
    if ok:
        return make_check(
            "title_body_alignment",
            "pass",
            "标题主题锚点在正文中有持续展开: " + ", ".join(matched[:5]),
            data={"anchors": anchors, "matched": matched, "generic_hits": generic_hits},
        )
    detail = "标题主题锚点未在正文持续展开: " + ", ".join(anchors[:6])
    if generic_hits:
        detail += "；正文更像通用模板: " + ", ".join(generic_hits[:6])
    return make_check("title_body_alignment", "fail", detail, data={"anchors": anchors, "matched": matched, "generic_hits": generic_hits})


def check_raw_markdown_preview(article_dir: Path) -> dict:
    preview = article_dir / "preview.html"
    if not preview.exists():
        return make_check("preview_render_integrity", "fail", "preview.html missing")
    html = preview.read_text(encoding="utf-8", errors="replace")
    leaks = []
    if "![" in html:
        leaks.append("raw markdown image syntax")
    raw_markdown_code_blocks = re.findall(r"<code\b[^>]*>.*?(?:##\s|!\[).*?</code>", html, flags=re.I | re.S)
    if raw_markdown_code_blocks:
        leaks.append(f"raw markdown rendered as code blocks={len(raw_markdown_code_blocks)}")
    if leaks:
        return make_check("preview_render_integrity", "fail", "; ".join(leaks))
    return make_check("preview_render_integrity", "pass", "preview has no raw markdown leakage")


def run_editorial_gate(article_dir: Path) -> dict:
    generated = article_dir / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    article_path = article_dir / "article.md"
    metadata = read_json(article_dir / "draft-metadata.json")
    title = str(metadata.get("title") or "").strip()
    markdown = ""
    checks: list[dict] = []
    if not article_path.exists():
        checks.append(make_check("article_md", "fail", f"article.md missing: {article_path}"))
    else:
        markdown = article_path.read_text(encoding="utf-8", errors="replace")
        checks.append(make_check("article_md", "pass", f"article.md found: {article_path}"))
    if not title:
        md_title = re.search(r"^#\s+(.+)$", markdown, flags=re.M)
        title = md_title.group(1).strip() if md_title else ""
    if not title:
        checks.append(make_check("title_present", "fail", "title missing from metadata and article.md"))
    else:
        checks.append(make_check("title_present", "pass", f"title found: {title}"))
    if markdown:
        checks.append(check_internal_workflow_terms(markdown))
        checks.append(check_evidence_chain_public_language(markdown))
        checks.append(check_title_body_alignment(title, markdown))
        checks.append(check_raw_markdown_preview(article_dir))
    summary = {
        "pass": sum(1 for item in checks if item["status"] == "pass"),
        "fail": sum(1 for item in checks if item["status"] == "fail"),
        "warn": sum(1 for item in checks if item["status"] == "warn"),
    }
    summary["passed"] = summary["fail"] == 0
    report = {
        "article_dir": str(article_dir),
        "policy": "reader_facing_editorial_readiness: block internal workflow traces and severe title/body mismatch",
        "checks": checks,
        "summary": summary,
    }
    (generated / "editorial-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run reader-facing editorial readiness checks.")
    parser.add_argument("--article-dir", required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    configure_stdio()
    args = build_parser().parse_args()
    report = run_editorial_gate(Path(args.article_dir).resolve())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"editorial readiness passed={report['summary']['passed']} fail={report['summary']['fail']}")
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
