from argparse import Namespace
from contextlib import contextmanager
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


def test_tweet_extractor_excludes_virtualized_offscreen_articles() -> None:
    assert "rect.bottom > 0 && rect.top < window.innerHeight" in x_workflow.EXTRACT_VISIBLE_TWEETS_JS
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


def test_show_more_expansion_clicks_and_rejects_unexpanded_payload(monkeypatch) -> None:
    payload = x_workflow.TweetPayload(
        tweet_id="1", source_url="https://x.com/user/status/1", source_page="home",
        author_name="A", author_handle="@a", author_profile_url="", author_avatar_url="",
        text="preview", created_at_text="", created_at_iso="", tweet_type="tweet",
        reply_to={}, quoted_tweet={}, media=[], links=[], card={}, article={}, metrics={}, social_context={},
        is_bookmarked=False, raw_text_lines=["preview", "显示更多"], extraction_warnings=[],
    )
    expanded = x_workflow.TweetPayload(
        **{**payload.__dict__, "text": "preview with the full final paragraph", "raw_text_lines": ["preview", "with the full final paragraph"]}
    )

    @contextmanager
    def fake_tab(_book, _url):
        yield "temporary"

    monkeypatch.setattr(x_workflow, "temporary_tab", fake_tab)
    monkeypatch.setattr(x_workflow, "wait_tab_articles", lambda *_args: None)
    monkeypatch.setattr(x_workflow, "click_show_more_for_payload", lambda *_args: True)
    monkeypatch.setattr(x_workflow, "wait_for_parent_expansion", lambda *_args: expanded)
    monkeypatch.setattr(x_workflow, "wait_for_expanded_payload", lambda *_args: expanded)

    x_workflow.expand_show_more_payloads(object(), [payload])

    assert payload.text.endswith("final paragraph")
    assert not x_workflow.needs_show_more_expansion(payload)


def test_show_more_expansion_returns_typed_failure_when_click_is_missing(monkeypatch) -> None:
    payload = x_workflow.TweetPayload(
        tweet_id="1", source_url="https://x.com/user/status/1", source_page="home",
        author_name="A", author_handle="@a", author_profile_url="", author_avatar_url="",
        text="preview", created_at_text="", created_at_iso="", tweet_type="tweet",
        reply_to={}, quoted_tweet={}, media=[], links=[], card={}, article={}, metrics={}, social_context={},
        is_bookmarked=False, raw_text_lines=["preview", "Show more"], extraction_warnings=[],
    )

    @contextmanager
    def fake_tab(_book, _url):
        yield "temporary"

    monkeypatch.setattr(x_workflow, "temporary_tab", fake_tab)
    monkeypatch.setattr(x_workflow, "wait_tab_articles", lambda *_args: None)
    monkeypatch.setattr(x_workflow, "click_show_more_for_payload", lambda *_args: False)

    with pytest.raises(x_workflow.ShowMoreExpansionError, match="selector_failed"):
        x_workflow.expand_show_more_payloads(object(), [payload])


def test_show_more_click_activates_the_observed_browser_control() -> None:
    payload = x_workflow.TweetPayload(
        tweet_id="2075342549351297525", source_url="https://x.com/dotey/status/2075342549351297525", source_page="home",
        author_name="A", author_handle="@a", author_profile_url="", author_avatar_url="",
        text="preview", created_at_text="", created_at_iso="", tweet_type="tweet",
        reply_to={}, quoted_tweet={}, media=[], links=[], card={}, article={}, metrics={}, social_context={},
        is_bookmarked=False, raw_text_lines=["preview", "显示更多"], extraction_warnings=[],
    )

    class Book:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[str, ...]]] = []

        def browser(self, command: str, *args: str, **_kwargs):
            self.calls.append((command, args))
            return True

    book = Book()

    assert x_workflow.click_show_more_for_payload(book, payload) == 1
    assert book.calls[1][0] == "eval"
    assert 'button[data-testid="tweet-text-show-more-link"]' in book.calls[1][1][0]
    assert "button.click()" in book.calls[1][1][0]


def test_show_more_expansion_falls_back_to_detail_when_parent_control_remains(monkeypatch) -> None:
    payload = x_workflow.TweetPayload(
        tweet_id="1", source_url="https://x.com/user/status/1", source_page="home",
        author_name="A", author_handle="@a", author_profile_url="", author_avatar_url="",
        text="preview", created_at_text="", created_at_iso="", tweet_type="tweet",
        reply_to={}, quoted_tweet={}, media=[], links=[], card={}, article={}, metrics={}, social_context={},
        is_bookmarked=False, raw_text_lines=["preview", "显示更多"], extraction_warnings=[],
    )
    expanded = x_workflow.TweetPayload(
        **{**payload.__dict__, "text": "preview with the full final paragraph", "raw_text_lines": ["preview", "with the full final paragraph"]}
    )

    @contextmanager
    def fake_tab(_book, _url):
        yield "temporary"

    monkeypatch.setattr(x_workflow, "temporary_tab", fake_tab)
    monkeypatch.setattr(x_workflow, "wait_tab_articles", lambda *_args: None)
    monkeypatch.setattr(x_workflow, "click_show_more_for_payload", lambda *_args: True)
    monkeypatch.setattr(x_workflow, "wait_for_parent_expansion", lambda *_args: payload)
    monkeypatch.setattr(x_workflow, "wait_for_expanded_payload", lambda *_args: expanded)

    x_workflow.expand_show_more_payloads(object(), [payload])

    assert payload.text.endswith("final paragraph")
    assert "parent_show_more_unsettled" in payload.extraction_warnings


def test_show_more_expansion_does_not_silently_keep_preview_after_limit() -> None:
    payload = x_workflow.TweetPayload(
        tweet_id="1", source_url="https://x.com/user/status/1", source_page="search",
        author_name="A", author_handle="@a", author_profile_url="", author_avatar_url="",
        text="preview", created_at_text="", created_at_iso="", tweet_type="tweet",
        reply_to={}, quoted_tweet={}, media=[], links=[], card={}, article={}, metrics={}, social_context={},
        is_bookmarked=False, raw_text_lines=["preview", "Show more"], extraction_warnings=[],
    )

    with pytest.raises(x_workflow.ShowMoreExpansionError, match="expansion limit reached"):
        x_workflow.expand_show_more_payloads(object(), [payload], max_expansions=0)


def test_write_summary_keeps_recovered_parent_warning_out_of_failures(tmp_path) -> None:
    payload = x_workflow.TweetPayload(
        tweet_id="1", source_url="https://x.com/user/status/1", source_page="search",
        author_name="A", author_handle="@a", author_profile_url="", author_avatar_url="",
        text="full text", created_at_text="", created_at_iso="", tweet_type="tweet",
        reply_to={}, quoted_tweet={}, media=[], links=[], card={}, article={}, metrics={}, social_context={},
        is_bookmarked=False, raw_text_lines=["full text"], extraction_warnings=["parent_show_more_unsettled"],
    )

    x_workflow.write_summary([payload], tmp_path, "search", "download")

    assert json.loads((tmp_path / "failures.json").read_text(encoding="utf-8")) == []
