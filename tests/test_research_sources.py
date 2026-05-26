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
SCRIPT = REPO_ROOT / "scripts" / "research_sources.py"
CLI = REPO_ROOT / "toolkit" / "cli.py"


class ResearchSourcesTests(unittest.TestCase):
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

    def write_topic(self, tmpdir: Path) -> Path:
        topic = tmpdir / "topic.json"
        topic.write_text(json.dumps({
            "topics": [
                {
                    "recommended_title": "Agent 成本为什么降不下来",
                    "hotspot": {"title": "Agent 成本讨论", "source": "微博"},
                    "ai_engineer_question": "为什么多步 Agent 比普通问答更烧 token？",
                    "llm_review": {
                        "token_burner_angle": "从工具调用、上下文膨胀和重试拆成本。",
                        "overseas_evidence_plan": [
                            {"source_type": "official_docs", "query": "OpenAI tools docs agent token cost"},
                            {"source_type": "community", "query": "AI agent token cost Hacker News discussion"},
                            {"source_type": "mainstream_media", "query": "AI agent cost Reuters"}
                        ]
                    }
                }
            ]
        }, ensure_ascii=False), encoding="utf-8")
        return topic

    def write_fixture(self, tmpdir: Path) -> Path:
        fixture = tmpdir / "search-results.json"
        fixture.write_text(json.dumps({
            "results": [
                {"query": "OpenAI tools docs agent token cost", "title": "OpenAI tools documentation", "url": "https://platform.openai.com/docs/guides/tools"},
                {"query": "OpenAI tools docs agent token cost", "title": "OpenAI cookbook", "url": "https://github.com/openai/openai-cookbook"},
                {"query": "AI agent token cost Hacker News discussion", "title": "HN: Agent costs", "url": "https://news.ycombinator.com/item?id=123"},
                {"query": "AI agent cost Reuters", "title": "Reuters: AI agents and cost", "url": "https://www.reuters.com/technology/artificial-intelligence/example"}
            ]
        }, ensure_ascii=False), encoding="utf-8")
        return fixture

    def test_research_sources_uses_fixture_to_write_source_manifest_and_topic(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-research-sources-") as raw_tmp:
            tmpdir = Path(raw_tmp)
            topic = self.write_topic(tmpdir)
            fixture = self.write_fixture(tmpdir)
            out_sources = tmpdir / "sources.json"
            out_topic = tmpdir / "topic-with-sources.json"

            proc = self.run_script(
                "--topic-file", str(topic),
                "--search-fixture", str(fixture),
                "--output", str(out_sources),
                "--topic-output", str(out_topic),
                "--json",
            )
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["summary"]["passed"])
            self.assertEqual(payload["summary"]["categories"]["primary"], 2)
            self.assertEqual(payload["summary"]["categories"]["community"], 1)
            self.assertEqual(payload["summary"]["categories"]["media_or_secondary"], 1)
            self.assertTrue(out_sources.exists())
            self.assertTrue(out_topic.exists())
            sources = json.loads(out_sources.read_text(encoding="utf-8"))["sources"]
            self.assertEqual(len(sources), 4)
            merged_topic = json.loads(out_topic.read_text(encoding="utf-8"))
            self.assertIn("sources", merged_topic["topics"][0])
            self.assertEqual(len(merged_topic["topics"][0]["sources"]), 4)

    def test_research_sources_fails_closed_when_required_category_missing(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-research-sources-") as raw_tmp:
            tmpdir = Path(raw_tmp)
            topic = self.write_topic(tmpdir)
            fixture = tmpdir / "search-results.json"
            fixture.write_text(json.dumps({
                "results": [
                    {"title": "OpenAI tools documentation", "url": "https://platform.openai.com/docs/guides/tools"},
                    {"title": "Reuters: AI agents and cost", "url": "https://www.reuters.com/technology/artificial-intelligence/example"}
                ]
            }, ensure_ascii=False), encoding="utf-8")

            proc = self.run_script(
                "--topic-file", str(topic),
                "--search-fixture", str(fixture),
                "--json",
                expect=1,
            )
            payload = json.loads(proc.stdout)
            self.assertFalse(payload["summary"]["passed"])
            self.assertIn("community", payload["summary"]["missing_categories"])

    def test_research_sources_output_can_feed_draft_from_topic(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-research-to-draft-") as raw_tmp:
            tmpdir = Path(raw_tmp)
            topic = self.write_topic(tmpdir)
            fixture = self.write_fixture(tmpdir)
            out_topic = tmpdir / "topic-with-sources.json"
            self.run_script(
                "--topic-file", str(topic),
                "--search-fixture", str(fixture),
                "--topic-output", str(out_topic),
                "--json",
            )
            proc = subprocess.run(
                [str(PYTHON), str(CLI), "draft-from-topic", "--topic-file", str(out_topic), "--author", "烧 Token 的人"],
                cwd=str(REPO_ROOT),
                env={**dict(), **{"WEWRITE_OUTPUT_ROOT": str(tmpdir / "output")}},
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
            draft_payload = json.loads(proc.stdout)
            source_report = json.loads(Path(draft_payload["artifacts"]["source_report"]).read_text(encoding="utf-8"))
            self.assertTrue(source_report["summary"]["passed"])


if __name__ == "__main__":
    unittest.main()
