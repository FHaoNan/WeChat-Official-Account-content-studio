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

    def test_research_sources_fails_closed_when_first_hand_source_is_missing(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-research-sources-") as raw_tmp:
            tmpdir = Path(raw_tmp)
            topic = self.write_topic(tmpdir)
            fixture = tmpdir / "search-results.json"
            fixture.write_text(json.dumps({
                "results": [
                    {"title": "HN: Agent costs", "url": "https://news.ycombinator.com/item?id=123"},
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
            self.assertIn("primary", payload["summary"]["missing_categories"])

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

    def test_research_sources_passes_with_first_hand_sources_without_community_or_media(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-research-first-hand-") as raw_tmp:
            tmpdir = Path(raw_tmp)
            topic = self.write_topic(tmpdir)
            fixture = tmpdir / "search-results.json"
            fixture.write_text(json.dumps({
                "results": [
                    {"query": "OpenAI tools docs agent token cost", "title": "OpenAI tools documentation", "url": "https://platform.openai.com/docs/guides/tools"},
                    {"query": "OpenAI tools docs agent token cost", "title": "OpenAI cookbook", "url": "https://github.com/openai/openai-cookbook"}
                ]
            }, ensure_ascii=False), encoding="utf-8")
            out_sources = tmpdir / "sources.json"

            proc = self.run_script(
                "--topic-file", str(topic),
                "--search-fixture", str(fixture),
                "--output", str(out_sources),
                "--json",
            )
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["summary"]["passed"])
            self.assertGreaterEqual(payload["summary"]["categories"]["primary"], 2)
            self.assertEqual(payload["summary"]["missing_categories"], [])
            self.assertIn("first-hand", payload["policy"])
            sources = json.loads(out_sources.read_text(encoding="utf-8"))["sources"]
            self.assertTrue(all("primary" in item.get("categories", []) for item in sources))

    def test_chinese_chip_topic_retries_with_english_fallback_queries(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-research-retry-") as raw_tmp:
            tmpdir = Path(raw_tmp)
            topic = tmpdir / "chip-topic.json"
            topic.write_text(json.dumps({
                "topics": [{
                    "recommended_title": "中国芯片又传来好消息",
                    "hotspot": {"title": "中国芯片又传来好消息", "source": "微博热搜"},
                    "ai_engineer_question": "国产 AI 芯片进入真实推理链路，还差哪些工程条件？",
                    "llm_review": {
                        "overseas_evidence_plan": [
                            {"source_type": "official_docs", "query": "官方/文档：中国芯片又传来好消息"},
                            {"source_type": "github_or_paper", "query": "GitHub/论文：中国芯片 推理 软件栈"},
                        ]
                    }
                }]
            }, ensure_ascii=False), encoding="utf-8")
            fixture = tmpdir / "search-results.json"
            fixture.write_text(json.dumps({
                "queries": {
                    "AI chip inference documentation": [
                        {"title": "NVIDIA Triton Inference Server", "url": "https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/index.html"}
                    ],
                    "AI chip inference GitHub arXiv software stack": [
                        {"title": "FlashAttention GitHub", "url": "https://github.com/Dao-AILab/flash-attention"}
                    ]
                }
            }, ensure_ascii=False), encoding="utf-8")

            proc = self.run_script(
                "--topic-file", str(topic),
                "--search-fixture", str(fixture),
                "--json",
            )
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["summary"]["passed"])
            self.assertGreaterEqual(payload["summary"]["categories"]["primary"], 2)
            queries = {source["research_query"] for source in payload["sources"]}
            self.assertIn("AI chip inference documentation", queries)
            self.assertIn("AI chip inference GitHub arXiv software stack", queries)

    def test_parse_duckduckgo_lite_results_with_snippets(self):
        from scripts.research_sources import parse_duckduckgo_results

        html = """
        <a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.nvidia.com%2Fdeeplearning%2Ftriton%2Dinference%2Dserver%2Fuser%2Dguide%2Fdocs%2Findex.html&amp;rut=x" class='result-link'>NVIDIA Triton Inference Server - NVIDIA Documentation Hub</a>
        <td class='result-snippet'>Triton <b>Inference</b> Server delivers optimized performance.</td>
        """
        results = parse_duckduckgo_results(html, "NVIDIA inference platform documentation", limit=3)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/index.html")
        self.assertIn("Triton Inference Server", results[0]["snippet"])

    def test_curated_fallback_sources_are_topic_family_constrained_and_auditable(self):
        from scripts.research_sources import fallback_sources

        chip_topic = {
            "proposed_title": "AI产业链钱烧在哪：中国芯片又传来好消息",
            "ai_engineer_question": "国产 AI 芯片进入真实推理链路，还差哪些工程条件？",
        }
        sources = fallback_sources("official_docs", chip_topic, "AI chip inference documentation")
        self.assertGreaterEqual(len(sources), 1)
        self.assertTrue(all(source["url"].startswith("https://") for source in sources))
        self.assertTrue(all(source["origin"] == "curated_fallback_after_search_empty" for source in sources))
        self.assertTrue(all(source.get("snippet") for source in sources))

        unrelated_topic = {"proposed_title": "明星机场穿搭又上热搜"}
        self.assertEqual(fallback_sources("mainstream_media", unrelated_topic, "celebrity airport outfit Reuters"), [])


if __name__ == "__main__":
    unittest.main()
