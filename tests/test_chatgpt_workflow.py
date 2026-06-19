from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import chatgpt_workflow as chatgpt  # noqa: E402


class ChatGptTaskParsingTests(unittest.TestCase):
    def test_parse_task_record_accepts_required_fields(self) -> None:
        task = chatgpt.parse_task_record(
            {"title": "Q13：示例问题", "question": "这里是问题正文"},
            "record 1",
        )

        self.assertEqual(task.title, "Q13：示例问题")
        self.assertEqual(task.question, "这里是问题正文")
        self.assertEqual(task.output_name, "")

    def test_parse_task_record_accepts_output_name(self) -> None:
        task = chatgpt.parse_task_record(
            {"title": "Q14：示例问题", "question": "问题", "output_name": "custom-name"},
            "record 1",
        )

        self.assertEqual(task.output_name, "custom-name")
        self.assertEqual(chatgpt.task_output_stem(task), "custom-name")

    def test_parse_task_record_rejects_missing_required_fields(self) -> None:
        for record in ({}, {"title": "Q"}, {"question": "问题"}, {"title": "", "question": "问题"}):
            with self.assertRaisesRegex(ValueError, "record 1"):
                chatgpt.parse_task_record(record, "record 1")

    def test_parse_task_record_rejects_non_object_and_non_string_output_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "record 1"):
            chatgpt.parse_task_record("bad", "record 1")

        with self.assertRaisesRegex(ValueError, "record 2"):
            chatgpt.parse_task_record({"title": "Q", "question": "问题", "output_name": 1}, "record 2")

    def test_load_tasks_file_reads_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"title": "Q13：示例", "question": "问题一"}, ensure_ascii=False),
                        json.dumps({"title": "Q14：示例", "question": "问题二"}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            tasks = chatgpt.load_tasks_file(path)

        self.assertEqual([task.title for task in tasks], ["Q13：示例", "Q14：示例"])
        self.assertEqual([task.question for task in tasks], ["问题一", "问题二"])

    def test_load_tasks_file_reads_json_array(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            path.write_text(
                json.dumps(
                    [
                        {"title": "Q13：示例", "question": "问题一"},
                        {"title": "Q14：示例", "question": "问题二"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            tasks = chatgpt.load_tasks_file(path)

        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[1].title, "Q14：示例")

    def test_load_tasks_file_rejects_empty_or_malformed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty.jsonl"
            empty.write_text("", encoding="utf-8")
            bad = Path(tmp) / "bad.jsonl"
            bad.write_text("{bad json}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "empty"):
                chatgpt.load_tasks_file(empty)
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                chatgpt.load_tasks_file(bad)


if __name__ == "__main__":
    unittest.main()
