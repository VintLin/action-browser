import json
from pathlib import Path
import sys

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.workflow_runtime import (
    evaluate,
    wait_until_stable,
    write_json,
)
from scripts.actionbook_errors import ActionBookFailure


class FakeBook:
    def __init__(self, session: str = "shared", tab: str = "owned") -> None:
        self.session = session
        self.tab = tab
        self.events: list[tuple[str, str]] = []
        self.tabs = {tab} if tab else set()
        self.states: list[object] = []

    def use_tab(self, tab_id: str) -> dict[str, str]:
        self.events.append(("use", tab_id))
        self.tab = tab_id
        return {"session_id": self.session, "tab_id": tab_id, "url": "https://old.example/page", "title": "Old"}

    def start(self, url: str, force_new_tab: bool = False) -> None:
        raise AssertionError("workflow runtime must not create tabs")

    def goto(self, url: str) -> None:
        self.events.append(("goto", url))

    def eval(self, script: str, timeout: float = 30.0):
        self.events.append(("eval", self.tab))
        value = self.states.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def open_new_tab(self, url: str) -> str:
        self.events.append(("open", url))
        self.tabs.add("temporary")
        return "temporary"

    def close_tab(self, tab_id: str) -> dict[str, str]:
        self.events.append(("close", tab_id))
        self.tabs.remove(tab_id)
        return {"status": "closed"}

    def list_tabs(self) -> list[dict[str, str]]:
        return [{"tab_id": tab_id} for tab_id in self.tabs]


def test_evaluate_retries_transient_context_loss() -> None:
    book = FakeBook("shared", "owned")
    book.states = [ActionBookFailure("EXECUTION_CONTEXT_DESTROYED", "context reset"), {"ok": True}]

    assert evaluate(book, "return true", "read page", retries=1, retry_delay=0) == {"ok": True}
    assert book.events == [("eval", "owned"), ("eval", "owned")]


def test_wait_until_stable_returns_state_and_allows_timeout() -> None:
    book = FakeBook("shared", "owned")
    stable = {"href": "https://example.com", "title": "A", "text_length": 2, "height": 10}
    book.states = [{**stable, "text_length": 1}, stable, stable, stable]
    assert wait_until_stable(book, timeout_secs=1, interval=0) == stable

    book.states = [{**stable, "text_length": value} for value in range(1000)]
    last_state = wait_until_stable(book, timeout_secs=0.002, interval=0.001)
    assert last_state["href"] == "https://example.com"

    with pytest.raises(RuntimeError, match="did not settle"):
        wait_until_stable(book, timeout_secs=0.002, interval=0.001, require_stable=True)


def test_write_json_is_atomic(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "result.json"
    write_json(output, {"ok": True})
    assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}
    assert not output.with_suffix(".json.tmp").exists()
