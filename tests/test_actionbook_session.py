from pathlib import Path
import sys

import pytest

# `pytest tests/test_actionbook_session.py -v` does not place the repo root on sys.path here.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import actionbook_session
from scripts.actionbook_session import ActionBookSession


def test_describe_uses_explicit_tab() -> None:
    book = ActionBookSession("s1", "tab-default")
    calls: list[tuple[str, str]] = []

    def fake_browser(subcommand: str, *args: str, timeout: float = 30.0, tab: str | None = None):  # type: ignore[override]
        calls.append((subcommand, tab or ""))
        return "https://example.com" if subcommand == "url" else "Example"

    book.browser = fake_browser  # type: ignore[method-assign]
    state = book.describe(tab="tab-2")

    assert state["tab_id"] == "tab-2"
    assert calls == [("url", "tab-2"), ("title", "tab-2")]


def test_open_new_tab_switch_updates_current_tab() -> None:
    book = ActionBookSession("s1", "tab-default")
    book._open_new_tab = lambda url, timeout_secs=15.0: "tab-2"  # type: ignore[method-assign]

    tab_id = book.open_new_tab("https://example.com", switch=True)

    assert tab_id == "tab-2"
    assert book.tab == "tab-2"


def test_main_new_tab_recovers_session_before_open(monkeypatch) -> None:
    events: list[tuple[str, str]] = []

    class FakeSession:
        def __init__(self, session: str, tab: str = "", allow_adopt: bool = True) -> None:
            self.session = session
            self.tab = tab

        def start(self, url: str) -> None:
            events.append(("start", url))
            self.tab = "t1"

        def open_new_tab(self, url: str, switch: bool = False) -> str:
            events.append(("new-tab", url))
            return "t2"

        def describe(self, tab: str | None = None) -> dict[str, str]:
            return {
                "session_id": self.session,
                "tab_id": tab or self.tab,
                "url": "https://example.com/",
                "title": "Example Domain",
            }

    monkeypatch.setattr(actionbook_session, "ActionBookSession", FakeSession)

    assert actionbook_session.main(["new-tab", "--session", "s1", "--url", "https://example.com"]) == 0
    assert events == [("start", "about:blank"), ("new-tab", "https://example.com")]


def test_main_ensure_force_new_tab_opens_new_tab(monkeypatch) -> None:
    events: list[tuple[str, str]] = []

    class FakeSession:
        def __init__(self, session: str, tab: str = "", allow_adopt: bool = True) -> None:
            self.session = session
            self.tab = "old-tab"
            self.allow_adopt = allow_adopt

        def start(self, url: str, force_new_tab: bool = False) -> None:
            events.append(("start", f"{url}|force={force_new_tab}|adopt={self.allow_adopt}"))
            if force_new_tab:
                self.tab = "new-tab"

        def describe(self, tab: str | None = None) -> dict[str, str]:
            return {
                "session_id": self.session,
                "tab_id": tab or self.tab,
                "url": "https://example.com",
                "title": "Example",
            }

    monkeypatch.setattr(actionbook_session, "ActionBookSession", FakeSession)

    assert (
        actionbook_session.main(
            ["ensure", "--session", "s1", "--url", "https://example.com", "--force-new-tab", "--no-adopt"]
        )
        == 0
    )
    assert events == [("start", "https://example.com|force=True|adopt=False")]


def test_start_force_new_tab_does_not_fall_back_to_existing_tab(monkeypatch) -> None:
    book = ActionBookSession("s1", "old-tab", allow_adopt=False)
    recover_called = False

    monkeypatch.setattr(actionbook_session, "ensure_chrome_app_running", lambda: None)
    book._check_extension = lambda require_connected=False: None  # type: ignore[method-assign]
    book._session_exists = lambda: True  # type: ignore[method-assign]
    book._open_new_tab = lambda url: ""  # type: ignore[method-assign]

    def fail_if_recover_called(url: str) -> None:
        nonlocal recover_called
        recover_called = True

    book._recover_or_attach = fail_if_recover_called  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="failed to open new tab"):
        book.start("https://example.com", force_new_tab=True)

    assert recover_called is False


