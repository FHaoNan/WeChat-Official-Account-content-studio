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
SCRIPT = REPO_ROOT / "scripts" / "draft_writer.py"
CLI = REPO_ROOT / "toolkit" / "cli.py"


class DraftWriterTests(unittest.TestCase):
    def run_writer(self, *args, expect=0):
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

    def write_topic_and_sources(self, tmpdir: Path) -> tuple[Path, Path]:
        topic = tmpdir / "topic.json"
        topic.write_text(json.dumps({
            "topics": [
                {
                    "recommended_title": "Agent 成本为什么降不下来",
                    "hotspot": {"title": "Agent 成本讨论升温", "source": "微博"},
                    "engineering_question": "为什么多步 Agent 比普通问答更烧 token？",
                    "token_burner_angle": "从工具调用、上下文膨胀和重试拆成本。",
                }
            ]
        }, ensure_ascii=False), encoding="utf-8")
        sources = tmpdir / "sources.json"
        sources.write_text(json.dumps({
            "sources": [
                {
                    "title": "OpenAI tools docs",
                    "url": "https://platform.openai.com/docs/guides/tools",
                    "source_type": "official_docs",
                    "categories": ["primary"],
                    "snippet": "Tools let models call external functions and APIs, adding extra steps to the application flow."
                },
                {
                    "title": "HN discussion on agent costs",
                    "url": "https://news.ycombinator.com/item?id=123",
                    "source_type": "community",
                    "categories": ["community"],
                    "snippet": "Developers complain that multi-step agents burn tokens quickly because they retry tool calls and carry long context."
                },
                {
                    "title": "Reuters report on AI agent economics",
                    "url": "https://www.reuters.com/technology/artificial-intelligence/example",
                    "source_type": "mainstream_media",
                    "categories": ["media_or_secondary"],
                    "snippet": "Reuters reports that enterprises are watching inference cost and reliability before deploying AI agents widely."
                }
            ]
        }, ensure_ascii=False), encoding="utf-8")
        return topic, sources

    def test_draft_writer_generates_article_v1_with_citations_and_evidence_ledger(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-draft-writer-") as raw_tmp:
            tmpdir = Path(raw_tmp)
            topic, sources = self.write_topic_and_sources(tmpdir)
            article = tmpdir / "article.md"
            ledger = tmpdir / "evidence-ledger.json"

            proc = self.run_writer(
                "--topic-file", str(topic),
                "--sources-file", str(sources),
                "--output", str(article),
                "--ledger-output", str(ledger),
                "--json",
            )
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["success"])
            self.assertEqual(payload["claims"], 3)
            text = article.read_text(encoding="utf-8")
            self.assertIn("# Agent 成本为什么降不下来", text)
            self.assertIn("## 先说结论", text)
            self.assertIn("## 证据链", text)
            self.assertIn("[S1]", text)
            self.assertIn("[S2]", text)
            self.assertIn("[S3]", text)
            self.assertIn("工具调用", text)
            self.assertNotIn("下一步需要人工或 agent 深挖", text)
            ledger_payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(len(ledger_payload["claims"]), 3)
            self.assertEqual(ledger_payload["claims"][0]["source_id"], "S1")

    def test_draft_from_topic_uses_writer_output_and_reports_artifact(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-draft-from-topic-writer-") as raw_tmp:
            tmpdir = Path(raw_tmp)
            topic, sources = self.write_topic_and_sources(tmpdir)
            payload = json.loads(topic.read_text(encoding="utf-8"))
            payload["topics"][0]["sources"] = json.loads(sources.read_text(encoding="utf-8"))["sources"]
            topic.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            proc = subprocess.run(
                [str(PYTHON), str(CLI), "draft-from-topic", "--topic-file", str(topic), "--author", "烧 Token 的人"],
                cwd=str(REPO_ROOT),
                env={"WEWRITE_OUTPUT_ROOT": str(tmpdir / "output")},
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
            result = json.loads(proc.stdout)
            article_dir = Path(result["article_dir"])
            article = (article_dir / "article.md").read_text(encoding="utf-8")
            self.assertIn("## 证据链", article)
            self.assertIn("[S1]", article)
            self.assertTrue((article_dir / "generated" / "evidence-ledger.json").exists())
            self.assertIn("evidence_ledger", result["artifacts"])

    def test_draft_writer_keeps_source_urls_in_ledger_not_article_body(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-draft-no-links-") as raw_tmp:
            tmpdir = Path(raw_tmp)
            topic, sources = self.write_topic_and_sources(tmpdir)
            article = tmpdir / "article.md"
            ledger = tmpdir / "evidence-ledger.json"

            proc = self.run_writer(
                "--topic-file", str(topic),
                "--sources-file", str(sources),
                "--output", str(article),
                "--ledger-output", str(ledger),
                "--json",
            )
            self.assertTrue(json.loads(proc.stdout)["success"])
            text = article.read_text(encoding="utf-8")
            self.assertNotIn("https://", text)
            self.assertNotIn("## 来源", text)
            self.assertIn("[S1]", text)
            ledger_payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertIn("https://platform.openai.com/docs/guides/tools", json.dumps(ledger_payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
