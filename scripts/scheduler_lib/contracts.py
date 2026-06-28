SCHEMA_VERSION = 1

TERMINAL_STATUSES = {"completed", "failed", "blocked", "canceled"}
RUNNING_STATUSES = {"queued", "running", "waiting_user"}

DEFAULT_LIMITS = {
    "max_running_tasks": 2,
    "max_tabs_per_session": 5,
    "max_running_tasks_per_site": 1,
}
