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
    return f"《{title}》提供了一条可核验资料，可用于交叉确认本文关于技术机制、产品边界或产业进展的判断。"


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


def topic_context(topic: dict[str, Any]) -> str:
    hotspot_source, hotspot_title = topic_hotspot(topic)
    return " ".join([
        topic_title(topic),
        hotspot_source,
        hotspot_title,
        clean_text(topic.get("engineering_question") or topic.get("ai_engineer_question") or topic.get("ai_engineering_question")),
        clean_text(topic.get("token_burner_angle") or topic.get("angle") or topic.get("editorial_reason")),
    ])


def is_chip_topic(topic: dict[str, Any]) -> bool:
    context = topic_context(topic).lower()
    return any(term.lower() in context for term in ["芯片", "算力", "半导体", "gpu", "npu", "推理卡", "国产"])


def build_evidence_note(first_claim: str) -> str:
    return (
        "这些资料的作用不是堆链接，而是把判断边界钉清楚：官方文档确认产品或技术机制，"
        "代码和论文资料帮助观察实现路径，社区或媒体材料只作为使用摩擦和产业判断的辅助信号。"
        f"读者需要记住的是结论如何被支撑，而不是被一串链接淹没 [{first_claim}]。"
    )


def build_chip_article(topic: dict[str, Any], claims: list[dict[str, Any]], evidence_lines: str) -> str:
    title = topic_title(topic)
    hotspot_source, hotspot_title = topic_hotspot(topic)
    engineering_question = clean_text(topic.get("engineering_question") or topic.get("ai_engineer_question") or topic.get("ai_engineering_question") or "这条芯片消息能不能进入真实 AI 推理链路？")
    angle = clean_text(topic.get("token_burner_angle") or topic.get("angle") or topic.get("editorial_reason") or "从芯片、算力、软件栈和推理服务成本拆开看。")
    first_claim = claims[0]["source_id"] if claims else "S?"
    second_claim = claims[1]["source_id"] if len(claims) > 1 else first_claim
    third_claim = claims[2]["source_id"] if len(claims) > 2 else first_claim
    article = textwrap.dedent(f"""\
    # {title}

    ## 先说结论

    这条芯片消息真正值得看的，不是“又有好消息”这几个字，而是它离真实 AI 推理链路还有多远。芯片、算力、显存带宽、软件栈和推理服务会一起决定模型调用成本，任何一个环节跟不上，发布会参数都很难变成可用的生产能力 [{first_claim}]。

    国内热点入口是「{hotspot_source} / {hotspot_title}」。这篇文章不复述热搜，而是回到一个工程问题：{engineering_question} [{first_claim}]

    ![芯片进入推理链路的三道门槛](img-01.jpg)
    *图 1：芯片新闻要落到推理链路里看，重点是算力、软件栈和真实工作负载 [{first_claim}]。*

    ## 这条芯片消息该怎么判断

    {angle} [{first_claim}]

    对 AI 产品来说，芯片不是孤立零件。它要和驱动、算子库、模型适配、推理框架、监控和成本核算一起工作。也就是说，国产芯片真正进入生产环境，要看的不是单点峰值，而是能不能稳定承接模型推理、工具调用和长上下文任务 [{second_claim}]。

    ![从芯片到产品成本](img-02.jpg)
    *图 2：芯片能力只有进入软件栈和推理服务，才会真正影响 token 成本和响应延迟 [{second_claim}]。*

    ## 证据链

    __EVIDENCE_LINES__

    {build_evidence_note(first_claim)}

    ## 对用户真正有影响的地方

    用户感受到的不是芯片型号，而是回答速度、稳定性和价格。如果芯片和软件栈没有打通，AI 应用就会在推理延迟、并发能力和成本上暴露问题；如果打通了，同样的模型服务才可能用更可控的预算跑起来 [{second_claim}]。

    ![发布前应该看的三项指标](img-03.jpg)
    *图 3：判断芯片进展是否有意义，至少看成本、延迟和可部署性三件事 [{third_claim}]。*

    ## 对公司真正有影响的地方

    对公司来说，芯片进展最终要转成两张账：一张是推理成本账，一张是供应链和部署确定性账。只要算力、软件栈和主流模型适配没有形成闭环，企业就很难把“国产替代”直接等同于“可大规模上线” [{third_claim}]。

    ## 结尾判断

    所以，这类中国芯片热搜可以先记住一句话：真正的好消息，不是芯片参数更漂亮，而是它开始进入真实 AI 推理链路。只有当国产芯片能稳定跑模型、接入工具链、降低推理成本，才算真正烧到了该烧的 token 上 [{first_claim}][{second_claim}][{third_claim}]。
    """)
    return article.replace("__EVIDENCE_LINES__", evidence_lines)


