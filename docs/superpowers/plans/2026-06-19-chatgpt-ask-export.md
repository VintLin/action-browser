# ChatGPT Ask Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `scripts/chatgpt_workflow.py` so ChatGPT web UI tasks can be submitted singly or in batches and their latest assistant replies saved as Markdown.

**Architecture:** Keep `scripts/chatgpt_workflow.py` as the single ChatGPT CLI entry point, but add typed task parsing, shared Markdown writing, UI action helpers, and ask/batch orchestration as separate named functions. Existing `list` and `export` stay intact and reuse the same copy-response path.

**Tech Stack:** Python 3 standard library, `unittest`, ActionBook extension mode, macOS `pbcopy`/`pbpaste`, existing `actionbook_session.py` and `actionbook_run.py`.

## Global Constraints

- Use ActionBook extension mode so the workflow reuses the user's logged-in Chrome session.
- Do not call OpenAI APIs.
- Do not read browser cookies, local storage, session storage, tokens, or passwords.
- Final answer content must come from ChatGPT's `Copy response` / `复制回复` control and macOS system clipboard validation.
- Do not silently save DOM text as the final answer.
- Existing `list` and `export` commands must continue to work.
- Batch execution must continue after an individual task failure and exit non-zero if any failures occurred.
- Default run output is `assets/chatgpt/runs/<timestamp>/`.

---

### Task 1: Typed Task Input And File Parsing

**Files:**
- Modify: `scripts/chatgpt_workflow.py`
- Create: `tests/test_chatgpt_workflow.py`

**Interfaces:**
- Produces: `ChatGptTask(title: str, question: str, output_name: str = "")`
- Produces: `parse_task_record(record: Any, label: str) -> ChatGptTask`
- Produces: `load_tasks_file(path: Path) -> list[ChatGptTask]`
- Produces: `task_output_stem(task: ChatGptTask) -> str`
- Consumes: existing `sanitize_name(value: str, fallback: str = "conversation", max_length: int = 90) -> str`

- [ ] **Step 1: Write failing tests for task parsing**

Add `tests/test_chatgpt_workflow.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_chatgpt_workflow.ChatGptTaskParsingTests -v
```

Expected: failures mentioning missing `parse_task_record`, `load_tasks_file`, or `task_output_stem`.

- [ ] **Step 3: Implement task data model and parsers**

Modify imports in `scripts/chatgpt_workflow.py`:

```python
from dataclasses import dataclass
```

Add near constants:

```python
@dataclass(frozen=True)
class ChatGptTask:
    title: str
    question: str
    output_name: str = ""
```

Add below `parse_prefixes`:

```python
def parse_task_record(record: Any, label: str) -> ChatGptTask:
    if not isinstance(record, dict):
        raise ValueError(f"{label}: task record must be an object")
    title = str(record.get("title") or "").strip()
    question = str(record.get("question") or "").strip()
    if not title:
        raise ValueError(f"{label}: title is required")
    if not question:
        raise ValueError(f"{label}: question is required")
    output_name_value = record.get("output_name", "")
    if output_name_value is None:
        output_name = ""
    elif isinstance(output_name_value, str):
        output_name = output_name_value.strip()
    else:
        raise ValueError(f"{label}: output_name must be a string when present")
    return ChatGptTask(title=title, question=question, output_name=output_name)


def load_tasks_file(path: Path) -> list[ChatGptTask]:
    raw = path.expanduser().read_text(encoding="utf-8")
    if not raw.strip():
        raise ValueError(f"{path}: task file is empty")
    stripped = raw.lstrip()
    if stripped.startswith("["):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: invalid JSON: {exc.msg}") from exc
        if not isinstance(payload, list):
            raise ValueError(f"{path}: JSON task file must contain an array")
        if not payload:
            raise ValueError(f"{path}: task file is empty")
        return [parse_task_record(record, f"record {index}") for index, record in enumerate(payload, start=1)]
    tasks: list[ChatGptTask] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: invalid JSON on line {line_number}: {exc.msg}") from exc
        tasks.append(parse_task_record(record, f"line {line_number}"))
    if not tasks:
        raise ValueError(f"{path}: task file is empty")
    return tasks


def task_output_stem(task: ChatGptTask) -> str:
    return sanitize_name(task.output_name or task.title, fallback="chatgpt-answer")
```

