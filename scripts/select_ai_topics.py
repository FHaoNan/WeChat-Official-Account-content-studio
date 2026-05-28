#!/usr/bin/env python3
"""Select AI-engineering-friendly topics from Chinese hotspot input.

Policy: 国内热点发现，海外信息补证。This script is intentionally local and
heuristic: it does not pretend to verify facts. It ranks hotspot candidates for
"烧 Token 的人" and emits concrete overseas evidence directions for the later
research step.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

AI_DIRECT = [
    "ai", "AI", "大模型", "模型", "Agent", "agent", "智能体", "OpenAI", "ChatGPT", "Claude",
    "Gemini", "DeepSeek", "通义", "豆包", "Kimi", "机器人", "推理", "token", "Token", "算力",
    "GPU", "芯片", "英伟达", "NVIDIA", "开源", "AIGC", "多模态", "RAG", "MCP",
]
AI_INDIRECT = ["手机", "汽车", "办公", "教育", "医疗", "游戏", "搜索", "浏览器", "电商", "云", "软件", "App", "应用"]
ENGINEERING = [
    "发布", "开源", "上下文", "成本", "token", "Token", "推理", "调用", "API", "训练", "部署", "评测",
    "基准", "benchmark", "芯片", "GPU", "云", "Agent", "RAG", "MCP", "工作流", "自动化", "财报", "涨价",
]
COMMUNITY_EVIDENCE = ["开源", "GitHub", "论文", "arxiv", "模型", "OpenAI", "Anthropic", "Google", "Meta", "微软", "英伟达", "NVIDIA", "财报", "发布"]
ENTERTAINMENT = ["明星", "恋情", "机场", "穿搭", "综艺", "演唱会", "八卦", "粉丝", "塌房"]
INVESTMENT = ["股票", "股价", "财报", "市值", "营收", "利润", "涨停", "产业链", "芯片", "算力"]

COLUMN_RULES = [
    ("模型发布解读", ["模型", "OpenAI", "ChatGPT", "Claude", "Gemini", "DeepSeek", "Kimi", "发布", "开源", "评测"]),
    ("AI 产品体验", ["App", "应用", "产品", "搜索", "浏览器", "办公", "插件", "Agent", "工作流"]),
    ("工程师科普", ["token", "Token", "推理", "RAG", "MCP", "部署", "训练", "调用", "API", "上下文"]),
    ("产业链观察", ["芯片", "GPU", "英伟达", "NVIDIA", "云", "财报", "算力", "产业链", "营收"]),
]

FRAMEWORKS = ["痛点型", "故事型", "清单型", "对比型", "热点解读型"]


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def load_hotspots(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    items = data.get("items", []) if isinstance(data, dict) else []
    return [item for item in items if isinstance(item, dict)]


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse an LLM JSON object, tolerating fenced code blocks."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(stripped[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("LLM output must be a JSON object")
    return data


def contains_any(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)


def count_hits(text: str, words: list[str]) -> int:
    return sum(1 for word in words if word in text)


def clamp(value: float, low: int = 1, high: int = 10) -> int:
    return max(low, min(high, int(round(value))))


def score_heat(item: dict[str, Any]) -> int:
    hot = item.get("hot_normalized", item.get("hot", 0)) or 0
    try:
        hot = float(hot)
    except Exception:
        hot = 0.0
    if hot <= 10:
        return clamp(hot)
    return clamp(1 + hot / 100 * 9)


def extract_platform_signals(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized domestic platform signals for traffic-aware ranking."""
    raw = item.get("platform_signals")
    signals: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            source = str(entry.get("source") or entry.get("platform") or "").strip()
            if not source:
                continue
            signal = dict(entry)
            signal["source"] = source
            signals.append(signal)
    if not signals:
        source_text = str(item.get("source") or "").strip()
        sources = [part.strip() for part in re.split(r"[,，/、|]", source_text) if part.strip()]
        if not sources and source_text:
            sources = [source_text]
        for source in sources:
            signals.append({
                "source": source,
                "hot": item.get("hot", 0),
                "hot_normalized": item.get("hot_normalized", None),
                "url": item.get("url", ""),
            })
    return signals


