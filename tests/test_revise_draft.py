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
REVISE = REPO_ROOT / "scripts" / "revise_draft.py"
CLI = REPO_ROOT / "toolkit" / "cli.py"


class ReviseDraftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wewrite-revise-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_revise(self, article_dir: Path, expect: int = 0):
        proc = subprocess.run(
            [str(PYTHON), str(REVISE), "--article-dir", str(article_dir), "--json"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(proc.returncode, expect, msg=f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        return proc

    def write_article_fixture(self) -> Path:
        article_dir = self.tmp / "article"
        generated = article_dir / "generated"
        generated.mkdir(parents=True)
        (article_dir / "assets").mkdir()
        (article_dir / "draft-metadata.json").write_text(json.dumps({
            "title": "Agent 成本为什么降不下来",
            "author": "烧 Token 的人",
            "digest": "从工程链路看 Agent 为什么烧 token。",
            "cover_image": "assets/cover-wide.jpg",
        }, ensure_ascii=False), encoding="utf-8")
        (article_dir / "article.md").write_text("""# Agent 成本为什么降不下来

## 先说结论

多步 Agent 会烧很多 token。

因为工具调用链路太长，所以成本上升。

## 来源

- [S1] OpenAI tools docs — https://platform.openai.com/docs/guides/tools
- [S2] HN Agent discussion — https://news.ycombinator.com/item?id=123
""", encoding="utf-8")
        (generated / "evidence-ledger.json").write_text(json.dumps({
            "claims": [
                {"source_id": "S1", "fact": "Tools add external function/API steps to an application flow.", "title": "OpenAI tools docs", "url": "https://platform.openai.com/docs/guides/tools"},
                {"source_id": "S2", "fact": "Multi-step agents can burn tokens through retries and long context.", "title": "HN Agent discussion", "url": "https://news.ycombinator.com/item?id=123"},
            ]
        }, ensure_ascii=False), encoding="utf-8")
        (generated / "evidence-report.json").write_text(json.dumps({
            "summary": {"passed": False, "unsupported": 2},
            "unsupported_claims": [
                "多步 Agent 会烧很多 token",
                "因为工具调用链路太长，所以成本上升",
            ],
        }, ensure_ascii=False), encoding="utf-8")
        (generated / "source-report.json").write_text(json.dumps({
            "summary": {"passed": False, "missing_categories": ["media_or_secondary"]},
        }, ensure_ascii=False), encoding="utf-8")
        (generated / "quality-gates.json").write_text(json.dumps({
            "checks": [
                {"name": "evidence_coverage", "status": "fail"},
                {"name": "source_credibility", "status": "fail"},
            ],
            "summary": {"non_pass": 2},
        }, ensure_ascii=False), encoding="utf-8")
        return article_dir

    def test_revise_draft_adds_evidence_citations_and_reports_blockers(self):
        article_dir = self.write_article_fixture()
        proc = self.run_revise(article_dir)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["revision"]["changed"])
        self.assertIn("evidence_coverage", payload["revision"]["fixed"])
        self.assertIn("source_credibility", payload["revision"]["blocked"])
        article = (article_dir / "article.md").read_text(encoding="utf-8")
        self.assertIn("多步 Agent 会烧很多 token [S2]", article)
        self.assertIn("因为工具调用链路太长，所以成本上升 [S1]", article)
        report = article_dir / "generated" / "revision-report.json"
        self.assertTrue(report.exists())
        report_payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(report_payload["revision"]["blocked"]["source_credibility"], ["media_or_secondary"])

    def test_auto_draft_revise_once_runs_revision_and_rerenders(self):
        hotspots = self.tmp / "hotspots.json"
        hotspots.write_text(json.dumps({
            "items": [
                {"title": "OpenAI 发布 Agent 新功能引发成本讨论", "source": "微博", "hot_normalized": 95, "url": "https://example.com/hot"}
            ]
        }, ensure_ascii=False), encoding="utf-8")
        fixture = self.tmp / "search-results.json"
        fixture.write_text(json.dumps({
            "results": [
                {"title": "OpenAI tools docs", "url": "https://platform.openai.com/docs/guides/tools", "snippet": "Tools let models call external functions."},
                {"title": "HN Agent cost discussion", "url": "https://news.ycombinator.com/item?id=123", "snippet": "Multi-step agents burn tokens on retries."},
                {"title": "Reuters AI agents", "url": "https://www.reuters.com/technology/artificial-intelligence/example", "snippet": "Enterprises watch inference cost and reliability."},
            ]
        }, ensure_ascii=False), encoding="utf-8")
        env = os.environ.copy()
        env["WEWRITE_OUTPUT_ROOT"] = str(self.tmp / "output")
        proc = subprocess.run(
            [
                str(PYTHON), str(CLI), "auto-draft",
                "--hotspots", str(hotspots),
                "--search-fixture", str(fixture),
                "--limit", "1",
                "--author", "烧 Token 的人",
                "--revise-once",
            ],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["success"])
        self.assertIn("revision", payload["pipeline"])
        self.assertIn("revision_report", payload["artifacts"])
        self.assertTrue(Path(payload["artifacts"]["revision_report"]).exists())
        self.assertTrue(Path(payload["artifacts"]["quality_gates"]).exists())


if __name__ == "__main__":
    unittest.main()