- [ ] **Step 4: Run parsing tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_chatgpt_workflow.ChatGptTaskParsingTests -v
```

Expected: all tests in `ChatGptTaskParsingTests` pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add scripts/chatgpt_workflow.py tests/test_chatgpt_workflow.py
git commit -m "Add ChatGPT task parsing"
```

---

### Task 2: CLI Commands And Run Output Helpers

**Files:**
- Modify: `scripts/chatgpt_workflow.py`
- Modify: `tests/test_chatgpt_workflow.py`

**Interfaces:**
- Consumes: `ChatGptTask`, `load_tasks_file`, `task_output_stem`
- Produces: `default_run_output_dir() -> Path`
- Produces: `write_task_markdown(output_dir: Path, index: int, task: ChatGptTask, result: dict[str, Any], source_url: str, started_at: str, completed_at: str) -> Path`
- Produces CLI subcommands `ask` and `batch-ask`

- [ ] **Step 1: Add failing tests for CLI exposure and output path helpers**

Append to `tests/test_chatgpt_workflow.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_chatgpt_workflow.ChatGptCliAndOutputTests -v
```

Expected: failures for missing `default_run_output_dir`, `write_task_markdown`, or CLI command names.

- [ ] **Step 3: Add run output helper**

Add below `default_output_dir`:

```python
def default_run_output_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ASSETS_DIR / "runs" / stamp
```

- [ ] **Step 4: Add task Markdown writer**

Add below existing `write_markdown` or replace only shared duplication with this new function:

```python
def write_task_markdown(
    output_dir: Path,
    index: int,
    task: ChatGptTask,
    result: dict[str, Any],
    source_url: str,
    started_at: str,
    completed_at: str,
) -> Path:
    filename = f"{index:03d}-{task_output_stem(task)}.md"
    path = output_dir / filename
    metadata = {
        "title": task.title,
        "question": task.question,
        "source_url": source_url,
        "created_at": started_at,
        "copied_at": completed_at,
        "method": "system-clipboard",
        "web_search": "true",
        "mode": "intelligent",
        "extension": "pro",
        "clicked_copy": bool(result.get("clicked_copy")),
    }
    content = normalize_text(result.get("text") or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter_string(metadata) + "\n\n" + content.rstrip() + "\n", encoding="utf-8")
    return path
```

- [ ] **Step 5: Add temporary command handlers that fail clearly**

Add these handlers before `positive_int`; Task 4 replaces both function bodies with the production orchestration:

```python
def run_ask(args: argparse.Namespace) -> int:
    task = ChatGptTask(title=str(args.title or "").strip(), question=str(args.question or "").strip())
    parse_task_record({"title": task.title, "question": task.question}, "ask")
    raise RuntimeError("ask command is not implemented yet")


def run_batch_ask(args: argparse.Namespace) -> int:
    load_tasks_file(Path(args.tasks_file))
    raise RuntimeError("batch-ask command is not implemented yet")
```

- [ ] **Step 6: Add CLI parser entries**

In `build_parser`, add before `list_parser`:

```python
    ask_parser = sub.add_parser("ask", help="Ask one ChatGPT question and export the latest answer")
    ask_parser.add_argument("--title", required=True, help="Task title for metadata and filename")
    ask_parser.add_argument("--question", required=True, help="Question text to send to ChatGPT")
    ask_parser.add_argument("--output-dir", default="", help="Output directory")
    ask_parser.add_argument("--answer-timeout", type=positive_int, default=900, help="Seconds to wait for answer completion")
    ask_parser.set_defaults(func=run_ask)

    batch_parser = sub.add_parser("batch-ask", help="Ask multiple ChatGPT questions from a JSON or JSONL task file")
    batch_parser.add_argument("--tasks-file", required=True, help="JSON or JSONL task file")
    batch_parser.add_argument("--output-dir", default="", help="Output directory")
    batch_parser.add_argument("--delay", type=float, default=1.0, help="Delay between tasks")
    batch_parser.add_argument("--answer-timeout", type=positive_int, default=900, help="Seconds to wait for answer completion")
    batch_parser.set_defaults(func=run_batch_ask)
```

- [ ] **Step 7: Run CLI/output tests**

Run:

```bash
python3 -m unittest tests.test_chatgpt_workflow.ChatGptCliAndOutputTests -v
```

