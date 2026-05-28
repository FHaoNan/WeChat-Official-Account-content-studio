import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)
CLI = REPO_ROOT / "toolkit" / "cli.py"

sys.path.insert(0, str(REPO_ROOT / "toolkit"))
from converter import WeChatConverter  # noqa: E402
from theme import load_theme  # noqa: E402


class MobileRenderSpacingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wewrite-mobile-spacing-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_converter_applies_mobile_reading_spacing_to_paragraphs_images_and_cards(self):
        converter = WeChatConverter(theme=load_theme("token-clean"))
        result = converter.convert(
            "# 标题\n\n"
            "第一段正文用来验证手机端行距和段间距，不能太松也不能贴边。\n\n"
            "![配图](img-01.jpg)\n"
            "*图 1：这是一句图注。*\n\n"
            "> 这是一个引用卡片，需要有手机端安全留白。\n"
        )
        soup = BeautifulSoup(result.html, "html.parser")
        first_p = soup.find("p")
        self.assertIsNotNone(first_p)
        p_style = first_p.get("style", "")
        self.assertIn("line-height: 1.74", p_style)
        self.assertIn("margin: 0 0 14px 0", p_style)
        self.assertIn("letter-spacing: 0.02em", p_style)

        img = soup.find("img")
        self.assertIsNotNone(img)
        img_style = img.get("style", "")
        self.assertIn("width: 100%", img_style)
        self.assertIn("max-width: 100%", img_style)
        self.assertIn("margin: 18px 0 6px 0", img_style)
        self.assertNotIn("24px auto", img_style)

        blockquote = soup.find("blockquote")
        self.assertIsNotNone(blockquote)
        bq_style = blockquote.get("style", "")
        self.assertIn("margin: 18px 0", bq_style)
        self.assertIn("padding: 14px 15px", bq_style)
        self.assertIn("border-radius: 12px", bq_style)

    def test_render_shell_uses_mobile_safe_canvas_instead_of_desktop_card(self):
        env = os.environ.copy()
        env["WEWRITE_OUTPUT_ROOT"] = str(self.tmp)
        proc = subprocess.run(
            [str(PYTHON), str(CLI), "new", "--title", "P14 边距测试", "--author", "烧 Token 的人"],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        article_dir = Path(json.loads(proc.stdout)["article_dir"])
        (article_dir / "article.md").write_text(
            "# P14 边距测试\n\n"
            "这是一段用于验证公众号手机端左右留白的正文。" * 8 + "\n\n"
            "![配图 1：边距示意](img-01.jpg)\n"
            "*图 1：图片应该占满正文宽度，但不突破安全区。*\n",
            encoding="utf-8",
        )
        for name in ["img-01.jpg", "cover-wide.jpg", "cover-square.jpg"]:
            (article_dir / "assets" / name).write_bytes(b"placeholder")

        proc = subprocess.run(
            [str(PYTHON), str(CLI), "render", "--article-dir", str(article_dir)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(proc.returncode, 0, msg=f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        html = (article_dir / "article-body.template.html").read_text(encoding="utf-8")
        self.assertIn("padding:0 16px", html)
        self.assertIn("max-width:677px", html)
        self.assertIn("box-shadow:none", html)
        self.assertNotIn("padding:40px 10px", html)
        self.assertNotIn("max-width:800px", html)
        self.assertNotIn("padding:28px", html)


if __name__ == "__main__":
    unittest.main()
