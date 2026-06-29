from __future__ import annotations

import argparse
import time
from typing import Any

from scripts.actionbook_session import ActionBookSession


def unwrap_eval(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def prepare_task_book(
    args: argparse.Namespace,
    url: str,
    action_book_cls: type[ActionBookSession] = ActionBookSession,
) -> ActionBookSession:
    book = action_book_cls(args.session, args.tab, allow_adopt=False)
    if args.tab:
        book.use_tab(args.tab)
        return book
    book.start(url, force_new_tab=True)
    if book.tab:
        args.tab = book.tab
    return book


def wait_for_page_settle(book: Any, timeout_secs: float = 3.0, interval: float = 0.4) -> None:
    deadline = time.time() + timeout_secs
    previous = ""
    stable_rounds = 0
    while time.time() < deadline:
        state = unwrap_eval(book.eval(
            """(() => ({
                href: location.href,
                title: document.title || '',
                text_length: (document.body?.innerText || '').length,
                height: document.body?.scrollHeight || 0,
            }))()""",
            timeout=10.0,
        ))
        if isinstance(state, dict):
            signature = "|".join(str(state.get(key) or "") for key in ("href", "title", "text_length", "height"))
            stable_rounds = stable_rounds + 1 if signature == previous else 0
            previous = signature
            if stable_rounds >= 2:
                return
        time.sleep(interval)


def close_temporary_tab(book: Any, tab_id: str) -> None:
    book.close_tab(tab_id)
    remaining = {
        str(tab.get("tab_id") or "").strip()
        for tab in book.list_tabs()
        if isinstance(tab, dict)
    }
    if tab_id in remaining:
        raise RuntimeError(f"tab still open after close-tab: {tab_id}")
