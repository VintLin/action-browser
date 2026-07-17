from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class ActionBookFailure(RuntimeError):
    """Typed ActionBook failure preserved across the browser adapter seam."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        self.code = str(code or "ACTIONBOOK_ERROR").strip().upper()
        self.message = str(message or self.code).strip()
        self.details = dict(details or {})
        super().__init__(f"{self.code}: {self.message}")


def failure_code(error: BaseException) -> str:
    return error.code if isinstance(error, ActionBookFailure) else ""


def has_failure_code(error: BaseException, codes: Iterable[str]) -> bool:
    expected = {str(code).strip().upper() for code in codes}
    return failure_code(error) in expected