Expected: all tests in `ChatGptCliAndOutputTests` pass.

- [ ] **Step 8: Commit Task 2**

```bash
git add scripts/chatgpt_workflow.py tests/test_chatgpt_workflow.py
git commit -m "Add ChatGPT ask CLI skeleton"
```

---

### Task 3: Browser UI Action Helpers For Asking

**Files:**
- Modify: `scripts/chatgpt_workflow.py`
- Modify: `tests/test_chatgpt_workflow.py`

**Interfaces:**
- Produces: `click_visible_control(book: ActionBook, label: str, selector_script: str, timeout: float = 10.0) -> dict[str, Any]`
- Produces: `create_new_chat(book: ActionBook) -> None`
- Produces: `enable_web_search(book: ActionBook) -> None`
- Produces: `select_intelligent_mode(book: ActionBook) -> None`
- Produces: `select_pro_extension(book: ActionBook) -> None`
- Produces: `submit_prompt(book: ActionBook, question: str) -> None`
- Produces: `wait_for_answer_complete(book: ActionBook, timeout_seconds: int) -> None`

- [ ] **Step 1: Add failing source safety and helper existence tests**

Append to `tests/test_chatgpt_workflow.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_chatgpt_workflow.ChatGptBrowserHelperContractTests -v
```

Expected: failures for missing helper functions.

- [ ] **Step 3: Add generic visible-control click helper**

Add below `go_to_conversation_bottom`:

```python
def click_visible_control(
    book: ActionBook,
    label: str,
    selector_script: str,
    timeout: float = 10.0,
) -> dict[str, Any]:
    result = api_eval(book, selector_script, f"locate {label}", timeout=timeout)
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError(f"{label} control not found: {result}")
    book.browser("click", f"{int(result['x'])},{int(result['y'])}", timeout=timeout)
    time.sleep(0.4)
    return result
```

- [ ] **Step 4: Add new chat helper**

Add:

```python
NEW_CHAT_CONTROL_JS = r"""
(() => {
  const visible = node => {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const candidates = [...document.querySelectorAll('a, button, [role="button"]')]
    .filter(visible)
    .map(node => {
      const text = [node.getAttribute('aria-label'), node.innerText, node.textContent]
        .map(value => String(value || '').trim()).join('\n');
      const href = node.getAttribute('href') || '';
      const score = /新聊天|new chat/i.test(text) || href === '/' ? 100 : 0;
      const rect = node.getBoundingClientRect();
      return { node, score, x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top + rect.height / 2), text };
    })
    .filter(item => item.score > 0)
    .sort((a, b) => b.score - a.score);
  const item = candidates[0];
  return item ? { ok: true, x: item.x, y: item.y, text: item.text } : { ok: false };
})()
"""


def create_new_chat(book: ActionBook) -> None:
    before_url = str(book.browser("url", timeout=10.0) or "")
    click_visible_control(book, "new chat", NEW_CHAT_CONTROL_JS)
    api_eval(
        book,
        f"""
        (async () => {{
          const before = {json.dumps(before_url)};
          const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
          for (let i = 0; i < 40; i += 1) {{
            const text = document.body?.innerText || '';
            const composer = document.querySelector('[contenteditable="true"], textarea, [data-testid="composer"]');
            if (composer && (location.href !== before || /有什么可以帮忙|message chatgpt|ask anything/i.test(text))) return true;
            await sleep(250);
          }}
          return {{ error: 'new chat did not become ready' }};
        }})()
        """,
        "wait new ChatGPT chat",
        timeout=15.0,
    )
```

- [ ] **Step 5: Add web search, intelligent mode, and Pro extension helpers**

Add selector constants and functions:

