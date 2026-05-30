import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)
SCRIPT = REPO_ROOT / "scripts" / "evidence_gate.py"
CLI = REPO_ROOT / "toolkit" / "cli.py"


class EvidenceGateTests(unittest.TestCase):
    def run_script(self, *args, expect=0):
        proc = subprocess.run(
            [str(PYTHON), str(SCRIPT), *args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(proc.returncode, expect, msg=f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        return proc

    def write_article_with_evidence(self, tmpdir: Path) -> Path:
        article = tmpdir / "article.md"
        article.write_text("""# Agent 成本为什么降不下来

## 先说结论

这不是单纯的 AI 热点 [S1]。

## 证据链

- [S1] OpenAI tools let models call external functions.
- [S2] HN: multi-step agents burn tokens on retries.
""", encoding="utf-8")
        return article

    def write_article_without_evidence(self, tmpdir: Path) -> Path:
        article = tmpdir / "article.md"
        article.write_text("""# Agent 成本为什么降不下来

## 先说结论

多步 Agent 会烧很多 token。

因为工具调用链路太长，所以成本上升。
""", encoding="utf-8")
        return article

    def test_evidence_gate_passes_when_all_claims_have_citations(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-evidence-") as raw_tmp:
            tmpdir = Path(raw_tmp)
            article = self.write_article_with_evidence(tmpdir)
            report = tmpdir / "evidence-report.json"
            proc = self.run_script(
                "--article-dir", str(tmpdir),
                "--output", str(report),
                "--json",
            )
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["summary"]["passed"])
            self.assertEqual(payload["summary"]["unsupported"], 0)
            self.assertTrue(report.exists())

    def test_evidence_gate_fails_when_claims_lack_citations(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-evidence-") as raw_tmp:
            tmpdir = Path(raw_tmp)
            article = self.write_article_without_evidence(tmpdir)
            proc = self.run_script(
                "--article-dir", str(tmpdir),
                "--json",
                expect=1,
            )
            payload = json.loads(proc.stdout)
            self.assertFalse(payload["summary"]["passed"])
            self.assertGreater(payload["summary"]["unsupported"], 0)

    def test_evidence_report_explains_cited_claim_support_strength(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-evidence-audit-") as raw_tmp:
            tmpdir = Path(raw_tmp)
            generated = tmpdir / "generated"
            generated.mkdir()
            (tmpdir / "article.md").write_text("""# Agent 成本为什么降不下来

## 先说结论

工具调用会把外部函数和 API 纳入模型应用流程 [S1]。

企业部署 AI Agent 前会关注推理成本和可靠性 [S2]。
""", encoding="utf-8")
            (generated / "evidence-ledger.json").write_text(json.dumps({
                "claims": [
                    {
                        "source_id": "S1",
                        "title": "OpenAI tools docs",
                        "url": "https://platform.openai.com/docs/guides/tools",
                        "source_type": "official_docs",
                        "fact": "Tools let models call external functions and APIs as part of an application flow.",
                    },
                    {
                        "source_id": "S2",
                        "title": "Reuters AI agent coverage",
                        "url": "https://www.reuters.com/technology/artificial-intelligence/",
                        "source_type": "mainstream_media",
                        "fact": "Reuters reports that companies watch inference cost and reliability before deploying AI agents.",
                    },
                ]
            }, ensure_ascii=False), encoding="utf-8")

            proc = self.run_script("--article-dir", str(tmpdir), "--json")
            payload = json.loads(proc.stdout)
            audits = payload["claim_audits"]

            self.assertEqual(payload["summary"]["support_levels"]["direct"], 1)
            self.assertEqual(payload["summary"]["support_levels"]["background"], 1)
            self.assertEqual(payload["summary"]["needs_human_review"], 1)
            direct = next(item for item in audits if item["source_ids"] == ["S1"])
            background = next(item for item in audits if item["source_ids"] == ["S2"])
            self.assertEqual(direct["support_level"], "direct")
            self.assertIn("official_docs", direct["support_reason"])
            self.assertFalse(direct["needs_human_review"])
            self.assertEqual(background["support_level"], "background")
            self.assertIn("媒体", background["support_reason"])
            self.assertTrue(background["needs_human_review"])

    def test_evidence_report_marks_unmapped_citations_for_human_review(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-evidence-unmapped-") as raw_tmp:
            tmpdir = Path(raw_tmp)
            (tmpdir / "article.md").write_text("""# Agent 成本

## 先说结论

这个产品一定会改变企业工作流 [S9]。
""", encoding="utf-8")

            proc = self.run_script("--article-dir", str(tmpdir), "--json")
            payload = json.loads(proc.stdout)
            audit = payload["claim_audits"][0]

            self.assertTrue(payload["summary"]["passed"])
            self.assertEqual(audit["support_level"], "indirect")
            self.assertTrue(audit["needs_human_review"])
            self.assertIn("未找到", audit["support_reason"])

    def test_draft_from_topic_includes_evidence_report_in_artifacts(self):
        # This will fail until evidence_gate is integrated into draft-from-topic
        topic_file = tmpdir = Path(tempfile.mkdtemp(prefix="wewrite-evidence-draft-")) / "topic.json"
        # minimal topic with sources that draft_writer can use
        topic_file.write_text(json.dumps({
            "topics": [{
                "recommended_title": "Agent 成本",
                "hotspot": {"title": "成本讨论", "source": "微博"},
                "sources": [
                    {"title": "OpenAI", "url": "https://example.com/1", "source_type": "official_docs", "snippet": "tools call external"},
                    {"title": "HN", "url": "https://example.com/2", "source_type": "community", "snippet": "retries burn tokens"},
                    {"title": "Reuters", "url": "https://example.com/3", "source_type": "mainstream_media", "snippet": "cost reliability"}
                ]
            }]
        }, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run(
            [str(PYTHON), str(CLI), "draft-from-topic", "--topic-file", str(topic_file), "--author", "烧 Token 的人"],
            cwd=str(REPO_ROOT),
            env={"WEWRITE_OUTPUT_ROOT": str(topic_file.parent / "output")},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertIn("evidence_report", result["artifacts"])
        report_path = Path(result["artifacts"]["evidence_report"])
        self.assertTrue(report_path.exists())
        quality = json.loads(Path(result["artifacts"]["quality_gates"]).read_text(encoding="utf-8"))
        checks = {item["name"]: item for item in quality["checks"]}
        self.assertEqual(checks["evidence_coverage"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
