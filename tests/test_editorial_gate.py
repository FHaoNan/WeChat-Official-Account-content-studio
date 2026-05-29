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
EDITORIAL_GATE = REPO_ROOT / "scripts" / "editorial_gate.py"
CLI = REPO_ROOT / "toolkit" / "cli.py"


class EditorialGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wewrite-editorial-gate-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_gate(self, article_dir: Path, expect: int = 0):
        proc = subprocess.run(
            [str(PYTHON), str(EDITORIAL_GATE), "--article-dir", str(article_dir), "--json"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(proc.returncode, expect, msg=f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        return json.loads(proc.stdout)

    def make_article(self, title: str, body: str) -> Path:
        article_dir = self.tmp / "article"
        article_dir.mkdir()
        (article_dir / "article.md").write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
        (article_dir / "preview.html").write_text("<html><body><h1>preview</h1><p>正文预览</p></body></html>", encoding="utf-8")
        (article_dir / "draft-metadata.json").write_text(json.dumps({
            "title": title,
            "author": "烧 Token 的人",
            "digest": "从工程视角拆清楚这件事。",
            "cover_image": "assets/cover-wide.jpg",
        }, ensure_ascii=False), encoding="utf-8")
        return article_dir

    def test_editorial_gate_fails_internal_workflow_terms_in_public_article(self):
        article_dir = self.make_article(
            "Agent 成本为什么降不下来",
            "这篇文章解释 Agent 成本。\n\n"
            "## 证据链\n\n"
            "- [S1] NVIDIA Documentation Hub 是本选题的 official_docs 证据，需要在后续深读时补充更精确的原文摘录。\n\n"
            "链接和来源 URL 会保留在内部 evidence ledger 里；如果缺少一手来源，才应该阻塞发布。",
        )
        payload = self.run_gate(article_dir, expect=1)
        checks = {item["name"]: item for item in payload["checks"]}
        self.assertFalse(payload["summary"]["passed"])
        self.assertEqual(checks["internal_workflow_terms"]["status"], "fail")
        self.assertIn("official_docs", checks["internal_workflow_terms"]["detail"])
        self.assertTrue((article_dir / "generated" / "editorial-report.json").exists())

    def test_editorial_gate_fails_title_body_mismatch_for_generic_agent_template(self):
        body = "\n\n".join([
            "这件事不只是一个 AI 产品热点，它真正值得拆的是 Agent 成本。",
            "多步 Agent 会因为上下文、工具调用、失败重试和可靠性检查烧掉更多 token [S1]。",
            "对用户来说，问题不是贵不贵，而是任务变长之后系统还能不能稳定跑完。",
            "对公司来说，Agent 能不能规模化上线，看的也不只是模型能力。",
        ])
        article_dir = self.make_article("中国芯片又传来好消息", body)
        payload = self.run_gate(article_dir, expect=1)
        checks = {item["name"]: item for item in payload["checks"]}
        self.assertEqual(checks["title_body_alignment"]["status"], "fail")
        self.assertIn("芯片", checks["title_body_alignment"]["detail"])

    def test_editorial_gate_passes_reader_facing_aligned_article(self):
        body = "\n\n".join([
            "中国芯片这次被关注，关键不是一句好消息，而是它能不能进入真实 AI 推理链路。",
            "从工程角度看，芯片、显存带宽、软件栈和推理服务会一起决定模型调用成本。",
            "如果国产 AI 芯片只能停留在发布会参数，企业真正部署 Agent 时仍然会被延迟、成本和稳定性卡住。",
            "所以这类芯片新闻要看三件事：是否有可复现的软件工具链，是否有主流模型适配，是否进入真实生产流量。",
        ])
        article_dir = self.make_article("中国芯片又传来好消息", body)
        payload = self.run_gate(article_dir, expect=0)
        self.assertTrue(payload["summary"]["passed"])

    def test_publish_ready_blocks_failed_editorial_report(self):
        article_dir = self.make_article(
            "Agent 成本为什么降不下来",
            "这是正文。\n\n![配图](assets/img-01.jpg)\n",
        )
        assets = article_dir / "assets"
        generated = article_dir / "generated"
        assets.mkdir()
        generated.mkdir()
        (article_dir / "preview.html").write_text("<html><body>preview</body></html>", encoding="utf-8")
        (article_dir / "article-body.template.html").write_text("<p>body</p>", encoding="utf-8")
        for name in ["img-01.jpg", "cover-wide.jpg", "cover-square.jpg"]:
            (assets / name).write_bytes(b"placeholder")
        (generated / "quality-gates.json").write_text(json.dumps({
            "summary": {"fail": 0, "warn": 0, "skip": 0, "non_pass": 0},
            "checks": [],
        }, ensure_ascii=False), encoding="utf-8")
        (generated / "source-report.json").write_text(json.dumps({"summary": {"passed": True, "missing_categories": []}}, ensure_ascii=False), encoding="utf-8")
        (generated / "evidence-report.json").write_text(json.dumps({"summary": {"passed": True, "unsupported": 0}}, ensure_ascii=False), encoding="utf-8")
        (generated / "editorial-report.json").write_text(json.dumps({
            "summary": {"passed": False, "fail": 1, "warn": 0},
            "checks": [{"name": "internal_workflow_terms", "status": "fail", "detail": "official_docs"}],
        }, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run(
            [str(PYTHON), str(CLI), "publish-ready", "--article-dir", str(article_dir), "--skip-publish-dry-run"],
            cwd=str(REPO_ROOT),
            env={**os.environ, "WEWRITE_OUTPUT_ROOT": str(self.tmp)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(proc.returncode, 1, msg=f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        payload = json.loads(proc.stdout)
        checks = {item["name"]: item for item in payload["checks"]}
        self.assertFalse(payload["success"])
        self.assertEqual(checks["editorial_readiness"]["status"], "fail")


if __name__ == "__main__":
    unittest.main()
