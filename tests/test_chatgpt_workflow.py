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


class ChatGptCliAndOutputTests(unittest.TestCase):
    def test_default_run_output_dir_uses_runs_tree(self) -> None:
        path = chatgpt.default_run_output_dir()

        self.assertIn("assets/chatgpt/runs", str(path))

    def test_write_task_markdown_uses_output_name_and_frontmatter(self) -> None:
        task = chatgpt.ChatGptTask(title="Q13：标题", question="问题正文", output_name="custom-output")
        result = {"text": "## 回答\n\n内容", "clicked_copy": True, "used_system_clipboard": True}
        with tempfile.TemporaryDirectory() as tmp:
            path = chatgpt.write_task_markdown(
                Path(tmp),
                1,
                task,
                result,
                "https://chatgpt.com/c/example",
                "2026-06-19T10:00:00",
                "2026-06-19T10:01:00",
            )
            text = path.read_text(encoding="utf-8")

        self.assertEqual(path.name, "001-custom-output.md")
        self.assertIn('title: "Q13：标题"', text)
        self.assertIn('question: "问题正文"', text)
        self.assertIn('method: "system-clipboard"', text)
        self.assertIn('mode_fallback: "False"', text)
        self.assertIn("## 回答", text)

    def test_help_exposes_ask_batch_ask_list_and_export(self) -> None:
        result = subprocess.run(
            ["python3", str(SCRIPTS / "chatgpt_workflow.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )

        for command in ("ask", "batch-ask", "list", "export"):
            self.assertIn(command, result.stdout)


class ChatGptBrowserHelperContractTests(unittest.TestCase):
    def test_browser_helper_functions_exist(self) -> None:
        for name in (
            "click_visible_control",
            "create_new_chat",
            "enable_web_search",
            "select_intelligent_mode",
            "select_pro_extension",
            "submit_prompt",
            "wait_for_answer_complete",
        ):
            self.assertTrue(callable(getattr(chatgpt, name)))

    def test_script_does_not_read_sensitive_browser_storage(self) -> None:
        source = (SCRIPTS / "chatgpt_workflow.py").read_text(encoding="utf-8").lower()
        for term in ("document.cookie", "localstorage", "sessionstorage", "password"):
            self.assertNotIn(term, source)


class ChatGptFailureRecordTests(unittest.TestCase):
    def test_failure_record_contains_required_fields(self) -> None:
        task = chatgpt.ChatGptTask(title="Q13：标题", question="问题正文")
        record = chatgpt.failure_record(1, task, "https://chatgpt.com/", RuntimeError("boom"))

        self.assertEqual(record["index"], 1)
        self.assertEqual(record["title"], "Q13：标题")
        self.assertEqual(record["question"], "问题正文")
        self.assertEqual(record["url"], "https://chatgpt.com/")
        self.assertEqual(record["error"], "boom")
        self.assertIn("failed_at", record)


if __name__ == "__main__":
    unittest.main()