def platform_heat_summary(item: dict[str, Any]) -> dict[str, Any]:
    signals = extract_platform_signals(item)
    sources = list(dict.fromkeys(str(signal.get("source") or "").strip() for signal in signals if str(signal.get("source") or "").strip()))
    platform_count = len(sources)
    heat_values = []
    for signal in signals:
        value = signal.get("hot_normalized", signal.get("hot", 0)) or 0
        try:
            heat_values.append(float(value))
        except Exception:
            continue
    top_heat = max(heat_values) if heat_values else float(item.get("hot_normalized", item.get("hot", 0)) or 0)
    average_heat = sum(heat_values) / len(heat_values) if heat_values else top_heat
    # One platform = weak cross-platform proof; 2 platforms = meaningful; 3+ = strong current attention.
    platform_score = clamp(1 + min(platform_count, 4) * 2.2 + min(average_heat, 100) / 100 * 2)
    return {
        "sources": sources,
        "platform_count": platform_count,
        "top_heat": round(top_heat, 1),
        "average_heat": round(average_heat, 1),
        "score": platform_score,
    }


def build_why_now(platform_heat: dict[str, Any], domestic_heat: int, category: str) -> str:
    sources = platform_heat.get("sources") or []
    if sources:
        source_text = "、".join(sources[:4])
        if len(sources) > 4:
            source_text += f"等 {len(sources)} 个平台"
        platform_part = f"它已经出现在{source_text}"
    else:
        platform_part = "它已经进入国内热点池"
    if platform_heat.get("platform_count", 0) >= 2:
        heat_part = f"，且有跨平台热度信号（国内热度 {domestic_heat}/10）"
    else:
        heat_part = f"，当前国内热度 {domestic_heat}/10"
    return f"{platform_part}{heat_part}；类别为{category}，适合先用国内注意力切入，再用海外一手资料补事实。"


def classify_candidate(title: str) -> str:
    if contains_any(title, AI_DIRECT):
        return "直接 AI 热点"
    if contains_any(title, AI_INDIRECT):
        return "可 AI 化解释的泛科技热点"
    if contains_any(title, INVESTMENT):
        return "可产业链延展的财经/商业热点"
    return "纯娱乐/社会/情绪热点"


def score_item(item: dict[str, Any], style: dict[str, Any]) -> dict[str, Any] | None:
    title = str(item.get("title") or "").strip()
    description = str(item.get("description") or "").strip()
    text = f"{title} {description}"
    if not title:
        return None

    blacklist = style.get("blacklist", {}) if isinstance(style.get("blacklist"), dict) else {}
    blacklist_words = [str(x) for x in blacklist.get("words", [])]
    blacklist_topics = [str(x) for x in blacklist.get("topics", [])]
    if contains_any(text, blacklist_words + blacklist_topics):
        return None
    if contains_any(text, ENTERTAINMENT) and not contains_any(text, AI_DIRECT + AI_INDIRECT):
        return None

    category = classify_candidate(text)
    if category == "纯娱乐/社会/情绪热点" and not contains_any(text, AI_DIRECT + AI_INDIRECT):
        return None
    direct_hits = count_hits(text, AI_DIRECT)
    indirect_hits = count_hits(text, AI_INDIRECT)
    engineering_hits = count_hits(text, ENGINEERING)
    evidence_hits = count_hits(text, COMMUNITY_EVIDENCE)

    platform_heat = platform_heat_summary(item)
    base_domestic_heat = score_heat(item)
    # Traffic matters for this account: cross-platform heat should lift suitable AI topics.
    domestic_heat = clamp(max(base_domestic_heat, platform_heat["top_heat"] / 10) + max(0, platform_heat["platform_count"] - 1) * 0.8)
    ai_relevance = clamp(3 + direct_hits * 3 + indirect_hits * 1.5)
    if category == "纯娱乐/社会/情绪热点":
        ai_relevance = min(ai_relevance, 4)
    engineering_value = clamp(3 + engineering_hits * 1.5 + direct_hits)
    overseas_evidence = clamp(3 + evidence_hits * 1.4 + direct_hits * 0.8)
    if category == "纯娱乐/社会/情绪热点":
        overseas_evidence = min(overseas_evidence, 4)
    readability = clamp(8 if domestic_heat >= 7 else 6)
    if engineering_value >= 9 and domestic_heat <= 4:
        readability -= 1

    weighted = round(
        domestic_heat * 0.35
        + platform_heat["score"] * 0.10
        + ai_relevance * 0.25
        + engineering_value * 0.15
        + overseas_evidence * 0.05
        + readability * 0.10,
        2,
    )

    column = choose_column(text)
    question = build_engineer_question(title, column)
    english_keywords = suggest_english_keywords(title)
    return {
        "hotspot": {
            "title": title,
            "source": item.get("source", ""),
            "hot": item.get("hot", 0),
            "hot_normalized": item.get("hot_normalized", None),
            "url": item.get("url", ""),
            "description": description,
            "category": category,
            "platform_signals": extract_platform_signals(item),
        },
        "platform_heat": platform_heat,
        "why_now": build_why_now(platform_heat, domestic_heat, category),
        "proposed_title": build_title(title, column),
        "ai_engineer_question": question,
        "angle": build_angle(column),
        "column": column,
        "scores": {
            "domestic_heat": domestic_heat,
            "ai_relevance": ai_relevance,
            "engineering_value": engineering_value,
            "overseas_evidence": overseas_evidence,
            "readability": readability,
            "weighted_total": weighted,
        },
        "click_potential": click_potential(weighted, domestic_heat, engineering_value),
        "seo": {"score": None, "note": "未调用 seo_keywords.py；后续写作前可对拟题再跑 SEO 验证"},
        "recommended_framework": choose_framework(column, title),
        "overseas_evidence": build_overseas_evidence(title, english_keywords, column),
        "risk_warning": build_risk_warning(title, overseas_evidence, column),
        "history_marker": "未读取 history.yaml" if not (REPO_ROOT / "history.yaml").exists() else "待接入 history.yaml 去重",
        "auto_write_allowed": overseas_evidence >= 5,
    }


