from argparse import Namespace
from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.adapters import x_workflow


class FakeBook:
    instances: list["FakeBook"] = []

    def __init__(self, session: str, tab: str = "", allow_adopt: bool = True) -> None:
        self.session = session
        self.tab = tab
        self.allow_adopt = allow_adopt
        self.events: list[tuple[str, str]] = []
        self.tabs = [{"tab_id": tab or "main-tab", "url": "https://x.com/home", "title": "X"}]
        FakeBook.instances.append(self)

    def start(self, url: str, force_new_tab: bool = False) -> None:
        self.events.append(("start", f"{url}|force={force_new_tab}"))
        if force_new_tab:
            self.tab = "fresh-tab"
            self.tabs = [{"tab_id": "fresh-tab", "url": url, "title": "X"}]
        elif not self.tab:
            self.tab = "main-tab"

    def use_tab(self, tab_id: str) -> dict[str, str]:
        self.events.append(("use-tab", tab_id))
        self.tab = tab_id
        return {"session_id": self.session, "tab_id": tab_id, "url": "", "title": ""}

    def goto(self, url: str) -> None:
        self.events.append(("goto", f"{self.tab}:{url}"))

    def eval(self, script: str, timeout: float = 30.0):
        self.events.append(("eval", self.tab))
        return {}

    def browser(self, subcommand: str, *args: str, timeout: float = 30.0, tab: str | None = None):
        self.events.append((subcommand, tab or self.tab))
        return {}

    def close_tab(self, tab_id: str) -> dict[str, str]:
        self.events.append(("close-tab", tab_id))
        self.tabs = [tab for tab in self.tabs if tab.get("tab_id") != tab_id]
        return {"session_id": self.session, "tab_id": tab_id, "status": "closed"}

    def list_tabs(self) -> list[dict[str, str]]:
        self.events.append(("list-tabs", self.tab))
        return [dict(tab) for tab in self.tabs]


def base_args(**overrides):
    values = {
        "session": "s1",
        "tab": "",
        "count": 5,
        "max_scrolls": 3,
        "output_dir": "",
    }
    values.update(overrides)
    return Namespace(**values)


def test_run_view_without_tab_opens_fresh_task_tab(monkeypatch, tmp_path) -> None:
    FakeBook.instances = []
    monkeypatch.setattr(x_workflow, "ActionBook", FakeBook)
    monkeypatch.setattr(x_workflow, "wait_page_ready", lambda book, source: None)
    monkeypatch.setattr(x_workflow, "wait_for_visible_tweets", lambda book, source: None)
    monkeypatch.setattr(x_workflow, "collect_tweets", lambda book, source, count, max_scrolls: [])
    monkeypatch.setattr(x_workflow, "expand_show_more_payloads", lambda book, payloads: None)

    result = x_workflow.run_view(base_args(output_dir=str(tmp_path)), "home", x_workflow.HOME_URL)

    assert result == 0
    assert FakeBook.instances[0].events[:2] == [
        ("start", f"{x_workflow.HOME_URL}|force=True"),
        ("goto", f"fresh-tab:{x_workflow.HOME_URL}"),
    ]


def test_run_view_with_tab_uses_explicit_tab_without_start(monkeypatch, tmp_path) -> None:
    FakeBook.instances = []
    monkeypatch.setattr(x_workflow, "ActionBook", FakeBook)
    monkeypatch.setattr(x_workflow, "wait_page_ready", lambda book, source: None)
    monkeypatch.setattr(x_workflow, "wait_for_visible_tweets", lambda book, source: None)
    monkeypatch.setattr(x_workflow, "collect_tweets", lambda book, source, count, max_scrolls: [])
    monkeypatch.setattr(x_workflow, "expand_show_more_payloads", lambda book, payloads: None)

    result = x_workflow.run_view(base_args(tab="leased-tab", output_dir=str(tmp_path)), "home", x_workflow.HOME_URL)

    assert result == 0
    assert FakeBook.instances[0].events[:2] == [
        ("use-tab", "leased-tab"),
        ("goto", f"leased-tab:{x_workflow.HOME_URL}"),
    ]


def test_close_article_tab_uses_helper_and_verifies_absence() -> None:
    book = FakeBook("s1", "main-tab")
    book.tabs.append({"tab_id": "detail-tab", "url": "https://x.com/a/status/1", "title": "X"})

    x_workflow.close_article_tab(book, "detail-tab")

    assert ("close-tab", "detail-tab") in book.events
    assert ("list-tabs", "main-tab") in book.events
    assert all(tab.get("tab_id") != "detail-tab" for tab in book.tabs)


def test_close_article_tab_raises_when_tab_remains() -> None:
    class StickyBook(FakeBook):
        def close_tab(self, tab_id: str) -> dict[str, str]:
            self.events.append(("close-tab", tab_id))
            return {"session_id": self.session, "tab_id": tab_id, "status": "closed"}

    book = StickyBook("s1", "main-tab")
    book.tabs.append({"tab_id": "detail-tab", "url": "https://x.com/a/status/1", "title": "X"})

    with pytest.raises(RuntimeError, match="tab still open"):
        x_workflow.close_article_tab(book, "detail-tab")


def test_me_flow_reuses_profile_resolution_tab(monkeypatch, tmp_path) -> None:
    FakeBook.instances = []
    monkeypatch.setattr(x_workflow, "ActionBook", FakeBook)
    monkeypatch.setattr(x_workflow, "wait_page_ready", lambda book, source: None)
    monkeypatch.setattr(x_workflow, "wait_for_visible_tweets", lambda book, source: None)
    monkeypatch.setattr(x_workflow, "get_current_x_profile_url", lambda book: "https://x.com/me")
    monkeypatch.setattr(x_workflow, "collect_tweets", lambda book, source, count, max_scrolls: [])
    monkeypatch.setattr(x_workflow, "expand_show_more_payloads", lambda book, payloads: None)

    result = x_workflow.run_me_view(base_args(output_dir=str(tmp_path)))

    assert result == 0
    assert len(FakeBook.instances) == 2
    assert FakeBook.instances[1].events[:2] == [
        ("use-tab", "fresh-tab"),
        ("goto", "fresh-tab:https://x.com/me"),
    ]


def test_x_page_ready_state_requires_primary_content() -> None:
    assert not x_workflow.is_x_page_ready_state(
        {"href": "https://x.com/home", "body": "sidebar", "articles": 2, "primary_articles": 0}
    )

    assert x_workflow.is_x_page_ready_state(
        {"href": "https://x.com/home", "body": "post", "articles": 2, "primary_articles": 1}
    )


def test_x_page_ready_state_rejects_user_gates() -> None:
    assert not x_workflow.is_x_page_ready_state(
        {"href": "https://x.com/login", "body": "Log in", "articles": 1, "primary_articles": 1}
    )
    assert not x_workflow.is_x_page_ready_state(
        {"href": "https://x.com/account/access", "body": "Verify your account", "articles": 1, "primary_articles": 1}
    )
