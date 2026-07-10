from __future__ import annotations

from scripts import actionbook_run


def load_run_state(run_id: str) -> dict[str, object] | None:
    path = actionbook_run.state_path(run_id, actionbook_run.RUNS_DIR)
    return actionbook_run.refresh_state(path)


def has_active_run(run_id: str) -> bool:
    state = load_run_state(run_id)
    return isinstance(state, dict) and state.get("status") == actionbook_run.RUNNING_STATUS
