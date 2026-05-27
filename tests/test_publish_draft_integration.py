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


class PublishDraftIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wewrite-publish-draft-test-"))
        self.config = self.tmp / "config.yaml"
        self.config.write_text(
            "wechat:\n  appid: fake-appid\n  secret: fake-secret\nimage:\n  api_key: fake-image-key\n",
            encoding="utf-8",
        )

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

    def make_publishable_article(self, *, existing_media_id: str = "") -> Path:
        proc = self.run_cli("new", "--title", "Agent 成本发布测试", "--author", "烧 Token 的人")
        article_dir = Path(json.loads(proc.stdout)["article_dir"])
        article = (
            "# Agent 成本发布测试\n\n"
            + "多步 Agent 会因为工具调用和重试烧掉更多 token [S1]。" * 12
            + "\n\n![配图 1：链路示意](img-01.jpg)\n"
        )
        (article_dir / "article.md").write_text(article, encoding="utf-8")
        for name in ["img-01.jpg", "cover-wide.jpg", "cover-square.jpg"]:
            (article_dir / "assets" / name).write_bytes(b"placeholder")
        metadata_path = article_dir / "draft-metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata.update({
            "digest": "从工程链路看 Agent 为什么烧 token。",
            "cover_image": "assets/cover-wide.jpg",
        })
        if existing_media_id:
            metadata["media_id"] = existing_media_id
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        generated = article_dir / "generated"
        generated.mkdir(exist_ok=True)
        (generated / "sources.json").write_text(json.dumps({
            "sources": [
                {"title": "OpenAI tools docs", "url": "https://platform.openai.com/docs/guides/tools", "source_type": "official_docs", "summary": "工具调用会增加链路。"},
                {"title": "HN discussion", "url": "https://news.ycombinator.com/item?id=123", "source_type": "community", "summary": "社区讨论 Agent 成本。"},
                {"title": "Reuters report", "url": "https://www.reuters.com/technology/artificial-intelligence/example", "source_type": "mainstream_media", "summary": "媒体报道 AI 基础设施成本。"},
            ]
        }, ensure_ascii=False), encoding="utf-8")
        return article_dir

    def test_publish_draft_fake_wechat_creates_draft_payload_and_updates_metadata(self):
        article_dir = self.make_publishable_article()
        proc = self.run_cli(
            "publish-draft",
            "--article-dir", str(article_dir),
            "--config", str(self.config),
            "--fake-wechat",
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["action"], "created")
        self.assertEqual(payload["media_id"], "fake-draft-media-id")
        self.assertTrue((article_dir / "generated" / "draft.json").exists())
        self.assertTrue((article_dir / "generated" / "publish-result.json").exists())
        metadata = json.loads((article_dir / "draft-metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["media_id"], "fake-draft-media-id")
        draft = json.loads((article_dir / "generated" / "draft.json").read_text(encoding="utf-8"))
        article = draft["articles"][0]
        self.assertEqual(article["thumb_media_id"], "fake-thumb-media-id")
        self.assertIn("https://fake.wechat.local/uploadimg/img-01.jpg", article["content"])

    def test_publish_draft_fake_wechat_updates_existing_draft(self):
        article_dir = self.make_publishable_article(existing_media_id="existing-media-id")
        proc = self.run_cli(
            "publish-draft",
            "--article-dir", str(article_dir),
            "--config", str(self.config),
            "--fake-wechat",
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["action"], "updated")
        self.assertEqual(payload["media_id"], "existing-media-id")
        result = json.loads((article_dir / "generated" / "publish-result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["action"], "updated")


if __name__ == "__main__":
    unittest.main()
