#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generic ActionBook extension-session bootstrap helper.

With an explicit session id it reuses only that same session, opens a fresh tab
in that session, and only falls back to creating that named session when reuse
is not possible. Cross-session adoption is off by default; callers opt in by
passing allow_adopt=True (the standalone CLI does this automatically for the
default bootstrap session or when --adopt-running-session is set).
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlparse

try:
    from diagnostics.actionbook_chrome_extension_state import chrome_root, inspect_profiles
except ModuleNotFoundError:  # pragma: no cover - exercised when imported as scripts.actionbook_session in tests
    from scripts.diagnostics.actionbook_chrome_extension_state import chrome_root, inspect_profiles

try:
    from script_common import add_session_tab_args, log, parse_json_output, run_command
except ModuleNotFoundError:  # pragma: no cover - exercised when imported as scripts.actionbook_session in tests
    from scripts.script_common import add_session_tab_args, log, parse_json_output, run_command

try:
    from actionbook_errors import ActionBookFailure, has_failure_code
except ModuleNotFoundError:  # pragma: no cover - exercised when imported as scripts.actionbook_session in tests
    from scripts.actionbook_errors import ActionBookFailure, has_failure_code


DEFAULT_SESSION = "task-1"
CHROME_APP_NAME = "Google Chrome"
DEFAULT_ALLOW_VISIBLE_RECOVERY = True

RECOVERABLE_START_CODES = {
    "SESSION_CLOSED",
    "SESSION_NOT_FOUND",
    "SESSION_NOT_READY",
    "TAB_NOT_FOUND",
    "TAB_NOT_READY",
    "TAB_OPEN_FAILED",
    "BRIDGE_BIND_FAILED",
    "BRIDGE_NOT_LISTENING",
    "NO_CURRENT_WINDOW",
    "EXTENSION_NOT_CONNECTED",
}

CHROME_CLOSE_EXACT_TAB_SCRIPT = r"""
on run argv
    set targetURL to item 1 of argv
    set targetTitle to item 2 of argv
    set urlMatchCount to 0
    set urlMatchWindow to 0
    set urlMatchTab to 0
    set exactMatchCount to 0
    set exactMatchWindow to 0
    set exactMatchTab to 0
    tell application "Google Chrome"
        repeat with windowIndex from 1 to count windows
            set currentWindow to window windowIndex
            repeat with tabIndex from 1 to count tabs of currentWindow
                set currentTab to tab tabIndex of currentWindow
                if (URL of currentTab as text) is targetURL then
                    set urlMatchCount to urlMatchCount + 1
                    set urlMatchWindow to windowIndex
                    set urlMatchTab to tabIndex
                    if (title of currentTab as text) is targetTitle then
                        set exactMatchCount to exactMatchCount + 1
                        set exactMatchWindow to windowIndex
                        set exactMatchTab to tabIndex
                    end if
                end if
            end repeat
        end repeat
        if exactMatchCount is 1 then
            close tab exactMatchTab of window exactMatchWindow
            return "closed"
        end if
        if urlMatchCount is 1 then
            close tab urlMatchTab of window urlMatchWindow
            return "closed"
        end if
    end tell
    return "matches:" & urlMatchCount
end run
"""


def sleep_between(low: float = 0.8, high: float = 1.8) -> None:
    time.sleep(random.uniform(low, high))
