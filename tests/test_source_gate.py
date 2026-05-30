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
SOURCE_GATE = REPO_ROOT / "scripts" / "source_gate.py"
CLI = REPO_ROOT / "toolkit" / "cli.py"


class SourceGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wewrite-source-gate-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_source_gate(self, article_dir: Path, expect: int = 0):
        proc = subprocess.run(
            [str(PYTHON), str(SOURCE_GATE), "--article-dir", str(article_dir), "--json"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(proc.returncode, expect, msg=f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        return proc

    def make_article(self, name="article") -> Path:
        article_dir = self.tmp / name
        (article_dir / "generated").mkdir(parents=True)
        (article_dir / "assets").mkdir(parents=True)
        (article_dir / "article.md").write_text("# 测试文章\n\n正文引用素材。\n", encoding="utf-8")
        return article_dir

    def test_source_gate_passes_with_required_source_mix(self):
        article_dir = self.make_article()
        (article_dir / "generated" / "sources.json").write_text(json.dumps({
            "sources": [
                {"title": "GitHub repo", "url": "https://github.com/openai/openai-cookbook"},
                {"title": "HN discussion", "url": "https://news.ycombinator.com/item?id=123"},
                {"title": "Reuters report", "url": "https://www.reuters.com/technology/example"},
            ]
        }, ensure_ascii=False), encoding="utf-8")

        proc = self.run_source_gate(article_dir)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["summary"]["passed"])
        self.assertGreaterEqual(payload["summary"]["categories"]["primary"], 1)
        self.assertGreaterEqual(payload["summary"]["categories"]["community"], 1)
        self.assertGreaterEqual(payload["summary"]["categories"]["media_or_secondary"], 1)
        self.assertTrue((article_dir / "generated" / "source-report.json").exists())

    def test_source_gate_fails_when_primary_source_is_missing(self):
        article_dir = self.make_article()
        (article_dir / "article.md").write_text(
            "# 缺少一手来源\n\n"
            "社区讨论：[Reddit](https://www.reddit.com/r/MachineLearning/comments/abc/example)。\n\n"
            "媒体报道：[Reuters](https://www.reuters.com/technology/example)。\n",
            encoding="utf-8",
        )

        proc = self.run_source_gate(article_dir, expect=1)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["summary"]["passed"])
        self.assertIn("primary", payload["summary"]["missing_categories"])

    def test_quality_gates_include_source_report(self):
        env = os.environ.copy()
        env["WEWRITE_OUTPUT_ROOT"] = str(self.tmp)
        new_proc = subprocess.run(
            [str(PYTHON), str(CLI), "new", "--title", "来源门禁集成", "--author", "烧 Token 的人"],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(new_proc.returncode, 0, msg=new_proc.stderr)
        article_dir = Path(json.loads(new_proc.stdout)["article_dir"])
        (article_dir / "article.md").write_text(
            "# 来源门禁集成\n\n"
            "这里是一篇足够长的测试文章。" * 20 + "\n\n"
            "![配图](img-01.jpg)\n",
            encoding="utf-8",
        )
        for name in ["img-01.jpg", "cover-wide.jpg", "cover-square.jpg"]:
            (article_dir / "assets" / name).write_bytes(b"placeholder")
        (article_dir / "generated" / "sources.json").write_text(json.dumps({
            "sources": [
                {"url": "https://arxiv.org/abs/2401.00001"},
                {"url": "https://x.com/example/status/1"},
                {"url": "https://www.bloomberg.com/news/articles/example"},
            ]
        }), encoding="utf-8")

        render_proc = subprocess.run(
            [str(PYTHON), str(CLI), "render", "--article-dir", str(article_dir)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(render_proc.returncode, 0, msg=render_proc.stderr)
        quality = json.loads((article_dir / "generated" / "quality-gates.json").read_text(encoding="utf-8"))
        checks = {item["name"]: item for item in quality["checks"]}
        self.assertIn("source_credibility", checks)
        self.assertEqual(checks["source_credibility"]["status"], "pass")
        self.assertEqual(quality["artifacts"]["source_report"], str(article_dir / "generated" / "source-report.json"))

    def test_source_gate_passes_with_first_hand_sources_without_forcing_three_categories(self):
        article_dir = self.make_article("first-hand-only")
        (article_dir / "generated" / "sources.json").write_text(json.dumps({
            "sources": [
                {"title": "OpenAI docs", "url": "https://platform.openai.com/docs/guides/tools", "source_type": "official_docs"},
                {"title": "OpenAI cookbook", "url": "https://github.com/openai/openai-cookbook", "source_type": "github"},
            ]
        }, ensure_ascii=False), encoding="utf-8")

        proc = self.run_source_gate(article_dir)
        payload = json.loads(proc.stdout)

        self.assertTrue(payload["summary"]["passed"])
        self.assertGreaterEqual(payload["summary"]["categories"]["primary"], 2)
        self.assertEqual(payload["summary"]["categories"].get("community", 0), 0)
        self.assertEqual(payload["summary"]["categories"].get("media_or_secondary", 0), 0)
        self.assertEqual(payload["summary"]["missing_categories"], [])
        self.assertIn("first_hand", payload["policy"])

    def test_source_report_explains_what_each_source_supports_and_cannot_prove(self):
        article_dir = self.make_article("explainable")
        (article_dir / "article.md").write_text(
            "# 中国芯片又传来好消息\n\n"
            "## 先说结论\n\n"
            "芯片进入推理链路要看软件栈和成本 [S1]。\n\n"
            "## 对用户真正有影响的地方\n\n"
            "用户感受到的是响应速度、价格和稳定性 [S2]。\n",
            encoding="utf-8",
        )
        (article_dir / "generated" / "sources.json").write_text(json.dumps({
            "sources": [
                {
                    "title": "NVIDIA Triton Inference Server Documentation",
                    "url": "https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/index.html",
                    "source_type": "official_docs",
                    "snippet": "NVIDIA documents Triton Inference Server as serving software for deploying AI models.",
                },
                {
                    "title": "Reuters AI Chips Coverage",
                    "url": "https://www.reuters.com/technology/artificial-intelligence/",
                    "source_type": "mainstream_media",
                    "snippet": "Reuters tracks AI chip supply and deployment constraints across the industry.",
                },
            ]
        }, ensure_ascii=False), encoding="utf-8")

        proc = self.run_source_gate(article_dir)
        payload = json.loads(proc.stdout)
        first = payload["sources"][0]
        second = payload["sources"][1]

        for source in payload["sources"]:
            self.assertTrue(source["why_this_source"])
            self.assertTrue(source["what_it_supports"])
            self.assertTrue(source["what_it_cannot_prove"])
            self.assertIn("snippet", source)
        self.assertIn("产品或技术机制", first["what_it_supports"])
        self.assertIn("用户反馈", first["what_it_cannot_prove"])
        self.assertIn("产业背景", second["what_it_supports"])
        self.assertIn("单独证明底层机制", second["what_it_cannot_prove"])

    def test_source_report_assigns_sources_to_h2_sections_and_audits_fallback_ratio(self):
        article_dir = self.make_article("section-audit")
        (article_dir / "article.md").write_text(
            "# 中国芯片又传来好消息\n\n"
            "## 先说结论\n\n"
            "芯片能力要进入真实推理链路 [S1]。\n\n"
            "## 这条芯片消息该怎么判断\n\n"
            "软件栈和算子实现决定部署难度 [S2]。\n\n"
            "## 对公司真正有影响的地方\n\n"
            "财报材料只能说明产业需求和收入背景 [S3]。\n",
            encoding="utf-8",
        )
        (article_dir / "generated" / "sources.json").write_text(json.dumps({
            "sources": [
                {"title": "NVIDIA docs", "url": "https://docs.nvidia.com/", "source_type": "official_docs", "origin": "curated_fallback_after_search_empty", "snippet": "NVIDIA documentation describes AI inference software."},
                {"title": "FlashAttention", "url": "https://github.com/Dao-AILab/flash-attention", "source_type": "github_or_paper", "origin": "curated_fallback_after_search_empty", "snippet": "FlashAttention implements memory-efficient attention."},
                {"title": "NVIDIA investor relations", "url": "https://investor.nvidia.com/financial-info/quarterly-results/default.aspx", "source_type": "earnings", "origin": "curated_fallback_after_search_empty", "snippet": "NVIDIA investor materials explain financial context."},
            ]
        }, ensure_ascii=False), encoding="utf-8")

        proc = self.run_source_gate(article_dir)
        payload = json.loads(proc.stdout)

        sections = {item["heading"]: item for item in payload["section_evidence"]}
        self.assertEqual(sections["先说结论"]["source_ids"], ["S1"])
        self.assertEqual(sections["这条芯片消息该怎么判断"]["source_ids"], ["S2"])
        self.assertEqual(sections["对公司真正有影响的地方"]["source_ids"], ["S3"])
        self.assertEqual(payload["summary"]["sections_without_evidence"], [])
        self.assertEqual(payload["fallback_audit"]["count"], 3)
        self.assertEqual(payload["fallback_audit"]["ratio"], 1.0)
        self.assertEqual(payload["fallback_audit"]["status"], "info")
        self.assertIn("人工补证", payload["fallback_audit"]["recommendation"])


if __name__ == "__main__":
    unittest.main()
