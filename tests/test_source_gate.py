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


if __name__ == "__main__":
    unittest.main()