def choose_column(text: str) -> str:
    best = ("工程师科普", 0)
    for column, words in COLUMN_RULES:
        hits = count_hits(text, words)
        if hits > best[1]:
            best = (column, hits)
    return best[0]


def build_engineer_question(title: str, column: str) -> str:
    if column == "产业链观察":
        return f"这个热点真正值得写的问题是：{title}背后的 AI 需求，落在算力、推理服务、企业软件，还是营销口径里？"
    if column == "模型发布解读":
        return f"这个热点真正值得写的问题是：{title}到底提升了什么能力，又把 token 成本和使用门槛转移到了哪里？"
    if column == "AI 产品体验":
        return f"这个热点真正值得写的问题是：{title}是真正改善工作流，还是用模型调用成本换短期增长？"
    return f"这个热点真正值得写的问题是：{title}能解释哪条调用链路、能力边界或工程取舍？"


def build_title(title: str, column: str) -> str:
    cleaned = re.sub(r"[#【】\[\]]", "", title).strip()
    prefix = {
        "模型发布解读": "新模型热度背后",
        "AI 产品体验": "这个AI产品值不值",
        "工程师科普": "把这个AI问题讲透",
        "产业链观察": "AI产业链钱烧在哪",
    }.get(column, "这条AI热点怎么看")
    candidate = f"{prefix}：{cleaned}"
    return candidate[:28]


def build_angle(column: str) -> str:
    return {
        "模型发布解读": "先讲读者看到的发布热度，再拆能力边界、推理成本、可复现证据和适用场景。",
        "AI 产品体验": "从一个具体使用场景切入，拆产品承诺、真实工作流、调用成本和替代方案。",
        "工程师科普": "把抽象概念翻译成一次请求、一条链路、一个成本账本，让非工程读者也能看懂。",
        "产业链观察": "只拆公司、产品、供需、成本和竞争格局，不写荐股、不写确定性收益。",
    }.get(column, "从热点里的真实问题切入，回到海外证据补证。")


def choose_framework(column: str, title: str) -> str:
    if column == "AI 产品体验":
        return "痛点型"
    if column == "产业链观察":
        return "对比型"
    if "发布" in title or "热议" in title:
        return "热点解读型"
    return "清单型"


def suggest_english_keywords(title: str) -> list[str]:
    mapping = {
        "OpenAI": "OpenAI", "ChatGPT": "ChatGPT", "Claude": "Claude", "Gemini": "Google Gemini",
        "DeepSeek": "DeepSeek", "英伟达": "NVIDIA", "芯片": "AI chip", "财报": "earnings AI demand",
        "模型": "large language model", "Agent": "AI agent", "智能体": "AI agent", "开源": "open source model",
        "推理": "inference cost", "算力": "AI compute", "机器人": "AI robotics",
    }
    keywords = [v for k, v in mapping.items() if k in title]
    if not keywords:
        keywords = ["AI product", "large language model"]
    return list(dict.fromkeys(keywords))[:4]