```python
COMPOSER_PLUS_CONTROL_JS = r"""
(() => {
  const visible = node => {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const candidates = [...document.querySelectorAll('button, [role="button"]')]
    .filter(visible)
    .map(node => {
      const text = [node.getAttribute('aria-label'), node.getAttribute('data-testid'), node.innerText, node.textContent]
        .map(value => String(value || '').trim()).join('\n');
      const score = /composer-plus-btn|添加文件|add/i.test(text) ? 100 : 0;
      const rect = node.getBoundingClientRect();
      return { node, score, x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top + rect.height / 2), text };
    })
    .filter(item => item.score > 0)
    .sort((a, b) => b.score - a.score);
  const item = candidates[0];
  return item ? { ok: true, x: item.x, y: item.y, text: item.text } : { ok: false };
})()
"""


def menu_item_control_js(pattern: str, label: str) -> str:
    return f"""
    (() => {{
      const regex = new RegExp({json.dumps(pattern)}, 'i');
      const visible = node => {{
        const rect = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
      }};
      const candidates = [...document.querySelectorAll('[role="menuitem"], button, [role="button"]')]
        .filter(visible)
        .map(node => {{
          const text = [node.getAttribute('aria-label'), node.getAttribute('data-testid'), node.innerText, node.textContent]
            .map(value => String(value || '').trim()).join('\\n');
          const rect = node.getBoundingClientRect();
          const insideComposerArea = rect.top > window.innerHeight * 0.35;
          const score = regex.test(text) && insideComposerArea ? 100 : 0;
          return {{ node, score, x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top + rect.height / 2), text }};
        }})
        .filter(item => item.score > 0)
        .sort((a, b) => b.score - a.score);
      const item = candidates[0];
      return item ? {{ ok: true, x: item.x, y: item.y, text: item.text, label: {json.dumps(label)} }} : {{ ok: false }};
    }})()
    """


def enable_web_search(book: ActionBook) -> None:
    click_visible_control(book, "composer plus", COMPOSER_PLUS_CONTROL_JS)
    click_visible_control(book, "web search", menu_item_control_js("网页搜索|web search|search", "web search"))


def select_intelligent_mode(book: ActionBook) -> None:
    click_visible_control(book, "intelligent mode", menu_item_control_js("智能|intelligent", "intelligent mode"))


def select_pro_extension(book: ActionBook) -> None:
    click_visible_control(book, "Pro extension", menu_item_control_js("Pro 扩展|Pro", "Pro extension"))
```

- [ ] **Step 6: Add prompt submit and answer wait helpers**

Add:

```python
def submit_prompt(book: ActionBook, question: str) -> None:
    script = f"""
    (() => {{
      const question = {json.dumps(question)};
      const candidates = [
        ...document.querySelectorAll('[contenteditable="true"], textarea')
      ].filter(node => {{
        const rect = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
      }});
      const composer = candidates[candidates.length - 1];
      if (!composer) return {{ error: 'composer not found' }};
      composer.focus();
      if (composer.tagName === 'TEXTAREA') {{
        composer.value = question;
        composer.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: question }}));
      }} else {{
        document.execCommand('selectAll', false);
        document.execCommand('insertText', false, question);
      }}
      return {{ ok: true }};
    }})()
    """
    result = api_eval(book, script, "fill ChatGPT composer", timeout=10.0)
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(f"fill ChatGPT composer: {result.get('error')}")
    send_result = api_eval(
        book,
        """
        (() => {
          const visible = node => {
            const rect = node.getBoundingClientRect();
            const style = getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && !node.disabled;
          };
          const buttons = [...document.querySelectorAll('button')].filter(visible);
          const send = buttons.find(node => /send|发送|submit/i.test([
            node.getAttribute('aria-label'),
            node.getAttribute('data-testid'),
            node.innerText,
            node.textContent
          ].join('\\n')));
          if (!send) return { ok: false };
          const rect = send.getBoundingClientRect();
          return { ok: true, x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top + rect.height / 2) };
        })()
        """,
        "locate send button",
        timeout=10.0,
    )
    if isinstance(send_result, dict) and send_result.get("ok"):
        book.browser("click", f"{int(send_result['x'])},{int(send_result['y'])}", timeout=10.0)
    else:
        book.browser("press", "Enter", timeout=10.0)


def wait_for_answer_complete(book: ActionBook, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    last_text = ""
    stable_rounds = 0
    saw_assistant = False
    while time.time() < deadline:
        state = api_eval(
            book,
            """
            (() => {
              const visible = node => {
                if (!node) return false;
                const rect = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
              };
              const assistants = [...document.querySelectorAll('[data-message-author-role="assistant"]')].filter(visible);
              const latest = assistants[assistants.length - 1];
              const text = String(latest?.innerText || latest?.textContent || '').trim();
              const stopVisible = [...document.querySelectorAll('button')]
                .filter(visible)
                .some(node => /stop|停止|中止/i.test([node.getAttribute('aria-label'), node.innerText, node.textContent].join('\\n')));
              const composer = [...document.querySelectorAll('[contenteditable="true"], textarea')].find(visible);
              return { assistant_count: assistants.length, text, stop_visible: stopVisible, composer_ready: Boolean(composer) };
            })()
            """,
            "read ChatGPT answer state",
            timeout=10.0,
        )
        if isinstance(state, dict) and int(state.get("assistant_count") or 0) > 0:
            saw_assistant = True
            text = normalize_text(state.get("text") or "")
            stable_rounds = stable_rounds + 1 if text and text == last_text else 0
            last_text = text
            if stable_rounds >= 4 and not state.get("stop_visible") and state.get("composer_ready"):
                return
        time.sleep(1.0)
    if saw_assistant:
        raise RuntimeError(f"answer did not finish before timeout: {timeout_seconds}s")
    raise RuntimeError(f"answer did not start before timeout: {timeout_seconds}s")
```