def is_chrome_running() -> bool:
    result = subprocess.run(
        ["pgrep", "-f", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    return result.returncode == 0


def chrome_window_count() -> int:
    result = subprocess.run(
        ["osascript", "-e", 'tell application "Google Chrome" to count of windows'],
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    if result.returncode != 0:
        return 0
    try:
        return int(str(result.stdout or "").strip() or "0")
    except ValueError:
        return 0


def close_unique_chrome_tab(url: str, title: str) -> bool:
    if sys.platform != "darwin" or not url:
        return False
    result = subprocess.run(
        ["osascript", "-e", CHROME_CLOSE_EXACT_TAB_SCRIPT, url, title],
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    return result.returncode == 0 and str(result.stdout or "").strip() == "closed"


def ensure_chrome_app_running(
    timeout_secs: float = 12.0,
    allow_launch: bool = DEFAULT_ALLOW_VISIBLE_RECOVERY,
) -> None:
    if is_chrome_running():
        return
    if not allow_launch:
        raise ActionBookFailure("CHROME_NOT_RUNNING", "Google Chrome is not running. Open Chrome yourself, then retry.")
    log("未检测到 Chrome 进程，直接打开 Chrome 应用")
    run_command(["open", "-a", CHROME_APP_NAME], timeout=10.0)
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        if is_chrome_running():
            sleep_between(1.0, 1.6)
            return
        sleep_between(0.4, 0.8)
    raise ActionBookFailure("CHROME_START_FAILED", "Google Chrome did not start after opening the app directly")


def ensure_chrome_window(
    timeout_secs: float = 12.0,
    allow_create: bool = DEFAULT_ALLOW_VISIBLE_RECOVERY,
) -> None:
    ensure_chrome_app_running(timeout_secs=timeout_secs, allow_launch=allow_create)
    if chrome_window_count() > 0:
        return
    if not allow_create:
        raise ActionBookFailure(
            "NO_CURRENT_WINDOW",
            "Google Chrome has no browser window available. Open a Chrome window yourself, then retry.",
        )
    run_command(["osascript", "-e", 'tell application "Google Chrome" to make new window'], timeout=10.0, check=False)
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        if chrome_window_count() > 0:
            sleep_between(1.0, 1.6)
            return
        sleep_between(0.4, 0.8)
    raise ActionBookFailure("NO_CURRENT_WINDOW", "Google Chrome is running but no browser window became available")


def find_profiles_with_actionbook_extension() -> list[str]:
    root = chrome_root()
    if not root.exists():
        return []
    report = inspect_profiles(root)
    return [
        str(profile.get("profile") or "")
        for profile in report.get("profiles") or []
        if isinstance(profile, dict) and profile.get("records")
    ]


def current_actionbook_extension_hint() -> str:
    root = chrome_root()
    if not root.exists():
        return "Chrome profile directory does not exist yet. Open Chrome, load actionbook-extension-v0.5.0, then retry."
    report = inspect_profiles(root)
    selected = str(report.get("selected_profile_directory") or "").strip()
    profiles = report.get("profiles") or []
    selected_profile = next(
        (
            profile
            for profile in profiles
            if isinstance(profile, dict) and str(profile.get("profile") or "").strip() == selected
        ),
        None,
    )
    broken_paths: list[str] = []
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        for record in profile.get("records") or []:
            if not isinstance(record, dict):
                continue
            active = record.get("secure_preferences") or record.get("preferences") or {}
            if active.get("record_status") == "broken_path" and active.get("path"):
                broken_paths.append(f"{profile.get('profile')}: {active.get('path')}")
    if isinstance(selected_profile, dict) and selected_profile.get("records"):
        for record in selected_profile.get("records") or []:
            if not isinstance(record, dict):
                continue
            active = record.get("secure_preferences") or record.get("preferences") or {}
            status = str(active.get("record_status") or "").strip()
            path_value = str(active.get("path") or "").strip()
            if status == "broken_path" and path_value:
                return (
                    f"Selected Chrome profile '{selected}' still points at a missing ActionBook unpacked extension path: "
                    f"{path_value}. Reload actionbook-extension-v0.5.0 for that profile in chrome://extensions, then retry."
                )
        return (
            f"Selected Chrome profile '{selected}' has ActionBook extension metadata, but it is not connected. "
            "Open the extension popup in that profile and confirm it shows Connected."
        )
    if broken_paths:
        return (
            "Chrome still has stale ActionBook extension records with missing unpacked paths: "
            + "; ".join(broken_paths)
            + ". Remove or reload those unpacked installs in chrome://extensions for the profile you are actually using."
        )
    return "No Chrome profile currently shows an ActionBook unpacked extension record. Load actionbook-extension-v0.5.0 in chrome://extensions for the profile you are actually running."


def parse_actionbook_output(output: str) -> Any:
    envelope = parse_json_output(output)
    return unwrap_actionbook_envelope(envelope)


def unwrap_actionbook_envelope(envelope: Any) -> Any:
    if not isinstance(envelope, dict) or "ok" not in envelope:
        return envelope
    if not envelope.get("ok"):
        error = envelope.get("error") or {}
        if isinstance(error, dict):
            raise ActionBookFailure(
                str(error.get("code") or "ACTIONBOOK_ERROR"),
                str(error.get("message") or json.dumps(error, ensure_ascii=False)),
                details=error,
            )
        raise ActionBookFailure("ACTIONBOOK_ERROR", json.dumps(envelope, ensure_ascii=False))
    data = envelope.get("data")
    if isinstance(data, dict) and "value" in data:
        return data.get("value")
    return data


class ActionBookSession:
    def __init__(
        self,
        session: str,
        tab: str = "",
        allow_adopt: bool = False,
        allow_visible_recovery: bool = DEFAULT_ALLOW_VISIBLE_RECOVERY,
    ) -> None:
        self.session = session
        self.tab = tab
        self.allow_adopt = allow_adopt
        self.allow_visible_recovery = allow_visible_recovery

    @classmethod
    def owned(cls, session: str, tab: str) -> "ActionBookSession":
        return cls(session, tab, allow_adopt=False, allow_visible_recovery=False)

    @classmethod
    def bootstrap(
        cls,
        session: str,
        *,
        adopt_running_session: bool,
        allow_visible_recovery: bool,
    ) -> "ActionBookSession":
        return cls(
            session,
            allow_adopt=adopt_running_session,
            allow_visible_recovery=allow_visible_recovery,
        )

    def start(self, url: str, force_new_tab: bool = False) -> None:
        ensure_chrome_app_running(allow_launch=self.allow_visible_recovery)
        self._check_extension(require_connected=False)
        last_error: BaseException | None = None
        adopt_attempted = False
        for attempt in range(3):
            try:
                if force_new_tab:
                    if self._session_exists():
                        new_tab = self._open_new_tab(url)
                        if not new_tab:
                            raise ActionBookFailure("TAB_OPEN_FAILED", f"failed to open new tab: {url}")
                        self.tab = new_tab
                    elif self.allow_adopt and not adopt_attempted and self._adopt_running_session(url, force_new_tab=True):
                        adopt_attempted = True
                    else:
                        adopt_attempted = True
                        self._start_new_session(url)
                        self.tab = self._wait_for_accessible_tab(preferred_tab=self.tab or None, target_url=url)
                        if not self.tab:
                            raise ActionBookFailure(
                                "TAB_NOT_READY",
                                f"session started but no accessible tab found: session={self.session}",
                            )
                    self._finalize_start(url, preserve_tab=True)
                    return
                self._recover_or_attach(url)
                adopt_attempted = True
                self._finalize_start(url)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < 2 and self._is_recoverable_start_error(exc):
                    if self.allow_adopt and not adopt_attempted and self._adopt_running_session(url, force_new_tab=force_new_tab):
                        self._finalize_start(url, preserve_tab=force_new_tab)
                        return
                    if self._is_extension_connectivity_error(exc):
                        log("ActionBook extension 冷启动未连上，短时轮询后重试")
                        try:
                            self._wait_for_extension_connection(timeout_secs=12.0)
                        except Exception as wait_exc:  # noqa: BLE001
                            last_error = wait_exc
                    log(f"ActionBook 会话恢复失败，准备重试: {last_error}")
                    self._safe_close_session()
                    sleep_between(0.8, 1.4)
                    continue
                break
        if last_error is not None:
            raise last_error
        raise ActionBookFailure("SESSION_START_FAILED", "failed to start ActionBook extension session")

    def _finalize_start(self, url: str, preserve_tab: bool = False) -> None:
        if preserve_tab:
            self._wait_for_stable_session(target_url=url, required_tab=self.tab)
        else:
            self._wait_for_stable_session(target_url=url)
        self._ensure_target_url(url)

    def goto(self, url: str) -> None:
        self.browser("goto", url, timeout=45.0)

    def open_new_tab(self, url: str, switch: bool = False) -> str:
        tab_id = self._open_new_tab(url)
        if not tab_id:
            raise ActionBookFailure("TAB_OPEN_FAILED", f"failed to open new tab: {url}")
        if switch:
            self.tab = tab_id
        return tab_id

    def eval(self, script: str, timeout: float = 30.0) -> Any:
        return self.browser("eval", script, timeout=timeout)

    def browser(self, subcommand: str, *args: str, timeout: float = 30.0, tab: str | None = None) -> Any:
        active_tab = tab or self.tab
        if not active_tab:
            raise ActionBookFailure("TAB_NOT_READY", f"ActionBook tab is not ready for session {self.session!r}")
        envelope = self._run_browser_command(subcommand, *args, timeout=timeout, tab=active_tab)
        return unwrap_actionbook_envelope(envelope)

    def describe(self, tab: str | None = None) -> dict[str, str]:
        active_tab = tab or self.tab
        if not active_tab:
            raise RuntimeError(f"ActionBook tab is not ready for session {self.session!r}")
        return {
            "session_id": self.session,
            "tab_id": active_tab,
            "url": str(self.browser("url", timeout=10.0, tab=active_tab) or ""),
            "title": str(self.browser("title", timeout=10.0, tab=active_tab) or ""),
        }

    def list_tabs(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for tab in self._list_tabs():
            if not isinstance(tab, dict):
                continue
            tab_id = str(tab.get("tab_id") or tab.get("tabId") or tab.get("id") or "").strip()
            if not tab_id:
                continue
            items.append(
                {
                    "tab_id": tab_id,
                    "url": str(tab.get("url") or "").strip(),
                    "title": str(tab.get("title") or "").strip(),
                    "active": "true" if tab_id == self.tab else "false",
                }
            )
        return items

    def use_tab(self, tab_id: str) -> dict[str, str]:
        tab_id = str(tab_id or "").strip()
        if not tab_id:
            raise ValueError("tab id is required")
        if not self._is_tab_accessible(tab_id):
            raise ActionBookFailure("TAB_NOT_FOUND", f"tab is not accessible: {tab_id}")
        self.tab = tab_id
        return self.describe()

    def close_tab(self, tab_id: str) -> dict[str, str]:
        tab_id = str(tab_id or "").strip()
        if not tab_id:
            raise ValueError("tab id is required")
        envelope = self._run_raw_command(
            ["actionbook", "browser", "close-tab", "--session", self.session, "--tab", tab_id, "--json"],
            timeout=15.0,
        )
        if envelope is None:
            raise ActionBookFailure("TAB_CLOSE_FAILED", f"failed to close tab: {tab_id}")
        if isinstance(envelope, str):
            raise ActionBookFailure("ACTIONBOOK_PROTOCOL_ERROR", envelope or f"failed to close tab: {tab_id}")
        unwrap_actionbook_envelope(envelope)
        if self.tab == tab_id:
            self.tab = ""
        return {"session_id": self.session, "tab_id": tab_id, "status": "closed"}

    def _recover_or_attach(self, url: str) -> None:
        existing_tab = self._find_accessible_tab(preferred_tab=self.tab or None, target_url=url)
        if existing_tab:
            self.tab = existing_tab
            return
        if self._session_exists():
            new_tab = self._open_new_tab(url)
            if new_tab:
                self.tab = new_tab
                return
            log(f"发现空会话或失效 tab，关闭并重建: session={self.session}")
            self._safe_close_session()
        if self.allow_adopt and self._adopt_running_session(url):
            return
        self._start_new_session(url)
        tab_id = self._wait_for_accessible_tab(preferred_tab=self.tab or None, target_url=url)
        if not tab_id:
            raise ActionBookFailure(
                "TAB_NOT_READY",
                f"session started but no accessible tab found: session={self.session}",
            )
        self.tab = tab_id

    def _start_new_session(self, url: str) -> None:
        commands = [
            [
                "actionbook",
                "browser",
                "start",
                "--mode",
                "extension",
                "--session",
                self.session,
                "--open-url",
                url,
                "--timeout",
                "30000",
                "--json",
            ],
            [
                "actionbook",
                "browser",
                "start",
                "--mode",
                "extension",
                "--set-session-id",
                self.session,
                "--open-url",
                url,
                "--timeout",
                "30000",
                "--json",
            ],
        ]
        last_error: BaseException | None = None
        for command in commands:
            for attempt in range(2):
                try:
                    envelope = self._run_raw_command(command, timeout=35.0)
                    data = unwrap_actionbook_envelope(envelope)
                    if isinstance(data, dict):
                        tab_info = data.get("tab") if isinstance(data.get("tab"), dict) else {}
                        tab_id = str((tab_info or {}).get("tab_id") or "").strip()
                        if tab_id:
                            self.tab = tab_id
                    if not self._session_exists():
                        raise ActionBookFailure(
                            "SESSION_NOT_FOUND",
                            f"session started but not registered: session={self.session}",
                        )
                    if not self._session_is_reachable():
                        raise ActionBookFailure(
                            "SESSION_NOT_READY",
                            f"session started but is not reachable: session={self.session}",
                        )
                    sleep_between(0.8, 1.2)
                    return
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if has_failure_code(exc, {"NO_CURRENT_WINDOW"}):
                        if not self.allow_visible_recovery:
                            break
                        log("Chrome 已连接但没有可用窗口，补一个窗口后重试 browser start")
                        ensure_chrome_window(allow_create=True)
                    if attempt == 0 and self._is_recoverable_start_error(exc):
                        sleep_between(0.8, 1.4)
                        continue
                    break
        if last_error is not None:
            raise last_error
        raise ActionBookFailure("SESSION_START_FAILED", "failed to start ActionBook extension session")

    def _run_raw_command(self, command: list[str], timeout: float = 30.0) -> Any:
        return parse_json_output(run_command(command, timeout=timeout, check=False))

    def _run_browser_command(
        self,
        subcommand: str,
        *args: str,
        timeout: float = 30.0,
        tab: str | None = None,
    ) -> Any:
        command = ["actionbook", "browser", subcommand, *args, "--session", self.session]
        if tab:
            command.extend(["--tab", tab])
        command.append("--json")
        return self._run_raw_command(command, timeout=timeout)

    def _session_exists(self) -> bool:
        sessions = self._list_sessions()
        return any(
            isinstance(item, dict) and str(item.get("session_id") or "") == self.session
            for item in sessions
        )

    def _session_is_reachable(self) -> bool:
        envelope = self._run_browser_command("status", timeout=10.0)
        data = unwrap_actionbook_envelope(envelope)
        session = data.get("session") if isinstance(data, dict) else None
        return isinstance(session, dict) and str(session.get("session_id") or "") == self.session

    def _wait_for_stable_session(
        self,
        target_url: str = "",
        timeout_secs: float = 8.0,
        required_tab: str = "",
    ) -> None:
        deadline = time.time() + timeout_secs
        last_error: BaseException | None = None
        while time.time() < deadline:
            try:
                self._check_extension(timeout_secs=1.5, require_connected=True)
                if not self._session_is_reachable():
                    raise ActionBookFailure(
                        "SESSION_NOT_READY",
                        f"session is not reachable yet: session={self.session}",
                    )
                if required_tab:
                    tab_id = required_tab if self._is_tab_accessible(required_tab) else ""
                else:
                    tab_id = self._find_accessible_tab(preferred_tab=self.tab or None, target_url=target_url)
                if not tab_id:
                    raise ActionBookFailure(
                        "TAB_NOT_READY",
                        f"session is reachable but no accessible tab is ready: session={self.session}",
                    )
                self.tab = tab_id
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                sleep_between(0.3, 0.6)
        if last_error is not None:
            raise last_error
        raise ActionBookFailure("SESSION_NOT_READY", f"session did not become stable: session={self.session}")

    def _list_sessions(self) -> list[dict[str, Any]]:
        envelope = self._run_raw_command(
            ["actionbook", "browser", "list-sessions", "--json"],
            timeout=10.0,
        )
        data = unwrap_actionbook_envelope(envelope)
        sessions = data.get("sessions") if isinstance(data, dict) else None
        return sessions if isinstance(sessions, list) else []

    def _list_tabs(self) -> list[dict[str, Any]]:
        envelope = self._run_browser_command("list-tabs", timeout=10.0)
        if isinstance(envelope, dict) and envelope.get("ok") is False:
            error = envelope.get("error") or {}
            if isinstance(error, dict) and error.get("code") == "SESSION_NOT_FOUND":
                return []
        data = unwrap_actionbook_envelope(envelope)
        tabs = data.get("tabs") if isinstance(data, dict) else None
        return tabs if isinstance(tabs, list) else []

    def _find_accessible_tab(self, preferred_tab: str | None = None, target_url: str = "") -> str:
        tabs = self._list_tabs()
        if not tabs:
            return ""
        tab_urls = {
            str(tab.get("tab_id") or "").strip(): str(tab.get("url") or "").strip()
            for tab in tabs
            if isinstance(tab, dict) and str(tab.get("tab_id") or "").strip()
        }
        target_origin = self._origin_key(target_url)
        ordered_tab_ids: list[str] = []
        if preferred_tab:
            ordered_tab_ids.append(preferred_tab)
        ordered_tab_ids.extend(
            str(tab.get("tab_id") or "").strip()
            for tab in tabs
            if isinstance(tab, dict)
            and str(tab.get("tab_id") or "").strip()
            and (
                not target_origin
                or self._origin_key(str(tab.get("url") or "")) == target_origin
            )
        )
        seen: set[str] = set()
        for tab_id in ordered_tab_ids:
            if not tab_id or tab_id in seen:
                continue
            seen.add(tab_id)
            if target_origin and self._origin_key(tab_urls.get(tab_id, "")) != target_origin:
                continue
            if self._is_tab_accessible(tab_id):
                return tab_id
        return ""

    def _wait_for_accessible_tab(
        self,
        preferred_tab: str | None = None,
        target_url: str = "",
        timeout_secs: float = 12.0,
    ) -> str:
        deadline = time.time() + timeout_secs
        last_error: BaseException | None = None
        while time.time() < deadline:
            try:
                tab_id = self._find_accessible_tab(preferred_tab=preferred_tab, target_url=target_url)
                if tab_id:
                    return tab_id
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            sleep_between(0.4, 0.8)
        if last_error is not None:
            raise last_error
        return ""

    def _open_new_tab(self, url: str, timeout_secs: float = 15.0) -> str:
        before_tabs = {
            str(tab.get("tab_id") or "").strip()
            for tab in self._list_tabs()
            if isinstance(tab, dict)
        }
        command = [
            "actionbook",
            "browser",
            "new-tab",
            url,
            "--session",
            self.session,
            "--timeout",
            "30000",
            "--json",
        ]
        try:
            envelope = self._run_raw_command(command, timeout=35.0)
            data = unwrap_actionbook_envelope(envelope)
        except ActionBookFailure as exc:
            if not has_failure_code(exc, {"NO_CURRENT_WINDOW"}):
                raise
            if not self.allow_visible_recovery:
                raise ActionBookFailure(
                    "NO_CURRENT_WINDOW",
                    "Chrome 已连接但没有可用窗口。为避免打断用户当前工作，helper 不会自动创建可见窗口；请手动打开 Chrome 窗口后重试。"
                ) from exc
            log("Chrome 已连接但没有可用窗口，直接打开 Chrome 窗口后重试")
            ensure_chrome_window(allow_create=True)
            envelope = self._run_raw_command(command, timeout=35.0)
            data = unwrap_actionbook_envelope(envelope)
        returned_tab = self._extract_tab_id(data)
        if returned_tab and self._is_tab_accessible(returned_tab):
            return returned_tab
        deadline = time.time() + timeout_secs
        while time.time() < deadline:
            tabs = self._list_tabs()
            new_tab_ids = [
                str(tab.get("tab_id") or "").strip()
                for tab in tabs
                if isinstance(tab, dict) and str(tab.get("tab_id") or "").strip() not in before_tabs
            ]
            for tab_id in new_tab_ids:
                if self._is_tab_accessible(tab_id):
                    return tab_id
            sleep_between(0.4, 0.8)
        return ""

    def _adopt_running_session(self, url: str, force_new_tab: bool = False) -> bool:
        original_session = self.session
        original_tab = self.tab
        for item in self._list_sessions():
            if not isinstance(item, dict):
                continue
            session_id = str(item.get("session_id") or "").strip()
            if not session_id or session_id == original_session:
                continue
            if str(item.get("mode") or "") != "extension":
                continue
            if str(item.get("status") or "").lower() != "running":
                continue
            self.session = session_id
            self.tab = ""
            try:
                if not force_new_tab:
                    tab_id = self._find_accessible_tab(target_url=url)
                    if tab_id:
                        self.tab = tab_id
                        log(f"复用现有扩展会话: session={self.session} tab={self.tab}")
                        return True
                fresh_tab = self._open_new_tab(url)
                if fresh_tab:
                    self.tab = fresh_tab
                    log(f"复用现有扩展会话: session={self.session} tab={self.tab}")
                    return True
            except Exception:
                continue
        self.session = original_session
        self.tab = original_tab
        return False

    def _is_tab_accessible(self, tab_id: str) -> bool:
        try:
            self.browser("title", timeout=10.0, tab=tab_id)
            current_url = str(self.browser("url", timeout=10.0, tab=tab_id) or "")
            if current_url.startswith(("chrome://", "chrome-extension://", "devtools://")):
                return False
            return True
        except Exception:
            return False

    def _safe_close_session(self) -> None:
        if not self._session_exists():
            return
        run_command(
            ["actionbook", "browser", "close", "--session", self.session],
            timeout=15.0,
            check=False,
        )
        self.tab = ""

    @staticmethod
    def _extract_tab_id(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        candidates = [
            data.get("tab_id"),
            data.get("tabId"),
            data.get("id"),
        ]
        tab = data.get("tab")
        if isinstance(tab, dict):
            candidates.extend([tab.get("tab_id"), tab.get("tabId"), tab.get("id")])
        for candidate in candidates:
            tab_id = str(candidate or "").strip()
            if tab_id:
                return tab_id
        return ""

    def _ensure_target_url(self, url: str) -> None:
        if not self.tab:
            raise ActionBookFailure("TAB_NOT_READY", f"ActionBook tab is not ready for session {self.session!r}")
        try:
            current_url = str(self.browser("url", timeout=10.0) or "").strip()
        except ActionBookFailure as exc:
            if not has_failure_code(exc, {"CHROME_URL_BLOCKED"}):
                raise
            current_url = ""
        target = self._normalize_url(url)
        current = self._normalize_url(current_url)
        if current == target:
            return
        self.goto(url)

    def _wait_for_extension_connection(self, timeout_secs: float = 12.0) -> None:
        ensure_chrome_window(timeout_secs=timeout_secs, allow_create=self.allow_visible_recovery)
        self._check_extension(timeout_secs=timeout_secs, require_connected=True)

    def _check_extension(self, timeout_secs: float = 8.0, require_connected: bool = True) -> None:
        deadline = time.time() + timeout_secs
        last_output = ""
        while time.time() < deadline:
            output = run_command(["actionbook", "extension", "status", "--json"], timeout=10.0, check=False)
            last_output = output
            try:
                data = parse_actionbook_output(output)
            except Exception:
                sleep_between(0.4, 0.7)
                continue
            if (
                isinstance(data, dict)
                and data.get("bridge") == "listening"
                and data.get("extension_connected") is True
            ):
                return
            if not require_connected and isinstance(data, dict):
                log(
                    "ActionBook extension 尚未连接，继续尝试 browser start 触发 bridge: "
                    f"bridge={data.get('bridge')} connected={data.get('extension_connected')}"
                )
                return
            sleep_between(0.4, 0.7)
        installed_profiles = find_profiles_with_actionbook_extension()
        if installed_profiles:
            install_hint = (
                "Detected ActionBook extension metadata in Chrome profiles: "
                + ", ".join(installed_profiles)
                + f". {current_actionbook_extension_hint()}"
            )
        else:
            install_hint = current_actionbook_extension_hint()
        raise ActionBookFailure(
            "EXTENSION_NOT_CONNECTED",
            "ActionBook extension is not connected. Open Chrome with the extension connected, then retry. "
            f"{install_hint} last_status={last_output}"
        )

    @staticmethod
    def _is_recoverable_start_error(error: BaseException) -> bool:
        return has_failure_code(error, RECOVERABLE_START_CODES)

    @staticmethod
    def _is_extension_connectivity_error(error: BaseException) -> bool:
        return has_failure_code(error, {"EXTENSION_NOT_CONNECTED", "BRIDGE_NOT_LISTENING"})

    @staticmethod
    def _normalize_url(value: str) -> str:
        return str(value or "").strip().rstrip("/")

    @staticmethod
    def _origin_key(value: str) -> str:
        parsed = urlparse(str(value or ""))
        if not parsed.scheme or not parsed.netloc:
            return ""
        hostname = parsed.hostname or ""
        if hostname.startswith("www."):
            hostname = hostname[4:]
        return f"{parsed.scheme}://{hostname}"

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ensure a usable ActionBook extension session/tab for browser tasks."
    )
    subparsers = parser.add_subparsers(dest="command")

    ensure = subparsers.add_parser("ensure", help="Ensure a usable session and tab")
    ensure.set_defaults(command="ensure")
    add_session_tab_args(
        ensure,
        default_session=DEFAULT_SESSION,
        session_help="Preferred ActionBook session id",
        tab_help="Preferred ActionBook tab id; auto-detect when omitted",
    )
    ensure.add_argument("--url", default="about:blank", help="Target URL to open or attach to")
    ensure.add_argument("--force-new-tab", action="store_true", help="Always open a new tab in an existing session")
    ensure.add_argument(
        "--no-adopt",
        action="store_true",
        help="Do not adopt another running session; explicit --session already disables cross-session adoption",
    )
    ensure.add_argument(
        "--adopt-running-session",
        action="store_true",
        help="Opt in to reusing another running extension session when the named session cannot be created or recovered",
    )
    ensure.add_argument(
        "--allow-visible-recovery",
        action="store_true",
        default=DEFAULT_ALLOW_VISIBLE_RECOVERY,
        help="Allow cold-start recovery to launch Chrome or create one visible window (default)",
    )
    ensure.add_argument("--json", action="store_true", help="Print final session state as JSON")

    list_tabs = subparsers.add_parser("list-tabs", help="List accessible tabs in a session")
    add_session_tab_args(
        list_tabs,
        default_session=DEFAULT_SESSION,
        session_help="ActionBook session id",
        tab_help="Current tab id to mark as active",
    )
    list_tabs.add_argument("--json", action="store_true", help="Print tabs as JSON")

    new_tab = subparsers.add_parser("new-tab", help="Open a new tab in a session")
    add_session_tab_args(
        new_tab,
        default_session=DEFAULT_SESSION,
        session_help="ActionBook session id",
        tab_help="Current tab id",
    )
    new_tab.add_argument("--url", required=True, help="Target URL for the new tab")
    new_tab.add_argument("--switch", action="store_true", help="Update the current tab pointer to the new tab")
    new_tab.add_argument(
        "--allow-visible-recovery",
        action="store_true",
        default=DEFAULT_ALLOW_VISIBLE_RECOVERY,
        help="Allow cold-start recovery to create one visible Chrome window (default)",
    )
    new_tab.add_argument("--json", action="store_true", help="Print the new tab state as JSON")

    select_tab = subparsers.add_parser("select-tab", help="Verify and select an existing tab")
    select_tab.add_argument("--session", default=DEFAULT_SESSION, help="ActionBook session id")
    select_tab.add_argument("--tab", required=True, help="Existing ActionBook tab id")
    select_tab.add_argument("--json", action="store_true", help="Print selected tab state as JSON")

    close_tab = subparsers.add_parser("close-tab", help="Close one tab in a session")
    close_tab.add_argument("--session", default=DEFAULT_SESSION, help="ActionBook session id")
    close_tab.add_argument("--tab", required=True, help="Existing ActionBook tab id")
    close_tab.add_argument("--json", action="store_true", help="Print close result as JSON")

    acquire_tab = subparsers.add_parser("acquire-tab", help="Acquire one tracked tab for a task")
    acquire_tab.add_argument("--task", required=True, help="Stable task id that owns the tab")
    acquire_tab.add_argument("--session", default=DEFAULT_SESSION, help="Shared ActionBook session id")
    acquire_tab.add_argument("--url", default="about:blank", help="Initial URL for a newly acquired tab")
    acquire_tab.add_argument(
        "--adopt-running-session",
        action="store_true",
        help="Allow reuse of another healthy extension session when the named session is unavailable",
    )
    acquire_tab.add_argument(
        "--allow-visible-recovery",
        action="store_true",
        default=DEFAULT_ALLOW_VISIBLE_RECOVERY,
        help="Allow cold-start recovery to launch Chrome or create one visible window (default)",
    )
    acquire_tab.add_argument("--json", action="store_true", help="Print the task tab record as JSON")

    release_tab = subparsers.add_parser("release-tab", help="Close and release the tab owned by a task")
    release_tab.add_argument("--task", required=True, help="Task id that owns the tab")
    release_tab.add_argument("--json", action="store_true", help="Print the release result as JSON")

    list_owned_tabs_parser = subparsers.add_parser("list-owned-tabs", help="List tracked owned-tab leases")
    list_owned_tabs_parser.add_argument("--json", action="store_true", help="Print owned tabs as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_args = list(argv if argv is not None else sys.argv[1:])
    if not raw_args:
        raw_args = ["ensure"]
    elif raw_args[0].startswith("-"):
        raw_args = ["ensure", *raw_args]
    args = parser.parse_args(raw_args)
    if args.command == "ensure":
        allow_cross_session_adopt = not args.no_adopt and (
            args.session == DEFAULT_SESSION or args.adopt_running_session
        )
        session = ActionBookSession(
            args.session,
            args.tab,
            allow_adopt=allow_cross_session_adopt,
            allow_visible_recovery=args.allow_visible_recovery,
        )
        session.start(args.url, force_new_tab=args.force_new_tab)
        state = session.describe()
    elif args.command == "list-tabs":
        session = ActionBookSession(args.session, args.tab, allow_adopt=False)
        state = {
            "session_id": session.session,
            "current_tab_id": session.tab,
            "tabs": session.list_tabs(),
        }
    elif args.command == "new-tab":
        session = ActionBookSession(
            args.session,
            args.tab,
            allow_adopt=False,
            allow_visible_recovery=args.allow_visible_recovery,
        )
        tab_id = session.open_new_tab(args.url, switch=args.switch)
        state = session.describe(tab=tab_id)
        state["current_tab_id"] = session.tab
    elif args.command == "select-tab":
        session = ActionBookSession(args.session, args.tab, allow_adopt=False)
        state = session.use_tab(args.tab)
    elif args.command == "close-tab":
        session = ActionBookSession(args.session, args.tab, allow_adopt=False)
        state = session.close_tab(args.tab)
    elif args.command == "acquire-tab":
        from scripts.owned_tab_lifecycle import acquire_owned_tab

        state = acquire_owned_tab(
            task_id=args.task,
            session_id=args.session,
            url=args.url,
            adopt_running_session=args.adopt_running_session,
            allow_visible_recovery=args.allow_visible_recovery,
        )
    elif args.command == "release-tab":
        from scripts.owned_tab_lifecycle import release_owned_tab

        state = release_owned_tab(args.task)
    elif args.command == "list-owned-tabs":
        from scripts.owned_tab_lifecycle import list_owned_tabs

        state = list_owned_tabs()
    else:
        raise RuntimeError(f"unsupported command: {args.command}")

    if getattr(args, "json", False):
        print(json.dumps(state, ensure_ascii=False, indent=2))
    elif isinstance(state, dict) and "owned_tabs" in state:
        for record in state["owned_tabs"]:
            print(
                f"task={record.get('task_id', '')}\tsession={record.get('session_id', '')}"
                f"\ttab={record.get('tab_id', '')}\turl={record.get('url', '')}"
            )
    elif isinstance(state, dict) and "task_id" in state:
        print(f"task={state['task_id']}")
        print(f"status={state['status']}")
        if state.get("session_id"):
            print(f"session={state['session_id']}")
        if state.get("tab_id"):
            print(f"tab={state['tab_id']}")
    elif isinstance(state, dict) and "tabs" in state:
        print(f"session={state['session_id']}")
        print(f"current_tab={state['current_tab_id']}")
        for tab in state["tabs"]:
            print(f"tab={tab['tab_id']}\tactive={tab['active']}\turl={tab['url']}\ttitle={tab['title']}")
    else:
        print(f"session={state['session_id']}")
        print(f"tab={state['tab_id']}")
        print(f"url={state['url']}")
        print(f"title={state['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