def build_overseas_evidence(title: str, english_keywords: list[str], column: str) -> dict[str, Any]:
    kw = " ".join(english_keywords)
    directions = [
        f"官方/文档：{kw} official blog documentation release notes",
        f"GitHub/论文：{kw} site:github.com OR site:arxiv.org OR site:huggingface.co",
        f"社区线索：{kw} site:x.com OR site:reddit.com OR site:news.ycombinator.com",
        f"英文媒体：{kw} site:reuters.com OR site:bloomberg.com OR site:theverge.com OR site:techcrunch.com",
    ]
    if column == "产业链观察" or contains_any(title, INVESTMENT):
        directions.append(f"财报/产业链：{kw} earnings transcript annual report investor relations")
    return {"english_keywords": english_keywords, "directions": directions}


def build_risk_warning(title: str, overseas_score: int, column: str) -> str:
    risks = []
    if overseas_score < 5:
        risks.append("海外证据可得分低于 5，不能进入自动写作，必须先补素材")
    if column == "产业链观察" or contains_any(title, INVESTMENT):
        risks.append("产业链/财报内容只能拆商业逻辑，避免荐股、买卖点和确定性收益")
    if not risks:
        risks.append("注意不要只复述国内热搜，必须用海外一手或强二手来源补证")
    return "；".join(risks)


def click_potential(total: float, heat: int, engineering: int) -> dict[str, str]:
    if total >= 8 or (heat >= 8 and engineering >= 8):
        return {"level": "高", "reason": "国内热度和工程解释价值同时较强"}
    if total >= 6.5:
        return {"level": "中", "reason": "适合账号定位，但需要更强标题承诺或证据支撑"}
    return {"level": "低", "reason": "热度、AI 相关度或工程解释价值不足"}


def build_llm_prompt(topics: list[dict[str, Any]], style: dict[str, Any]) -> str:
    compact_topics = []
    for idx, topic in enumerate(topics, 1):
        compact_topics.append({
            "index": idx,
            "hotspot_title": topic["hotspot"]["title"],
            "source": topic["hotspot"].get("source", ""),
            "description": topic["hotspot"].get("description", ""),
            "heuristic_scores": topic["scores"],
            "column": topic["column"],
            "ai_engineer_question": topic["ai_engineer_question"],
            "overseas_evidence": topic["overseas_evidence"],
        })
    style_brief = {
        "name": style.get("name", "烧 Token 的人"),
        "topics": style.get("topics", []),
        "tone": style.get("tone", ""),
        "topic_policy": style.get("topic_policy", {}),
        "source_policy": style.get("source_policy", {}),
    }
    return (
        "你是公众号《烧 Token 的人》的选题主编。账号定位：用 AI 大模型工程师视角，讲清楚 AI、模型、产品和那些被烧掉的 token。\n"
        "国内热点只用于发现读者关心什么，且当前阶段要优先选择已经进入国内注意力场的 AI 相关热点；事实、技术判断、产品细节和产业链证据必须优先用海外一手来源、GitHub、论文、官方文档、财报和英文主流媒体补证。\n"
        "任务：对候选热点做复评和重排。不要编事实，只判断选题适配度与海外补证方向。\n"
        "只返回 JSON 对象，格式：{\"reviews\":[{\"hotspot_title\":\"...\",\"fit_score\":1-10,\"evidence_plan_score\":1-10,\"write_or_skip\":\"write|skip\",\"editorial_reason\":\"...\",\"token_burner_angle\":\"...\",\"reader_question\":\"...\",\"overseas_evidence_plan\":[{\"source_type\":\"official_docs|github_or_paper|earnings|mainstream_media|community\",\"query\":\"...\"}],\"risk_flags\":[\"...\"]}]}。\n"
        f"账号风格配置：{json.dumps(style_brief, ensure_ascii=False)}\n"
        f"候选热点：{json.dumps(compact_topics, ensure_ascii=False)}"
    )