- [ ] **Step 7: Run helper contract tests**

Run:

```bash
python3 -m unittest tests.test_chatgpt_workflow.ChatGptBrowserHelperContractTests -v
```

Expected: all tests in `ChatGptBrowserHelperContractTests` pass.

- [ ] **Step 8: Commit Task 3**

```bash
git add scripts/chatgpt_workflow.py tests/test_chatgpt_workflow.py
git commit -m "Add ChatGPT ask browser helpers"
```

---

### Task 4: Ask And Batch-Ask Orchestration

**Files:**
- Modify: `scripts/chatgpt_workflow.py`
- Modify: `tests/test_chatgpt_workflow.py`

**Interfaces:**
- Consumes: Task 1 and Task 3 interfaces
- Produces: `ask_one_task(book: ActionBook, task: ChatGptTask, index: int, output_dir: Path, answer_timeout: int) -> dict[str, Any]`
- Produces fully implemented `run_ask(args: argparse.Namespace) -> int`
- Produces fully implemented `run_batch_ask(args: argparse.Namespace) -> int`

- [ ] **Step 1: Add failing pure orchestration tests for failure summary shape**

Append:

```python
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
```

- [ ] **Step 2: Run failure test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_chatgpt_workflow.ChatGptFailureRecordTests -v
```

Expected: failure for missing `failure_record`.

- [ ] **Step 3: Add failure record helper**

Add below `write_task_markdown`:

```python
def failure_record(index: int, task: ChatGptTask, url: str, exc: Exception) -> dict[str, Any]:
    return {
        "index": index,
        "title": task.title,
        "question": task.question,
        "url": url,
        "error": str(exc),
        "failed_at": datetime.now().isoformat(timespec="seconds"),
    }
```

- [ ] **Step 4: Implement single task orchestration**

Replace the temporary `run_ask` body from Task 2 and add `ask_one_task`:

```python
def ask_one_task(
    book: ActionBook,
    task: ChatGptTask,
    index: int,
    output_dir: Path,
    answer_timeout: int,
) -> dict[str, Any]:
    started_at = datetime.now().isoformat(timespec="seconds")
    create_new_chat(book)
    enable_web_search(book)
    select_intelligent_mode(book)
    select_pro_extension(book)
    submit_prompt(book, task.question)
    wait_for_answer_complete(book, answer_timeout)
    scroll_state = go_to_conversation_bottom(book)
    if not scroll_state.get("ok"):
        raise RuntimeError(f"failed to scroll conversation to bottom: {scroll_state}")
    clipboard_sentinel = f"__chatgpt_ask_sentinel_{datetime.now().timestamp()}_{index}__"
    write_system_clipboard(clipboard_sentinel)
    result = locate_latest_assistant_copy_button(book)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "copy response button not found"))
    book.browser("click", f"{int(result['x'])},{int(result['y'])}", timeout=10.0)
    time.sleep(0.5)
    system_clipboard = read_system_clipboard()
    if not system_clipboard or system_clipboard == clipboard_sentinel:
        raise RuntimeError("copy clicked but system clipboard did not change")
    completed_at = datetime.now().isoformat(timespec="seconds")
    result["text"] = system_clipboard
    result["used_system_clipboard"] = True
    result["clicked_copy"] = True
    current_url = str(book.browser("url", timeout=10.0) or "")
    path = write_task_markdown(output_dir, index, task, result, current_url, started_at, completed_at)
    return {
        "index": index,
        "title": task.title,
        "question": task.question,
        "url": current_url,
        "file": str(path),
        "clicked_copy": True,
        "used_system_clipboard": True,
        "text_length": len(system_clipboard),
        "started_at": started_at,
        "completed_at": completed_at,
    }


