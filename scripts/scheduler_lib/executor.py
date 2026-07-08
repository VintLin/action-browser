from __future__ import annotations

from scripts import actionbook_run


def call_actionbook_run(argv: list[str]) -> int:
    return actionbook_run.main(argv)


def has_tracked_run(run_id: str) -> bool:
    path = actionbook_run.state_path(run_id, actionbook_run.RUNS_DIR)
    state = actionbook_run.load_state(path)
    return isinstance(state, dict) and state.get("status") != "missing"
