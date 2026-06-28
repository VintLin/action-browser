# Browser Task Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a narrow, reliable browser task control plane that gives Action Browser durable task state, exclusive tab leases, conservative recovery, and one real site integration without rewriting the existing workflow system.

**Architecture:** The implementation adds a new scheduler control layer under `scripts/scheduler.py` and `scripts/scheduler_lib/` while keeping `actionbook_session.py`, `actionbook_run.py`, and existing `*_workflow.py` scripts as the current execution substrate. The scheduler owns task lifecycle, state persistence, file locking, exclusive tab leases, reconciliation, and run tracking; the agent still chooses whether to use direct browser actions or a site adapter. First pass only integrates one site adapter, `taobao_workflow.py`, through a thin `summary/progress/artifacts` contract.

**Tech Stack:** Python 3, pytest, ActionBook CLI, JSON file persistence, file locks via stdlib `fcntl`, existing `scripts/actionbook_session.py`, existing `scripts/actionbook_run.py`

---

## File Structure

**Create:**

- `docs/superpowers/plans/2026-06-28-browser-task-scheduler.md`
- `references/task-lifecycle.md`
- `references/adapter-authoring.md`
- `scripts/scheduler.py`
- `scripts/scheduler_lib/__init__.py`
- `scripts/scheduler_lib/contracts.py`
- `scripts/scheduler_lib/state.py`
- `scripts/scheduler_lib/lease.py`
- `scripts/scheduler_lib/lifecycle.py`
- `scripts/scheduler_lib/executor.py`
- `scripts/scheduler_lib/reconcile.py`
- `tests/test_scheduler_state.py`
- `tests/test_scheduler_cli.py`
- `tests/test_scheduler_reconcile.py`
- `tests/test_taobao_adapter_contract.py`

**Modify:**

- `SKILL.md`
- `README.md`
- `scripts/actionbook_session.py`
- `scripts/adapters/taobao_workflow.py`
- `tests/test_actionbook_session.py`

**Keep unchanged in first pass:**

- other `scripts/*_workflow.py`
- `scripts/actionbook_run.py` behavior except direct reuse from scheduler
- site references outside Taobao

### Task 1: Freeze First-Pass Schema And Documentation

**Files:**
- Create: `references/task-lifecycle.md`
- Create: `references/adapter-authoring.md`
- Test: none

- [ ] **Step 1: Write the lifecycle reference before code**

Write `references/task-lifecycle.md` with the concrete first-pass states, stage meanings, lease rules, concurrency caps, and reconciliation outcomes.

```md
# Task Lifecycle

## Statuses

- `queued`
- `running`
- `waiting_user`
- `blocked`
- `completed`
- `failed`
- `canceled`

## Result Quality

Completed tasks may still set:

```json
{
  "result_quality": "partial",
  "completed_items": 8,
  "requested_items": 20
}
```

## Lease Rules

- Scheduler-managed tasks always request `--force-new-tab --no-adopt`
- One running task owns exactly one `lease_id`
- Releasing a lease closes only that task tab

## Recovery Rules

- live run + live tab => `running`
- dead run + valid summary => `completed`
- dead run + no valid summary => `blocked`
- live run + lost tab => stop run, then `failed`
```

- [ ] **Step 2: Write the adapter contract reference**

Write `references/adapter-authoring.md` with the minimum adapter CLI contract and expected output files.

```md
# Adapter Authoring

## Required Inputs

- `--task-id`
- `--session`
- `--tab`
- `--output`

## Required Outputs

- `summary.json`
- `progress.json`
- `artifacts/`

## summary.json

```json
{
  "ok": true,
  "site": "taobao",
  "intent": "search",
  "requested_count": 20,
  "collected_count": 18,
  "artifacts": ["results.json"],
  "warnings": [],
  "needs_user_action": false
}
```
```

- [ ] **Step 3: Review both docs against the spec**

Manual check only. Confirm the docs explicitly cover:

- file-based persistence
- `state.lock`
- `events.jsonl`
- `schema_version`
- `waiting_user`
- `followups`
- same-tab retry ceiling

Expected result: both docs mention all seven items with no `TODO` or `TBD`.

- [ ] **Step 4: Commit the docs slice**

Run:

```bash
git add references/task-lifecycle.md references/adapter-authoring.md
git commit -m "docs: define scheduler lifecycle and adapter contract"
```

