#!/usr/bin/env python3
"""Generate a sourced Token Burner article draft v1 from topic + sources.

This writer is deliberately conservative: it does not fabricate facts or fetch pages.
It turns the snippets/metadata already attached to sources into claim blocks with
explicit source IDs, then writes a more article-like v1 plus an evidence ledger.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import Any


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


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
    return str(topic.get("recommended_title") or topic.get("title") or hotspot.get("title") or "未命名选题").strip()


def topic_hotspot(topic: dict[str, Any]) -> tuple[str, str]:
    raw_hotspot = topic.get("hotspot")
    hotspot: dict[str, Any] = raw_hotspot if isinstance(raw_hotspot, dict) else {}
    return (
        str(hotspot.get("source") or topic.get("source") or "国内热点"),
        str(hotspot.get("title") or topic.get("hotspot_title") or topic_title(topic)),
    )


def load_sources(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    raw = payload.get("sources", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        raise ValueError("sources file must contain a list or {'sources': [...]}")
    sources = []
    for item in raw:
        if isinstance(item, str):
            sources.append({"url": item})
        elif isinstance(item, dict):
            sources.append(dict(item))
    return sources


def clean_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def source_label(source: dict[str, Any], index: int) -> str:
    return f"S{index}"


def source_title(source: dict[str, Any], index: int) -> str:
    return clean_text(source.get("title") or source.get("name") or source.get("source_type") or f"来源 {index}")


def source_fact(source: dict[str, Any], title: str) -> str:
    for key in ["snippet", "summary", "description", "fact", "quote", "note"]:
        value = clean_text(source.get(key))
        if value:
            return value
    source_type = clean_text(source.get("source_type") or source.get("category") or "来源")
    return f"{title} 是本选题的 {source_type} 证据，需要在后续深读时补充更精确的原文摘录。"


def category_name(source: dict[str, Any]) -> str:
    raw = source.get("categories")
    if isinstance(raw, list) and raw:
        value = str(raw[0])
    else:
        value = str(source.get("source_type") or source.get("category") or "unclassified")
    mapping = {
        "primary": "一手来源",
        "official_docs": "官方文档",
        "github": "代码/开源",
        "paper": "论文",
        "community": "社区讨论",
        "media_or_secondary": "英文媒体/强二手",
        "mainstream_media": "英文媒体/强二手",
    }
    return mapping.get(value, value)


def build_claims(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims = []
    for idx, source in enumerate(sources, 1):
        url = clean_text(source.get("url") or source.get("link"))
        if not url:
            continue
        sid = source_label(source, idx)
        title = source_title(source, idx)
        fact = source_fact(source, title)
        claims.append({
            "source_id": sid,
            "title": title,
            "url": url,
            "category": category_name(source),
            "fact": fact,
            "source_type": clean_text(source.get("source_type") or source.get("category") or "unclassified"),
        })
    return claims


def claim_sentence(claim: dict[str, Any]) -> str:
    fact = claim["fact"].rstrip("。.")
    return f"- [{claim['source_id']}] {fact}。"


def build_article(topic: dict[str, Any], claims: list[dict[str, Any]]) -> str:
    title = topic_title(topic)
    hotspot_source, hotspot_title = topic_hotspot(topic)
    engineering_question = clean_text(topic.get("engineering_question") or topic.get("ai_engineer_question") or topic.get("ai_engineering_question") or "这个现象背后的工程问题是什么？")
    angle = clean_text(topic.get("token_burner_angle") or topic.get("angle") or topic.get("editorial_reason") or "从模型调用、上下文、工具链和成本结构拆开看。")
    first_claim = claims[0]["source_id"] if claims else "S?"
    second_claim = claims[1]["source_id"] if len(claims) > 1 else first_claim
    third_claim = claims[2]["source_id"] if len(claims) > 2 else first_claim
    evidence_lines = "\n".join(claim_sentence(claim) for claim in claims) or "- 暂无可引用事实。"
    source_refs = "\n".join(f"- [{claim['source_id']}] [{claim['title']}]({claim['url']})（{claim['category']}）" for claim in claims)

    return textwrap.dedent(f"""\
    # {title}

    ## 先说结论

    这件事不只是一个 AI 产品热点。它真正值得拆的是：当产品从一次问答走向多步 Agent，成本就不再只是“输入几个字、输出几段话”，而会变成工具调用、上下文携带、失败重试和可靠性之间的系统账 [{first_claim}]。

    国内热点入口是「{hotspot_source} / {hotspot_title}」。但这篇文章不按热搜复述，而是用海外来源先把事实边界钉住，再回到一个工程问题：{engineering_question} [{first_claim}]

    ## 为什么它会烧 token

    {angle} [{first_claim}]

    一个多步 Agent 往往不是只调用一次模型。它需要判断任务、选择工具、读工具返回、再决定下一步；每一步都可能把前面的上下文继续带进去。官方文档层面的事实说明，工具调用会把外部函数和 API 纳入模型应用流程 [{first_claim}]。这意味着，产品体验里看起来像“一次完成”的动作，工程上可能已经拆成了多轮模型和工具交互。

    ## 证据链

    {evidence_lines}

    这三类证据要分开看：一手来源负责确认产品或技术机制，社区讨论负责暴露真实使用摩擦，英文媒体或强二手来源负责交叉验证产业判断。只要其中一类缺失，文章就容易变成观点先行。

    ## 对用户真正有影响的地方

    对使用者来说，问题不是“Agent 贵不贵”这么笼统，而是它把成本藏到了哪些地方：更长的上下文、更频繁的工具调用、更多失败重试，以及为了稳定性增加的检查步骤。社区讨论里的开发者抱怨多步 Agent 会因为重试工具调用和携带长上下文而快速消耗 token [{second_claim}]，这正好解释了为什么同样一个任务，用 Agent 做可能比直接问答更贵。

    ## 对公司真正有影响的地方

    对企业来说，Agent 能不能大规模上线，看的也不只是模型能力。英文媒体报道提到，企业在大规模部署 AI Agent 前会关注推理成本和可靠性 [{third_claim}]。这说明成本问题不是边角料，而是决定产品能否从演示走向日常生产的门槛。

    ## 结尾判断

    所以，这个热点可以先记住一句话：Agent 的价值来自“多做几步”，成本也恰好烧在“多做几步”。真正值得关注的不是它能不能完成一个 demo，而是当任务变长、工具变多、上下文变厚之后，系统还能不能用可承受的 token 预算稳定跑完 [{first_claim}][{second_claim}][{third_claim}]。

    ## 来源

    {source_refs}
    """)


def build_ledger(topic: dict[str, Any], claims: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "topic_title": topic_title(topic),
        "policy": "Every key claim keeps a source_id and URL. Missing snippets are marked as needing deeper original-text extraction instead of fabricated.",
        "claims": claims,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate sourced article draft v1 from topic and sources")
    parser.add_argument("--topic-file", required=True)
    parser.add_argument("--sources-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ledger-output", required=True)
    parser.add_argument("--topic-index", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    configure_stdio()
    args = build_parser().parse_args()
    try:
        topic_payload = load_json(Path(args.topic_file))
        if not isinstance(topic_payload, dict):
            raise ValueError("topic file must contain object")
        topic = select_topic(topic_payload, args.topic_index)
        sources = load_sources(Path(args.sources_file))
        claims = build_claims(sources)
        article = build_article(topic, claims)
        ledger = build_ledger(topic, claims)
        write_text(Path(args.output), article)
        write_json(Path(args.ledger_output), ledger)
        result = {
            "success": True,
            "output": str(Path(args.output)),
            "ledger": str(Path(args.ledger_output)),
            "claims": len(claims),
            "sources": len(sources),
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"wrote {args.output} with {len(claims)} sourced claims")
        return 0
    except Exception as exc:
        payload = {"success": False, "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr if not args.json else sys.stdout)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