def normalize_llm_reviews(data: dict[str, Any]) -> list[dict[str, Any]]:
    reviews = data.get("reviews", [])
    if not isinstance(reviews, list):
        raise ValueError("LLM JSON must contain reviews list")
    normalized = []
    for item in reviews:
        if not isinstance(item, dict):
            continue
        title = str(item.get("hotspot_title") or item.get("title") or "").strip()
        if not title:
            continue
        fit_score = clamp(float(item.get("fit_score", 1)))
        evidence_plan_score = clamp(float(item.get("evidence_plan_score", item.get("evidence_score", 1))))
        write_or_skip = str(item.get("write_or_skip") or "write").strip().lower()
        if write_or_skip not in {"write", "skip"}:
            write_or_skip = "write"
        plan = item.get("overseas_evidence_plan", [])
        if not isinstance(plan, list):
            plan = []
        risk_flags = item.get("risk_flags", [])
        if not isinstance(risk_flags, list):
            risk_flags = [str(risk_flags)]
        normalized.append({
            "index": int(item["index"]) if str(item.get("index", "")).isdigit() else None,
            "hotspot_title": title,
            "fit_score": fit_score,
            "evidence_plan_score": evidence_plan_score,
            "write_or_skip": write_or_skip,
            "editorial_reason": str(item.get("editorial_reason") or "").strip(),
            "token_burner_angle": str(item.get("token_burner_angle") or "").strip(),
            "reader_question": str(item.get("reader_question") or "").strip(),
            "overseas_evidence_plan": plan,
            "risk_flags": [str(flag) for flag in risk_flags],
        })
    return normalized