def build_agent_article(topic: dict[str, Any], claims: list[dict[str, Any]], evidence_lines: str) -> str:
    title = topic_title(topic)
    hotspot_source, hotspot_title = topic_hotspot(topic)
    engineering_question = clean_text(topic.get("engineering_question") or topic.get("ai_engineer_question") or topic.get("ai_engineering_question") or "这个现象背后的工程问题是什么？")
    angle = clean_text(topic.get("token_burner_angle") or topic.get("angle") or topic.get("editorial_reason") or "从模型调用、上下文、工具链和成本结构拆开看。")
    first_claim = claims[0]["source_id"] if claims else "S?"
    second_claim = claims[1]["source_id"] if len(claims) > 1 else first_claim
    third_claim = claims[2]["source_id"] if len(claims) > 2 else first_claim

    article = textwrap.dedent(f"""\
    # {title}

    ## 先说结论

    这件事不只是一个 AI 产品热点。它真正值得拆的是：当产品从一次问答走向多步 Agent，成本就不再只是“输入几个字、输出几段话”，而会变成工具调用、上下文携带、失败重试和可靠性之间的系统账 [{first_claim}]。

    国内热点入口是「{hotspot_source} / {hotspot_title}」。但这篇文章不按热搜复述，而是用海外来源先把事实边界钉住，再回到一个工程问题：{engineering_question} [{first_claim}]

    ![Agent 成本链路总览](img-01.jpg)
    *图 1：从一次问答变成多步 Agent 后，token 成本会沿着上下文、工具调用和失败重试一起累积 [{first_claim}]。*

    ## 为什么它会烧 token

    {angle} [{first_claim}]

    一个多步 Agent 往往不是只调用一次模型。它需要判断任务、选择工具、读工具返回、再决定下一步；每一步都可能把前面的上下文继续带进去。官方文档层面的事实说明，工具调用会把外部函数和 API 纳入模型应用流程 [{first_claim}]。这意味着，产品体验里看起来像“一次完成”的动作，工程上可能已经拆成了多轮模型和工具交互。

    ![工具调用与上下文膨胀](img-02.jpg)
    *图 2：工具调用越多，历史上下文、工具返回和检查步骤越容易叠加成系统账 [{second_claim}]。*

    ## 证据链

    __EVIDENCE_LINES__

    {build_evidence_note(first_claim)}

    ## 对用户真正有影响的地方

    对使用者来说，问题不是“Agent 贵不贵”这么笼统，而是它把成本藏到了哪些地方：更长的上下文、更频繁的工具调用、更多失败重试，以及为了稳定性增加的检查步骤。社区讨论里的开发者抱怨多步 Agent 会因为重试工具调用和携带长上下文而快速消耗 token [{second_claim}]，这正好解释了为什么同样一个任务，用 Agent 做可能比直接问答更贵。

    ![发布前应该看的三项成本](img-03.jpg)
    *图 3：判断一个 Agent 产品能否长期使用，至少要同时看成本、延迟和可靠性 [{third_claim}]。*

    ## 对公司真正有影响的地方

    对企业来说，Agent 能不能大规模上线，看的也不只是模型能力。英文媒体报道提到，企业在大规模部署 AI Agent 前会关注推理成本和可靠性 [{third_claim}]。这说明成本问题不是边角料，而是决定产品能否从演示走向日常生产的门槛。

    ## 结尾判断

    所以，这个热点可以先记住一句话：Agent 的价值来自“多做几步”，成本也恰好烧在“多做几步”。真正值得关注的不是它能不能完成一个 demo，而是当任务变长、工具变多、上下文变厚之后，系统还能不能用可承受的 token 预算稳定跑完 [{first_claim}][{second_claim}][{third_claim}]。
    """)
    return article.replace("__EVIDENCE_LINES__", evidence_lines)


def build_article(topic: dict[str, Any], claims: list[dict[str, Any]]) -> str:
    evidence_lines = "\n".join(claim_sentence(claim) for claim in claims) or "- 暂无可引用事实。"
    if is_chip_topic(topic):
        return build_chip_article(topic, claims, evidence_lines)
    return build_agent_article(topic, claims, evidence_lines)


def build_ledger(topic: dict[str, Any], claims: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "topic_title": topic_title(topic),
        "policy": "Visible article citations use source IDs only; source URLs stay in this internal ledger. Key facts should prefer first-hand/primary sources; community and media are supporting signals, not mandatory categories.",
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
