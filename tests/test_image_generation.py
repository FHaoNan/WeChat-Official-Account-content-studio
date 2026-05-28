import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"


def load_placeholder_module():
    path = REPO_ROOT / "scripts" / "make_placeholder_image.py"
    spec = importlib.util.spec_from_file_location("make_placeholder_image", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ImageGenerationTests(unittest.TestCase):
    def test_placeholder_font_supports_chinese_text(self):
        module = load_placeholder_module()
        font = module._load_font(36)

        self.assertIsInstance(font, ImageFont.FreeTypeFont)
        font_path = str(getattr(font, "_selected_font_path", getattr(font, "path", "")))
        self.assertRegex(font_path.lower(), r"(pingfang|heiti|songti|noto|simhei|msyh|sourcehan|wqy|hiragino)")

    def test_placeholder_uses_clean_light_background_not_neon_blue(self):
        module = load_placeholder_module()
        image = module.build_placeholder(900, 383, "Agent 成本", "多步任务的系统账")
        r, g, b = image.getpixel((10, 10))
        self.assertGreater(r + g + b, 600)
        self.assertLess(abs(b - r), 80)

    def test_draft_writer_inserts_at_least_three_article_images(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            topic = {
                "topics": [{
                    "recommended_title": "Agent 图片测试",
                    "hotspot": {"title": "Agent 成本讨论", "source": "国内热点"},
                    "engineering_question": "为什么多步 Agent 更容易烧 token？",
                    "token_burner_angle": "从上下文、工具调用和重试链路拆开看。",
                }]
            }
            sources = {
                "sources": [
                    {"title": "OpenAI Tools", "url": "https://platform.openai.com/docs/guides/tools", "source_type": "official_docs", "summary": "官方文档说明工具调用会纳入模型应用流程。"},
                    {"title": "HN Agent discussion", "url": "https://news.ycombinator.com/item?id=41210075", "source_type": "community", "summary": "开发者社区讨论 Agent 工具调用和上下文成本。"},
                    {"title": "Reuters AI infra", "url": "https://www.reuters.com/technology/artificial-intelligence/", "source_type": "mainstream_media", "summary": "媒体报道企业关注 AI 推理成本和可靠性。"},
                ]
            }
            topic_path = tmp / "topic.json"
            sources_path = tmp / "sources.json"
            out = tmp / "article.md"
            ledger = tmp / "ledger.json"
            topic_path.write_text(json.dumps(topic, ensure_ascii=False), encoding="utf-8")
            sources_path.write_text(json.dumps(sources, ensure_ascii=False), encoding="utf-8")

            proc = subprocess.run([
                str(PYTHON), str(REPO_ROOT / "scripts" / "draft_writer.py"),
                "--topic-file", str(topic_path),
                "--sources-file", str(sources_path),
                "--output", str(out),
                "--ledger-output", str(ledger),
                "--json",
            ], cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(proc.returncode, 0, msg=f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
            article = out.read_text(encoding="utf-8")
            self.assertGreaterEqual(article.count("!["), 3)
            for image_name in ["img-01.jpg", "img-02.jpg", "img-03.jpg"]:
                self.assertIn(f"]({image_name})", article)


if __name__ == "__main__":
    unittest.main()
