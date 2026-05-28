import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)
CLI = REPO_ROOT / "toolkit" / "cli.py"
QUALITY_GATES = REPO_ROOT / "skill2 paibanyouhua" / "scripts" / "run-quality-gates.py"


def load_quality_gates_module():
    spec = importlib.util.spec_from_file_location("run_quality_gates", QUALITY_GATES)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CliWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wewrite-cli-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args, expect=0):
        env = os.environ.copy()
        env["WEWRITE_OUTPUT_ROOT"] = str(self.tmp)
        proc = subprocess.run(
            [str(PYTHON), str(CLI), *args],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(proc.returncode, expect, msg=f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        return proc

    def write_renderable_article(self, article_dir: Path) -> None:
        (article_dir / "article.md").write_text(
            "# P0 渲染测试\n\n"
            "开头先给一个判断：这条链路必须在 macOS 上直接跑通。\n\n"
            ":::callout info\n这是一段测试提示块，用来验证容器语法。\n:::\n\n"
            "## 为什么要迁移\n\n"
            "因为 agent 不能稳定依赖 PowerShell。这里放一张占位图。\n\n"
            "![配图 1：链路示意](img-01.jpg)\n"
            "*图 1：Python 主链路示意。*\n\n"
            "## 结论\n\n"
            "主逻辑进入 Python 后，Windows wrapper 只负责转发。\n",
            encoding="utf-8",
        )
        assets = article_dir / "assets"
        # Small placeholder bytes are enough for existence checks; render itself does not decode them.
        (assets / "img-01.jpg").write_bytes(b"placeholder")
        (assets / "cover-wide.jpg").write_bytes(b"placeholder")
        (assets / "cover-square.jpg").write_bytes(b"placeholder")

    def test_new_creates_standard_article_directory(self):
        proc = self.run_cli("new", "--title", "P0 自动化测试", "--author", "烧 Token 的人")
        payload = json.loads(proc.stdout)
        article_dir = Path(payload["article_dir"])
        self.assertTrue(article_dir.exists())
        self.assertEqual(article_dir.parent.resolve(), self.tmp.resolve())
        self.assertTrue((article_dir / "article.md").exists())
        self.assertTrue((article_dir / "assets").is_dir())
        self.assertTrue((article_dir / "generated").is_dir())
        metadata = json.loads((article_dir / "draft-metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["title"], "P0 自动化测试")
        self.assertEqual(metadata["author"], "烧 Token 的人")

    def test_render_writes_preview_and_humanness_report(self):
        proc = self.run_cli("new", "--title", "P0 渲染测试", "--author", "烧 Token 的人")
        article_dir = Path(json.loads(proc.stdout)["article_dir"])
        self.write_renderable_article(article_dir)

        proc = self.run_cli("render", "--article-dir", str(article_dir))
        payload = json.loads(proc.stdout)
        self.assertTrue(Path(payload["preview_html"]).exists())
        self.assertTrue((article_dir / "article-body.template.html").exists())
        self.assertTrue((article_dir / "generated" / "humanness-report.json").exists())
        self.assertTrue((article_dir / "generated" / "layout-plan.json").exists())
        self.assertTrue((article_dir / "generated" / "quality-gates.json").exists())

    def test_render_strict_check_returns_quality_gate_status(self):
        proc = self.run_cli("new", "--title", "P0 严格渲染测试", "--author", "烧 Token 的人")
        article_dir = Path(json.loads(proc.stdout)["article_dir"])
        self.write_renderable_article(article_dir)

        self.run_cli("render", "--article-dir", str(article_dir), expect=0)
        self.assertTrue((article_dir / "generated" / "quality-gates.json").exists())

        # The fixture intentionally has diagnose warnings in this repo, so strict render should propagate them.
        self.run_cli("render", "--article-dir", str(article_dir), "--strict-check", expect=1)

    def test_article_relative_path_rejects_unsafe_paths(self):
        module = load_quality_gates_module()
        article_dir = self.tmp / "article"
        article_dir.mkdir()
        safe = module.article_relative_path(article_dir, "assets/img-01.jpg")
        self.assertEqual(safe, (article_dir / "assets" / "img-01.jpg").resolve())

        unsafe_refs = [
            "../outside.jpg",
            "/tmp/outside.jpg",
            "assets/../../outside.jpg",
            "C:/outside.jpg",
            "C:\\outside.jpg",
            "bad\x00name.jpg",
        ]
        for ref in unsafe_refs:
            with self.subTest(ref=ref):
                with self.assertRaises(ValueError):
                    module.article_relative_path(article_dir, ref)

    def test_check_generates_quality_reports_without_powershell(self):
        proc = self.run_cli("new", "--title", "P0 检查测试", "--author", "烧 Token 的人")
        article_dir = Path(json.loads(proc.stdout)["article_dir"])
        (article_dir / "article.md").write_text(
            "# P0 检查测试\n\n" + "这是一段用于质量门禁的正文。" * 30 + "\n\n"
            ":::callout info\n保留一个非正文模块。\n:::\n\n"
            "![配图 1：链路示意](img-01.jpg)\n*图 1：Python 主链路示意。*\n",
            encoding="utf-8",
        )
        for name in ["img-01.jpg", "cover-wide.jpg", "cover-square.jpg"]:
            (article_dir / "assets" / name).write_bytes(b"placeholder")
        self.run_cli("render", "--article-dir", str(article_dir))
        # Missing config/history may create warnings, but the command must not fail because pwsh is absent.
        self.run_cli("check", "--article-dir", str(article_dir), expect=1)
        generated = article_dir / "generated"
        self.assertTrue((generated / "quality-gates.json").exists())
        self.assertTrue((generated / "diagnose-report.json").exists())
        self.assertTrue((generated / "seo-report.json").exists())
        self.assertTrue((generated / "article-doctor-report.json").exists())
        doctor = json.loads((generated / "article-doctor-report.json").read_text(encoding="utf-8"))
        self.assertEqual(doctor["engine"], "python-fallback")

    def test_publish_draft_dry_run_validates_before_config_and_does_not_upload(self):
        proc = self.run_cli("new", "--title", "P0 干跑测试", "--author", "烧 Token 的人")
        article_dir = Path(json.loads(proc.stdout)["article_dir"])
        proc = self.run_cli("publish-draft", "--article-dir", str(article_dir), "--dry-run", "--config", str(self.tmp / "missing-config.yaml"), expect=1)
        payload = json.loads(proc.stderr)
        self.assertFalse(payload["success"])
        self.assertIn("config", payload["error"].lower())
        self.assertIn("not found", payload["error"].lower())
        self.assertFalse((article_dir / "generated" / "draft.json").exists())

    def test_draft_from_topic_creates_article_sources_and_reports(self):
        topic_file = self.tmp / "topic.json"
        topic_file.write_text(json.dumps({
            "topics": [
                {
                    "recommended_title": "GPT-5 Agent 成本为什么降不下来",
                    "engineering_question": "为什么多步 Agent 比普通问答更烧 token？",
                    "hotspot": {"title": "Agent 应用成本讨论升温", "source": "微博", "url": "https://example.com/hot"},
                    "token_burner_angle": "从上下文膨胀、工具调用和重试链路拆解 Agent 成本。",
                    "sources": [
                        {"title": "OpenAI docs", "url": "https://platform.openai.com/docs/guides/tools", "source_type": "official_docs"},
                        {"title": "HN discussion", "url": "https://news.ycombinator.com/item?id=123", "source_type": "community"},
                        {"title": "Reuters report", "url": "https://www.reuters.com/technology/artificial-intelligence/example", "source_type": "mainstream_media"},
                    ],
                }
            ]
        }, ensure_ascii=False), encoding="utf-8")

        proc = self.run_cli("draft-from-topic", "--topic-file", str(topic_file), "--author", "烧 Token 的人")
        payload = json.loads(proc.stdout)
        article_dir = Path(payload["article_dir"])
        self.assertTrue((article_dir / "article.md").exists())
        self.assertTrue((article_dir / "preview.html").exists())
        self.assertTrue((article_dir / "generated" / "sources.json").exists())
        self.assertTrue((article_dir / "generated" / "source-report.json").exists())
        self.assertTrue((article_dir / "generated" / "quality-gates.json").exists())
        source_report = json.loads((article_dir / "generated" / "source-report.json").read_text(encoding="utf-8"))
        self.assertTrue(source_report["summary"]["passed"])
        quality = json.loads((article_dir / "generated" / "quality-gates.json").read_text(encoding="utf-8"))
        checks = {item["name"]: item for item in quality["checks"]}
        self.assertEqual(checks["source_credibility"]["status"], "pass")
        self.assertIn("sources_json", payload["artifacts"])
        self.assertIn("quality_gates", payload["artifacts"])

    def test_auto_draft_runs_topic_selection_research_and_draft_pipeline(self):
        hotspots = self.tmp / "hotspots.json"
        hotspots.write_text(json.dumps({
            "items": [
                {"title": "OpenAI 发布 Agent 新功能引发成本讨论", "source": "微博", "hot_normalized": 95, "url": "https://example.com/hot"},
                {"title": "某明星机场穿搭", "source": "微博", "hot_normalized": 100, "url": "https://example.com/skip"},
            ]
        }, ensure_ascii=False), encoding="utf-8")
        fixture = self.tmp / "search-results.json"
        fixture.write_text(json.dumps({
            "results": [
                {"title": "OpenAI tools docs", "url": "https://platform.openai.com/docs/guides/tools"},
                {"title": "HN Agent cost discussion", "url": "https://news.ycombinator.com/item?id=123"},
                {"title": "Reuters AI agents", "url": "https://www.reuters.com/technology/artificial-intelligence/example"},
            ]
        }, ensure_ascii=False), encoding="utf-8")

        proc = self.run_cli(
            "auto-draft",
            "--hotspots", str(hotspots),
            "--search-fixture", str(fixture),
            "--limit", "1",
            "--author", "烧 Token 的人",
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["pipeline"]["selected_topics"]["count"], 1)
        self.assertTrue(payload["pipeline"]["research_sources"]["summary"]["passed"])
        article_dir = Path(payload["article_dir"])
        self.assertTrue((article_dir / "article.md").exists())
        self.assertTrue((article_dir / "preview.html").exists())
        self.assertTrue((article_dir / "generated" / "sources.json").exists())
        self.assertTrue((article_dir / "generated" / "source-report.json").exists())
        source_report = json.loads((article_dir / "generated" / "source-report.json").read_text(encoding="utf-8"))
        self.assertTrue(source_report["summary"]["passed"])
        artifacts = payload["artifacts"]
        self.assertTrue(Path(artifacts["selected_topics"]).exists())
        self.assertTrue(Path(artifacts["topic_with_sources"]).exists())
        self.assertTrue(Path(artifacts["research_report"]).exists())
        self.assertEqual(Path(artifacts["article_dir"]), article_dir)


if __name__ == "__main__":
    unittest.main()