Expected: one docs-only commit with two new reference files.

### Task 2: Tighten Session Helper For Exclusive Tabs

**Files:**
- Modify: `scripts/actionbook_session.py`
- Modify: `tests/test_actionbook_session.py`
- Test: `tests/test_actionbook_session.py`

- [ ] **Step 1: Write failing tests for force-new-tab, no-adopt, and close-tab**

Append these tests to `tests/test_actionbook_session.py` first.

```python
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
            return {"session_id": self.session, "tab_id": tab or self.tab, "url": "https://example.com", "title": "Example"}

    monkeypatch.setattr(actionbook_session, "ActionBookSession", FakeSession)

    assert actionbook_session.main(["ensure", "--session", "s1", "--url", "https://example.com", "--force-new-tab", "--no-adopt"]) == 0
    assert events == [("start", "https://example.com|force=True|adopt=False")]


def test_main_close_tab_calls_close_tab(monkeypatch, capsys) -> None:
    events: list[tuple[str, str]] = []

    class FakeSession:
        def __init__(self, session: str, tab: str = "", allow_adopt: bool = True) -> None:
            self.session = session
            self.tab = tab

        def start(self, url: str, force_new_tab: bool = False) -> None:
            events.append(("start", url))

        def close_tab(self, tab_id: str) -> dict[str, str]:
            events.append(("close", tab_id))
            return {"session_id": self.session, "tab_id": tab_id, "status": "closed"}

    monkeypatch.setattr(actionbook_session, "ActionBookSession", FakeSession)

    assert actionbook_session.main(["close-tab", "--session", "s1", "--tab", "tab-9", "--json"]) == 0
    assert events == [("start", "about:blank"), ("close", "tab-9")]
    assert '"status": "closed"' in capsys.readouterr().out
```

- [ ] **Step 2: Run the session tests and verify failure**

Run:

```bash
pytest tests/test_actionbook_session.py -v
```

Expected: FAIL because `main()` does not accept `--force-new-tab`, `--no-adopt`, or `close-tab` yet.

- [ ] **Step 3: Add the minimum session-helper implementation**

Modify `scripts/actionbook_session.py` with the smallest possible interface changes.

```python
class ActionBookSession:
    def start(self, url: str, force_new_tab: bool = False) -> None:
        ensure_chrome_app_running()
        self._check_extension(require_connected=False)
        last_error = ""
        for attempt in range(3):
            try:
                if force_new_tab and self._session_exists():
                    new_tab = self._open_new_tab(url)
                    if new_tab:
                        self.tab = new_tab
                        self._check_extension(require_connected=True)
                        self._ensure_target_url(url)
                        return
                self._recover_or_attach(url)
                self._check_extension(require_connected=True)
                self._ensure_target_url(url)
                return
            except Exception as exc:
                last_error = str(exc)
                if attempt < 2 and self._is_recoverable_start_error(last_error):
                    self._safe_close_session()
                    sleep_between(0.8, 1.4)
                    continue
                break
        raise RuntimeError(last_error or "failed to start ActionBook extension session")

    def close_tab(self, tab_id: str) -> dict[str, str]:
        self._run_raw_command(
            ["actionbook", "browser", "close-tab", "--session", self.session, "--tab", tab_id, "--json"],
            timeout=15.0,
        )
        if self.tab == tab_id:
            self.tab = ""
        return {"session_id": self.session, "tab_id": tab_id, "status": "closed"}
```

Also update CLI parsing:

```python
ensure.add_argument("--force-new-tab", action="store_true")
ensure.add_argument("--no-adopt", action="store_true")

close_tab = subparsers.add_parser("close-tab", help="Close one tab in a session")
close_tab.add_argument("--session", default=DEFAULT_SESSION)
close_tab.add_argument("--tab", required=True)
close_tab.add_argument("--json", action="store_true")
```

And in `main()`:

```python
if args.command == "ensure":
    session = ActionBookSession(args.session, args.tab, allow_adopt=not args.no_adopt)
    session.start(args.url, force_new_tab=args.force_new_tab)
    state = session.describe()
elif args.command == "close-tab":
    session = ActionBookSession(args.session, allow_adopt=False)
    session.start("about:blank")
    state = session.close_tab(args.tab)
```

- [ ] **Step 4: Run the session tests and verify pass**

Run:

```bash
pytest tests/test_actionbook_session.py -v
```

