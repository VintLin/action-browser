#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ChatGPT workflow helper for the action-browser skill.

The workflow uses ActionBook extension mode and the user's Chrome session to
export recent conversations whose sidebar title matches a regex or chosen
prefix. For each conversation, it scrolls to the bottom, clicks the latest
assistant message copy button when available, reads the copied Markdown, and
writes local Markdown files.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

CURRENT_SCRIPT_DIR = Path(__file__).resolve().parent
if str(CURRENT_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_SCRIPT_DIR))

from actionbook_interrupts import install_interrupt_handlers
from actionbook_session import ActionBookSession as ActionBook


CHATGPT_URL = "https://chatgpt.com/"
DEFAULT_SESSION = "chatgpt-qx"
DEFAULT_TAB = ""
DEFAULT_PREFIXES = ""
DEFAULT_TITLE_PATTERN = r"^Q\d+[：:]"
SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_DIR / "assets" / "chatgpt"


@dataclass(frozen=True)
class ChatGptTask:
    title: str
    question: str
    output_name: str = ""


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def sanitize_name(value: str, fallback: str = "conversation", max_length: int = 90) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value or "").strip("._-")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return (cleaned or fallback)[:max_length]


def normalize_text(value: Any) -> str:
    text = str(value or "").replace("\u00a0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def unwrap_eval(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def api_eval(book: ActionBook, script: str, label: str, timeout: float = 45.0) -> Any:
    value = unwrap_eval(book.eval(script, timeout=timeout))
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(f"{label}: {value.get('error')}")
    return value


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def default_output_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ASSETS_DIR / "exports" / "qx" / stamp


def default_run_output_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ASSETS_DIR / "runs" / stamp


def parse_prefixes(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


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


def frontmatter_string(data: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {json.dumps(str(item), ensure_ascii=False)}")
        else:
            lines.append(f"{key}: {json.dumps(str(value), ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


def start_book(args: argparse.Namespace, url: str = CHATGPT_URL) -> ActionBook:
    book = ActionBook(args.session, args.tab)
    book.start(url)
    return book


def get_page_state(book: ActionBook) -> dict[str, str]:
    value = api_eval(
        book,
        """
        (() => ({
          href: location.href,
          title: document.title || '',
          text: (document.body?.innerText || '').slice(0, 1600)
        }))()
        """,
        "chatgpt page state",
        timeout=10.0,
    )
    return value if isinstance(value, dict) else {}


def page_has_login_or_risk(state: dict[str, str]) -> bool:
    haystack = "\n".join(str(state.get(key) or "") for key in ("href", "title", "text"))
    if re.search(r"captcha|cloudflare|verify|verification|unusual activity|验证码|验证|异常活动", haystack, re.I):
        return True
    if re.search(r"login|sign in|log in", haystack, re.I):
        return True
    return bool(re.search(r"登录|登入", haystack) and "退出登录" not in haystack)


def ensure_chatgpt_ready(book: ActionBook) -> None:
    state = get_page_state(book)
    if page_has_login_or_risk(state):
        raise RuntimeError(
            f"ChatGPT requires login or verification: {state.get('href')} title={state.get('title')}"
        )


def collect_conversations(
    book: ActionBook,
    prefixes: list[str],
    title_pattern: str,
    limit: int,
    max_scrolls: int,
) -> list[dict[str, str]]:
    prefixes_json = json.dumps(prefixes, ensure_ascii=False)
    pattern_json = json.dumps(title_pattern, ensure_ascii=False)
    script = f"""
    (async () => {{
      const prefixes = {prefixes_json};
      const titlePattern = {pattern_json};
      const titleRegex = titlePattern ? new RegExp(titlePattern) : null;
      const limit = {int(limit)};
      const maxScrolls = {int(max_scrolls)};
      const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
      const normalize = value => String(value || '')
        .replace(/\\u00a0/g, ' ')
        .replace(/\\s+/g, ' ')
        .trim();
      const absUrl = value => {{
        try {{ return new URL(value, location.origin).toString(); }}
        catch (error) {{ return String(value || ''); }}
      }};
      const isMatch = title => (
        (titleRegex && titleRegex.test(title))
        || prefixes.some(prefix => title.startsWith(prefix))
      );
      const readLinks = () => {{
        const out = [];
        for (const anchor of document.querySelectorAll('a[href*="/c/"]')) {{
          const title = normalize(anchor.innerText || anchor.textContent || anchor.getAttribute('aria-label') || '');
          const href = absUrl(anchor.getAttribute('href'));
          if (!title || !href || !isMatch(title)) continue;
          out.push({{ title, url: href }});
        }}
        return out;
      }};
      const findScrollRoot = () => {{
        const candidates = [
          ...document.querySelectorAll('nav, aside, [data-testid*="sidebar"], div')
        ].filter(node => {{
          const style = getComputedStyle(node);
          return node.scrollHeight > node.clientHeight + 40
            && style.overflowY !== 'hidden'
            && node.querySelector('a[href*="/c/"]');
        }});
        return candidates.sort((a, b) => b.scrollHeight - a.scrollHeight)[0]
          || document.scrollingElement
          || document.documentElement;
      }};
      const seen = new Map();
      const root = findScrollRoot();
      for (let index = 0; index <= maxScrolls; index += 1) {{
        for (const item of readLinks()) {{
          if (!seen.has(item.url)) seen.set(item.url, item);
          if (seen.size >= limit) break;
        }}
        if (seen.size >= limit) break;
        const before = root.scrollTop;
        root.scrollTop = root.scrollTop + Math.max(420, Math.floor(root.clientHeight * 0.85));
        await sleep(450);
        if (root.scrollTop === before && index > 1) break;
      }}
      return Array.from(seen.values()).slice(0, limit).map((item, index) => ({{
        ...item,
        rank: index + 1
      }}));
    }})()
    """
    value = api_eval(book, script, "collect ChatGPT conversations", timeout=60.0)
    return value if isinstance(value, list) else []


def goto_conversation(book: ActionBook, url: str) -> None:
    book.goto(url)
    api_eval(
        book,
        """
        (async () => {
          const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
          for (let i = 0; i < 80; i += 1) {
            if (document.querySelector('[data-message-author-role="assistant"], article, .markdown')) {
              return true;
            }
            await sleep(250);
          }
          return false;
        })()
        """,
        "wait ChatGPT conversation",
        timeout=25.0,
    )


def read_system_clipboard() -> str:
    result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=10.0)
    if result.returncode != 0:
        return ""
    return normalize_text(result.stdout)


def write_system_clipboard(value: str) -> None:
    subprocess.run(["pbcopy"], input=value, text=True, timeout=10.0, check=True)


def scroll_conversation_to_bottom(book: ActionBook) -> dict[str, Any]:
    script = r"""
    (async () => {
      const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
      const getRoots = () => {
        const roots = new Set([document.scrollingElement, document.documentElement, document.body]);
        for (const node of document.querySelectorAll('main, [role="main"], div')) {
          if (!node) continue;
          const style = getComputedStyle(node);
          if (
            node.scrollHeight > node.clientHeight + 80
            && style.overflowY !== 'hidden'
            && style.display !== 'none'
            && style.visibility !== 'hidden'
          ) {
            roots.add(node);
          }
        }
        return [...roots].filter(Boolean);
      };
      let stableRounds = 0;
      let previousSignature = '';
      for (let round = 0; round < 80; round += 1) {
        const roots = getRoots();
        for (const root of roots) {
          root.scrollTop = root.scrollHeight;
        }
        window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' });
        await sleep(220);
        const signature = roots
          .map(root => `${Math.round(root.scrollTop)}:${Math.round(root.scrollHeight)}:${Math.round(root.clientHeight)}`)
          .join('|');
        stableRounds = signature === previousSignature ? stableRounds + 1 : 0;
        previousSignature = signature;
        if (stableRounds >= 4) {
          return { ok: true, rounds: round + 1, roots: roots.length, signature };
        }
      }
      return { ok: false, rounds: 80, roots: getRoots().length, signature: previousSignature };
    })()
    """
    value = api_eval(book, script, "scroll ChatGPT conversation to bottom", timeout=35.0)
    return value if isinstance(value, dict) else {"ok": False, "error": "Malformed scroll result"}


def locate_scroll_to_bottom_button(book: ActionBook) -> dict[str, Any]:
    script = r"""
    (() => {
      const visible = node => {
        if (!node) return false;
        const rect = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
      };
      const buttonScore = node => {
        const label = [
          node.getAttribute('aria-label'),
          node.getAttribute('title'),
          node.getAttribute('data-testid'),
          node.innerText,
          node.textContent
        ].map(value => String(value || '').trim()).join('\n');
        const lower = label.toLowerCase();
        if (/scroll.*bottom|jump.*bottom|go.*bottom|向下|到底|底部/.test(lower)) return 100;
        const svgText = [...node.querySelectorAll('svg, path')]
          .map(child => [
            child.getAttribute('class'),
            child.getAttribute('data-testid'),
            child.getAttribute('d')
          ].join(' '))
          .join(' ');
        const rect = node.getBoundingClientRect();
        const nearBottomCenter = rect.top > window.innerHeight * 0.45
          && rect.left > window.innerWidth * 0.35
          && rect.left < window.innerWidth * 0.75;
        if (!label.trim() && nearBottomCenter && /down|chevron|arrow|m19|v|l/i.test(svgText)) return 50;
        return 0;
      };
      const candidates = [...document.querySelectorAll('button, [role="button"]')]
        .filter(visible)
        .map(node => ({ node, score: buttonScore(node) }))
        .filter(item => item.score > 0)
        .sort((a, b) => b.score - a.score);
      const item = candidates[0];
      if (!item) return { ok: false, error: 'scroll-to-bottom button not found' };
      const rect = item.node.getBoundingClientRect();
      return {
        ok: true,
        x: Math.round(rect.left + rect.width / 2),
        y: Math.round(rect.top + rect.height / 2),
        score: item.score,
        label: [
          item.node.getAttribute('aria-label'),
          item.node.getAttribute('title'),
          item.node.innerText,
          item.node.textContent
        ].filter(Boolean).join(' | ')
      };
    })()
    """
    value = api_eval(book, script, "locate ChatGPT scroll-to-bottom button", timeout=10.0)
    return value if isinstance(value, dict) else {"ok": False, "error": "Malformed bottom button result"}


def go_to_conversation_bottom(book: ActionBook) -> dict[str, Any]:
    button = locate_scroll_to_bottom_button(book)
    if button.get("ok"):
        book.browser("click", f"{int(button['x'])},{int(button['y'])}", timeout=10.0)
        time.sleep(1.0)
        scroll_state = scroll_conversation_to_bottom(book)
        scroll_state["used_bottom_button"] = True
        scroll_state["bottom_button"] = button
        return scroll_state
    scroll_state = scroll_conversation_to_bottom(book)
    scroll_state["used_bottom_button"] = False
    scroll_state["bottom_button"] = button
    return scroll_state


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
    click_visible_control(book, "new chat", NEW_CHAT_CONTROL_JS)
    time.sleep(1.0)
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
          const text = document.body?.innerText || '';
          const composer = [...document.querySelectorAll('[contenteditable="true"], textarea, [data-testid="composer"]')]
            .find(visible);
          return {
            ok: Boolean(composer),
            href: location.href,
            has_empty_chat_text: /有什么可以帮忙|message chatgpt|ask anything|准备好开始了吗/i.test(text)
          };
        })()
        """,
        "wait new ChatGPT chat",
        timeout=10.0,
    )
    if not isinstance(state, dict) or not state.get("ok"):
        raise RuntimeError(f"new chat did not become ready: {state}")
    api_eval(
        book,
        """
        (() => {
          const candidates = [...document.querySelectorAll('[contenteditable="true"], textarea')]
            .filter(node => {
              const rect = node.getBoundingClientRect();
              const style = getComputedStyle(node);
              return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            });
          const composer = candidates[candidates.length - 1];
          if (!composer) return { ok: false, error: 'composer not found' };
          composer.focus();
          if (composer.tagName === 'TEXTAREA') {
            composer.value = '';
            composer.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward' }));
          } else {
            document.execCommand('selectAll', false);
            document.execCommand('delete', false);
          }
          return { ok: true };
        })()
        """,
        "clear ChatGPT composer",
        timeout=10.0,
    )


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
      const candidates = [...document.querySelectorAll('[role^="menuitem"], button, [role="button"]')]
        .filter(visible)
        .map(node => {{
          const text = [node.getAttribute('aria-label'), node.getAttribute('data-testid'), node.innerText, node.textContent]
            .map(value => String(value || '').trim()).join('\\n');
          const rect = node.getBoundingClientRect();
          const inMainPane = rect.left > Math.min(260, window.innerWidth * 0.25);
          const score = regex.test(text) && inMainPane ? 100 : 0;
          return {{ node, score, x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top + rect.height / 2), text }};
        }})
        .filter(item => item.score > 0)
        .sort((a, b) => b.score - a.score);
      const item = candidates[0];
      return item ? {{ ok: true, x: item.x, y: item.y, text: item.text, label: {json.dumps(label)} }} : {{ ok: false }};
    }})()
    """


def enable_web_search(book: ActionBook) -> None:
    state = api_eval(book, search_mode_state_js(), "check search mode state", timeout=10.0)
    if isinstance(state, dict) and state.get("search_enabled"):
        return
    last_result: Any = None
    for _attempt in range(2):
        click_visible_control(book, "composer plus", COMPOSER_PLUS_CONTROL_JS)
        time.sleep(0.5)
        result = api_eval(
            book,
            menu_item_control_js("网页搜索|web search|search", "web search"),
            "find web search",
            timeout=10.0,
        )
        last_result = result
        if isinstance(result, dict) and result.get("ok"):
            book.browser("click", f"{int(result['x'])},{int(result['y'])}", timeout=10.0)
            time.sleep(0.5)
            state = api_eval(book, search_mode_state_js(), "check search mode state", timeout=10.0)
            if isinstance(state, dict) and state.get("search_enabled"):
                return
    raise RuntimeError(f"web search control not found or did not enable: {last_result}")


def search_mode_state_js() -> str:
    return """
    (() => {
      const visible = node => {
        const rect = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
      };
      const controls = [...document.querySelectorAll('button, [role="button"], [role^="menuitem"]')]
        .filter(visible)
        .map(node => {
          const rect = node.getBoundingClientRect();
          const text = [
            node.getAttribute('aria-label'),
            node.getAttribute('data-testid'),
            node.innerText,
            node.textContent
          ].map(value => String(value || '').trim()).join('\\n');
          return {
            text,
            pressed: node.getAttribute('aria-pressed'),
            checked: node.getAttribute('aria-checked'),
            insideComposerArea: rect.top > window.innerHeight * 0.35
          };
        });
      const searchControl = controls.find(item => item.insideComposerArea && /网页搜索|搜索|web search|search/i.test(item.text));
      const intelligentControl = controls.find(item => /智能|intelligent/i.test(item.text));
      return {
        search_enabled: Boolean(searchControl),
        search_text: searchControl ? searchControl.text : '',
        intelligent_visible: Boolean(intelligentControl),
        intelligent_text: intelligentControl ? intelligentControl.text : ''
      };
    })()
    """


def select_intelligent_mode(book: ActionBook) -> dict[str, Any]:
    result = api_eval(book, menu_item_control_js("智能|intelligent", "intelligent mode"), "find intelligent mode", timeout=10.0)
    if isinstance(result, dict) and result.get("ok"):
        book.browser("click", f"{int(result['x'])},{int(result['y'])}", timeout=10.0)
        time.sleep(0.4)
        return {"selected": True, "fallback": False, "text": str(result.get("text") or "")}
    state = api_eval(book, search_mode_state_js(), "check search mode state", timeout=10.0)
    if isinstance(state, dict) and state.get("search_enabled"):
        return {
            "selected": False,
            "fallback": True,
            "text": str(state.get("search_text") or ""),
            "reason": "intelligent option not visible after web search was enabled",
        }
    raise RuntimeError(f"intelligent mode control not found: {result}")


def select_pro_extension(book: ActionBook) -> None:
    click_visible_control(book, "Pro extension", menu_item_control_js("Pro 扩展|Pro", "Pro extension"))


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


def wait_for_submission_started(book: ActionBook, timeout_seconds: int = 30) -> str:
    deadline = time.time() + timeout_seconds
    last_url = ""
    while time.time() < deadline:
        current_url = str(book.browser("url", timeout=10.0) or "")
        last_url = current_url
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
              const body = document.body?.innerText || '';
              const stopVisible = [...document.querySelectorAll('button')]
                .filter(visible)
                .some(node => /stop|停止|中止/i.test([node.getAttribute('aria-label'), node.innerText, node.textContent].join('\n')));
              const assistantStarted = [...document.querySelectorAll('[data-message-author-role="assistant"], article, .markdown')]
                .some(visible);
              const thinking = /正在思考|thinking|搜索|searching/i.test(body);
              return { stopVisible, assistantStarted, thinking };
            })()
            """,
            "read ChatGPT submission state",
            timeout=10.0,
        )
        if "/c/" in current_url and isinstance(state, dict) and (
            state.get("stopVisible") or state.get("assistantStarted") or state.get("thinking")
        ):
            return current_url
        time.sleep(0.5)
    raise RuntimeError(f"submission did not start before timeout: {timeout_seconds}s url={last_url}")


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


def locate_latest_assistant_copy_button(book: ActionBook) -> dict[str, Any]:
    script = r"""
    (async () => {
      const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
      const normalize = value => String(value || '')
        .replace(/\u00a0/g, ' ')
        .replace(/[ \t]+\n/g, '\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
      const visible = node => {
        if (!node) return false;
        const rect = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
      };
      const isCopyButton = node => {
        if (!node || !visible(node)) return false;
        const text = [
          node.getAttribute('aria-label'),
          node.getAttribute('title'),
          node.getAttribute('data-testid'),
          node.innerText,
          node.textContent
        ].map(value => String(value || '').toLowerCase()).join('\n');
        return /copy-turn-action-button|copy response|copy reply|复制回复/.test(text);
      };
      const messageCandidates = [
        ...document.querySelectorAll('[data-message-author-role="assistant"]')
      ].filter(visible);
      const fallbackCandidates = messageCandidates.length ? [] : [
        ...document.querySelectorAll('article, [class*="markdown"], .markdown')
      ].filter(node => visible(node) && normalize(node.innerText || node.textContent).length > 20);
      const messages = messageCandidates.length ? messageCandidates : fallbackCandidates;
      const latest = messages[messages.length - 1];
      if (!latest) return { ok: false, error: 'No assistant message found' };

      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' });
      latest.scrollIntoView({ block: 'end', inline: 'nearest' });
      latest.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
      latest.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
      await sleep(650);

      const containers = [];
      let current = latest;
      for (let depth = 0; current && depth < 8; depth += 1) {
        containers.push(current);
        current = current.parentElement;
      }
      const allButtons = [...document.querySelectorAll('button, [role="button"]')];
      let copyButton = null;
      for (const container of containers) {
        copyButton = [...container.querySelectorAll('button, [role="button"]')].find(isCopyButton);
        if (copyButton) break;
      }
      if (!copyButton) {
        const rect = latest.getBoundingClientRect();
        copyButton = allButtons
          .filter(isCopyButton)
          .map(button => {
            const r = button.getBoundingClientRect();
            return { button, distance: Math.abs(r.top - rect.bottom) + Math.abs(r.left - rect.left) };
          })
          .sort((a, b) => a.distance - b.distance)[0]?.button || null;
      }

      const domText = normalize(latest.innerText || latest.textContent || '');
      const markdownRoot = latest.querySelector('.markdown, [class*="markdown"]') || latest;
      const fallbackText = normalize(markdownRoot.innerText || markdownRoot.textContent || domText);
      if (!copyButton) {
        return {
          ok: false,
          error: 'No copy button found for latest assistant message',
          fallback_length: fallbackText.length,
          message_text_length: domText.length
        };
      }

      copyButton.scrollIntoView({ block: 'center', inline: 'nearest' });
      await sleep(250);
      const rect = copyButton.getBoundingClientRect();
      const latestRect = latest.getBoundingClientRect();
      return {
        ok: true,
        x: Math.round(rect.left + rect.width / 2),
        y: Math.round(rect.top + rect.height / 2),
        button_text: normalize(copyButton.innerText || copyButton.textContent || copyButton.getAttribute('aria-label') || ''),
        latest_top: Math.round(latestRect.top),
        latest_bottom: Math.round(latestRect.bottom),
        fallback_length: fallbackText.length,
        message_text_length: domText.length
      };
    })()
    """
    value = api_eval(book, script, "locate latest assistant copy button", timeout=45.0)
    if not isinstance(value, dict):
        return {"ok": False, "error": "Malformed copy button result"}
    return value


def write_markdown(output_dir: Path, index: int, item: dict[str, str], result: dict[str, Any]) -> Path:
    title = normalize_text(item.get("title") or f"conversation-{index}")
    filename = f"{index:03d}-{sanitize_name(title)}.md"
    path = output_dir / filename
    warnings: list[str] = []
    if not result.get("clicked_copy"):
        warnings.append("copy button not found or not clicked")
    metadata = {
        "title": title,
        "source_url": item.get("url") or "",
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "method": "system-clipboard",
        "clicked_copy": bool(result.get("clicked_copy")),
        "warnings": warnings,
    }
    content = normalize_text(result.get("text") or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter_string(metadata) + "\n\n" + content.rstrip() + "\n", encoding="utf-8")
    return path


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
        "mode": result.get("mode") or "intelligent",
        "mode_fallback": bool(result.get("mode_fallback")),
        "extension": "pro",
        "clicked_copy": bool(result.get("clicked_copy")),
    }
    content = normalize_text(result.get("text") or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter_string(metadata) + "\n\n" + content.rstrip() + "\n", encoding="utf-8")
    return path


def failure_record(index: int, task: ChatGptTask, url: str, exc: Exception) -> dict[str, Any]:
    return {
        "index": index,
        "title": task.title,
        "question": task.question,
        "url": url,
        "error": str(exc),
        "failed_at": datetime.now().isoformat(timespec="seconds"),
    }


def submission_record(
    index: int,
    task: ChatGptTask,
    url: str,
    attempts: int,
    submitted_at: str,
) -> dict[str, Any]:
    return {
        "index": index,
        "title": task.title,
        "question": task.question,
        "url": url,
        "status": "submitted",
        "mode": {
            "web_search": True,
            "extension": "pro",
        },
        "submitted_at": submitted_at,
        "attempts": attempts,
    }


def is_nonfatal_submit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    nonfatal_markers = [
        "send button not found",
        "web search control not found",
        "new chat did not become ready",
        "submission did not start before timeout",
        "composer not found",
        "pro extension control not found",
    ]
    return any(marker in text for marker in nonfatal_markers)


def is_fatal_submit_error(exc: Exception) -> bool:
    text = str(exc)
    if re.search(
        r"captcha|cloudflare|verify|verification|unusual activity|rate limit|restricted|login|sign in|log in|验证码|验证|异常活动|频率|限制|登录|登入|受限",
        text,
        re.I,
    ):
        return True
    return not is_nonfatal_submit_error(exc)


def write_submit_outputs(
    output_dir: Path,
    submissions: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> None:
    write_json(output_dir / "submissions.json", submissions)
    write_json(output_dir / "failures.json", failures)


def submit_one_task(
    book: ActionBook,
    task: ChatGptTask,
    index: int,
    attempts: int,
) -> dict[str, Any]:
    create_new_chat(book)
    enable_web_search(book)
    select_pro_extension(book)
    submit_prompt(book, task.question)
    current_url = wait_for_submission_started(book)
    submitted_at = datetime.now().isoformat(timespec="seconds")
    return submission_record(index, task, current_url, attempts, submitted_at)


def run_list(args: argparse.Namespace) -> int:
    book = start_book(args)
    ensure_chatgpt_ready(book)
    prefixes = parse_prefixes(args.prefix)
    conversations = collect_conversations(book, prefixes, args.title_pattern, args.limit, args.max_scrolls)
    print(json.dumps(conversations, ensure_ascii=False, indent=2))
    return 0


def run_export(args: argparse.Namespace) -> int:
    install_interrupt_handlers()
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_output_dir()
    book = start_book(args)
    ensure_chatgpt_ready(book)
    prefixes = parse_prefixes(args.prefix)
    conversations = collect_conversations(book, prefixes, args.title_pattern, args.limit, args.max_scrolls)
    if not conversations:
        raise RuntimeError(
            "No ChatGPT conversations found with "
            f"title_pattern={args.title_pattern!r} prefixes={', '.join(prefixes)}"
        )

    summary: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, item in enumerate(conversations, start=1):
        title = normalize_text(item.get("title") or "")
        url = str(item.get("url") or "")
        log(f"导出 {index}/{len(conversations)}: {title}")
        try:
            goto_conversation(book, url)
            scroll_state = go_to_conversation_bottom(book)
            if not scroll_state.get("ok"):
                raise RuntimeError(f"failed to scroll conversation to bottom: {scroll_state}")
            clipboard_sentinel = f"__chatgpt_qx_export_sentinel_{datetime.now().timestamp()}_{index}__"
            write_system_clipboard(clipboard_sentinel)
            result = locate_latest_assistant_copy_button(book)
            if not result.get("ok"):
                raise RuntimeError(str(result.get("error") or "copy button not found"))
            book.browser("click", f"{int(result['x'])},{int(result['y'])}", timeout=10.0)
            time.sleep(0.4)
            system_clipboard = read_system_clipboard()
            if system_clipboard and system_clipboard != clipboard_sentinel:
                result["text"] = system_clipboard
                result["used_system_clipboard"] = True
                result["clicked_copy"] = True
            elif not normalize_text(result.get("text") or ""):
                raise RuntimeError("copy clicked but system clipboard did not change")
            path = write_markdown(output_dir, index, item, result)
            summary.append(
                {
                    "index": index,
                    "title": title,
                    "url": url,
                    "file": str(path),
                    "clicked_copy": bool(result.get("clicked_copy")),
                    "used_system_clipboard": bool(result.get("used_system_clipboard")),
                    "text_length": len(str(result.get("text") or "")),
                }
            )
        except Exception as exc:  # noqa: BLE001
            failures.append({"index": index, "title": title, "url": url, "error": str(exc)})
            log(f"失败 {index}: {exc}")
        time.sleep(max(0.2, float(args.delay)))

    write_json(output_dir / "summary.json", summary)
    write_json(output_dir / "failures.json", failures)
    log(f"完成: 成功 {len(summary)}，失败 {len(failures)}，输出 {output_dir}")
    return 0 if not failures else 1


def run_ask(args: argparse.Namespace) -> int:
    install_interrupt_handlers()
    task = parse_task_record({"title": args.title, "question": args.question}, "ask")
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_run_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    book = start_book(args)
    ensure_chatgpt_ready(book)
    submissions: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    attempts = 0
    while attempts < 2 and not submissions:
        attempts += 1
        try:
            submissions.append(submit_one_task(book, task, 1, attempts))
        except Exception as exc:  # noqa: BLE001
            if attempts >= 2:
                current_url = ""
                try:
                    current_url = str(book.browser("url", timeout=10.0) or "")
                except Exception:
                    current_url = ""
                failure = failure_record(1, task, current_url, exc)
                failure["attempts"] = attempts
                failure["fatal"] = is_fatal_submit_error(exc)
                failures.append(failure)
                log(f"失败 1: {exc}")
    write_submit_outputs(output_dir, submissions, failures)
    log(f"完成: 提交 {len(submissions)}，失败 {len(failures)}，输出 {output_dir}")
    return 0 if not failures else 1


def run_batch_ask(args: argparse.Namespace) -> int:
    install_interrupt_handlers()
    tasks = load_tasks_file(Path(args.tasks_file))
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_run_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    book = start_book(args)
    ensure_chatgpt_ready(book)
    submissions: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    stop_batch = False
    for index, task in enumerate(tasks, start=1):
        if stop_batch:
            break
        log(f"提交 {index}/{len(tasks)}: {task.title}")
        submitted = False
        for attempts in range(1, 3):
            try:
                submissions.append(submit_one_task(book, task, index, attempts))
                submitted = True
                break
            except Exception as exc:  # noqa: BLE001
                if attempts < 2:
                    log(f"重试 {index}: {exc}")
                    continue
                current_url = ""
                try:
                    current_url = str(book.browser("url", timeout=10.0) or "")
                except Exception:
                    current_url = ""
                fatal = is_fatal_submit_error(exc)
                failure = failure_record(index, task, current_url, exc)
                failure["attempts"] = attempts
                failure["fatal"] = fatal
                failures.append(failure)
                log(f"失败 {index}: {exc}")
                if fatal:
                    stop_batch = True
        write_submit_outputs(output_dir, submissions, failures)
        if submitted:
            time.sleep(max(0.2, float(args.delay)))
    log(f"完成: 提交 {len(submissions)}，失败 {len(failures)}，输出 {output_dir}")
    return 0 if not failures else 1


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
    mode_state = select_intelligent_mode(book)
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
    result["mode"] = "intelligent"
    result["mode_fallback"] = bool(mode_state.get("fallback"))
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
        "mode": "intelligent",
        "mode_fallback": bool(mode_state.get("fallback")),
        "started_at": started_at,
        "completed_at": completed_at,
    }


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export latest ChatGPT QX conversations to Markdown.")
    parser.add_argument("--session", default=DEFAULT_SESSION, help="ActionBook session id")
    parser.add_argument("--tab", default=DEFAULT_TAB, help="ActionBook tab id; auto-detect when omitted")
    parser.add_argument("--prefix", default=DEFAULT_PREFIXES, help="Comma-separated title prefixes")
    parser.add_argument("--title-pattern", default=DEFAULT_TITLE_PATTERN, help="Regex for matching conversation titles")
    parser.add_argument("--limit", type=positive_int, default=20, help="Maximum conversations to export")
    parser.add_argument("--max-scrolls", type=positive_int, default=30, help="Sidebar scroll attempts")
    sub = parser.add_subparsers(dest="command", required=True)

    ask_parser = sub.add_parser("ask", help="Ask one ChatGPT question and export the latest answer")
    ask_parser.add_argument("--title", required=True, help="Task title for metadata and filename")
    ask_parser.add_argument("--question", required=True, help="Question text to send to ChatGPT")
    ask_parser.add_argument("--output-dir", default="", help="Output directory")
    ask_parser.add_argument("--answer-timeout", type=positive_int, default=900, help="Seconds to wait for answer completion")
    ask_parser.set_defaults(func=run_ask)

    batch_parser = sub.add_parser("batch-ask", help="Ask multiple ChatGPT questions from a JSON or JSONL task file")
    batch_parser.add_argument("--tasks-file", required=True, help="JSON or JSONL task file")
    batch_parser.add_argument("--output-dir", default="", help="Output directory")
    batch_parser.add_argument("--delay", type=float, default=60.0, help="Delay between tasks")
    batch_parser.add_argument("--answer-timeout", type=positive_int, default=900, help="Seconds to wait for answer completion")
    batch_parser.set_defaults(func=run_batch_ask)

    list_parser = sub.add_parser("list", help="List matching ChatGPT conversations")
    list_parser.add_argument("--prefix", dest="prefix_override", default="", help="Comma-separated title prefixes")
    list_parser.add_argument("--title-pattern", dest="title_pattern_override", default="", help="Regex for matching titles")
    list_parser.add_argument("--limit", dest="limit_override", type=positive_int, default=0, help="Maximum conversations")
    list_parser.add_argument("--max-scrolls", dest="max_scrolls_override", type=positive_int, default=0, help="Sidebar scroll attempts")
    list_parser.set_defaults(func=run_list)

    export_parser = sub.add_parser("export", help="Export matching ChatGPT conversations")
    export_parser.add_argument("--prefix", dest="prefix_override", default="", help="Comma-separated title prefixes")
    export_parser.add_argument("--title-pattern", dest="title_pattern_override", default="", help="Regex for matching titles")
    export_parser.add_argument("--limit", dest="limit_override", type=positive_int, default=0, help="Maximum conversations")
    export_parser.add_argument("--max-scrolls", dest="max_scrolls_override", type=positive_int, default=0, help="Sidebar scroll attempts")
    export_parser.add_argument("--output-dir", default="", help="Output directory")
    export_parser.add_argument("--delay", type=float, default=0.8, help="Delay between conversations")
    export_parser.set_defaults(func=run_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "prefix_override", ""):
        args.prefix = args.prefix_override
    if getattr(args, "title_pattern_override", ""):
        args.title_pattern = args.title_pattern_override
    if getattr(args, "limit_override", 0):
        args.limit = args.limit_override
    if getattr(args, "max_scrolls_override", 0):
        args.max_scrolls = args.max_scrolls_override
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