def test_start_no_adopt_does_not_try_other_running_sessions(monkeypatch) -> None:
    book = ActionBookSession("s1", allow_adopt=False)

    monkeypatch.setattr(actionbook_session, "ensure_chrome_app_running", lambda: None)
    book._check_extension = lambda require_connected=False: None  # type: ignore[method-assign]
    book._session_exists = lambda: False  # type: ignore[method-assign]
    book._find_accessible_tab = lambda preferred_tab=None, target_url="": ""  # type: ignore[method-assign]
    book._start_new_session = lambda url: None  # type: ignore[method-assign]
    book._wait_for_accessible_tab = lambda preferred_tab=None, target_url="", timeout_secs=12.0: "new-tab"  # type: ignore[method-assign]
    book._ensure_target_url = lambda url: None  # type: ignore[method-assign]

    def fail_if_adopt_called(url: str) -> bool:
        raise AssertionError("allow_adopt=False should not attempt adoption")

    book._adopt_running_session = fail_if_adopt_called  # type: ignore[method-assign]

    book.start("https://example.com", force_new_tab=False)

    assert book.tab == "new-tab"


def test_close_tab_raises_on_failed_command_payload() -> None:
    book = ActionBookSession("s1", "tab-1")
    book._run_raw_command = lambda command, timeout=30.0: {  # type: ignore[method-assign]
        "ok": False,
        "error": {"message": "close failed"},
    }

    with pytest.raises(RuntimeError, match="close failed"):
        book.close_tab("tab-1")


def test_close_tab_clears_current_tab_on_success() -> None:
    book = ActionBookSession("s1", "tab-1")
    book._run_raw_command = lambda command, timeout=30.0: {"ok": True, "data": {}}  # type: ignore[method-assign]

    state = book.close_tab("tab-1")

    assert book.tab == ""
    assert state == {"session_id": "s1", "tab_id": "tab-1", "status": "closed"}


def test_main_close_tab_calls_close_tab(monkeypatch, capsys) -> None:
    events: list[tuple[str, str]] = []

    class FakeSession:
        def __init__(self, session: str, tab: str = "", allow_adopt: bool = True) -> None:
            self.session = session
            self.tab = tab

        def close_tab(self, tab_id: str) -> dict[str, str]:
            events.append(("close", tab_id))
            return {"session_id": self.session, "tab_id": tab_id, "status": "closed"}

    monkeypatch.setattr(actionbook_session, "ActionBookSession", FakeSession)

    assert actionbook_session.main(["close-tab", "--session", "s1", "--tab", "tab-9", "--json"]) == 0
    assert events == [("close", "tab-9")]
    assert '"status": "closed"' in capsys.readouterr().out


def test_main_close_tab_surfaces_missing_session_without_bootstrap(monkeypatch) -> None:
    events: list[tuple[str, str]] = []

    class FakeSession:
        def __init__(self, session: str, tab: str = "", allow_adopt: bool = True) -> None:
            self.session = session
            self.tab = tab

        def start(self, url: str, force_new_tab: bool = False) -> None:
            events.append(("start", url))
            raise AssertionError("close-tab should not bootstrap a new session")

        def close_tab(self, tab_id: str) -> dict[str, str]:
            events.append(("close", tab_id))
            raise RuntimeError("SESSION_NOT_FOUND")

    monkeypatch.setattr(actionbook_session, "ActionBookSession", FakeSession)

    with pytest.raises(RuntimeError, match="SESSION_NOT_FOUND"):
        actionbook_session.main(["close-tab", "--session", "s1", "--tab", "tab-9"])

    assert events == [("close", "tab-9")]
