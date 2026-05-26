#!/usr/bin/env python3
"""
CLI entry point for WeWrite.

Usage:
    python cli.py preview article.md --theme professional-clean
    python cli.py publish article.md --appid wx123 --secret abc123
    python cli.py themes
"""

import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import textwrap
import webbrowser
from pathlib import Path

import yaml

from converter import WeChatConverter, preview_html
from theme import load_theme, list_themes
from wechat_api import get_access_token, upload_image, upload_thumb
from publisher import create_draft, create_image_post

# Config file search order
SKILL_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATHS = [
    SKILL_ROOT / "skill2 paibanyouhua" / ".config" / "md2wechat" / "config.yaml",
    Path.cwd() / "config.yaml",
    SKILL_ROOT / "config.yaml",  # skill root
    Path(__file__).parent / "config.yaml",          # toolkit dir
    Path.home() / ".config" / "wewrite" / "config.yaml",
]


def load_config() -> dict:
    """Load config from first found config.yaml."""
    paths: list[Path] = []
    env_path = os.environ.get("WEWRITE_PUBLISH_CONFIG", "")
    if env_path:
        raw = Path(env_path).expanduser()
        paths.append(raw if raw.is_absolute() else Path.cwd() / raw)
    paths.extend(CONFIG_PATHS)

    for p in paths:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    return {}



