from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

from scripts.actionbook_errors import ActionBookFailure, failure_code
from scripts.script_common import unwrap_eval


TRANSIENT_EVAL_CODES = {
    "EXECUTION_CONTEXT_DESTROYED",
    "CONTEXT_NOT_FOUND",
    "TARGET_DETACHED",
    "TARGET_CLOSED",
}


def evaluate(
    book: Any,
    script: str,
    label: str,
    timeout: float = 45.0,
    *,
    retries: int = 2,
    retry_delay: float = 0.4,
) -> Any:
    for attempt in range(retries + 1):
        try:
            value = unwrap_eval(book.eval(script, timeout=timeout))
            if isinstance(value, dict) and value.get("error"):
                raise RuntimeError(str(value.get("error")))
            return value
        except Exception as exc:
            if attempt >= retries or failure_code(exc) not in TRANSIENT_EVAL_CODES:
                if isinstance(exc, ActionBookFailure):
                    exc.add_note(label)
                    raise
                raise RuntimeError(f"{label}: {exc}") from exc
            time.sleep(retry_delay)
    raise AssertionError("unreachable")


def wait_until_stable(
    book: Any,
    *,
    timeout_secs: float = 3.0,
    interval: float = 0.4,
    require_stable: bool = False,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_secs
    previous = ""
    stable_rounds = 0
    last_state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        state = evaluate(
            book,
            """(() => ({
                href: location.href,
                title: document.title || '',
                text_length: (document.body?.innerText || '').length,
                height: document.body?.scrollHeight || 0,
            }))()""",
            "read page state",
            timeout=10.0,
        )
        if isinstance(state, dict):
            last_state = state
            signature = "|".join(str(state.get(key) or "") for key in ("href", "title", "text_length", "height"))
            stable_rounds = stable_rounds + 1 if signature == previous else 0
            previous = signature
            if stable_rounds >= 2:
                return state
        time.sleep(interval)
    if require_stable:
        raise RuntimeError(f"page did not settle within {timeout_secs}s: {last_state}")
    return last_state

def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as output:
        output.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        output.flush()
        os.fsync(output.fileno())
    tmp.replace(path)
