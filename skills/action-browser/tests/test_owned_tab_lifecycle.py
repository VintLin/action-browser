from __future__ import annotations

from argparse import ArgumentParser
import json
from pathlib import Path
import sys

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import owned_tab_lifecycle as lifecycle
from scripts.actionbook_errors import ActionBookFailure


class FakeSession:
    live_tabs: set[str] = set()
    next_tab = 0
    start_hook = None

    def __init__(self, session: str, tab: str = "") -> None:
        self.session = session
        self.tab = tab
        self.events: list[tuple[str, str]] = []

    @classmethod
    def bootstrap(
        cls,
        session: str,
        *,
        adopt_running_session: bool,
        allow_visible_recovery: bool,
    ) -> "FakeSession":
        return cls(session)

    @classmethod
    def owned(cls, session: str, tab: str) -> "FakeSession":
        return cls(session, tab)

    def start(self, url: str, force_new_tab: bool = False) -> None:
        assert force_new_tab is True
        if type(self).start_hook:
            type(self).start_hook()
        type(self).next_tab += 1
        self.tab = f"tab-{type(self).next_tab}"
        type(self).live_tabs.add(self.tab)

    def describe(self, tab: str | None = None) -> dict[str, str]:
        active = tab or self.tab
        return {
            "session_id": self.session,
            "tab_id": active,
            "url": "https://example.com",
            "title": "Example",
        }

    def use_tab(self, tab_id: str) -> dict[str, str]:
        if tab_id not in type(self).live_tabs:
            raise ActionBookFailure("TAB_NOT_FOUND", f"missing {tab_id}")
        self.tab = tab_id
        self.events.append(("use", tab_id))
        return self.describe()

    def goto(self, url: str) -> None:
        self.events.append(("goto", url))

    def open_new_tab(self, url: str) -> str:
        type(self).next_tab += 1
        tab_id = f"temporary-{type(self).next_tab}"
        type(self).live_tabs.add(tab_id)
        self.events.append(("open", url))
        return tab_id

    def close_tab(self, tab_id: str) -> dict[str, str]:
        if tab_id not in type(self).live_tabs:
            raise ActionBookFailure("TAB_NOT_FOUND", f"missing {tab_id}")
        type(self).live_tabs.remove(tab_id)
        if self.tab == tab_id:
            self.tab = ""
        self.events.append(("close", tab_id))
        return {"status": "closed"}

    def list_tabs(self) -> list[dict[str, str]]:
        return [{"tab_id": tab_id, "url": "https://example.com", "title": "Example"} for tab_id in sorted(type(self).live_tabs)]


@pytest.fixture(autouse=True)
def reset_fake_session() -> None:
    FakeSession.live_tabs = set()
    FakeSession.next_tab = 0
    FakeSession.start_hook = None


def configure_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "owned-tabs.json"
    monkeypatch.setenv("ACTION_BROWSER_OWNED_TABS_FILE", str(path))
    monkeypatch.setattr(lifecycle, "ActionBookSession", FakeSession)
    return path


def test_acquire_persists_reservation_before_browser_io_and_releases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = configure_store(tmp_path, monkeypatch)
    observed: list[str] = []
    FakeSession.start_hook = lambda: observed.append(lifecycle.get_owned_tab("task-a").status)  # type: ignore[union-attr]

    acquired = lifecycle.acquire_owned_tab(
        task_id="task-a",
        session_id="shared",
        url="https://example.com",
    )

    assert observed == ["acquiring"]
    assert acquired["acquisition"] == "acquired"
    assert acquired["status"] == "active"
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2

    reused = lifecycle.acquire_owned_tab(task_id="task-a", session_id="shared", url="https://example.com")
    assert reused["acquisition"] == "reused"
    assert reused["lease_id"] == acquired["lease_id"]

    released = lifecycle.release_owned_tab("task-a")
    assert released["status"] == "released"
    assert lifecycle.get_owned_tab("task-a") is None
    assert FakeSession.live_tabs == set()


def test_failed_cleanup_retains_lease_for_exact_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_store(tmp_path, monkeypatch)
    acquired = lifecycle.acquire_owned_tab(task_id="task-a", session_id="shared", url="https://example.com")

    monkeypatch.setattr(
        lifecycle,
        "close_and_verify_tab",
        lambda session, tab, chrome_tab_id="": (_ for _ in ()).throw(
            ActionBookFailure("TAB_CLOSE_FAILED", "still open")
        ),
    )

    with pytest.raises(ActionBookFailure, match="TAB_CLOSE_FAILED"):
        lifecycle.release_owned_tab("task-a")

    retained = lifecycle.get_owned_tab("task-a")
    assert retained is not None
    assert retained.lease_id == acquired["lease_id"]
    assert retained.status == "cleanup_failed"