def run_ask(args: argparse.Namespace) -> int:
    install_interrupt_handlers()
    task = parse_task_record({"title": args.title, "question": args.question}, "ask")
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_run_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    book = start_book(args)
    ensure_chatgpt_ready(book)
    summary: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    try:
        summary.append(ask_one_task(book, task, 1, output_dir, int(args.answer_timeout)))
    except Exception as exc:  # noqa: BLE001
        current_url = ""
        try:
            current_url = str(book.browser("url", timeout=10.0) or "")
        except Exception:
            current_url = ""
        failures.append(failure_record(1, task, current_url, exc))
        log(f"失败 1: {exc}")
    write_json(output_dir / "summary.json", summary)
    write_json(output_dir / "failures.json", failures)
    log(f"完成: 成功 {len(summary)}，失败 {len(failures)}，输出 {output_dir}")
    return 0 if not failures else 1
```

- [ ] **Step 5: Implement batch orchestration**

Replace the temporary `run_batch_ask` body from Task 2:

```python
def run_batch_ask(args: argparse.Namespace) -> int:
    install_interrupt_handlers()
    tasks = load_tasks_file(Path(args.tasks_file))
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_run_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    book = start_book(args)
    ensure_chatgpt_ready(book)
    summary: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, task in enumerate(tasks, start=1):
        log(f"提问 {index}/{len(tasks)}: {task.title}")
        try:
            summary.append(ask_one_task(book, task, index, output_dir, int(args.answer_timeout)))
        except Exception as exc:  # noqa: BLE001
            current_url = ""
            try:
                current_url = str(book.browser("url", timeout=10.0) or "")
            except Exception:
                current_url = ""
            failures.append(failure_record(index, task, current_url, exc))
            log(f"失败 {index}: {exc}")
        time.sleep(max(0.2, float(args.delay)))
    write_json(output_dir / "summary.json", summary)
    write_json(output_dir / "failures.json", failures)
    log(f"完成: 成功 {len(summary)}，失败 {len(failures)}，输出 {output_dir}")
    return 0 if not failures else 1
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
python3 -m unittest tests.test_chatgpt_workflow -v
```

Expected: all ChatGPT tests pass.

- [ ] **Step 7: Run script help commands**

Run:

```bash
python3 scripts/chatgpt_workflow.py --help
python3 scripts/chatgpt_workflow.py ask --help
python3 scripts/chatgpt_workflow.py batch-ask --help
python3 scripts/chatgpt_workflow.py export --help
```

Expected: each command exits 0 and shows its expected arguments.

- [ ] **Step 8: Commit Task 4**

```bash
git add scripts/chatgpt_workflow.py tests/test_chatgpt_workflow.py
git commit -m "Implement ChatGPT ask orchestration"
```

---

### Task 5: Documentation And Real Browser Verification

**Files:**
- Modify: `references/chatgpt.md`
- Modify: `scripts/chatgpt_workflow.py` only if real-browser verification exposes selector fixes

**Interfaces:**
- Consumes: all previous task interfaces
- Produces: updated user-facing command reference and verified output evidence

- [ ] **Step 1: Update ChatGPT reference documentation**

Replace the command section in `references/chatgpt.md` with:

```markdown
## Commands

Ask one question and export the latest assistant answer:

```bash
python3 scripts/chatgpt_workflow.py ask \
  --title "Q13：示例问题" \
  --question "这里是问题正文"
```

Ask many questions from JSONL or JSON:

```bash
python3 scripts/chatgpt_workflow.py batch-ask \
  --tasks-file /path/to/tasks.jsonl
```

Preview matching existing conversations:

```bash
python3 scripts/chatgpt_workflow.py list --limit 20
```

Export latest matching existing conversations:

