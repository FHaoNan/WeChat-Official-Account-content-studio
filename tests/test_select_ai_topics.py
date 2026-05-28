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
SCRIPT = REPO_ROOT / "scripts" / "select_ai_topics.py"


class SelectAiTopicsTests(unittest.TestCase):
    def write_hotspots(self, tmpdir: str) -> Path:
        hotspots = Path(tmpdir) / "hotspots.json"
        hotspots.write_text(json.dumps({
            "items": [
                {"title": "OpenAI 发布新模型引发热议", "source": "微博", "hot_normalized": 95, "url": "https://example.com/a"},
                {"title": "某明星机场穿搭", "source": "微博", "hot_normalized": 100, "url": "https://example.com/b"},
                {"title": "AI 芯片公司财报增长", "source": "百度", "hot_normalized": 80, "url": "https://example.com/c"},
            ]
        }, ensure_ascii=False), encoding="utf-8")
        return hotspots

    def run_script(self, *args):
        return subprocess.run(
            [str(PYTHON), str(SCRIPT), *args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_scores_ai_topics_and_filters_low_evidence_for_auto_write(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-topic-test-") as tmpdir:
            hotspots = self.write_hotspots(tmpdir)
            proc = self.run_script("--hotspots", str(hotspots), "--style", str(REPO_ROOT / "style.yaml"), "--json")
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["policy"], "国内热点发现，海外信息补证")
            self.assertGreaterEqual(len(payload["topics"]), 2)
            titles = [item["hotspot"]["title"] for item in payload["topics"]]
            self.assertNotIn("某明星机场穿搭", titles)
            first = payload["topics"][0]
            self.assertIn("ai_engineer_question", first)
            self.assertIn("overseas_evidence", first)
            self.assertIn("scores", first)
            self.assertGreaterEqual(first["scores"]["overseas_evidence"], 5)
            for topic in payload["topics"]:
                if topic["scores"]["overseas_evidence"] < 5:
                    self.assertFalse(topic["auto_write_allowed"])

    def test_domestic_multi_platform_heat_can_outrank_niche_engineering_topic(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-topic-traffic-test-") as tmpdir:
            hotspots = Path(tmpdir) / "hotspots.json"
            hotspots.write_text(json.dumps({
                "items": [
                    {
                        "title": "豆包 AI 助手登上应用榜引发讨论",
                        "source": "微博",
                        "hot_normalized": 92,
                        "url": "https://example.com/doubao-weibo",
                        "description": "AI 助手、多平台热议",
                        "platform_signals": [
                            {"source": "微博", "hot_normalized": 92, "rank": 3},
                            {"source": "百度", "hot_normalized": 88, "rank": 6},
                            {"source": "小红书", "hot_normalized": 80, "rank": 8},
                        ],
                    },
                    {
                        "title": "小众开源 RAG 框架发布新版本",
                        "source": "GitHub Trending",
                        "hot_normalized": 35,
                        "url": "https://example.com/rag",
                        "description": "RAG、Agent、开源、GitHub、论文、模型、推理、部署、API",
                    },
                    {
                        "title": "某明星演唱会门票秒空",
                        "source": "微博",
                        "hot_normalized": 100,
                        "url": "https://example.com/star",
                    },
                ]
            }, ensure_ascii=False), encoding="utf-8")

            proc = self.run_script("--hotspots", str(hotspots), "--style", str(REPO_ROOT / "style.yaml"), "--json")
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["scoring_weights"]["domestic_heat"], 0.35)
            self.assertIn("platform_heat", payload["scoring_weights"])
            titles = [item["hotspot"]["title"] for item in payload["topics"]]
            self.assertNotIn("某明星演唱会门票秒空", titles)
            first = payload["topics"][0]
            self.assertEqual(first["hotspot"]["title"], "豆包 AI 助手登上应用榜引发讨论")
            self.assertIn("platform_heat", first)
            self.assertGreaterEqual(first["platform_heat"]["platform_count"], 3)
            self.assertIn("why_now", first)
            self.assertIn("微博", first["why_now"])
            self.assertIn("百度", first["why_now"])
            self.assertGreater(first["scores"]["weighted_total"], payload["topics"][1]["scores"]["weighted_total"])

    def test_high_heat_social_topic_is_filtered_when_it_has_no_ai_angle(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-topic-social-filter-") as tmpdir:
            hotspots = Path(tmpdir) / "hotspots.json"
            hotspots.write_text(json.dumps({
                "items": [
                    {"title": "甘孜通报稻城亚丁景区违规封堵省道", "source": "微博", "hot_normalized": 100, "url": "https://example.com/social"},
                    {"title": "中国自研高算力芯片突破4纳米", "source": "微博", "hot_normalized": 70, "url": "https://example.com/chip"},
                ]
            }, ensure_ascii=False), encoding="utf-8")

            proc = self.run_script("--hotspots", str(hotspots), "--style", str(REPO_ROOT / "style.yaml"), "--json")
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(proc.stdout)
            titles = [item["hotspot"]["title"] for item in payload["topics"]]
            self.assertNotIn("甘孜通报稻城亚丁景区违规封堵省道", titles)
            self.assertIn("中国自研高算力芯片突破4纳米", titles)

    def test_llm_rerank_uses_fixture_and_is_explicitly_enabled(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-topic-llm-test-") as tmpdir:
            hotspots = self.write_hotspots(tmpdir)
            fixture = Path(tmpdir) / "llm-review.json"
            fixture.write_text(json.dumps({
                "reviews": [
                    {
                        "index": 2,
                        "hotspot_title": "AI 芯片公司财报增长（LLM 可能轻微改写）",
                        "fit_score": 9,
                        "evidence_plan_score": 8,
                        "write_or_skip": "write",
                        "editorial_reason": "适合拆 AI 算力需求与真实收入，而不是写股价。",
                        "token_burner_angle": "从推理成本和 GPU 供给讲清 token 被烧在哪。",
                        "reader_question": "为什么模型越便宜，芯片公司反而更重要？",
                        "overseas_evidence_plan": [
                            {"source_type": "earnings", "query": "NVIDIA earnings transcript AI inference demand"}
                        ],
                        "risk_flags": ["避免荐股"]
                    },
                    {
                        "hotspot_title": "OpenAI 发布新模型引发热议",
                        "fit_score": 7,
                        "evidence_plan_score": 7,
                        "write_or_skip": "write",
                        "editorial_reason": "需要官方文档和评测补证。",
                        "token_burner_angle": "拆能力提升是否带来更高推理成本。",
                        "reader_question": "新模型到底省 token 还是烧 token？",
                        "overseas_evidence_plan": [
                            {"source_type": "official_docs", "query": "OpenAI release notes new model"}
                        ],
                        "risk_flags": []
                    }
                ]
            }, ensure_ascii=False), encoding="utf-8")

            proc = self.run_script(
                "--hotspots", str(hotspots),
                "--style", str(REPO_ROOT / "style.yaml"),
                "--llm-rerank",
                "--llm-fixture", str(fixture),
                "--json",
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["llm_rerank"]["enabled"])
            self.assertEqual(payload["llm_rerank"]["provider"], "fixture")
            self.assertEqual(payload["topics"][0]["hotspot"]["title"], "AI 芯片公司财报增长")
            self.assertEqual(payload["topics"][0]["llm_review"]["fit_score"], 9)
            self.assertIn("final_score", payload["topics"][0]["scores"])

    def test_llm_rerank_missing_config_falls_back_to_heuristic(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-topic-llm-test-") as tmpdir:
            hotspots = self.write_hotspots(tmpdir)
            proc = self.run_script(
                "--hotspots", str(hotspots),
                "--style", str(REPO_ROOT / "style.yaml"),
                "--llm-rerank",
                "--config", str(Path(tmpdir) / "missing-config.yaml"),
                "--json",
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["llm_rerank"]["enabled"])
            self.assertEqual(payload["llm_rerank"]["status"], "fallback")
            self.assertIn("missing", payload["llm_rerank"]["error"])
            self.assertNotIn("llm_review", payload["topics"][0])
    def test_llm_rerank_missing_config_fallback_uses_full_heuristic_pool(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-topic-llm-test-") as tmpdir:
            hotspots = self.write_hotspots(tmpdir)
            proc = self.run_script(
                "--hotspots", str(hotspots),
                "--style", str(REPO_ROOT / "style.yaml"),
                "--llm-rerank",
                "--config", str(Path(tmpdir) / "missing-config.yaml"),
                "--prefilter-limit", "1",
                "--limit", "2",
                "--json",
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["llm_rerank"]["status"], "fallback")
            self.assertEqual(len(payload["topics"]), 2)

    def test_llm_options_do_nothing_without_explicit_rerank_flag(self):
        with tempfile.TemporaryDirectory(prefix="wewrite-topic-llm-test-") as tmpdir:
            hotspots = self.write_hotspots(tmpdir)
            fixture = Path(tmpdir) / "llm-review.json"
            fixture.write_text(json.dumps({"reviews": []}, ensure_ascii=False), encoding="utf-8")
            proc = self.run_script(
                "--hotspots", str(hotspots),
                "--style", str(REPO_ROOT / "style.yaml"),
                "--llm-fixture", str(fixture),
                "--json",
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["llm_rerank"]["status"], "disabled")
            self.assertNotIn("llm_review", payload["topics"][0])


if __name__ == "__main__":
    unittest.main()