Expected: PASS for old and new tests.

- [ ] **Step 5: Commit the helper changes**

Run:

```bash
git add scripts/actionbook_session.py tests/test_actionbook_session.py
git commit -m "feat: add exclusive tab session controls"
```

Expected: one commit limited to helper and tests.

### Task 3: Build File-Backed Scheduler State And Locking

**Files:**
- Create: `scripts/scheduler_lib/contracts.py`
- Create: `scripts/scheduler_lib/state.py`
- Create: `tests/test_scheduler_state.py`
- Test: `tests/test_scheduler_state.py`

- [ ] **Step 1: Write failing state tests first**

Create `tests/test_scheduler_state.py`.

```python
from pathlib import Path

from scripts.scheduler_lib.state import SchedulerStore, sanitize_id


def test_sanitize_id_matches_run_style() -> None:
    assert sanitize_id(" taobao/search:儿童童书 ") == "taobao_search_儿童童书"


def test_store_writes_schema_and_snapshot(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path)
    task = store.create_task(site="taobao", intent="search", payload={"query": "儿童童书", "limit": 20})

    snapshot = store.load_snapshot()

    assert snapshot["schema_version"] == 1
    assert task["status"] == "queued"
    assert (tmp_path / "state.json").exists()
    assert (tmp_path / "tasks" / f"{task['task_id']}.json").exists()


def test_store_appends_event_before_snapshot(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path)
    task = store.create_task(site="taobao", intent="search", payload={"query": "儿童童书"})
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()

    assert len(lines) >= 1
    assert '"event_type": "task_created"' in lines[0]
    assert task["task_id"] in lines[0]
```

- [ ] **Step 2: Run state tests and verify failure**

Run:

```bash
pytest tests/test_scheduler_state.py -v
```

Expected: FAIL because `scripts.scheduler_lib.state` does not exist yet.

- [ ] **Step 3: Implement the minimum state store and schemas**

Create `scripts/scheduler_lib/contracts.py`.

```python
SCHEMA_VERSION = 1

TERMINAL_STATUSES = {"completed", "failed", "blocked", "canceled"}
RUNNING_STATUSES = {"queued", "running", "waiting_user"}

DEFAULT_LIMITS = {
    "max_running_tasks": 2,
    "max_tabs_per_session": 5,
    "max_running_tasks_per_site": 1,
}
```

Create `scripts/scheduler_lib/state.py`.

```python
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import fcntl

from scripts.scheduler_lib.contracts import DEFAULT_LIMITS, SCHEMA_VERSION


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sanitize_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value or "")).strip("._-")
    if not safe:
        raise ValueError("identifier is empty after sanitization")
    return safe


class SchedulerStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.tasks_dir = self.root / "tasks"
        self.progress_dir = self.root / "progress"
        self.lock_path = self.root / "state.lock"
        self.events_path = self.root / "events.jsonl"
        self.snapshot_path = self.root / "state.json"

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.progress_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def load_snapshot(self) -> dict[str, Any]:
        try:
            return json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"schema_version": SCHEMA_VERSION, "limits": DEFAULT_LIMITS, "tasks": {}, "leases": {}, "updated_at": utc_now()}

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        payload["schema_version"] = SCHEMA_VERSION
        payload["updated_at"] = utc_now()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

    def _append_event(self, payload: dict[str, Any]) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def create_task(self, *, site: str, intent: str, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = sanitize_id(f"{site}_{intent}_{payload.get('query') or payload.get('url') or utc_now()}")
        task = {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "site": site,
            "intent": intent,
            "payload": payload,
            "status": "queued",
            "stage": "triaging",
            "attempts": 0,
            "followups": [],
            "updated_at": utc_now(),
        }
        with self.locked():
            snapshot = self.load_snapshot()
            snapshot["tasks"][task_id] = {"status": task["status"], "stage": task["stage"]}
            self._append_event({"event_type": "task_created", "task_id": task_id, "at": utc_now()})
            self._write_json(self.tasks_dir / f"{task_id}.json", task)
            self._write_json(self.snapshot_path, snapshot)
        return task
```

- [ ] **Step 4: Run state tests and verify pass**

Run:

