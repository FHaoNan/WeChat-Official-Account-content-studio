#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_ROOT = REPO_ROOT / "toolkit"
IS_WINDOWS = os.name == "nt"


def local_site_package_candidates() -> list[Path]:
    venv_root = REPO_ROOT / ".venv"
    if IS_WINDOWS:
        return [venv_root / "Lib" / "site-packages"]

    lib_root = venv_root / "lib"
    if not lib_root.exists():
        return []
    return sorted(lib_root.glob("python*/site-packages"))


def existing_local_site_packages() -> list[Path]:
    return [path for path in local_site_package_candidates() if path.exists()]


def runtime_deps_available() -> bool:
    try:
        import bs4  # noqa: F401
        import cssutils  # noqa: F401
        import markdown  # noqa: F401
        import requests  # noqa: F401
        import yaml  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


if not runtime_deps_available() and sys.version_info >= (3, 10):
    for site_package_path in reversed(existing_local_site_packages()):
        sys.path.insert(0, str(site_package_path))

if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

import yaml  # noqa: E402
from publisher import create_draft_from_payload, update_draft  # noqa: E402
from wechat_api import get_access_token, upload_image, upload_thumb  # noqa: E402


def write_utf8(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def run_step(command: list[str], *, cwd: Path = REPO_ROOT, extra_env: dict[str, str] | None = None) -> None:
    env = os.environ.copy()
    local_site_packages = existing_local_site_packages()
    if local_site_packages and sys.version_info >= (3, 10):
        existing_pythonpath = env.get("PYTHONPATH", "")
        paths = [str(path) for path in local_site_packages]
        if existing_pythonpath:
            paths.append(existing_pythonpath)
        env["PYTHONPATH"] = os.pathsep.join(paths)
    if extra_env:
        env.update(extra_env)

    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raw = (completed.stdout or "") + (completed.stderr or "")
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{raw.strip()}")


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def resolve_config_path(explicit_config: str = "") -> Path:
    if explicit_config:
        explicit_path = Path(explicit_config).expanduser()
        if not explicit_path.is_absolute():
            explicit_path = Path.cwd() / explicit_path
        if not explicit_path.exists():
            raise FileNotFoundError(f"Publish config not found: {explicit_path}")
        return explicit_path.resolve()

    candidates: list[Path] = []
    env_path = os.environ.get("WEWRITE_PUBLISH_CONFIG", "")
    if env_path:
        env_config = Path(env_path).expanduser()
        if not env_config.is_absolute():
            env_config = Path.cwd() / env_config
        candidates.append(env_config)

    candidates.extend(
        [
            WORKFLOW_ROOT / ".config" / "md2wechat" / "config.yaml",
            Path.cwd() / "config.yaml",
            REPO_ROOT / "config.yaml",
            TOOLKIT_ROOT / "config.yaml",
            Path.home() / ".config" / "wewrite" / "config.yaml",
        ]
    )

    for path in candidates:
        if path.exists():
            return path.resolve()
    raise FileNotFoundError("No publish config.yaml found")


def load_config(explicit_config: str = "") -> tuple[dict[str, Any], Path]:
    path = resolve_config_path(explicit_config)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config file is not a mapping: {path}")
    return data, path


def resolve_article_dir(path_value: str) -> Path:
    raw = Path(path_value)
    candidates = [raw] if raw.is_absolute() else [REPO_ROOT / raw, REPO_ROOT / "output" / raw]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Article folder not found. Tried: {', '.join(str(item) for item in candidates)}")


def resolve_article_file(article_dir: Path, relative_path: str | None, fallbacks: list[str] | None = None) -> Path:
    candidates: list[str] = []
    if relative_path:
        candidates.append(relative_path)
    candidates.extend(fallbacks or [])

    for candidate in candidates:
        normalized = candidate.replace("\\", "/").lstrip("./")
        path = article_dir / normalized
        if path.exists():
            return path.resolve()

        if not IS_WINDOWS and "\\" in candidate:
            # Compatibility with old macOS runs that created literal backslash filenames.
            backslash_path = article_dir / candidate.replace("/", "\\")
            if backslash_path.exists():
                return backslash_path.resolve()

    raise FileNotFoundError(f"Required file not found in article folder. Tried: {', '.join(candidates)}")


def normalize_image_src(src: str) -> str:
    normalized = src.replace("\\", "/").lstrip("./")
    if normalized.startswith("assets/"):
        return normalized
    pure = PurePosixPath(normalized)
    if len(pure.parts) == 1:
        return f"assets/{pure.name}"
    return normalized


def has_suspicious_mojibake(text: str) -> bool:
    consecutive = 0
    total = 0
    for ch in text:
        codepoint = ord(ch)
        if 0x0080 <= codepoint <= 0x00FF:
            consecutive += 1
            total += 1
            if consecutive >= 3 or total >= 6:
                return True
        else:
            consecutive = 0
    return False


def assert_clean_payload(title: str, digest: str, html: str) -> None:
    joined = "\n".join(part for part in (title, digest, html) if part)
    if "\ufffd" in joined:
        raise ValueError("Replacement character detected in publish payload")
    if "<!--" in html:
        raise ValueError("HTML comments detected in publish payload")
    if re.search(r"\?{3,}", joined):
        raise ValueError("Suspicious question-mark runs detected in publish payload")
    if has_suspicious_mojibake(joined):
        raise ValueError("Suspicious mojibake text detected in publish payload")


def assert_preflight(article_dir: Path, html: str, *, allow_native_lists: bool) -> None:
    errors: list[str] = []
    warnings: list[str] = []
    generated_dir = article_dir / "generated"
    report_path = generated_dir / "preflight-report.json"

    if re.search(r"<\s*(ul|ol|li)\b", html, flags=re.I):
        if allow_native_lists:
            warnings.append("Native list tags detected; allowed by flag")
        else:
            errors.append("Native list tags detected in article-body.template.html")
    if "{{BODY_IMAGE_URL}}" in html:
        warnings.append("Legacy {{BODY_IMAGE_URL}} placeholder detected")
    for match in re.finditer(r"\{\{([^}]+)\}\}", html):
        token = match.group(1).strip()
        if not token.startswith("IMAGE:"):
            errors.append(f"Unknown unresolved placeholder detected: {{{{{token}}}}}")

    report = {
        "article_dir": str(article_dir),
        "allow_native_lists": allow_native_lists,
        "errors": errors,
        "warnings": warnings,
    }
    write_utf8(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    if errors:
        raise ValueError("Preflight failed:\n" + "\n".join(f"- {item}" for item in errors))
    if warnings:
        raise ValueError("Preflight warnings are not allowed:\n" + "\n".join(f"- {item}" for item in warnings))


def publish_article(
    article_dir: Path,
    *,
    allow_native_lists: bool,
    config_path: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    render_script = WORKFLOW_ROOT / "scripts" / "render-article.py"
    quality_script = WORKFLOW_ROOT / "scripts" / "run-quality-gates.py"
    publish_config_path = resolve_config_path(config_path)
    step_env = {
        "WEWRITE_PUBLISH_CONFIG": str(publish_config_path),
        "WEWRITE_REQUIRE_IMAGE_CONFIG": "0",
    }
    run_step([sys.executable, str(render_script), "--article-dir", str(article_dir)], extra_env=step_env)
    run_step([sys.executable, str(quality_script), "--article-dir", str(article_dir), "--strict"], extra_env=step_env)

    generated_dir = article_dir / "generated"
    meta_path = article_dir / "draft-metadata.json"
    html_template_path = article_dir / "article-body.template.html"
    output_html_path = generated_dir / "output.html"
    draft_json_path = generated_dir / "draft.json"
    result_path = generated_dir / "publish-result.json"

    metadata = load_json(meta_path)
    html = html_template_path.read_text(encoding="utf-8")

    title = str(metadata.get("title") or "").strip()
    author = str(metadata.get("author") or "").strip()
    digest = str(metadata.get("digest") or "").strip()
    source_url = str(metadata.get("content_source_url") or "").strip()
    cover_image = str(metadata.get("cover_image") or "assets/cover-wide.jpg").strip() or "assets/cover-wide.jpg"

    if not title:
        raise ValueError("Metadata title is empty")

    html = (
        html.replace("{{TITLE}}", title)
        .replace("{{AUTHOR}}", author)
        .replace("{{DIGEST}}", digest)
        .replace("{{SOURCE_URL}}", source_url)
    )
    assert_preflight(article_dir, html, allow_native_lists=allow_native_lists)

    config, config_source_path = load_config(str(publish_config_path))
    wechat_cfg = config.get("wechat", {}) if isinstance(config, dict) else {}
    appid = str(wechat_cfg.get("appid") or "").strip()
    secret = str(wechat_cfg.get("secret") or "").strip()
    if not appid or not secret:
        raise ValueError("wechat.appid or wechat.secret missing in publish config")

    cover_path = resolve_article_file(article_dir, cover_image, ["assets/cover-wide.jpg", "cover-wide.jpg"])
    planned_images = sorted(
        {
            normalize_image_src(match.group(1).strip())
            for match in re.finditer(r"\{\{IMAGE:([^}]+)\}\}", html)
        }
    )

    existing_media_id = str(metadata.get("media_id") or "").strip()
    if dry_run:
        return {
            "success": True,
            "action": "dry-run",
            "article_dir": str(article_dir),
            "config_path": str(config_source_path),
            "would_update": bool(existing_media_id),
            "media_id": existing_media_id,
            "cover_image": cover_image,
            "cover_path": str(cover_path),
            "planned_images": planned_images,
        }

    token = get_access_token(appid, secret)
    cover_media_id = upload_thumb(token, str(cover_path))

    image_cache: dict[str, str] = {}

    def replace_image(match: re.Match[str]) -> str:
        relative_image_path = normalize_image_src(match.group(1).strip())
        if relative_image_path not in image_cache:
            image_path = resolve_article_file(article_dir, relative_image_path)
            image_cache[relative_image_path] = upload_image(token, str(image_path))
        return image_cache[relative_image_path]

    html = re.sub(r"\{\{IMAGE:([^}]+)\}\}", replace_image, html)
    if re.search(r"\{\{[^}]+\}\}", html):
        raise ValueError("Unresolved placeholders remain after rendering")
    assert_clean_payload(title, digest, html)
    write_utf8(output_html_path, html)

    article = {
        "article_type": "news",
        "title": title,
        "author": author,
        "digest": digest,
        "content": html,
        "content_source_url": source_url,
        "thumb_media_id": cover_media_id,
        "need_open_comment": int(metadata.get("need_open_comment", 1)),
        "only_fans_can_comment": int(metadata.get("only_fans_can_comment", 0)),
    }
    draft = {"articles": [article]}
    write_utf8(draft_json_path, json.dumps(draft, ensure_ascii=False, indent=2) + "\n")

    if existing_media_id:
        result = update_draft(access_token=token, media_id=existing_media_id, article=article, index=0)
        action = "updated"
    else:
        result = create_draft_from_payload(access_token=token, body=draft)
        action = "created"

    metadata["media_id"] = result.media_id
    write_utf8(meta_path, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")

    publish_result = {
        "success": True,
        "action": action,
        "media_id": result.media_id,
        "article_dir": str(article_dir),
        "uploaded_images": sorted(image_cache),
        "cover_image": cover_image,
        "draft_json": str(draft_json_path),
    }
    write_utf8(result_path, json.dumps(publish_result, ensure_ascii=False, indent=2) + "\n")
    return publish_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Render, validate, upload images, and publish a WeChat draft.")
    parser.add_argument("--article-dir", required=True)
    parser.add_argument("--allow-native-lists", action="store_true")
    parser.add_argument("--config", default="")
    parser.add_argument("--dry-run", action="store_true", help="Validate render, gates, preflight, and config without touching WeChat.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        article_dir = resolve_article_dir(args.article_dir)
        result = publish_article(
            article_dir,
            allow_native_lists=bool(args.allow_native_lists),
            config_path=args.config,
            dry_run=bool(args.dry_run),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        error = {"success": False, "error": str(exc)}
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
