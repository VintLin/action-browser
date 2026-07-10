from argparse import Namespace
import json
from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.adapters import x_workflow


@pytest.fixture(autouse=True)
def owned_tab_registry(tmp_path, monkeypatch) -> None:
    path = tmp_path / "task-tabs.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tasks": {
                    "task-a": {
                        "task_id": "task-a",
                        "session_id": "s1",
                        "tab_id": "leased-tab",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ACTION_BROWSER_TASK_TABS_FILE", str(path))


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
        "task_id": "task-a",
        "session": "s1",
        "tab": "leased-tab",
        "count": 5,
        "max_scrolls": 3,
        "output_dir": "",
    }
    values.update(overrides)
    return Namespace(**values)


def test_run_view_without_owned_tab_is_rejected(monkeypatch, tmp_path) -> None:
    FakeBook.instances = []
    monkeypatch.setattr(x_workflow, "ActionBook", FakeBook)
    monkeypatch.setattr(x_workflow, "wait_page_ready", lambda book, source: None)
    monkeypatch.setattr(x_workflow, "wait_for_visible_tweets", lambda book, source: None)
    monkeypatch.setattr(x_workflow, "collect_tweets", lambda book, source, count, max_scrolls: [])
    monkeypatch.setattr(x_workflow, "expand_show_more_payloads", lambda book, payloads: None)

    with pytest.raises(ValueError, match="require --tab"):
        x_workflow.run_view(base_args(tab="", output_dir=str(tmp_path)), "home", x_workflow.HOME_URL)


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
        ("use-tab", "leased-tab"),
        ("goto", "leased-tab:https://x.com/me"),
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


def test_show_more_detection_uses_explicit_control_not_link_ellipsis() -> None:
    payload = x_workflow.TweetPayload(
        tweet_id="1",
        source_url="https://x.com/user/status/1",
        source_page="bookmarks",
        author_name="",
        author_handle="",
        author_profile_url="",
        author_avatar_url="",
        text="Read https://example.com/article/\u2026",
        created_at_text="",
        created_at_iso="",
        tweet_type="tweet",
        reply_to={},
        quoted_tweet={},
        media=[],
        links=[],
        card={},
        article={},
        metrics={},
        social_context={},
        is_bookmarked=True,
        raw_text_lines=["Read", "https://example.com/article/", "\u2026"],
        extraction_warnings=[],
    )
    assert not x_workflow.needs_show_more_expansion(payload)

    payload.raw_text_lines.append("显示更多")
    assert x_workflow.needs_show_more_expansion(payload)
