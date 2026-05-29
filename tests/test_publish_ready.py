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


class PublishReadyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wewrite-publish-ready-test-"))

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

    def make_article(self, *, ready_reports: bool = True) -> Path:
        article_dir = self.tmp / "ready-article"
        generated = article_dir / "generated"
        assets = article_dir / "assets"
        generated.mkdir(parents=True)
        assets.mkdir()
        (article_dir / "article.md").write_text(
            "# Agent 成本为什么降不下来\n\n"
            "多步 Agent 会因为工具调用和重试烧掉更多 token [S1]。\n\n"
            "![配图 1：链路示意](assets/img-01.jpg)\n",
            encoding="utf-8",
        )
        (article_dir / "preview.html").write_text("<html><body>preview</body></html>", encoding="utf-8")
        (article_dir / "article-body.template.html").write_text("<p>body</p>", encoding="utf-8")
        (article_dir / "draft-metadata.json").write_text(json.dumps({
            "title": "Agent 成本为什么降不下来",
            "author": "烧 Token 的人",
            "digest": "从工程链路看 Agent 为什么烧 token。",
            "cover_image": "assets/cover-wide.jpg",
        }, ensure_ascii=False), encoding="utf-8")
        for name in ["img-01.jpg", "cover-wide.jpg", "cover-square.jpg"]:
            (assets / name).write_bytes(b"placeholder")
        if ready_reports:
            (generated / "sources.json").write_text(json.dumps({
                "sources": [
                    {"title": "OpenAI tools docs", "url": "https://platform.openai.com/docs/guides/tools", "source_type": "official_docs", "categories": ["primary"]}
                ]
            }, ensure_ascii=False), encoding="utf-8")
            (generated / "humanness-report.json").write_text(json.dumps({"summary": {"passed": True}}, ensure_ascii=False), encoding="utf-8")
            (generated / "image-prompts.md").write_text("# image prompts\n\n- img-01.jpg\n", encoding="utf-8")
            (generated / "source-report.json").write_text(json.dumps({
                "summary": {"passed": True, "missing_categories": []},
            }, ensure_ascii=False), encoding="utf-8")
            (generated / "evidence-report.json").write_text(json.dumps({
                "summary": {"passed": True, "unsupported": 0},
                "unsupported_claims": [],
            }, ensure_ascii=False), encoding="utf-8")
            (generated / "editorial-report.json").write_text(json.dumps({
                "summary": {"passed": True, "fail": 0, "warn": 0},
                "checks": [
                    {"name": "internal_workflow_terms", "status": "pass"},
                    {"name": "title_body_alignment", "status": "pass"},
                ],
            }, ensure_ascii=False), encoding="utf-8")
            (generated / "quality-gates.json").write_text(json.dumps({
                "summary": {"fail": 0, "warn": 1, "skip": 0, "non_pass": 1},
                "checks": [
                    {"name": "source_credibility", "status": "pass"},
                    {"name": "evidence_coverage", "status": "pass"},
                    {"name": "diagnose", "status": "warn"},
                ],
            }, ensure_ascii=False), encoding="utf-8")
        return article_dir

    def test_publish_ready_passes_report_gate_when_publish_dry_run_is_explicitly_skipped(self):
        article_dir = self.make_article(ready_reports=True)
        proc = self.run_cli("publish-ready", "--article-dir", str(article_dir), "--skip-publish-dry-run")
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["success"])
        checks = {item["name"]: item for item in payload["checks"]}
        self.assertEqual(checks["source_credibility"]["status"], "pass")
        self.assertEqual(checks["evidence_coverage"]["status"], "pass")
        self.assertEqual(checks["editorial_readiness"]["status"], "pass")
        self.assertEqual(checks["quality_no_failures"]["status"], "pass")
        self.assertEqual(checks["publish_dry_run"]["status"], "skip")
        self.assertTrue((article_dir / "generated" / "publish-ready-report.json").exists())

    def test_publish_ready_fails_when_required_reports_or_gates_are_missing(self):
        article_dir = self.make_article(ready_reports=False)
        proc = self.run_cli("publish-ready", "--article-dir", str(article_dir), "--skip-publish-dry-run", expect=1)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["success"])
        checks = {item["name"]: item for item in payload["checks"]}
        self.assertEqual(checks["source_report"].get("status"), "fail")
        self.assertEqual(checks["evidence_report"].get("status"), "fail")
        self.assertEqual(checks["editorial_report"].get("status"), "fail")
        self.assertEqual(checks["quality_gates"].get("status"), "fail")

    def test_publish_ready_default_requires_publish_draft_dry_run(self):
        article_dir = self.make_article(ready_reports=True)
        proc = self.run_cli("publish-ready", "--article-dir", str(article_dir), "--config", str(self.tmp / "missing-config.yaml"), expect=1)
        payload = json.loads(proc.stdout)
        checks = {item["name"]: item for item in payload["checks"]}
        self.assertEqual(checks["publish_dry_run"]["status"], "fail")
        self.assertIn("config", checks["publish_dry_run"]["detail"].lower())


if __name__ == "__main__":
    unittest.main()
