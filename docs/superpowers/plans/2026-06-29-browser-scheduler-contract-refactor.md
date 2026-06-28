# Browser Scheduler Contract Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the scheduler contract executable in code, align docs to the real first-pass flow, and remove the worst session/tab policy drift.

**Architecture:** Centralize scheduler record shapes and summary-to-status mapping in `scripts/scheduler_lib/contracts.py`, then update persistence, lease, and reconcile helpers to consume that contract module. Keep first-pass runtime behavior narrow: one shared extension session, one leased tab per running task, and helper semantics that never silently cross explicit session boundaries.

**Tech Stack:** Python 3, pytest, ActionBook CLI, JSON file persistence, stdlib file locking, existing `scripts/actionbook_session.py`

---

## File Structure

**Create:**

- `docs/superpowers/specs/2026-06-29-browser-scheduler-contract-refactor-design.md`
- `docs/superpowers/plans/2026-06-29-browser-scheduler-contract-refactor.md`

**Modify:**

- `README.md`
- `SKILL.md`
- `references/task-lifecycle.md`
- `references/adapter-authoring.md`
- `references/status-check.md`
- `scripts/actionbook_session.py`
- `scripts/scheduler_lib/contracts.py`
- `scripts/scheduler_lib/state.py`
- `scripts/scheduler_lib/lease.py`
- `scripts/scheduler_lib/reconcile.py`
- `tests/test_actionbook_session.py`
- `tests/test_scheduler_state.py`
- `tests/test_scheduler_reconcile.py`

**Keep unchanged in this refactor:**

- `scripts/scheduler.py` command surface
- `scripts/actionbook_run.py`
- site workflow coverage beyond existing Taobao contract work

### Task 1: Freeze The New Contract Authority

**Files:**
- Modify: `scripts/scheduler_lib/contracts.py`
- Test: `tests/test_scheduler_state.py`, `tests/test_scheduler_reconcile.py`

- [ ] **Step 1: Centralize contract constants and builders**

Add the scheduler contract authority to `contracts.py`:

- `SCHEMA_VERSION`
- task statuses
- task stages
- result quality values
- `DEFAULT_LIMITS`
- task record builder
- snapshot builder
- lease builder
- task-created event builder
- summary-to-task mapping helper

Expected result: downstream modules can construct task/snapshot/lease state without repeating field literals.

- [ ] **Step 2: Run focused scheduler tests**

Run:

```bash
pytest tests/test_scheduler_state.py tests/test_scheduler_reconcile.py -v
```

Expected: pass, or fail only where state/reconcile still build records by hand.

### Task 2: Rewire State, Lease, And Reconcile To Use Contracts

**Files:**
- Modify: `scripts/scheduler_lib/state.py`
- Modify: `scripts/scheduler_lib/lease.py`
- Modify: `scripts/scheduler_lib/reconcile.py`
- Test: `tests/test_scheduler_state.py`
- Test: `tests/test_scheduler_reconcile.py`

- [ ] **Step 1: Route state creation through contract builders**

Update `state.py` so empty snapshots, task records, task snapshot rows, and
task-created events all come from `contracts.py`.

- [ ] **Step 2: Remove lease schema drift**

Update `lease.py` so it uses the shared lease builder instead of hardcoding
`schema_version` and record shape locally.

- [ ] **Step 3: Route summary mapping through contract helpers**

Update `reconcile.py` so task status transitions and adapter summary mapping
come from `contracts.py`.

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/test_scheduler_state.py tests/test_scheduler_reconcile.py -v
```

Expected: pass with no duplicated schema or status literals left in those modules.

### Task 3: Tighten Session Bootstrap Semantics

**Files:**
- Modify: `scripts/actionbook_session.py`
- Test: `tests/test_actionbook_session.py`

- [ ] **Step 1: Keep explicit session boundaries strict**

Preserve and document the current behavior:

- explicit `--session` must not silently adopt another named session
- `list-tabs`, `new-tab`, and `select-tab` must not bootstrap `about:blank`
- `new-tab` must wait for an accessible tab before returning

- [ ] **Step 2: Re-run helper tests**

Run:

```bash
pytest tests/test_actionbook_session.py -v
```

Expected: pass and keep helper semantics aligned with the contract docs.

### Task 4: Rewrite Docs Around The Real First-Pass Model

**Files:**
- Modify: `README.md`
- Modify: `SKILL.md`
- Modify: `references/task-lifecycle.md`
- Modify: `references/adapter-authoring.md`
- Modify: `references/status-check.md`

- [ ] **Step 1: Make session/tab mental model consistent**

Ensure every high-level doc says:

- `session` is the browser container
- `tab` is the task execution unit
- first-pass extension scheduling prefers one shared session plus leased tabs

- [ ] **Step 2: Remove duplicated contract prose where possible**

Shrink duplicated adapter/lifecycle semantics by making:

- `task-lifecycle.md` the scheduler lifecycle authority
- `adapter-authoring.md` the adapter author guide that references lifecycle

- [ ] **Step 3: Verify doc consistency manually**

Check for drift in:

- session adoption rules
- shared-session / leased-tab wording
- summary/progress contract paths

Expected: the docs describe one coherent flow and no longer imply one task per extension session.

### Task 5: Full Regression Pass

**Files:**
- Test only

- [ ] **Step 1: Run the focused regression suite**

Run:

```bash
pytest tests/test_actionbook_session.py tests/test_scheduler_state.py tests/test_scheduler_cli.py tests/test_scheduler_reconcile.py tests/test_taobao_adapter_contract.py -v
```

Expected: all pass.

- [ ] **Step 2: Smoke the helper CLI help output**

Run:

```bash
python3 scripts/actionbook_session.py ensure --help
```

Expected: help text matches the explicit-session semantics.

- [ ] **Step 3: Manual real-flow sanity check**

Run a serial extension-mode smoke:

```bash
python3 scripts/actionbook_session.py ensure --session sanity-flow --url "https://example.com" --json
python3 scripts/actionbook_session.py list-tabs --session sanity-flow --json
python3 scripts/actionbook_session.py new-tab --session sanity-flow --url "https://example.com/?tab=2" --switch --json
actionbook browser status --session sanity-flow --json
actionbook browser close --session sanity-flow --json
```

Expected: one session survives across commands, tabs are explicit, and no helper command creates a surprise bootstrap tab.
