from __future__ import annotations

import html
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[2]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from scripts.foundation_contracts import validate_adapter_contract, validate_result_envelope, validate_site_artifact, write_json_atomic


REFERENCE_BASELINE = "c1ad69676f220b5ef382bbf4c387a2486daf8355"
EXECUTION_BASELINE = "d9f2c639a454b72121c4189c94601b05ddae2655"
USER_AGENT = "action-browser/1.0 (+https://github.com/VintLin/action-browser)"


class FetchError(RuntimeError):
    def __init__(self, reason_code: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.retryable = retryable


@dataclass
class ReadResult:
    records: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    result_quality: str = "full"
    empty_state_proven: bool = False
    last_url: str = ""
    last_title: str = ""
    strategy_used: str = ""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_count(value: Any, default: int = 20, maximum: int = 50) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise FetchError("invalid_input", "count must be an integer", retryable=False) from exc
    if not 1 <= count <= maximum:
        raise FetchError("invalid_input", f"count must be between 1 and {maximum}", retryable=False)
    return count


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def fetch_bytes(url: str, *, headers: dict[str, str] | None = None, timeout: float = 20.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        retryable = exc.code in {408, 425, 429} or exc.code >= 500
        raise FetchError("http_error", f"HTTP {exc.code} for {url}", retryable=retryable) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError("network_error", f"request failed for {url}: {exc}") from exc


def fetch_text(url: str, *, headers: dict[str, str] | None = None, timeout: float = 20.0) -> str:
    return fetch_bytes(url, headers=headers, timeout=timeout).decode("utf-8", errors="replace")


def fetch_json(url: str, *, headers: dict[str, str] | None = None, timeout: float = 20.0) -> Any:
    try:
        return json.loads(fetch_text(url, headers={"Accept": "application/json", **(headers or {})}, timeout=timeout))
    except json.JSONDecodeError as exc:
        raise FetchError("schema_mismatch", f"invalid JSON from {url}", retryable=False) from exc


def default_output(site: str, resource: str) -> Path:
    return Path("assets") / site / "views" / resource / datetime.now().strftime("%Y%m%d-%H%M%S")


def _write_markdown(path: Path, title: str, records: list[dict[str, Any]]) -> None:
    lines = [f"# {title}", "", f"- 条目数: {len(records)}", ""]
    for index, item in enumerate(records, 1):
        heading = clean_text(item.get("title") or item.get("name") or item.get("question_id") or item.get("id") or str(index))
        lines.extend([f"## {index}. {heading}", ""])
        for key, value in item.items():
            if value in (None, "", [], {}):
                continue
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(f"- {key}: {value}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    tmp.replace(path)


def emit_read(
    args: Any,
    *,
    site: str,
    resource: str,
    loader: Callable[[], ReadResult],
    access: str = "public",
    strategy: str = "public_http",
    requested_count: int = 0,
    limits: dict[str, Any] | None = None,
    output_root: Path | None = None,
) -> int:
    started_at = now()
    capability_id = f"{site}.{resource}.view.read"
    root = output_root or Path(getattr(args, "output", "") or default_output(site, resource))
    try:
        result = loader()
        if not result.records and not result.empty_state_proven:
            raise FetchError(
                "empty_unproven",
                "reader returned no records without explicit empty-state evidence",
                retryable=False,
            )
        effective_strategy = result.strategy_used or strategy
        status = "completed" if result.records else "verified_empty"
        quality = result.result_quality if result.records else "empty"
        artifact = {"schema_version": 1, "capability_id": capability_id, "items": result.records}
        contract = _contract(
            site=site,
            capability_id=capability_id,
            task_id=str(getattr(args, "task_id", "") or f"{site}-read"),
            status=status,
            result_quality=quality,
            requested_count=requested_count,
            collected_count=len(result.records),
            access=access,
            strategy=effective_strategy,
            limits=limits or {},
            warnings=result.warnings,
            last_url=result.last_url,
            last_title=result.last_title,
            started_at=started_at,
        )
        artifact_path = root / "artifacts" / f"{resource}.json"
        contract_path = root / "contract" / "summary.json"
        write_json_atomic(artifact_path, artifact)
        write_json_atomic(contract_path, contract)
        _write_markdown(root / "summary.md", f"{site}: {resource}", result.records)
        envelope = _envelope(capability_id, site, status, effective_strategy, contract_path, artifact_path, started_at, task_id=str(getattr(args, "task_id", "") or f"{site}-read"))
        validate_site_artifact(artifact)
        validate_adapter_contract(contract)
        validate_result_envelope(envelope)
        print(json.dumps(envelope, ensure_ascii=False))
        return 0
    except FetchError as exc:
        failure = {"reason_code": exc.reason_code, "message": str(exc), "retryable": exc.retryable}
        contract_path = _write_failure_contract(root, site, capability_id, str(getattr(args, "task_id", "") or f"{site}-read"), requested_count, access, strategy, limits or {}, started_at, failure)
        envelope = _envelope(capability_id, site, "failed", strategy, contract_path, None, started_at, task_id=str(getattr(args, "task_id", "") or f"{site}-read"), failure=failure)
        validate_result_envelope(envelope)
        print(json.dumps(envelope, ensure_ascii=False))
        return 1
    except (OSError, ValueError, TypeError) as exc:
        failure = {"reason_code": "storage_failed", "message": str(exc), "retryable": False}
        contract_path = _write_failure_contract(root, site, capability_id, str(getattr(args, "task_id", "") or f"{site}-read"), requested_count, access, strategy, limits or {}, started_at, failure)
        envelope = _envelope(capability_id, site, "failed", strategy, contract_path, None, started_at, task_id=str(getattr(args, "task_id", "") or f"{site}-read"), failure=failure)
        validate_result_envelope(envelope)
        print(json.dumps(envelope, ensure_ascii=False))
        return 1
    except RuntimeError as exc:
        failure = {"reason_code": "browser_error", "message": str(exc), "retryable": True}
        contract_path = _write_failure_contract(root, site, capability_id, str(getattr(args, "task_id", "") or f"{site}-read"), requested_count, access, strategy, limits or {}, started_at, failure)
        envelope = _envelope(capability_id, site, "failed", strategy, contract_path, None, started_at, task_id=str(getattr(args, "task_id", "") or f"{site}-read"), failure=failure)
        validate_result_envelope(envelope)
        print(json.dumps(envelope, ensure_ascii=False))
        return 1


def _contract(
    *,
    site: str,
    capability_id: str,
    task_id: str,
    status: str,
    result_quality: str,
    requested_count: int,
    collected_count: int,
    access: str,
    strategy: str,
    limits: dict[str, Any],
    warnings: list[str],
    last_url: str,
    last_title: str,
    started_at: str,
) -> dict[str, Any]:
    finished_at = now()
    return {
        "schema_version": 1,
        "run_id": task_id,
        "task_id": task_id,
        "reference_baseline": REFERENCE_BASELINE,
        "execution_baseline": EXECUTION_BASELINE,
        "capability_id": capability_id,
        "site": site,
        "status": status,
        "stage": "completed",
        "result_quality": result_quality,
        "requested_count": requested_count,
        "collected_count": collected_count,
        "access": access,
        "strategy_used": strategy,
        "fallback_reason": None,
        "limits": limits,
        "artifacts": ["artifacts/" + capability_id.split(".", 2)[1] + ".json", "summary.md"],
        "warnings": warnings,
        "failure": None,
        "progress": {"status": status, "completed": collected_count, "requested": requested_count, "last_url": last_url, "last_title": last_title},
        "started_at": started_at,
        "updated_at": finished_at,
        "finished_at": finished_at,
        "ok": True,
        "needs_user_action": False,
        "reason_code": None,
    }


def _write_failure_contract(
    root: Path,
    site: str,
    capability_id: str,
    task_id: str,
    requested_count: int,
    access: str,
    strategy: str,
    limits: dict[str, Any],
    started_at: str,
    failure: dict[str, Any],
) -> Path:
    finished_at = now()
    contract = {
        "schema_version": 1,
        "run_id": task_id,
        "task_id": task_id,
        "reference_baseline": REFERENCE_BASELINE,
        "execution_baseline": EXECUTION_BASELINE,
        "capability_id": capability_id,
        "site": site,
        "status": "failed",
        "stage": "failed",
        "result_quality": "none",
        "requested_count": requested_count,
        "collected_count": 0,
        "access": access,
        "strategy_used": strategy,
        "fallback_reason": None,
        "limits": limits,
        "artifacts": [],
        "warnings": [],
        "failure": failure,
        "progress": {"status": "failed", "completed": 0, "requested": requested_count, "last_url": "", "last_title": ""},
        "started_at": started_at,
        "updated_at": finished_at,
        "finished_at": finished_at,
        "ok": False,
        "needs_user_action": failure["reason_code"] in {"needs_user_action", "needs_login", "captcha", "permission_required"},
        "reason_code": failure["reason_code"],
    }
    validate_adapter_contract(contract)
    path = root / "contract" / "summary.json"
    write_json_atomic(path, contract)
    return path


def _envelope(
    capability_id: str,
    site: str,
    status: str,
    strategy: str,
    contract_path: Path | None,
    artifact_path: Path | None,
    started_at: str,
    *,
    task_id: str,
    failure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    finished_at = now()
    return {
        "schema_version": 1,
        "run_id": task_id,
        "task_id": task_id,
        "capability_id": capability_id,
        "site": site,
        "command": "view",
        "status": status,
        "result_quality": "none" if failure else ("empty" if status == "verified_empty" else "full"),
        "contract_ref": str(contract_path) if contract_path else None,
        "artifact_refs": [str(artifact_path)] if artifact_path else [],
        "strategy_used": strategy,
        "fallback_reason": None,
        "failure": failure,
        "started_at": started_at,
        "finished_at": finished_at,
    }
