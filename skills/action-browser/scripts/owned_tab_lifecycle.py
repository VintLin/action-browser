from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import time
from typing import Any, Iterator
from urllib.parse import urlparse
from uuid import uuid4

from scripts.actionbook_errors import ActionBookFailure, has_failure_code
from scripts.actionbook_session import (
    ActionBookSession,
    close_chrome_tab_by_id,
    close_unique_chrome_tab,
    list_chrome_tabs,
)


OWNED_TABS_SCHEMA_VERSION = 2
ACQUISITION_STALE_SECONDS = 120
ACTIVE_LEASE_STATUSES = {"active", "paused"}
TRANSITION_LEASE_STATUSES = {"acquiring", "releasing"}
MISSING_RESOURCE_CODES = {"SESSION_NOT_FOUND", "TAB_NOT_FOUND"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def owned_tabs_path() -> Path:
    configured = os.environ.get("ACTION_BROWSER_OWNED_TABS_FILE")
    return Path(configured).expanduser() if configured else Path.home() / ".action-browser" / "owned-tabs.json"


def _task_id(value: str) -> str:
    task_id = str(value or "").strip()
    if not task_id:
        raise ValueError("task id is required")
    return task_id


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class OwnedTabLease:
    lease_id: str
    task_id: str
    requested_session_id: str
    session_id: str
    tab_id: str
    status: str
    url: str
    title: str
    chrome_tab_id: str
    replacement_tab_ids: tuple[str, ...]
    cleanup_error: str
    cleanup_attempts: int
    created_at: str
    updated_at: str

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "OwnedTabLease":
        raw_replacements = record.get("replacement_tab_ids")
        if not isinstance(raw_replacements, (list, tuple)):
            raw_replacements = []
        try:
            cleanup_attempts = int(record.get("cleanup_attempts") or 0)
        except (TypeError, ValueError):
            cleanup_attempts = 0
        return cls(
            lease_id=str(record.get("lease_id") or ""),
            task_id=str(record.get("task_id") or ""),
            requested_session_id=str(record.get("requested_session_id") or ""),
            session_id=str(record.get("session_id") or ""),
            tab_id=str(record.get("tab_id") or ""),
            status=str(record.get("status") or ""),
            url=str(record.get("url") or ""),
            title=str(record.get("title") or ""),
            chrome_tab_id=str(record.get("chrome_tab_id") or ""),
            replacement_tab_ids=tuple(str(item).strip() for item in raw_replacements if str(item).strip()),
            cleanup_error=str(record.get("cleanup_error") or ""),
            cleanup_attempts=cleanup_attempts,
            created_at=str(record.get("created_at") or ""),
            updated_at=str(record.get("updated_at") or ""),
        )

    def as_dict(self, *, acquisition: str | None = None) -> dict[str, Any]:
        payload = {
            "schema_version": OWNED_TABS_SCHEMA_VERSION,
            "lease_id": self.lease_id,
            "task_id": self.task_id,
            "requested_session_id": self.requested_session_id,
            "session_id": self.session_id,
            "tab_id": self.tab_id,
            "status": self.status,
            "url": self.url,
            "title": self.title,
            "chrome_tab_id": self.chrome_tab_id,
            "replacement_tab_ids": list(self.replacement_tab_ids),
            "cleanup_error": self.cleanup_error,
            "cleanup_attempts": self.cleanup_attempts,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if acquisition:
            payload["acquisition"] = acquisition
        return payload


class OwnedTabStore:
    """Atomic persistence adapter kept internal to the owned-tab lifecycle module."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or owned_tabs_path())
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def _empty(self) -> dict[str, Any]:
        return {"schema_version": OWNED_TABS_SCHEMA_VERSION, "leases": {}}

    def _load(self) -> dict[str, Any]:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._empty()
        if (
            not isinstance(state, dict)
            or state.get("schema_version") != OWNED_TABS_SCHEMA_VERSION
            or not isinstance(state.get("leases"), dict)
        ):
            raise ValueError(f"invalid owned-tab lease store: {self.path}")
        for task_id, record in state["leases"].items():
            if not self._valid_record(task_id, record):
                raise ValueError(f"invalid owned-tab lease store: {self.path}")
        return state

    @staticmethod
    def _valid_record(task_id: Any, record: Any) -> bool:
        if not isinstance(task_id, str) or not task_id.strip() or not isinstance(record, dict):
            return False
        status = record.get("status")
        if status not in ACTIVE_LEASE_STATUSES | TRANSITION_LEASE_STATUSES | {"cleanup_failed"}:
            return False
        required_strings = ("lease_id", "task_id", "requested_session_id", "created_at", "updated_at")
        if any(not isinstance(record.get(key), str) or not record[key].strip() for key in required_strings):
            return False
        if record["task_id"] != task_id:
            return False
        if status != "acquiring":
            if not isinstance(record.get("session_id"), str) or not record["session_id"].strip():
                return False
            if not isinstance(record.get("tab_id"), str) or not record["tab_id"].strip():
                return False
        if not isinstance(record.get("replacement_tab_ids", []), list):
            return False
        if type(record.get("cleanup_attempts", 0)) is not int or record.get("cleanup_attempts", 0) < 0:
            return False
        return True

    @contextmanager
    def _locked(self) -> Iterator[dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                state = self._load()
                yield state
                self._write(state)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _write(self, state: dict[str, Any]) -> None:
        state["schema_version"] = OWNED_TABS_SCHEMA_VERSION
        state["updated_at"] = utc_now()
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as output:
            output.write(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            output.flush()
            os.fsync(output.fileno())
        tmp.replace(self.path)
        directory_fd = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def get(self, task_id: str) -> OwnedTabLease | None:
        record = self._load()["leases"].get(_task_id(task_id))
        return OwnedTabLease.from_record(record) if isinstance(record, dict) else None

    def reserve(self, task_id: str, requested_session_id: str, url: str) -> OwnedTabLease:
        task_id = _task_id(task_id)
        with self._locked() as state:
            if task_id in state["leases"]:
                raise ActionBookFailure("OWNED_TAB_BUSY", f"task {task_id!r} already has a lease transition")
            now = utc_now()
            record = {
                "lease_id": uuid4().hex,
                "task_id": task_id,
                "requested_session_id": str(requested_session_id or "").strip(),
                "session_id": "",
                "tab_id": "",
                "status": "acquiring",
                "url": str(url or ""),
                "title": "",
                "chrome_tab_id": "",
                "replacement_tab_ids": [],
                "cleanup_error": "",
                "cleanup_attempts": 0,
                "created_at": now,
                "updated_at": now,
            }
            state["leases"][task_id] = record
            return OwnedTabLease.from_record(record)

    def update(self, lease_id: str, **changes: Any) -> OwnedTabLease:
        with self._locked() as state:
            for task_id, record in state["leases"].items():
                if isinstance(record, dict) and record.get("lease_id") == lease_id:
                    record.update(changes)
                    record["updated_at"] = utc_now()
                    if not self._valid_record(task_id, record):
                        raise ValueError(f"invalid owned-tab lease update: {task_id}")
                    return OwnedTabLease.from_record(record)
        raise ActionBookFailure("OWNED_TAB_LEASE_NOT_FOUND", f"lease {lease_id!r} is not tracked")

    def delete(self, lease_id: str) -> bool:
        with self._locked() as state:
            for task_id, record in list(state["leases"].items()):
                if isinstance(record, dict) and record.get("lease_id") == lease_id:
                    state["leases"].pop(task_id, None)
                    return True
        return False

    def list(self) -> list[OwnedTabLease]:
        return [OwnedTabLease.from_record(record) for record in self._load()["leases"].values()]


@contextmanager
def tab_mutation_lock() -> Iterator[None]:
    lock_path = owned_tabs_path().with_suffix(".tab-mutations.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def close_and_verify_tab(session: Any, tab_id: str, chrome_tab_id: str = "") -> None:
    with tab_mutation_lock():
        before = session.list_tabs()
        before_ids = {
            str(tab.get("tab_id") or "").strip()
            for tab in before
            if isinstance(tab, dict)
        }
        if tab_id not in before_ids:
            raise ActionBookFailure(
                "TAB_NOT_FOUND",
                f"tab {tab_id!r} is not listed in session {session.session!r}",
            )
        session.close_tab(tab_id)
        after = session.list_tabs()
        remaining = {
            str(tab.get("tab_id") or "").strip()
            for tab in after
            if isinstance(tab, dict)
        }
        if tab_id in remaining:
            raise ActionBookFailure("TAB_CLOSE_FAILED", f"tab still open after close-tab: {tab_id}")
        replacement_ids = remaining - before_ids
        if not replacement_ids:
            return
        replacements = [
            tab
            for tab in after
            if isinstance(tab, dict) and str(tab.get("tab_id") or "").strip() in replacement_ids
        ]
        if chrome_tab_id:
            if not close_chrome_tab_by_id(chrome_tab_id):
                raise ActionBookFailure(
                    "TAB_REPLACEMENT_CLOSE_FAILED",
                    f"could not close replacement Chrome tab by stable id: {chrome_tab_id}",
                    details={
                        "session_id": session.session,
                        "old_tab_id": tab_id,
                        "chrome_tab_id": chrome_tab_id,
                        "replacement_tab_ids": sorted(replacement_ids),
                    },
                )
        elif not all(
            close_unique_chrome_tab(str(tab.get("url") or ""), str(tab.get("title") or ""))
            for tab in replacements
        ):
            raise ActionBookFailure(
                "TAB_REPLACEMENT_AMBIGUOUS",
                "could not close replacement tab by unique Chrome URL/title; retry with a stable Chrome tab id",
                details={
                    "session_id": session.session,
                    "old_tab_id": tab_id,
                    "replacement_tab_ids": sorted(replacement_ids),
                },
            )
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            live_ids = {
                str(tab.get("tab_id") or "").strip()
                for tab in session.list_tabs()
                if isinstance(tab, dict)
            }
            if not replacement_ids.intersection(live_ids):
                return
            time.sleep(0.1)
        raise ActionBookFailure(
            "TAB_CLOSE_FAILED",
            "replacement tab still visible after exact Chrome close: "
            f"session={session.session} new_tabs={sorted(replacement_ids)}",
            details={
                "session_id": session.session,
                "old_tab_id": tab_id,
                "chrome_tab_id": chrome_tab_id,
                "replacement_tab_ids": sorted(replacement_ids),
            },
        )


def _lease_is_alive(lease: OwnedTabLease) -> bool:
    if not lease.session_id or not lease.tab_id:
        return False
    try:
        ActionBookSession.owned(lease.session_id, lease.tab_id).use_tab(lease.tab_id)
    except Exception:
        return False
    return True


def _transition_is_fresh(lease: OwnedTabLease) -> bool:
    updated_at = _parse_time(lease.updated_at)
    if updated_at is None:
        return False
    return (datetime.now(timezone.utc) - updated_at).total_seconds() < ACQUISITION_STALE_SECONDS


def _new_chrome_tab_id(before: list[dict[str, str]], after: list[dict[str, str]], url: str) -> str:
    """Find the one Chrome tab created by a force-new-tab acquisition."""
    before_ids = {str(item.get("chrome_tab_id") or "").strip() for item in before}
    candidates = [
        item
        for item in after
        if str(item.get("chrome_tab_id") or "").strip() not in before_ids
    ]
    normalized_url = str(url or "").strip().rstrip("/")
    matching = [
        item
        for item in candidates
        if str(item.get("url") or "").strip().rstrip("/") == normalized_url
    ]
    candidates = matching or candidates
    return str(candidates[0].get("chrome_tab_id") or "").strip() if len(candidates) == 1 else ""


def acquire_owned_tab(
    *,
    task_id: str,
    session_id: str,
    url: str,
    adopt_running_session: bool = False,
    allow_visible_recovery: bool = True,
) -> dict[str, Any]:
    task_id = _task_id(task_id)
    store = OwnedTabStore()
    existing = store.get(task_id)
    if existing is not None:
        if existing.status in ACTIVE_LEASE_STATUSES and _lease_is_alive(existing):
            return existing.as_dict(acquisition="reused")
        if existing.status in TRANSITION_LEASE_STATUSES and _transition_is_fresh(existing):
            raise ActionBookFailure("OWNED_TAB_BUSY", f"task {task_id!r} has an active {existing.status} transition")
        if existing.session_id and existing.tab_id and _lease_is_alive(existing):
            if existing.status == "acquiring":
                existing = store.update(existing.lease_id, status="active")
                return existing.as_dict(acquisition="reused")
            raise ActionBookFailure(
                "OWNED_TAB_CLEANUP_REQUIRED",
                f"task {task_id!r} still owns tab {existing.tab_id!r} after {existing.status}",
            )
        store.delete(existing.lease_id)

    reservation = store.reserve(task_id, session_id, url)
    session = ActionBookSession.bootstrap(
        session_id,
        adopt_running_session=adopt_running_session,
        allow_visible_recovery=allow_visible_recovery,
    )
    try:
        with tab_mutation_lock():
            chrome_tabs_before = list_chrome_tabs()
            session.start(url, force_new_tab=True)
            chrome_tabs_after = list_chrome_tabs()
            chrome_tab_id = _new_chrome_tab_id(chrome_tabs_before, chrome_tabs_after, url)
        reservation = store.update(
            reservation.lease_id,
            session_id=session.session,
            tab_id=session.tab,
            chrome_tab_id=chrome_tab_id,
            status="acquiring",
        )
        state = session.describe()
        active = store.update(
            reservation.lease_id,
            session_id=state["session_id"],
            tab_id=state["tab_id"],
            url=state["url"],
            title=state["title"],
            status="active",
        )
        return active.as_dict(acquisition="acquired")
    except BaseException as primary_error:
        if session.tab:
            try:
                reservation = store.update(
                    reservation.lease_id,
                    session_id=session.session,
                    tab_id=session.tab,
                    status="acquiring",
                )
                close_and_verify_tab(session, session.tab, reservation.chrome_tab_id)
            except Exception as cleanup_error:
                try:
                    details = getattr(cleanup_error, "details", {})
                    store.update(
                        reservation.lease_id,
                        status="cleanup_failed",
                        replacement_tab_ids=list(details.get("replacement_tab_ids") or []),
                        cleanup_error=str(cleanup_error),
                        cleanup_attempts=reservation.cleanup_attempts + 1,
                    )
                except Exception:
                    pass
                if hasattr(primary_error, "add_note"):
                    primary_error.add_note(f"owned-tab cleanup failed: {cleanup_error}")
                raise primary_error
        store.delete(reservation.lease_id)
        raise


def release_owned_tab(task_id: str) -> dict[str, Any]:
    task_id = _task_id(task_id)
    store = OwnedTabStore()
    lease = store.get(task_id)
    if lease is None:
        return {"schema_version": OWNED_TABS_SCHEMA_VERSION, "task_id": task_id, "status": "missing"}
    if not lease.session_id or not lease.tab_id:
        store.delete(lease.lease_id)
        return {**lease.as_dict(), "status": "released"}
    lease = store.update(lease.lease_id, status="releasing")
    session = ActionBookSession.owned(lease.session_id, lease.tab_id)
    try:
        close_and_verify_tab(session, lease.tab_id, lease.chrome_tab_id)
    except Exception as exc:
        details = getattr(exc, "details", {})
        if has_failure_code(exc, MISSING_RESOURCE_CODES) and not lease.chrome_tab_id:
            store.delete(lease.lease_id)
            return {**lease.as_dict(), "status": "released", "cleanup_recovered": True}
        if lease.chrome_tab_id and close_chrome_tab_by_id(lease.chrome_tab_id):
            store.delete(lease.lease_id)
            return {**lease.as_dict(), "status": "released", "cleanup_recovered": True}
        store.update(
            lease.lease_id,
            status="cleanup_failed",
            replacement_tab_ids=list(details.get("replacement_tab_ids") or lease.replacement_tab_ids),
            cleanup_error=str(exc),
            cleanup_attempts=lease.cleanup_attempts + 1,
        )
        raise
    store.delete(lease.lease_id)
    return {**lease.as_dict(), "status": "released"}


def list_owned_tabs() -> dict[str, Any]:
    records = [lease.as_dict() for lease in OwnedTabStore().list()]
    return {"schema_version": OWNED_TABS_SCHEMA_VERSION, "owned_tabs": records, "count": len(records)}


def get_owned_tab(task_id: str) -> OwnedTabLease | None:
    return OwnedTabStore().get(_task_id(task_id))


def require_owned_tab(task_id: str, session_id: str, tab_id: str) -> OwnedTabLease:
    lease = OwnedTabStore().get(_task_id(task_id))
    if lease is None or lease.status not in ACTIVE_LEASE_STATUSES:
        raise ActionBookFailure("OWNED_TAB_NOT_FOUND", f"owned tab not found for task {task_id!r}; run acquire-tab first")
    if lease.session_id != session_id or lease.tab_id != tab_id:
        raise ActionBookFailure(
            "OWNED_TAB_MISMATCH",
            f"task={task_id!r} owns session={lease.session_id!r} tab={lease.tab_id!r}, "
            f"not session={session_id!r} tab={tab_id!r}",
        )
    return lease


def owned_tab_is_alive(task_id: str, *, lease_id: str = "") -> bool:
    lease = OwnedTabStore().get(_task_id(task_id))
    if lease is None or lease.status not in ACTIVE_LEASE_STATUSES:
        return False
    if lease_id and lease.lease_id != lease_id:
        return False
    return _lease_is_alive(lease)


def set_owned_tab_paused(task_id: str, paused: bool) -> OwnedTabLease | None:
    lease = OwnedTabStore().get(_task_id(task_id))
    if lease is None:
        return None
    target = "paused" if paused else "active"
    if lease.status == target:
        return lease
    if lease.status not in ACTIVE_LEASE_STATUSES:
        raise ActionBookFailure("OWNED_TAB_BUSY", f"cannot mark {lease.status} lease as {target}")
    return OwnedTabStore().update(lease.lease_id, status=target)


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
    require_owned_tab(str(args.task_id), str(args.session), str(args.tab))
    book = action_book_cls.owned(str(args.session), str(args.tab))
    state = book.use_tab(str(args.tab))
    current_url = str(state.get("url") or "") if isinstance(state, dict) else ""
    if expected_url and _origin(current_url) != _origin(expected_url):
        book.goto(expected_url)
    return book


@contextmanager
def temporary_tab(book: Any, url: str) -> Iterator[str]:
    parent_tab = str(getattr(book, "tab", "") or "").strip()
    if not parent_tab:
        raise ActionBookFailure("TAB_NOT_READY", "temporary tab requires an active parent owned tab")
    with tab_mutation_lock():
        chrome_tabs_before = list_chrome_tabs()
        tab_id = book.open_new_tab(url)
        chrome_tab_id = _new_chrome_tab_id(chrome_tabs_before, list_chrome_tabs(), url)
    primary_error: BaseException | None = None
    try:
        book.use_tab(tab_id)
        yield tab_id
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_errors: list[BaseException] = []
        try:
            close_and_verify_tab(book, tab_id, chrome_tab_id)
        except BaseException as exc:
            cleanup_errors.append(exc)
        try:
            book.use_tab(parent_tab)
        except BaseException as exc:
            cleanup_errors.append(exc)
        if cleanup_errors:
            if primary_error is not None:
                for cleanup_error in cleanup_errors:
                    if hasattr(primary_error, "add_note"):
                        primary_error.add_note(f"temporary tab cleanup failed: {cleanup_error}")
            else:
                first, *rest = cleanup_errors
                for cleanup_error in rest:
                    if hasattr(first, "add_note"):
                        first.add_note(f"additional temporary tab cleanup failure: {cleanup_error}")
                raise first


def _origin(value: str) -> str:
    parsed = urlparse(value)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