def load_llm_fixture(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("LLM fixture must be a JSON object")
    return normalize_llm_reviews(data)


def call_openai_compatible(config_path: Path, topics: list[dict[str, Any]], style: dict[str, Any]) -> list[dict[str, Any]]:
    if not config_path.exists():
        raise FileNotFoundError(f"missing LLM config: {config_path}")
    config = load_yaml(config_path)
    llm = config.get("llm", {}) if isinstance(config.get("llm"), dict) else {}
    provider = str(llm.get("provider") or "openai_compatible")
    if provider != "openai_compatible":
        raise ValueError(f"unsupported llm.provider: {provider}")
    base_url = str(llm.get("base_url") or "").rstrip("/")
    model = str(llm.get("model") or "").strip()
    api_key_env = str(llm.get("api_key_env") or "").strip()
    api_key = str(llm.get("api_key") or "").strip() or (os.environ.get(api_key_env, "").strip() if api_key_env else "")
    if not base_url:
        raise ValueError("llm.base_url missing")
    if not model:
        raise ValueError("llm.model missing")
    if not api_key:
        raise ValueError("llm api key missing; set llm.api_key_env or llm.api_key")
    timeout = float(llm.get("timeout_seconds", 60))
    prompt = build_llm_prompt(topics, style)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只输出严格 JSON，不输出 Markdown。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(llm.get("temperature", 0.2)),
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
    content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        raise ValueError("LLM response missing message content")
    return normalize_llm_reviews(parse_json_object(content))


def apply_llm_reviews(topics: list[dict[str, Any]], reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_title = {review["hotspot_title"]: review for review in reviews}
    by_index = {review["index"]: review for review in reviews if review.get("index") is not None}
    for idx, topic in enumerate(topics, 1):
        title = topic["hotspot"]["title"]
        review = by_index.get(idx) or by_title.get(title)
        if not review:
            topic["scores"]["final_score"] = topic["scores"]["weighted_total"]
            continue
        heuristic_total = float(topic["scores"]["weighted_total"])
        final_score = round(
            heuristic_total * 0.45
            + float(review["fit_score"]) * 0.35
            + float(review["evidence_plan_score"]) * 0.20,
            2,
        )
        topic["llm_review"] = review
        topic["scores"]["heuristic_total"] = heuristic_total
        topic["scores"]["final_score"] = final_score
        if review["write_or_skip"] == "skip" or review["evidence_plan_score"] < 5 or final_score < 6:
            topic["auto_write_allowed"] = False
    topics.sort(key=lambda item: item["scores"].get("final_score", item["scores"]["weighted_total"]), reverse=True)
    return topics


def render_markdown(topics: list[dict[str, Any]]) -> str:
    lines = ["# Top AI 选题", ""]
    for idx, topic in enumerate(topics, 1):
        scores = topic["scores"]
        display_score = scores.get("final_score", scores["weighted_total"])
        score_label = "最终分" if "final_score" in scores else "总分"
        lines.extend([
            f"### 选题 {idx}: {topic['hotspot']['title']}（{score_label} {display_score}）",
            "",
            f"- 对应标题（20-28字）：\"{topic['proposed_title']}\"",
            f"- 国内热点来源：{topic['hotspot'].get('source')} / hot={topic['hotspot'].get('hot_normalized') or topic['hotspot'].get('hot')}",
            f"- 为什么今天值得写：{topic.get('why_now', '')}",
            f"- 平台热度：{topic.get('platform_heat', {}).get('platform_count', 0)} 个平台 / {','.join(topic.get('platform_heat', {}).get('sources', []))}",
            f"- AI 工程师问题：{topic['ai_engineer_question']}",
            f"- 切入角度：{topic['angle']}",
            f"- 栏目：{topic['column']}",
            f"- 评分：国内热度 {scores['domestic_heat']}/10 | AI 相关度 {scores['ai_relevance']}/10 | 工程解释价值 {scores['engineering_value']}/10 | 海外证据可得 {scores['overseas_evidence']}/10 | 大众可读性 {scores['readability']}/10",
            *([f"- LLM 复评：最终分 {scores['final_score']}/10 | fit={topic['llm_review']['fit_score']}/10 | evidence_plan={topic['llm_review']['evidence_plan_score']}/10 | {topic['llm_review']['editorial_reason']}"] if "llm_review" in topic else []),
            f"- 点击率潜力：{topic['click_potential']['level']} — {topic['click_potential']['reason']}",
            f"- SEO 友好度：未验证 — {topic['seo']['note']}",
            f"- 推荐框架：{topic['recommended_framework']}",
            f"- 海外补证方向：{'；'.join(topic['overseas_evidence']['directions'])}",
            f"- 风险提醒：{topic['risk_warning']}",
            f"- 历史标记：{topic['history_marker']}",
            "",
        ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Select AI topics from Chinese hotspots using five-dimensional scoring.")
    parser.add_argument("--hotspots", required=True, help="hotspots JSON from scripts/fetch_hotspots.py")
    parser.add_argument("--style", default=str(REPO_ROOT / "style.yaml"), help="style.yaml path")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--prefilter-limit", type=int, default=20, help="Heuristic candidate count before optional LLM rerank")
    parser.add_argument("--llm-rerank", action="store_true", help="Use optional LLM reranker after heuristic prefilter")
    parser.add_argument("--llm-fixture", default="", help="Read LLM review JSON from fixture file instead of calling an API")
    parser.add_argument("--config", default=str(REPO_ROOT / "config.yaml"), help="config.yaml containing llm provider settings")
    parser.add_argument("--output", "-o", default="", help="Optional output path")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of markdown")
    args = parser.parse_args()

    hotspots = load_hotspots(Path(args.hotspots))
    style = load_yaml(Path(args.style))
    topics = [score_item(item, style) for item in hotspots]
    topics = [item for item in topics if item is not None]
    topics.sort(key=lambda item: item["scores"]["weighted_total"], reverse=True)
    heuristic_topics = list(topics)

    llm_status: dict[str, Any] = {"enabled": bool(args.llm_rerank), "status": "disabled"}
    if args.llm_rerank:
        topics = topics[: max(1, args.prefilter_limit)]
        try:
            if args.llm_fixture:
                reviews = load_llm_fixture(Path(args.llm_fixture))
                llm_status = {"enabled": True, "status": "applied", "provider": "fixture", "review_count": len(reviews)}
            else:
                reviews = call_openai_compatible(Path(args.config), topics, style)
                llm_status = {"enabled": True, "status": "applied", "provider": "openai_compatible", "review_count": len(reviews)}
            topics = apply_llm_reviews(topics, reviews)
        except Exception as exc:
            llm_status = {"enabled": True, "status": "fallback", "provider": "heuristic", "error": str(exc)}
            topics = list(heuristic_topics)
            topics.sort(key=lambda item: item["scores"]["weighted_total"], reverse=True)

    topics = topics[: max(1, args.limit)]

    payload = {
        "policy": "国内热点发现，海外信息补证",
        "scoring_weights": {
            "domestic_heat": 0.35,
            "platform_heat": 0.10,
            "ai_relevance": 0.25,
            "engineering_value": 0.15,
            "overseas_evidence": 0.05,
            "readability": 0.10,
            "llm_final_score_when_enabled": {
                "heuristic_total": 0.45,
                "llm_fit_score": 0.35,
                "llm_evidence_plan_score": 0.20,
            },
        },
        "llm_rerank": llm_status,
        "count": len(topics),
        "topics": topics,
    }
    output_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n" if args.json else render_markdown(topics) + "\n"
    if args.output:
        Path(args.output).write_text(output_text, encoding="utf-8")
    print(output_text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