```bash
pytest tests/test_scheduler_state.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit the state layer**

Run:

```bash
git add scripts/scheduler_lib/contracts.py scripts/scheduler_lib/state.py tests/test_scheduler_state.py
git commit -m "feat: add scheduler state store"
```

Expected: one commit containing only scheduler schema and store logic.

### Task 4: Add Minimum Scheduler CLI, Lease Logic, And Reconcile

**Files:**
- Create: `scripts/scheduler.py`
- Create: `scripts/scheduler_lib/lease.py`
- Create: `scripts/scheduler_lib/lifecycle.py`
- Create: `scripts/scheduler_lib/reconcile.py`
- Create: `tests/test_scheduler_cli.py`
- Create: `tests/test_scheduler_reconcile.py`
- Test: `tests/test_scheduler_cli.py`
- Test: `tests/test_scheduler_reconcile.py`

- [ ] **Step 1: Write failing CLI and reconcile tests**

Create `tests/test_scheduler_cli.py`.

```python
from pathlib import Path

from scripts import scheduler


def test_submit_creates_task_and_prints_id(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ACTION_BROWSER_SCHEDULER_DIR", str(tmp_path))

    assert scheduler.main(["submit", "--site", "taobao", "--intent", "search", "--query", "儿童童书", "--limit", "20"]) == 0

    out = capsys.readouterr().out
    assert "task_id" in out
    assert (tmp_path / "state.json").exists()


def test_list_shows_queued_task(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ACTION_BROWSER_SCHEDULER_DIR", str(tmp_path))
    scheduler.main(["submit", "--site", "taobao", "--intent", "search", "--query", "儿童童书"])

    assert scheduler.main(["list"]) == 0

    assert "queued" in capsys.readouterr().out
```

Create `tests/test_scheduler_reconcile.py`.

```python
from pathlib import Path

from scripts.scheduler_lib.reconcile import reconcile_task_state


def test_reconcile_marks_blocked_when_run_missing_and_no_summary(tmp_path: Path) -> None:
    task = {
        "task_id": "t1",
        "status": "running",
        "run_id": "run-1",
        "lease_id": "lease-1",
    }
    result = reconcile_task_state(task, run_state=None, tab_alive=False, summary_path=tmp_path / "summary.json")

    assert result["status"] == "blocked"
    assert result["reason_code"] == "run_missing"
```

- [ ] **Step 2: Run the new scheduler tests and verify failure**

Run:

```bash
pytest tests/test_scheduler_cli.py tests/test_scheduler_reconcile.py -v
```

Expected: FAIL because scheduler modules do not exist yet.

- [ ] **Step 3: Implement the minimum lease and reconcile logic**

Create `scripts/scheduler_lib/lease.py`.

```python
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_lease(*, lease_id: str, session_id: str, tab_id: str, task_id: str) -> dict[str, str]:
    now = utc_now()
    return {
        "schema_version": 1,
        "lease_id": lease_id,
        "session_id": session_id,
        "tab_id": tab_id,
        "task_id": task_id,
        "opened_at": now,
        "last_active_at": now,
        "updated_at": now,
    }
```

Create `scripts/scheduler_lib/reconcile.py`.

```python
import json
from pathlib import Path
from typing import Any


def reconcile_task_state(task: dict[str, Any], *, run_state: dict[str, Any] | None, tab_alive: bool, summary_path: Path) -> dict[str, Any]:
    if run_state and run_state.get("status") == "running" and tab_alive:
        task["status"] = "running"
        task["stage"] = task.get("stage") or "using_browser"
        return task
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        task["status"] = "completed"
        if summary.get("collected_count", 0) < summary.get("requested_count", 0):
            task["result_quality"] = "partial"
        return task
    if run_state and run_state.get("status") == "running" and not tab_alive:
        task["status"] = "failed"
        task["reason_code"] = "tab_lost"
        return task
    task["status"] = "blocked"
    task["reason_code"] = "run_missing"
    return task
```

Create `scripts/scheduler.py`.

```python
import argparse
import json
import os
from pathlib import Path

from scripts.scheduler_lib.state import SchedulerStore


def scheduler_root() -> Path:
    return Path(os.environ.get("ACTION_BROWSER_SCHEDULER_DIR", Path.home() / ".action-browser" / "scheduler")).expanduser()


def cmd_submit(args: argparse.Namespace) -> int:
    store = SchedulerStore(scheduler_root())
    task = store.create_task(site=args.site, intent=args.intent, payload={"query": args.query, "limit": args.limit})
    print(json.dumps({"task_id": task["task_id"], "status": task["status"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    snapshot = SchedulerStore(scheduler_root()).load_snapshot()
    print(json.dumps(snapshot.get("tasks", {}), ensure_ascii=False, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    path = scheduler_root() / "tasks" / f"{args.task}.json"
    print(path.read_text(encoding="utf-8"))
    return 0
```

Also add parser support for `submit`, `list`, `status`, `stop`, and `reconcile` even if `stop` and `reconcile` are initially thin wrappers.

- [ ] **Step 4: Run the scheduler CLI tests and verify pass**

Run:

```bash
pytest tests/test_scheduler_cli.py tests/test_scheduler_reconcile.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit the scheduler CLI slice**

Run:

```bash
git add scripts/scheduler.py scripts/scheduler_lib/lease.py scripts/scheduler_lib/lifecycle.py scripts/scheduler_lib/reconcile.py tests/test_scheduler_cli.py tests/test_scheduler_reconcile.py
git commit -m "feat: add minimal scheduler cli"
```

Expected: one commit for scheduler CLI plus reconcile primitives.

### Task 5: Wire Run Tracking And Stop/Reconcile Commands

**Files:**
- Modify: `scripts/scheduler.py`
- Create: `scripts/scheduler_lib/executor.py`
- Modify: `scripts/scheduler_lib/lifecycle.py`
- Test: `tests/test_scheduler_cli.py`
- Test: `tests/test_scheduler_reconcile.py`

- [ ] **Step 1: Add failing tests for stop and run-state reuse**

Extend `tests/test_scheduler_cli.py`.

```python
def test_stop_delegates_to_actionbook_run(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ACTION_BROWSER_SCHEDULER_DIR", str(tmp_path))
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> int:
        calls.append(args)
        return 0

    monkeypatch.setattr(scheduler, "call_actionbook_run", fake_run)
    scheduler.main(["submit", "--site", "taobao", "--intent", "search", "--query", "儿童童书"])
    task_id = next(iter(json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["tasks"].keys()))

    assert scheduler.main(["stop", "--task", task_id]) == 0
    assert calls and calls[0][:2] == ["stop", "--id"]
```

- [ ] **Step 2: Run scheduler tests and verify failure**

Run:

```bash
pytest tests/test_scheduler_cli.py tests/test_scheduler_reconcile.py -v
```

Expected: FAIL because `call_actionbook_run` and stop wiring do not exist yet.

- [ ] **Step 3: Implement the thinnest run executor integration**

Create `scripts/scheduler_lib/executor.py`.

```python
from pathlib import Path

from scripts import actionbook_run


def call_actionbook_run(argv: list[str]) -> int:
    return actionbook_run.main(argv)


def progress_path(root: Path, task_id: str) -> Path:
    return root / "progress" / f"{task_id}.json"
```

In `scripts/scheduler.py`, import and use it:

```python
from scripts.scheduler_lib.executor import call_actionbook_run


def cmd_stop(args: argparse.Namespace) -> int:
    task_path = scheduler_root() / "tasks" / f"{args.task}.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    run_id = task.get("run_id") or args.task
    return call_actionbook_run(["stop", "--id", run_id])
```

In `scripts/scheduler_lib/lifecycle.py`, add a small helper:

```python
def task_run_id(task: dict[str, object]) -> str:
    return str(task.get("run_id") or task["task_id"])
```

- [ ] **Step 4: Run the scheduler tests and verify pass**

Run:

```bash
pytest tests/test_scheduler_cli.py tests/test_scheduler_reconcile.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit the run integration**

Run:

```bash
git add scripts/scheduler.py scripts/scheduler_lib/executor.py scripts/scheduler_lib/lifecycle.py tests/test_scheduler_cli.py tests/test_scheduler_reconcile.py
git commit -m "feat: reuse tracked runs from scheduler"
```

Expected: one commit showing scheduler stop/reconcile reuse the existing run model.

### Task 6: Integrate Taobao As The First Adapter Contract

**Files:**
- Modify: `scripts/adapters/taobao_workflow.py`
- Create: `tests/test_taobao_adapter_contract.py`
- Modify: `README.md`
- Modify: `SKILL.md`
- Test: `tests/test_taobao_adapter_contract.py`

- [ ] **Step 1: Write failing adapter-contract tests**

Create `tests/test_taobao_adapter_contract.py`.

```python
import json
from pathlib import Path

from scripts.adapters import taobao_workflow


def test_write_contract_outputs(tmp_path: Path) -> None:
    records = [{"rank": 1, "title": "儿童童书", "url": "https://example.com/item/1"}]

    taobao_workflow.write_contract_outputs(
        records=records,
        output_dir=tmp_path,
        site="taobao",
        intent="search",
        requested_count=20,
        warnings=[],
        needs_user_action=False,
    )

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    progress = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))

    assert summary["site"] == "taobao"
    assert summary["requested_count"] == 20
    assert summary["collected_count"] == 1
    assert progress["stage"] == "writing_results"
```

- [ ] **Step 2: Run the Taobao adapter test and verify failure**

Run:

```bash
pytest tests/test_taobao_adapter_contract.py -v
```

Expected: FAIL because `write_contract_outputs` does not exist.

- [ ] **Step 3: Add the minimum contract output helper to Taobao workflow**

Modify `scripts/adapters/taobao_workflow.py`.

```python
def write_contract_outputs(
    *,
    records: list[dict[str, Any]],
    output_dir: Path,
    site: str,
    intent: str,
    requested_count: int,
    warnings: list[str],
    needs_user_action: bool,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = output_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    write_json(artifacts_dir / "results.json", records)
    write_json(
        output_dir / "summary.json",
        {
            "ok": True,
            "site": site,
            "intent": intent,
            "requested_count": requested_count,
            "collected_count": len(records),
            "artifacts": ["artifacts/results.json"],
            "warnings": warnings,
            "needs_user_action": needs_user_action,
        },
    )
    write_json(
        output_dir / "progress.json",
        {
            "stage": "writing_results",
            "completed_items": len(records),
            "requested_items": requested_count,
        },
    )
```

Then call it from `finish()` before returning:

```python
write_contract_outputs(
    records=records,
    output_dir=output_dir,
    site="taobao",
    intent=area,
    requested_count=len(records) if not getattr(args, "count", None) else read_count(args.count),
    warnings=[],
    needs_user_action=False,
)
```

- [ ] **Step 4: Run the Taobao contract test and verify pass**

Run:

```bash
pytest tests/test_taobao_adapter_contract.py -v
```

Expected: PASS.

- [ ] **Step 5: Update README and SKILL for the first-pass scheduler path**

Modify `README.md` and `SKILL.md` to describe only the first-pass scheduler path, not a future-state full migration.

```md
## Scheduler (First Pass)

- use `scripts/scheduler.py` for task submit/list/status/stop/reconcile
- scheduler-managed tasks open exclusive tabs with `--force-new-tab --no-adopt`
- first pass integrates one adapter contract through Taobao
- unsupported sites still default to direct agent browser work first
```

- [ ] **Step 6: Run the focused test set**

Run:

```bash
pytest tests/test_actionbook_session.py tests/test_scheduler_state.py tests/test_scheduler_cli.py tests/test_scheduler_reconcile.py tests/test_taobao_adapter_contract.py -v
```

Expected: PASS for the full first-pass scheduler slice.

- [ ] **Step 7: Commit the first site integration**

Run:

```bash
git add scripts/adapters/taobao_workflow.py tests/test_taobao_adapter_contract.py README.md SKILL.md
git commit -m "feat: add taobao adapter contract outputs"
```

Expected: one commit for the first adapter-backed scheduler integration.

## Self-Review

### Spec Coverage

- exclusive tab helper changes: Task 2
- `state.lock`, `events.jsonl`, `schema_version`: Task 3
- minimal scheduler CLI: Task 4
- reuse existing `actionbook_run.py`: Task 5
- one site integration only: Task 6
- docs split for lifecycle and adapter authoring: Task 1
- conservative concurrency caps and state semantics: Task 1 plus Task 3

No uncovered spec section remains for the first-pass scope.

### Placeholder Scan

- No `TODO`
- No `TBD`
- No “similar to previous task”
- All code-touching steps include concrete snippets
- All verification steps include exact commands

### Type Consistency

- scheduler snapshot field names consistently use `task_id`, `lease_id`, `run_id`, `status`, `stage`, `reason_code`, `result_quality`
- adapter output files consistently use `summary.json`, `progress.json`, `artifacts/*`
- session helper flags consistently use `--force-new-tab`, `--no-adopt`, `close-tab`
