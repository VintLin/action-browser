from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
from typing import Any, Iterator
from urllib.parse import urlparse

from scripts.actionbook_session import ActionBookSession, close_and_verify_tab, require_owned_task_tab, tab_mutation_lock
from scripts.script_common import unwrap_eval


TRANSIENT_EVAL_ERRORS = (
    "Execution context was destroyed",
    "Cannot find context with specified id",
    "Detached",
    "Target closed",
)


def add_workflow_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--task-id", default=os.environ.get("ACTIONBOOK_TASK_ID", ""), help="Stable task id that owns the browser tab")
    parser.add_argument("--session", default=os.environ.get("ACTIONBOOK_SESSION_ID", ""), help="Session id returned by acquire-tab")
    parser.add_argument("--tab", default=os.environ.get("ACTIONBOOK_TAB_ID", ""), help="Owned tab id returned by acquire-tab")


def attach_workflow(
    args: argparse.Namespace,
    expected_url: str = "",
    action_book_cls: type[ActionBookSession] = ActionBookSession,
) -> ActionBookSession:
    required = {
        "--task-id": getattr(args, "task_id", ""),
        "--session": getattr(args, "session", ""),
        "--tab": getattr(args, "tab", ""),
    }
    missing = [name for name, value in required.items() if not str(value or "").strip()]
    if missing:
        raise ValueError(f"workflow browser commands require {', '.join(missing)} from acquire-tab")
    require_owned_task_tab(str(args.task_id), str(args.session), str(args.tab))
    book = action_book_cls(args.session, args.tab, allow_adopt=False)
    state = book.use_tab(args.tab)
    current_url = str(state.get("url") or "") if isinstance(state, dict) else ""
    if expected_url and _origin(current_url) != _origin(expected_url):
        book.goto(expected_url)
    return book


def evaluate(
    book: Any,
    script: str,
    label: str,
    timeout: float = 45.0,
    *,
    retries: int = 2,
    retry_delay: float = 0.4,
) -> Any:
    for attempt in range(retries + 1):
        try:
            value = unwrap_eval(book.eval(script, timeout=timeout))
            if isinstance(value, dict) and value.get("error"):
                raise RuntimeError(str(value.get("error")))
            return value
        except Exception as exc:
            if attempt >= retries or not any(term in str(exc) for term in TRANSIENT_EVAL_ERRORS):
                raise RuntimeError(f"{label}: {exc}") from exc
            time.sleep(retry_delay)
    raise AssertionError("unreachable")


def wait_until_stable(
    book: Any,
    *,
    timeout_secs: float = 3.0,
    interval: float = 0.4,
    require_stable: bool = False,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_secs
    previous = ""
    stable_rounds = 0
    last_state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        state = evaluate(
            book,
            """(() => ({
                href: location.href,
                title: document.title || '',
                text_length: (document.body?.innerText || '').length,
                height: document.body?.scrollHeight || 0,
            }))()""",
            "read page state",
            timeout=10.0,
        )
        if isinstance(state, dict):
            last_state = state
            signature = "|".join(str(state.get(key) or "") for key in ("href", "title", "text_length", "height"))
            stable_rounds = stable_rounds + 1 if signature == previous else 0
            previous = signature
            if stable_rounds >= 2:
                return state
        time.sleep(interval)
    if require_stable:
        raise RuntimeError(f"page did not settle within {timeout_secs}s: {last_state}")
    return last_state


@contextmanager
def temporary_tab(book: Any, url: str) -> Iterator[str]:
    with tab_mutation_lock():
        tab_id = book.open_new_tab(url)
    try:
        yield tab_id
    except BaseException as primary_error:
        try:
            close_and_verify_tab(book, tab_id)
        except Exception as cleanup_error:
            primary_error.add_note(f"temporary tab cleanup failed: {cleanup_error}")
        raise
    else:
        close_and_verify_tab(book, tab_id)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as output:
        output.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        output.flush()
        os.fsync(output.fileno())
    tmp.replace(path)


def _origin(value: str) -> str:
    parsed = urlparse(value)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
