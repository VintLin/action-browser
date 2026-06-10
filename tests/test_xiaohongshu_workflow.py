import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import xiaohongshu_workflow as xhs  # noqa: E402


class XiaohongshuAiSearchTests(unittest.TestCase):
    def test_ai_search_result_url_encodes_keyword_once(self) -> None:
        url = xhs.ai_search_result_url("北京周末去哪玩")

        self.assertEqual(
            url,
            "https://www.xiaohongshu.com/search_result_ai?"
            "keyword=%E5%8C%97%E4%BA%AC%E5%91%A8%E6%9C%AB%E5%8E%BB%E5%93%AA%E7%8E%A9"
            "&source=web_explore_feed",
        )
        self.assertNotIn("%25E5", url)

    def test_parse_ai_answer_state_uses_markdown_blocks_and_source_count(self) -> None:
        payload = xhs.parse_ai_answer_state(
            "北京周末去哪玩",
            {
                "sourceUrl": "https://www.xiaohongshu.com/search_result_ai?keyword=test&type=51",
                "messageClass": "ai-message ai-message-finished",
                "rawText": "ai总结49篇笔记生成\n\n不应重复使用头部文本",
                "markdownBlocks": ["第一段", "第二段"],
            },
        )

        self.assertEqual(payload.keyword, "北京周末去哪玩")
        self.assertEqual(payload.status, "finished")
        self.assertEqual(payload.source_count, 49)
        self.assertEqual(payload.answer, "第一段\n\n第二段")
        self.assertEqual(payload.answer_length, len("第一段\n\n第二段"))

    def test_can_direct_open_note_url_requires_xsec_token_for_xiaohongshu_notes(self) -> None:
        self.assertFalse(
            xhs.can_direct_open_note_url("https://www.xiaohongshu.com/explore/69d708f40000000023022429")
        )
        self.assertFalse(
            xhs.can_direct_open_note_url(
                "https://www.xiaohongshu.com/explore/69d708f40000000023022429"
                "?xsec_source=pc_search&source=web_search_result_notes"
            )
        )
        self.assertTrue(
            xhs.can_direct_open_note_url(
                "https://www.xiaohongshu.com/explore/69d708f40000000023022429"
                "?xsec_token=abc&xsec_source=pc_search&source=web_search_result_notes"
            )
        )


if __name__ == "__main__":
    unittest.main()
