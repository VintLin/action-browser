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