def test_attach_requires_matching_active_lease(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_store(tmp_path, monkeypatch)
    acquired = lifecycle.acquire_owned_tab(task_id="task-a", session_id="shared", url="https://old.example/page")
    parser = ArgumentParser()
    lifecycle.add_workflow_args(parser)

    with pytest.raises(ValueError, match="require --task-id, --session, --tab"):
        lifecycle.attach_workflow(parser.parse_args([]), "https://target.example/start", FakeSession)

    args = parser.parse_args(
        ["--task-id", "task-a", "--session", acquired["session_id"], "--tab", acquired["tab_id"]]
    )
    book = lifecycle.attach_workflow(args, "https://target.example/start", FakeSession)
    assert book.events == [("use", acquired["tab_id"]), ("goto", "https://target.example/start")]

    with pytest.raises(ActionBookFailure, match="OWNED_TAB_MISMATCH"):
        lifecycle.attach_workflow(
            parser.parse_args(["--task-id", "task-a", "--session", "shared", "--tab", "other"]),
            action_book_cls=FakeSession,
        )


def test_temporary_tab_restores_parent_and_preserves_primary_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_store(tmp_path, monkeypatch)
    FakeSession.live_tabs.add("owned")
    book = FakeSession.owned("shared", "owned")

    with lifecycle.temporary_tab(book, "https://detail.example") as tab_id:
        assert book.tab == tab_id
        assert tab_id in FakeSession.live_tabs

    assert book.tab == "owned"
    assert FakeSession.live_tabs == {"owned"}

    monkeypatch.setattr(
        lifecycle,
        "close_and_verify_tab",
        lambda session, tab, chrome_tab_id="": (_ for _ in ()).throw(
            ActionBookFailure("TAB_CLOSE_FAILED", "close failed")
        ),
    )
    with pytest.raises(RuntimeError, match="body failed") as error:
        with lifecycle.temporary_tab(book, "https://detail.example"):
            raise RuntimeError("body failed")
    assert any("temporary tab cleanup failed" in note for note in error.value.__notes__)


def test_close_verification_handles_replacement_and_rejects_ambiguity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_store(tmp_path, monkeypatch)
    snapshots = iter(
        [
            [{"tab_id": "owned", "url": "https://example.com", "title": "Example"}],
            [{"tab_id": "replacement", "url": "https://example.com", "title": "Loading"}],
            [],
        ]
    )

    class ReplacingSession:
        session = "shared"

        def list_tabs(self) -> list[dict[str, str]]:
            return next(snapshots)

        def close_tab(self, tab_id: str) -> dict[str, str]:
            return {"status": "closed"}

    closed: list[tuple[str, str]] = []
    monkeypatch.setattr(lifecycle, "close_unique_chrome_tab", lambda url, title: closed.append((url, title)) or True)
    lifecycle.close_and_verify_tab(ReplacingSession(), "owned")
    assert closed == [("https://example.com", "Loading")]


def test_close_verification_uses_stable_chrome_id_for_duplicate_urls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_store(tmp_path, monkeypatch)
    snapshots = iter(
        [
            [{"tab_id": "owned", "url": "https://example.com", "title": "Example"}],
            [{"tab_id": "replacement", "url": "https://example.com", "title": "Loading"}],
            [],
        ]
    )

    class ReplacingSession:
        session = "shared"

        def list_tabs(self) -> list[dict[str, str]]:
            return next(snapshots)

        def close_tab(self, tab_id: str) -> dict[str, str]:
            return {"status": "closed"}

    closed: list[str] = []
    monkeypatch.setattr(lifecycle, "close_chrome_tab_by_id", lambda tab_id: closed.append(tab_id) or True)
    monkeypatch.setattr(
        lifecycle,
        "close_unique_chrome_tab",
        lambda *_args: (_ for _ in ()).throw(AssertionError("URL/title fallback must not run")),
    )

    lifecycle.close_and_verify_tab(ReplacingSession(), "owned", "chrome-tab-1")
    assert closed == ["chrome-tab-1"]


def test_release_retries_stale_actionbook_id_by_stable_chrome_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_store(tmp_path, monkeypatch)
    acquired = lifecycle.acquire_owned_tab(task_id="task-a", session_id="shared", url="https://example.com")
    lifecycle.OwnedTabStore().update(acquired["lease_id"], chrome_tab_id="chrome-tab-1")
    monkeypatch.setattr(
        lifecycle,
        "close_and_verify_tab",
        lambda *_args: (_ for _ in ()).throw(ActionBookFailure("TAB_NOT_FOUND", "replacement id is stale")),
    )
    monkeypatch.setattr(lifecycle, "close_chrome_tab_by_id", lambda tab_id: tab_id == "chrome-tab-1")

    released = lifecycle.release_owned_tab("task-a")

    assert released["status"] == "released"
    assert released["cleanup_recovered"] is True
    assert lifecycle.get_owned_tab("task-a") is None


def test_schema_v1_store_is_rejected_without_compatibility_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = configure_store(tmp_path, monkeypatch)
    path.write_text(json.dumps({"schema_version": 1, "tasks": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid owned-tab lease store"):
        lifecycle.list_owned_tabs()
