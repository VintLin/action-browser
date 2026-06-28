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


def test_main_new_tab_uses_existing_session_without_bootstrap(monkeypatch) -> None:
    events: list[tuple[str, str]] = []

    class FakeSession:
        def __init__(self, session: str, tab: str = "", allow_adopt: bool = True) -> None:
            self.session = session
            self.tab = tab

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
    assert events == [("new-tab", "https://example.com")]


def test_main_list_tabs_uses_existing_session_without_bootstrap(monkeypatch, capsys) -> None:
    events: list[str] = []

    class FakeSession:
        def __init__(self, session: str, tab: str = "", allow_adopt: bool = True) -> None:
            self.session = session
            self.tab = tab

        def list_tabs(self) -> list[dict[str, str]]:
            events.append("list-tabs")
            return [{"tab_id": "t1", "url": "https://example.com", "title": "Example", "active": "false"}]

    monkeypatch.setattr(actionbook_session, "ActionBookSession", FakeSession)

    assert actionbook_session.main(["list-tabs", "--session", "s1", "--json"]) == 0
    assert events == ["list-tabs"]
    assert '"tabs"' in capsys.readouterr().out


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


def test_main_ensure_explicit_session_disables_cross_session_adoption(monkeypatch) -> None:
    events: list[tuple[str, bool]] = []

    class FakeSession:
        def __init__(self, session: str, tab: str = "", allow_adopt: bool = True) -> None:
            self.session = session
            self.tab = "t1"
            self.allow_adopt = allow_adopt

        def start(self, url: str, force_new_tab: bool = False) -> None:
            events.append((self.session, self.allow_adopt))

        def describe(self, tab: str | None = None) -> dict[str, str]:
            return {
                "session_id": self.session,
                "tab_id": tab or self.tab,
                "url": "https://example.com",
                "title": "Example",
            }

    monkeypatch.setattr(actionbook_session, "ActionBookSession", FakeSession)

    assert actionbook_session.main(["ensure", "--session", "stability-b", "--url", "https://example.com"]) == 0
    assert events == [("stability-b", False)]


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
    book._wait_for_stable_session = lambda target_url="", timeout_secs=8.0: setattr(book, "tab", "new-tab")  # type: ignore[method-assign]
    book._ensure_target_url = lambda url: None  # type: ignore[method-assign]

    def fail_if_adopt_called(url: str) -> bool:
        raise AssertionError("allow_adopt=False should not attempt adoption")

    book._adopt_running_session = fail_if_adopt_called  # type: ignore[method-assign]

    book.start("https://example.com", force_new_tab=False)

    assert book.tab == "new-tab"


def test_wait_for_stable_session_retries_until_session_and_tab_are_ready(monkeypatch) -> None:
    book = ActionBookSession("s1", "t1")
    check_calls = 0
    state = {"reachable_calls": 0, "tab_calls": 0}

    monkeypatch.setattr(actionbook_session, "sleep_between", lambda *args, **kwargs: None)

    def fake_check_extension(*, timeout_secs=8.0, require_connected=True) -> None:
        nonlocal check_calls
        check_calls += 1

    book._check_extension = fake_check_extension  # type: ignore[method-assign]

    def fake_session_is_reachable() -> bool:
        state["reachable_calls"] += 1
        return state["reachable_calls"] >= 2

    def fake_find_accessible_tab(preferred_tab=None, target_url="") -> str:
        state["tab_calls"] += 1
        return "t1" if state["tab_calls"] >= 2 else ""

    book._session_is_reachable = fake_session_is_reachable  # type: ignore[method-assign]
    book._find_accessible_tab = fake_find_accessible_tab  # type: ignore[method-assign]

    book._wait_for_stable_session(target_url="https://example.com", timeout_secs=1.0)

    assert check_calls >= 2
    assert state["reachable_calls"] >= 2
    assert state["tab_calls"] >= 2
    assert book.tab == "t1"


def test_wait_for_stable_session_times_out_when_tab_never_becomes_accessible(monkeypatch) -> None:
    book = ActionBookSession("s1", "t1")

    monkeypatch.setattr(actionbook_session, "sleep_between", lambda *args, **kwargs: None)

    book._check_extension = lambda *, timeout_secs=8.0, require_connected=True: None  # type: ignore[method-assign]
    book._session_is_reachable = lambda: True  # type: ignore[method-assign]
    book._find_accessible_tab = lambda preferred_tab=None, target_url="": ""  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="no accessible tab is ready"):
        book._wait_for_stable_session(target_url="https://example.com", timeout_secs=0.01)


def test_start_new_session_requires_registered_session_after_start(monkeypatch) -> None:
    book = ActionBookSession("s1")

    monkeypatch.setattr(actionbook_session, "sleep_between", lambda *args, **kwargs: None)
    book._run_raw_command = lambda command, timeout=30.0: {  # type: ignore[method-assign]
        "ok": True,
        "data": {
            "session": {"session_id": "s1", "status": "running"},
            "tab": {"tab_id": "t1"},
        },
    }
    book._session_exists = lambda: False  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="session started but not registered"):
        book._start_new_session("https://example.com")


def test_start_new_session_requires_reachable_session_after_start(monkeypatch) -> None:
    book = ActionBookSession("s1")

    monkeypatch.setattr(actionbook_session, "sleep_between", lambda *args, **kwargs: None)
    book._run_raw_command = lambda command, timeout=30.0: {  # type: ignore[method-assign]
        "ok": True,
        "data": {
            "session": {"session_id": "s1", "status": "running"},
            "tab": {"tab_id": "t1"},
        },
    }
    book._session_exists = lambda: True  # type: ignore[method-assign]
    book._session_is_reachable = lambda: False  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="session started but is not reachable"):
        book._start_new_session("https://example.com")


def test_open_new_tab_waits_for_accessible_new_tab(monkeypatch) -> None:
    book = ActionBookSession("s1")
    list_calls = 0
    access_calls = 0
    tab_snapshots = iter(
        [
            [],
            [{"tab_id": "t2", "url": "", "title": ""}],
            [{"tab_id": "t2", "url": "https://example.com", "title": "Example"}],
        ]
    )
    accessibility = iter([False, False, True])

    monkeypatch.setattr(actionbook_session, "sleep_between", lambda *args, **kwargs: None)

    def fake_list_tabs():
        nonlocal list_calls
        list_calls += 1
        return next(tab_snapshots)

    def fake_is_tab_accessible(tab_id: str) -> bool:
        nonlocal access_calls
        access_calls += 1
        return next(accessibility)

    book._list_tabs = fake_list_tabs  # type: ignore[method-assign]
    book._run_raw_command = lambda command, timeout=30.0: {"ok": True, "data": {"tab": {"tab_id": "t2"}}}  # type: ignore[method-assign]
    book._is_tab_accessible = fake_is_tab_accessible  # type: ignore[method-assign]

    assert book._open_new_tab("https://example.com") == "t2"
    assert list_calls == 3
    assert access_calls == 3


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
