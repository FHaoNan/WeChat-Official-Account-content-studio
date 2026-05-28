import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "fetch_hotspots.py"


def load_fetch_hotspots_module():
    spec = importlib.util.spec_from_file_location("fetch_hotspots", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FetchHotspotsTests(unittest.TestCase):
    def test_deduplicate_merges_cross_platform_signals_for_same_hotspot(self):
        module = load_fetch_hotspots_module()
        items = [
            {"title": "豆包 AI 助手登上应用榜", "source": "微博", "hot": 9000, "hot_normalized": 95, "url": "https://weibo.example"},
            {"title": "豆包 AI 助手登上应用榜", "source": "百度", "hot": 8000, "hot_normalized": 90, "url": "https://baidu.example"},
            {"title": "OpenAI 新模型发布", "source": "今日头条", "hot": 7000, "hot_normalized": 80, "url": "https://toutiao.example"},
        ]

        merged = module.deduplicate(items)

        self.assertEqual(len(merged), 2)
        first = merged[0]
        self.assertEqual(first["title"], "豆包 AI 助手登上应用榜")
        self.assertEqual(first["source"], "微博,百度")
        self.assertEqual(first["hot_normalized"], 95)
        self.assertIn("platform_signals", first)
        self.assertEqual([signal["source"] for signal in first["platform_signals"]], ["微博", "百度"])
        self.assertEqual(first["platform_count"], 2)


if __name__ == "__main__":
    unittest.main()