```bash
python3 scripts/chatgpt_workflow.py export --limit 20
```
```

Also update the failure handling text to say:

```markdown
Final answer extraction does not use DOM text fallback. The workflow clicks
ChatGPT's `复制回复` / `Copy response` button and requires the macOS system
clipboard to change from a sentinel value before writing Markdown.
```

- [ ] **Step 2: Run full unit tests**

Run:

```bash
python3 -m unittest discover tests -v
```

Expected: all tests pass.

- [ ] **Step 3: Run single ask in real ChatGPT UI**

Run:

```bash
python3 scripts/chatgpt_workflow.py ask \
  --title "Q-test：ActionBook 单次提问验证" \
  --question "请用一句话回答：今天这个自动化测试是否成功收到问题？" \
  --output-dir /Users/Vint/Repos/00_Tasks/01_DailyMission/assets/chatgpt-ask-test/single
```

Expected:

- command exits 0,
- `summary.json` has one record,
- `failures.json` is `[]`,
- one Markdown file exists,
- Markdown body begins with assistant answer content, not the prompt.

- [ ] **Step 4: Run batch ask in real ChatGPT UI**

Create `/Users/Vint/Repos/00_Tasks/01_DailyMission/assets/chatgpt-ask-test/tasks.jsonl` with:

```json
{"title":"Q-test-batch-1：ActionBook 批量验证一","question":"请用一句话回答：这是批量测试的第一条吗？"}
{"title":"Q-test-batch-2：ActionBook 批量验证二","question":"请用一句话回答：这是批量测试的第二条吗？"}
```

Run:

```bash
python3 scripts/chatgpt_workflow.py batch-ask \
  --tasks-file /Users/Vint/Repos/00_Tasks/01_DailyMission/assets/chatgpt-ask-test/tasks.jsonl \
  --output-dir /Users/Vint/Repos/00_Tasks/01_DailyMission/assets/chatgpt-ask-test/batch
```

Expected:

- command exits 0,
- `summary.json` has two records,
- `failures.json` is `[]`,
- two Markdown files exist,
- both summary records have `clicked_copy: true` and `used_system_clipboard: true`.

- [ ] **Step 5: Verify existing export still works**

Run:

```bash
python3 scripts/chatgpt_workflow.py export \
  --limit 1 \
  --max-scrolls 5 \
  --output-dir /Users/Vint/Repos/00_Tasks/01_DailyMission/assets/chatgpt-ask-test/export
```

Expected:

- command exits 0,
- `summary.json` has one record,
- `failures.json` is `[]`,
- one Markdown file exists,
- summary record has `clicked_copy: true` and `used_system_clipboard: true`.

- [ ] **Step 6: Commit Task 5**

```bash
git add references/chatgpt.md scripts/chatgpt_workflow.py tests/test_chatgpt_workflow.py
git commit -m "Document and verify ChatGPT ask workflow"
```

---

## Final Verification

- [ ] Run all unit tests:

```bash
python3 -m unittest discover tests -v
```

Expected: all tests pass.

- [ ] Run help checks:

```bash
python3 scripts/chatgpt_workflow.py --help
python3 scripts/chatgpt_workflow.py ask --help
python3 scripts/chatgpt_workflow.py batch-ask --help
python3 scripts/chatgpt_workflow.py list --help
python3 scripts/chatgpt_workflow.py export --help
```

Expected: all commands exit 0.

- [ ] Confirm real-browser evidence exists:

```bash
find /Users/Vint/Repos/00_Tasks/01_DailyMission/assets/chatgpt-ask-test -maxdepth 3 -type f | sort
```

Expected: single ask, batch ask, and export output directories each contain Markdown, `summary.json`, and `failures.json`.

- [ ] Confirm git status is clean after final commit:

```bash
git status --short
```

Expected: no output.

## Self-Review Notes

- Spec coverage: Tasks 1-2 cover data model, input files, CLI, and output. Task 3 covers browser UI controls and waiting. Task 4 covers ask/batch orchestration and failure behavior. Task 5 covers documentation and real UI verification. Final verification covers tests, help, real output evidence, and clean git state.
- Placeholder scan: this plan contains no incomplete future-work markers or unnamed future steps. Each task has exact files, function names, commands, and expected results.
- Type consistency: `ChatGptTask`, `parse_task_record`, `load_tasks_file`, `write_task_markdown`, `ask_one_task`, `run_ask`, and `run_batch_ask` are introduced once and reused with the same signatures throughout.