def write_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def safe_folder_name(value: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", value).strip().strip(".")
    if not name:
        raise ValueError("The title becomes an empty folder name after sanitization.")
    return name


def render_template(path: Path, tokens: dict[str, str]) -> str:
    content = path.read_text(encoding="utf-8")
    for key, value in tokens.items():
        content = content.replace(key, value)
    return content


def resolve_article_dir(path_value: str) -> Path:
    raw = Path(path_value).expanduser()
    candidates = [raw] if raw.is_absolute() else [SKILL_ROOT / raw, SKILL_ROOT / "output" / raw]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Article folder not found. Tried: {', '.join(str(item) for item in candidates)}")


def run_python_script(script: Path, args: list[str]) -> int:
    command = [sys.executable, str(script), *args]
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    paths = [str(SKILL_ROOT / "toolkit"), str(SKILL_ROOT / "scripts")]
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    completed = subprocess.run(
        command,
        cwd=str(SKILL_ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return int(completed.returncode)


def run_python_script_capture(script: Path, args: list[str]) -> tuple[int, str, str]:
    command = [sys.executable, str(script), *args]
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    paths = [str(SKILL_ROOT / "toolkit"), str(SKILL_ROOT / "scripts")]
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    completed = subprocess.run(
        command,
        cwd=str(SKILL_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return int(completed.returncode), completed.stdout, completed.stderr


def output_root_path() -> Path:
    output_root = Path(os.environ.get("WEWRITE_OUTPUT_ROOT", str(SKILL_ROOT / "output"))).expanduser()
    if not output_root.is_absolute():
        output_root = (SKILL_ROOT / output_root).resolve()
    return output_root


def create_article_directory(title: str, author: str = "", source_url: str = "", *, force: bool = False) -> dict[str, str]:
    folder_name = safe_folder_name(title)
    output_root = output_root_path()
    article_dir = output_root / folder_name
    if article_dir.exists() and not force:
        raise FileExistsError(f"Article folder already exists: {article_dir}")

    assets_dir = article_dir / "assets"
    generated_dir = article_dir / "generated"
    assets_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)

    template_root = SKILL_ROOT / "skill2 paibanyouhua" / "templates"
    tokens = {"__TITLE__": title, "__AUTHOR__": author, "__SOURCE_URL__": source_url}
    template_map = {
        template_root / "article.md.template": article_dir / "article.md",
        template_root / "draft-metadata.json.template": article_dir / "draft-metadata.json",
        template_root / "article-body.template.html.template": article_dir / "article-body.template.html",
        template_root / "image-prompts.md.template": generated_dir / "image-prompts.md",
    }
    for template, output in template_map.items():
        if not template.exists():
            raise FileNotFoundError(f"Template not found: {template}")
        write_utf8(output, render_template(template, tokens))

    return {
        "article_dir": str(article_dir.resolve()),
        "folder_name": folder_name,
        "article_file": str((article_dir / "article.md").resolve()),
        "html_template": str((article_dir / "article-body.template.html").resolve()),
        "metadata_file": str((article_dir / "draft-metadata.json").resolve()),
        "image_prompt_file": str((generated_dir / "image-prompts.md").resolve()),
    }


def cmd_new(args) -> None:
    """Create a standard managed article directory without PowerShell."""
    title = args.title.strip()
    if not title:
        raise ValueError("--title is required")
    payload = create_article_directory(title, args.author or "", args.source_url or "", force=args.force)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_render(args) -> int:
    article_dir = resolve_article_dir(args.article_dir)
    render_script = SKILL_ROOT / "skill2 paibanyouhua" / "scripts" / "render-article.py"
    render_args = ["--article-dir", str(article_dir)]
    if args.theme:
        render_args.extend(["--theme", args.theme])
    render_code = run_python_script(render_script, render_args)
    if render_code != 0:
        return render_code

    # Keep the old render wrapper behavior: rendering also refreshes the quality
    # reports under generated/. By default this is report-only so `render` remains
    # usable while config.yaml/history.yaml are intentionally absent; `check` and
    # `publish-draft` remain the strict blocking gates.
    check_script = SKILL_ROOT / "skill2 paibanyouhua" / "scripts" / "run-quality-gates.py"
    check_code, check_stdout, check_stderr = run_python_script_capture(check_script, ["--article-dir", str(article_dir)])
    if check_stdout:
        print(check_stdout, end="", file=sys.stderr)
    if check_stderr:
        print(check_stderr, end="", file=sys.stderr)
    if check_code != 0 and not args.strict_check:
        print(
            "render completed; quality gates produced non-pass items. "
            "Run `python3 toolkit/cli.py check --article-dir ...` for strict validation.",
            file=sys.stderr,
        )
        return 0
    return check_code


def cmd_check(args) -> int:
    article_dir = resolve_article_dir(args.article_dir)
    script = SKILL_ROOT / "skill2 paibanyouhua" / "scripts" / "run-quality-gates.py"
    return run_python_script(script, ["--article-dir", str(article_dir), "--strict"])


def cmd_publish_draft(args) -> int:
    article_dir = resolve_article_dir(args.article_dir)
    script = SKILL_ROOT / "skill2 paibanyouhua" / "scripts" / "publish-article.py"
    script_args = ["--article-dir", str(article_dir), "--json"]
    if args.allow_native_lists:
        script_args.append("--allow-native-lists")
    if args.config:
        script_args.extend(["--config", args.config])
    if args.dry_run:
        script_args.append("--dry-run")
    return run_python_script(script, script_args)


def _load_topic_payload(topic_file: Path) -> dict:
    data = json.loads(topic_file.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data
    raise ValueError("topic file must contain a JSON object")


def _select_topic(payload: dict, index: int | None = None) -> dict:
    topics = payload.get("topics")
    if isinstance(topics, list) and topics:
        if index is not None:
            if index < 0 or index >= len(topics):
                raise IndexError(f"--topic-index out of range: {index}")
            topic = topics[index]
        else:
            topic = next((item for item in topics if item.get("auto_write_allowed", True)), topics[0])
    else:
        topic = payload.get("topic", payload)
    if not isinstance(topic, dict):
        raise ValueError("selected topic must be a JSON object")
    return topic


def _topic_title(topic: dict) -> str:
    raw_hotspot = topic.get("hotspot")
    hotspot: dict = raw_hotspot if isinstance(raw_hotspot, dict) else {}
    return str(topic.get("recommended_title") or topic.get("title") or hotspot.get("title") or "未命名选题").strip()


def _topic_sources(topic: dict, payload: dict) -> list[dict]:
    raw_sources = topic.get("sources") or topic.get("evidence_sources") or topic.get("verified_sources") or payload.get("sources") or []
    sources: list[dict] = []
    for item in raw_sources:
        if isinstance(item, str):
            sources.append({"url": item})
        elif isinstance(item, dict):
            copied = dict(item)
            if copied.get("query") and not copied.get("url"):
                copied.setdefault("title", copied.get("query"))
            sources.append(copied)
    return sources


def _source_lines(sources: list[dict]) -> str:
    if not sources:
        return "- 暂无已验证来源；需要先补齐 official/GitHub/论文/财报、社区讨论、英文媒体三类证据。"
    lines = []
    for idx, source in enumerate(sources, 1):
        title = str(source.get("title") or source.get("name") or source.get("source_type") or f"来源 {idx}").strip()
        url = str(source.get("url") or source.get("link") or "").strip()
        source_type = str(source.get("source_type") or source.get("category") or "unclassified").strip()
        if url:
            lines.append(f"- [{title}]({url})（{source_type}）")
        else:
            query = str(source.get("query") or "").strip()
            lines.append(f"- {title}（{source_type}）：{query or '待补 URL'}")
    return "\n".join(lines)


def _write_placeholder_assets(article_dir: Path) -> None:
    assets = article_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for name in ["img-01.jpg", "cover-wide.jpg", "cover-square.jpg"]:
        path = assets / name
        if not path.exists():
            path.write_bytes(b"placeholder")


def _build_topic_article(topic: dict, sources: list[dict]) -> str:
    title = _topic_title(topic)
    hotspot = topic.get("hotspot") if isinstance(topic.get("hotspot"), dict) else {}
    hotspot_title = str(hotspot.get("title") or topic.get("hotspot_title") or title)
    hotspot_source = str(hotspot.get("source") or topic.get("source") or "国内热点")
    engineering_question = str(topic.get("engineering_question") or topic.get("ai_engineering_question") or "这个现象背后的工程问题是什么？")
    angle = str(topic.get("token_burner_angle") or topic.get("angle") or topic.get("editorial_reason") or "从模型调用、上下文、工具链和成本结构拆开看。")
    reader_question = str(topic.get("reader_question") or "如果你正在用 AI 工具，这会影响你每天的使用成本和判断方式。")
    source_section = _source_lines(sources)
    return textwrap.dedent(f"""\
    # {title}

    先说结论：这不是一条单纯的 AI 热点，而是一个值得从模型工程、产品机制和 token 成本一起拆开的信号。

    :::callout info
    国内热点入口：{hotspot_source} / {hotspot_title}
    :::

    ## 这件事真正值得看的地方

    {reader_question}

    对「烧 Token 的人」来说，关键不是复述热搜，而是追问：一次看似简单的 AI 产品变化，背后到底多烧了哪些 token、哪些调用、哪些上下文窗口，以及哪些工程取舍。

    ## 工程问题

    {engineering_question}

    {angle}

    这里至少有三层需要拆开：第一层是用户看到的产品变化，第二层是模型和工具调用链路，第三层是成本、延迟、可靠性之间的权衡。很多争议表面上是体验问题，底层其实是 token 预算和系统设计问题。

    ## 事实链路怎么补

    这篇草稿已经先把可验证来源放进 sources.json，并在质量门禁里强制检查三类来源是否齐全：一手来源、社区讨论、英文媒体或强二手验证。

    {source_section}

    ![图 1：从热点到事实链路的检查路径](img-01.jpg)
    *图 1：从国内热点发现问题，再用海外一手和强二手来源补证。*

    ## 暂定写作结构

    :::timeline
    **第一步** 用国内热点说明读者为什么关心
    **第二步** 用官方 / GitHub / 论文 / 财报确认事实边界
    **第三步** 用社区讨论观察真实使用摩擦
    **第四步** 用英文媒体或强二手资料交叉验证产业判断
    :::

    ## 下一步需要人工或 agent 深挖

    - 把每个来源里的关键事实摘出来，标注哪些是事实，哪些是推断。
    - 把「烧 token」的位置具体化：上下文、工具调用、重试、缓存、推理时间或部署成本。
    - 删除没有证据支撑的判断，只保留能被来源链路支撑的段落。

    :::quote
    自动草稿的目标不是直接发布，而是把选题、补证、草稿和门禁串成一条可检查的生产线。
    :::
    """)


def cmd_draft_from_topic(args) -> int:
    payload = _load_topic_payload(Path(args.topic_file))
    topic = _select_topic(payload, args.topic_index)
    title = args.title or _topic_title(topic)
    sources = _topic_sources(topic, payload)
    primary_source_url = next((str(item.get("url") or item.get("link") or "") for item in sources if item.get("url") or item.get("link")), "")

    created = create_article_directory(title, args.author or "烧 Token 的人", primary_source_url, force=args.force)
    article_dir = Path(created["article_dir"])
    generated_dir = article_dir / "generated"
    write_utf8(article_dir / "article.md", _build_topic_article(topic, sources))
    write_utf8(generated_dir / "sources.json", json.dumps({"sources": sources}, ensure_ascii=False, indent=2) + "\n")
    write_utf8(generated_dir / "topic.json", json.dumps(topic, ensure_ascii=False, indent=2) + "\n")
    _write_placeholder_assets(article_dir)

    render_script = SKILL_ROOT / "skill2 paibanyouhua" / "scripts" / "render-article.py"
    render_args = ["--article-dir", str(article_dir)]
    if args.theme:
        render_args.extend(["--theme", args.theme])
    render_code, render_stdout, render_stderr = run_python_script_capture(render_script, render_args)
    if render_code != 0:
        if render_stdout:
            print(render_stdout, file=sys.stderr, end="")
        if render_stderr:
            print(render_stderr, file=sys.stderr, end="")
        return render_code

    gate_script = SKILL_ROOT / "skill2 paibanyouhua" / "scripts" / "run-quality-gates.py"
    gate_code, gate_stdout, gate_stderr = run_python_script_capture(gate_script, ["--article-dir", str(article_dir)] + (["--strict"] if args.strict_check else []))
    if gate_stderr:
        print(gate_stderr, file=sys.stderr, end="")
    if gate_code != 0 and args.strict_check:
        if gate_stdout:
            print(gate_stdout, file=sys.stderr, end="")
        return gate_code

    artifacts = {
        "article_md": str(article_dir / "article.md"),
        "preview_html": str(article_dir / "preview.html"),
        "sources_json": str(generated_dir / "sources.json"),
        "source_report": str(generated_dir / "source-report.json"),
        "quality_gates": str(generated_dir / "quality-gates.json"),
    }
    result = {
        "success": True,
        "article_dir": str(article_dir),
        "title": title,
        "render": json.loads(render_stdout) if render_stdout.strip().startswith("{") else {"stdout": render_stdout.strip()},
        "quality_gates_exit_code": gate_code,
        "artifacts": artifacts,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_auto_draft(args) -> int:
    output_root = output_root_path()
    pipeline_dir = output_root / "_auto-draft" / safe_folder_name(Path(args.hotspots).stem or "hotspots")
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    selected_topics_path = pipeline_dir / "selected-topics.json"
    topic_with_sources_path = pipeline_dir / "topic-with-sources.json"
    sources_path = pipeline_dir / "sources.json"
    research_report_path = pipeline_dir / "research-report.json"

    select_args = [
        "--hotspots", str(Path(args.hotspots).expanduser()),
        "--style", str(Path(args.style).expanduser()),
        "--limit", str(args.limit),
        "--json",
        "--output", str(selected_topics_path),
    ]
    if args.prefilter_limit:
        select_args.extend(["--prefilter-limit", str(args.prefilter_limit)])
    if args.llm_rerank:
        select_args.append("--llm-rerank")
    if args.llm_fixture:
        select_args.extend(["--llm-fixture", str(Path(args.llm_fixture).expanduser())])
    if args.config:
        select_args.extend(["--config", str(Path(args.config).expanduser())])

    select_code, select_stdout, select_stderr = run_python_script_capture(SKILL_ROOT / "scripts" / "select_ai_topics.py", select_args)
    if select_code != 0:
        if select_stdout:
            print(select_stdout, file=sys.stderr, end="")
        if select_stderr:
            print(select_stderr, file=sys.stderr, end="")
        return select_code
    selected_topics = json.loads(selected_topics_path.read_text(encoding="utf-8"))
    if not selected_topics.get("topics"):
        print(json.dumps({"success": False, "error": "No eligible topics selected", "artifacts": {"selected_topics": str(selected_topics_path)}}, ensure_ascii=False), file=sys.stderr)
        return 1

    research_args = [
        "--topic-file", str(selected_topics_path),
        "--topic-output", str(topic_with_sources_path),
        "--output", str(sources_path),
        "--report-output", str(research_report_path),
        "--per-query-limit", str(args.per_query_limit),
        "--max-sources", str(args.max_sources),
        "--timeout-seconds", str(args.timeout_seconds),
        "--json",
    ]
    if args.topic_index is not None:
        research_args.extend(["--topic-index", str(args.topic_index)])
    if args.search_fixture:
        research_args.extend(["--search-fixture", str(Path(args.search_fixture).expanduser())])
    if args.no_network:
        research_args.append("--no-network")
    if args.allow_incomplete_sources:
        research_args.append("--allow-incomplete")

    research_code, research_stdout, research_stderr = run_python_script_capture(SKILL_ROOT / "scripts" / "research_sources.py", research_args)
    if research_stderr:
        print(research_stderr, file=sys.stderr, end="")
    if research_code != 0 and not args.allow_incomplete_sources:
        if research_stdout:
            print(research_stdout, file=sys.stderr, end="")
        return research_code
    research_report = json.loads(research_report_path.read_text(encoding="utf-8")) if research_report_path.exists() else json.loads(research_stdout)

    draft_args = argparse.Namespace(
        topic_file=str(topic_with_sources_path),
        topic_index=args.topic_index,
        title=args.title,
        author=args.author or "烧 Token 的人",
        force=args.force,
        theme=args.theme,
        strict_check=args.strict_check,
    )
    stdout_buffer = io.StringIO()
    with contextlib.redirect_stdout(stdout_buffer):
        draft_code = cmd_draft_from_topic(draft_args)
    draft_stdout = stdout_buffer.getvalue()
    if draft_code != 0:
        if draft_stdout:
            print(draft_stdout, file=sys.stderr, end="")
        return draft_code
    draft_payload = json.loads(draft_stdout)
    artifacts = {
        "selected_topics": str(selected_topics_path),
        "topic_with_sources": str(topic_with_sources_path),
        "research_sources": str(sources_path),
        "research_report": str(research_report_path),
        "article_dir": draft_payload["article_dir"],
        **draft_payload.get("artifacts", {}),
    }
    result = {
        "success": True,
        "article_dir": draft_payload["article_dir"],
        "title": draft_payload.get("title", ""),
        "pipeline": {
            "selected_topics": {"count": int(selected_topics.get("count", len(selected_topics.get("topics", [])))), "llm_rerank": selected_topics.get("llm_rerank", {})},
            "research_sources": {"summary": research_report.get("summary", {})},
            "draft": {"quality_gates_exit_code": draft_payload.get("quality_gates_exit_code")},
        },
        "artifacts": artifacts,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_preview(args):
    """Generate HTML preview and open in browser."""
    theme = load_theme(args.theme)
    converter = WeChatConverter(theme=theme)
    result = converter.convert_file(args.input)

    # Wrap in full HTML for browser preview
    full_html = preview_html(result.html, theme)

    # Write to temp file
    input_path = Path(args.input)
    output = args.output or str(input_path.with_suffix(".html"))
    Path(output).write_text(full_html, encoding="utf-8")

    print(f"Title: {result.title}")
    print(f"Digest: {result.digest}")
    print(f"Images: {len(result.images)}")
    print(f"Output: {output}")

    if not args.no_open:
        webbrowser.open(f"file://{Path(output).absolute()}")
        print("Opened in browser.")


def cmd_publish(args):
    """Convert, upload images, and create WeChat draft."""
    cfg = load_config()
    wechat_cfg = cfg.get("wechat", {})

    # Resolve from CLI args → config.yaml fallback
    appid = args.appid or wechat_cfg.get("appid")
    secret = args.secret or wechat_cfg.get("secret")
    theme_name = args.theme or cfg.get("theme", "professional-clean")
    author = args.author or wechat_cfg.get("author")

    if not appid or not secret:
        print("Error: --appid and --secret required (or set in config.yaml)", file=sys.stderr)
        sys.exit(1)

    theme = load_theme(theme_name)
    converter = WeChatConverter(theme=theme)
    result = converter.convert_file(args.input)

    print(f"Title: {result.title}")
    print(f"Digest: {result.digest}")
    print(f"Images found: {len(result.images)}")

    # Get access token
    token = get_access_token(appid, secret)
    print("Access token obtained.")

    # Upload images referenced in article and replace src
    # Resolve relative paths against the markdown file's directory
    md_dir = Path(args.input).resolve().parent
    html = result.html
    for img_src in result.images:
        if img_src.startswith(("http://", "https://")):
            print(f"Skipping remote image: {img_src}")
            continue

        # Try: absolute → relative to CWD → relative to markdown file
        img_path = Path(img_src)
        if not img_path.is_absolute():
            if not img_path.exists():
                img_path = md_dir / img_src

        if img_path.exists():
            print(f"Uploading image: {img_src}")
            wechat_url = upload_image(token, str(img_path))
            html = html.replace(img_src, wechat_url)
            print(f"  -> {wechat_url}")
        else:
            print(f"Warning: image not found: {img_src} (searched {md_dir})")

    # Upload cover image if provided
    thumb_media_id = None
    if args.cover:
        print(f"Uploading cover: {args.cover}")
        thumb_media_id = upload_thumb(token, args.cover)
        print(f"  -> media_id: {thumb_media_id}")

    # Create draft
    title = args.title or result.title or Path(args.input).stem
    digest = result.digest
    draft = create_draft(
        access_token=token,
        title=title,
        html=html,
        digest=digest,
        thumb_media_id=thumb_media_id,
        author=author,
    )

    print(f"\nDraft created! media_id: {draft.media_id}")


def cmd_themes(args):
    """List available themes."""
    names = list_themes()
    for name in names:
        theme = load_theme(name)
        print(f"  {name:24s} {theme.description}")


def cmd_image_post(args):
    """Create a WeChat image post (小绿书) from image files."""
    cfg = load_config()
    wechat_cfg = cfg.get("wechat", {})

    appid = args.appid or wechat_cfg.get("appid")
    secret = args.secret or wechat_cfg.get("secret")

    if not appid or not secret:
        print("Error: --appid and --secret required (or set in config.yaml)", file=sys.stderr)
        sys.exit(1)

    images = args.images
    if not images:
        print("Error: at least 1 image required", file=sys.stderr)
        sys.exit(1)
    if len(images) > 20:
        print(f"Error: max 20 images, got {len(images)}", file=sys.stderr)
        sys.exit(1)

    token = get_access_token(appid, secret)
    print(f"Uploading {len(images)} images as permanent materials...")

    media_ids = []
    for img_path in images:
        p = Path(img_path)
        if not p.exists():
            print(f"Error: image not found: {img_path}", file=sys.stderr)
            sys.exit(1)
        print(f"  Uploading: {p.name}")
        mid = upload_thumb(token, str(p))
        media_ids.append(mid)
        print(f"    -> {mid}")

    title = args.title
    if len(title) > 32:
        print(f"Warning: title truncated to 32 chars (was {len(title)})")
        title = title[:32]

    content = args.content or ""

    result = create_image_post(
        access_token=token,
        title=title,
        image_media_ids=media_ids,
        content=content,
        open_comment=True,
    )

    print(f"\nImage post draft created!")
    print(f"  media_id: {result.media_id}")
    print(f"  images: {result.image_count}")
    print(f"  title: {title}")
    print(f"  请到公众号后台草稿箱检查并发布")


def cmd_gallery(args):
    """Render all themes side by side in a browser gallery."""
    from concurrent.futures import ThreadPoolExecutor

    # Use provided markdown or a built-in sample
    if args.input:
        md_text = Path(args.input).read_text(encoding="utf-8")
    else:
        md_text = _gallery_sample_markdown()

    names = list_themes()
    results = {}

    def render_theme(name):
        theme = load_theme(name)
        converter = WeChatConverter(theme=theme)
        result = converter.convert(md_text)
        return name, theme.description, result.html

    # Parallel rendering
    with ThreadPoolExecutor(max_workers=8) as pool:
        for name, desc, html in pool.map(lambda n: render_theme(n), names):
            results[name] = (desc, html)

    # Build gallery HTML
    gallery_html = _build_gallery_html(results, names)
    output = args.output or "/tmp/wewrite-gallery.html"
    Path(output).write_text(gallery_html, encoding="utf-8")
    print(f"Gallery: {output} ({len(names)} themes)")

    if not args.no_open:
        webbrowser.open(f"file://{Path(output).absolute()}")


def _gallery_sample_markdown():
    return """# 示例文章标题

先看一眼，这不是一篇只靠换颜色撑起来的公众号排版示例。

## 开头判断

这是一段正常的文章内容，用来展示不同主题的排版效果。真正拉开差距的，不只是配色，而是信息有没有被分层、节奏有没有被切开、重点有没有被提前抬出来。

:::callout info
好的排版不是“多塞一点元素”，而是让读者在三秒内知道哪里最重要、哪里可以停一下、哪里应该继续往下滑。
:::

## 关键数据卡

| 指标 | 数值 | 变化 |
|------|------|------|
| 阅读量 | 12,580 | +23% |
| 分享率 | 4.7% | +0.8% |
| 完读率 | 68% | -2% |

*图 1：示意图的图例说明应该紧跟在图片或图位下方。*

## 为什么有些文章看起来更高级

:::quote
真正耐看的版式，往往不是元素更多，而是重点更早浮出来。
:::

## 时间线展示

:::timeline
**第一步** 把开头从背景回顾改成场景或冲突
**第二步** 把关键数据提到段首，而不是埋进长段落
**第三步** 用图位、图例、提示块把阅读节奏切开
:::

## 对话式解释

:::dialogue
排版为什么总显得平？
> 因为所有信息都被塞进了同一种段落容器里。
那怎么改善？
> 让结论、时间线、争议点、图片各有自己的位置。
:::

## 最后的短清单

- 第一个要点：简洁是设计的灵魂
- 第二个要点：一致性比创意更重要
- 第三个要点：移动端体验优先

**加粗文本**、*斜体文本*、表格、引语、提示块和时间线，最好都在预览里看过一遍再决定最终主题。

最后这段用来展示文章结尾的留白和间距效果。一篇好文章的结尾，应该像一首好歌的最后一个音符——恰到好处地收束。
"""


def _join_newline(items):
    """Join items with comma + newline (workaround for f-string limitation)."""
    return ",\n".join(items)


def _build_gallery_html(results, names):
    cards = []
    for name in names:
        desc, html = results[name]
        # Escape for embedding in JS
        escaped_html = html.replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$')
        cards.append(f"""
        <div class="theme-card" onclick="selectTheme('{name}')">
          <div class="theme-name">{name}</div>
          <div class="theme-desc">{desc}</div>
          <div class="phone-frame">
            <div class="phone-content" id="preview-{name}">{html}</div>
          </div>
          <button class="copy-btn" onclick="event.stopPropagation(); copyHTML('{name}')">复制 HTML</button>
        </div>""")

    # Store HTML data for copy
    data_entries = []
    for name in names:
        desc, html = results[name]
        safe = html.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n')
        data_entries.append(f"  '{name}': '{safe}'")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WeWrite 主题画廊</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0f0f0f; color: #fff; }}
.header {{ text-align: center; padding: 40px 20px 20px; }}
.header h1 {{ font-size: 28px; font-weight: 700; }}
.header p {{ color: #888; margin-top: 8px; font-size: 15px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 24px; padding: 24px; max-width: 1440px; margin: 0 auto; }}
.theme-card {{ background: #1a1a1a; border-radius: 12px; padding: 16px; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; }}
.theme-card:hover {{ transform: translateY(-4px); box-shadow: 0 8px 24px rgba(0,0,0,0.4); }}
.theme-name {{ font-size: 16px; font-weight: 700; margin-bottom: 4px; }}
.theme-desc {{ font-size: 13px; color: #888; margin-bottom: 12px; }}
.phone-frame {{ background: #fff; border-radius: 8px; overflow: hidden; max-height: 480px; overflow-y: auto; }}
.phone-content {{ padding: 16px; font-size: 14px; transform: scale(0.85); transform-origin: top left; width: 118%; }}
.copy-btn {{ margin-top: 12px; width: 100%; padding: 8px; background: #333; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }}
.copy-btn:hover {{ background: #555; }}
.toast {{ position: fixed; bottom: 40px; left: 50%; transform: translateX(-50%); background: #333; color: #fff; padding: 10px 24px; border-radius: 8px; font-size: 14px; display: none; z-index: 999; }}
</style>
</head>
<body>
<div class="header">
  <h1>WeWrite 主题画廊</h1>
  <p>{len(names)} 个主题 · 点击卡片查看大图 · 点击「复制 HTML」直接粘贴到公众号编辑器</p>
</div>
<div class="grid">
{''.join(cards)}
</div>
<div class="toast" id="toast">已复制到剪贴板</div>
<script>
const themeData = {{
{_join_newline(data_entries)}
}};
function copyHTML(name) {{
  const html = themeData[name];
  if (html) {{
    navigator.clipboard.writeText(html).then(() => {{
      const t = document.getElementById('toast');
      t.style.display = 'block';
      setTimeout(() => t.style.display = 'none', 1500);
    }});
  }}
}}
function selectTheme(name) {{
  localStorage.setItem('wewrite-theme', name);
  // Scroll to card for visual feedback
  const el = document.getElementById('preview-' + name);
  if (el) el.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
}}
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(
        prog="wewrite",
        description="Markdown to WeChat HTML converter and publisher",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # managed article workflow (PowerShell-free primary path)
    p_new = sub.add_parser("new", help="Create standard article directory")
    p_new.add_argument("--title", required=True, help="Article title / output folder name")
    p_new.add_argument("--author", default="", help="Article author")
    p_new.add_argument("--source-url", default="", help="Original content source URL")
    p_new.add_argument("--force", action="store_true", help="Overwrite existing article folder files")

    p_render = sub.add_parser("render", help="Render managed article dir to preview HTML")
    p_render.add_argument("--article-dir", required=True, help="Article directory or name under output/")
    p_render.add_argument("--theme", default="", help="Override theme name")
    p_render.add_argument("--strict-check", action="store_true", help="Return non-zero if refreshed quality gates have non-pass items")

    p_check = sub.add_parser("check", help="Run managed article quality gates")
    p_check.add_argument("--article-dir", required=True, help="Article directory or name under output/")

    p_publish_draft = sub.add_parser("publish-draft", help="Publish managed article as WeChat draft")
    p_publish_draft.add_argument("--article-dir", required=True, help="Article directory or name under output/")
    p_publish_draft.add_argument("--config", default="", help="Publish config.yaml path")
    p_publish_draft.add_argument("--dry-run", action="store_true", help="Validate only; do not upload or create draft")
    p_publish_draft.add_argument("--allow-native-lists", action="store_true", help="Allow native ul/ol/li in final HTML")

    p_draft_topic = sub.add_parser("draft-from-topic", help="Create article draft from selected topic JSON and run render/source gates")
    p_draft_topic.add_argument("--topic-file", required=True, help="Topic JSON from select_ai_topics.py or curated research payload")
    p_draft_topic.add_argument("--topic-index", type=int, default=None, help="Index inside topics[]; default picks first auto-writeable topic")
    p_draft_topic.add_argument("--title", default="", help="Override article title")
    p_draft_topic.add_argument("--author", default="烧 Token 的人", help="Article author")
    p_draft_topic.add_argument("--theme", default="", help="Render theme override")
    p_draft_topic.add_argument("--strict-check", action="store_true", help="Return non-zero if quality gates fail")
    p_draft_topic.add_argument("--force", action="store_true", help="Overwrite existing article folder")

    p_auto_draft = sub.add_parser("auto-draft", help="Select topic, research sources, create draft, render and run gates")
    p_auto_draft.add_argument("--hotspots", required=True, help="Hotspots JSON from fetch_hotspots.py")
    p_auto_draft.add_argument("--limit", type=int, default=1, help="Number of candidate topics to select before drafting")
    p_auto_draft.add_argument("--topic-index", type=int, default=None, help="Index inside selected topics[] for research/draft; default first auto-writeable")
    p_auto_draft.add_argument("--style", default=str(SKILL_ROOT / "style.yaml"), help="style.yaml path for topic selection")
    p_auto_draft.add_argument("--author", default="烧 Token 的人", help="Article author")
    p_auto_draft.add_argument("--title", default="", help="Override final article title")
    p_auto_draft.add_argument("--theme", default="", help="Render theme override")
    p_auto_draft.add_argument("--strict-check", action="store_true", help="Return non-zero if final quality gates fail")
    p_auto_draft.add_argument("--force", action="store_true", help="Overwrite existing article folder")
    p_auto_draft.add_argument("--search-fixture", default="", help="Fixture JSON for deterministic/offline source research")
    p_auto_draft.add_argument("--no-network", action="store_true", help="Do not call web search during source research")
    p_auto_draft.add_argument("--allow-incomplete-sources", action="store_true", help="Continue even if research source mix is incomplete")
    p_auto_draft.add_argument("--per-query-limit", type=int, default=6)
    p_auto_draft.add_argument("--max-sources", type=int, default=12)
    p_auto_draft.add_argument("--timeout-seconds", type=float, default=12.0)
    p_auto_draft.add_argument("--prefilter-limit", type=int, default=20, help="Heuristic candidate count before optional LLM rerank")
    p_auto_draft.add_argument("--llm-rerank", action="store_true", help="Enable optional LLM rerank in topic selection")
    p_auto_draft.add_argument("--llm-fixture", default="", help="Fixture JSON for topic-selection LLM review")
    p_auto_draft.add_argument("--config", default=str(SKILL_ROOT / "config.yaml"), help="config.yaml for optional LLM rerank")

    # preview
    p_preview = sub.add_parser("preview", help="Generate HTML and open in browser")
    p_preview.add_argument("input", help="Markdown file path")
    p_preview.add_argument("-t", "--theme", default="professional-clean", help="Theme name")
    p_preview.add_argument("-o", "--output", help="Output HTML file path")
    p_preview.add_argument("--no-open", action="store_true", help="Don't open browser")

    # publish
    p_publish = sub.add_parser("publish", help="Convert and publish as WeChat draft")
    p_publish.add_argument("input", help="Markdown file path")
    p_publish.add_argument("-t", "--theme", default=None, help="Theme name")
    p_publish.add_argument("--appid", default=None, help="WeChat AppID (or set in config.yaml)")
    p_publish.add_argument("--secret", default=None, help="WeChat AppSecret (or set in config.yaml)")
    p_publish.add_argument("--cover", help="Cover image file path")
    p_publish.add_argument("--title", help="Override article title")
    p_publish.add_argument("--author", default=None, help="Article author")

    # themes
    sub.add_parser("themes", help="List available themes")

    # image-post (小绿书)
    p_imgpost = sub.add_parser("image-post", help="Create WeChat image post (小绿书)")
    p_imgpost.add_argument("images", nargs="+", help="Image file paths (1-20, first = cover)")
    p_imgpost.add_argument("-t", "--title", required=True, help="Post title (max 32 chars)")
    p_imgpost.add_argument("-c", "--content", default="", help="Plain text description (max ~1000 chars)")
    p_imgpost.add_argument("--appid", default=None, help="WeChat AppID")
    p_imgpost.add_argument("--secret", default=None, help="WeChat AppSecret")

    # gallery
    p_gallery = sub.add_parser("gallery", help="Open theme gallery in browser")
    p_gallery.add_argument("input", nargs="?", default=None, help="Markdown file (optional, uses sample if omitted)")
    p_gallery.add_argument("-o", "--output", help="Output HTML file path")
    p_gallery.add_argument("--no-open", action="store_true", help="Don't open browser")

    args = parser.parse_args()

    try:
        if args.command == "new":
            cmd_new(args)
        elif args.command == "render":
            sys.exit(cmd_render(args))
        elif args.command == "check":
            sys.exit(cmd_check(args))
        elif args.command == "publish-draft":
            sys.exit(cmd_publish_draft(args))
        elif args.command == "draft-from-topic":
            sys.exit(cmd_draft_from_topic(args))
        elif args.command == "auto-draft":
            sys.exit(cmd_auto_draft(args))
        elif args.command == "preview":
            cmd_preview(args)
        elif args.command == "publish":
            cmd_publish(args)
        elif args.command == "themes":
            cmd_themes(args)
        elif args.command == "image-post":
            cmd_image_post(args)
        elif args.command == "gallery":
            cmd_gallery(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
