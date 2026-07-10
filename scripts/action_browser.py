from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

if __package__ in {None, ""}:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from scripts.adapters.douban_public import CHART_URL, PageStateError, parse_movie_chart


CAPABILITY_ID = "douban.movie-ranking.trending.read"


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def envelope(args: argparse.Namespace, *, status: str, started_at: str, contract_ref: str | None = None, artifact_refs: list[str] | None = None, failure: dict[str, object] | None = None) -> dict[str, object]:
    quality = "empty" if status == "verified_empty" else "full" if status == "completed" else "none"
    return {"schema_version": 1, "run_id": args.task_id, "task_id": args.task_id, "capability_id": CAPABILITY_ID, "site": args.site, "command": "run", "status": status, "result_quality": quality, "contract_ref": contract_ref, "artifact_refs": artifact_refs or [], "strategy_used": "public_http", "fallback_reason": None, "failure": failure, "started_at": started_at, "finished_at": now()}


def validate_artifact(artifact: dict[str, object]) -> None:
    required = {"schema_version", "capability_id", "items"}
    if set(artifact) != required or artifact["schema_version"] != 1 or artifact["capability_id"] != CAPABILITY_ID or not isinstance(artifact["items"], list):
        raise ValueError("invalid site artifact")
    fields = {"id", "url", "title", "rank", "rating", "rating_count", "summary", "year"}
    if any(
        not isinstance(item, dict)
        or set(item) != fields
        or not isinstance(item["id"], str) or not item["id"]
        or not isinstance(item["url"], str) or not item["url"].startswith("https://movie.douban.com/subject/")
        or not isinstance(item["title"], str) or not item["title"]
        or not isinstance(item["rank"], int) or item["rank"] < 1
        or not isinstance(item["rating"], (int, float))
        or not isinstance(item["rating_count"], int) or item["rating_count"] < 0
        or not isinstance(item["summary"], str) or not item["summary"]
        or not isinstance(item["year"], str) or not item["year"]
        for item in artifact["items"]
    ):
        raise ValueError("invalid movie ranking item")


def validate_contract(contract: dict[str, object]) -> None:
    required = {"schema_version", "run_id", "task_id", "reference_baseline", "execution_baseline", "capability_id", "site", "status", "stage", "result_quality", "requested_count", "collected_count", "access", "strategy_used", "fallback_reason", "limits", "artifacts", "warnings", "failure", "progress", "started_at", "updated_at", "finished_at", "ok", "needs_user_action", "reason_code"}
    progress = contract.get("progress")
    progress_fields = {"schema_version", "task_id", "status", "stage", "completed", "requested", "last_url", "last_title"}
    limits = contract.get("limits")
    failure = contract.get("failure")
    if (
        set(contract) != required
        or contract["schema_version"] != 1
        or contract["capability_id"] != CAPABILITY_ID
        or not isinstance(contract["run_id"], str)
        or not isinstance(contract["task_id"], str)
        or contract["site"] != "douban"
        or contract["status"] not in {"completed", "verified_empty", "failed", "blocked"}
        or not isinstance(contract["stage"], str)
        or contract["result_quality"] not in {"full", "empty", "none"}
        or not isinstance(contract["requested_count"], int) or contract["requested_count"] < 0
        or not isinstance(contract["collected_count"], int) or contract["collected_count"] < 0
        or contract["access"] != "public" or contract["strategy_used"] != "public_http"
        or contract["fallback_reason"] is not None
        or not isinstance(limits, dict) or limits != {"max_items": 20, "timeout_seconds": 20}
        or not isinstance(contract["artifacts"], list) or not all(isinstance(path, str) for path in contract["artifacts"])
        or not isinstance(contract["warnings"], list) or not all(isinstance(warning, str) for warning in contract["warnings"])
        or not (failure is None or (isinstance(failure, dict) and set(failure) == {"reason_code", "message", "retryable"} and isinstance(failure["reason_code"], str) and isinstance(failure["message"], str) and isinstance(failure["retryable"], bool)))
        or not isinstance(progress, dict) or set(progress) != progress_fields
        or progress["schema_version"] != 1 or progress["task_id"] != contract["task_id"]
        or progress["status"] not in {"completed", "verified_empty", "failed", "blocked"} or not isinstance(progress["stage"], str)
        or not isinstance(progress["completed"], int) or progress["completed"] < 0 or not isinstance(progress["requested"], int) or progress["requested"] < 0
        or not isinstance(progress["last_url"], str) or not isinstance(progress["last_title"], str)
        or not isinstance(contract["started_at"], str) or not isinstance(contract["updated_at"], str) or not isinstance(contract["finished_at"], str)
        or not isinstance(contract["ok"], bool) or not isinstance(contract["needs_user_action"], bool)
        or contract["reason_code"] is not None and not isinstance(contract["reason_code"], str)
    ):
        raise ValueError("invalid adapter contract")


def fetch_chart(*, timeout: float) -> str:
    request = urllib.request.Request(CHART_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; action-browser/1.0)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def command_failure(args: argparse.Namespace, started_at: str, reason_code: str, message: str, *, blocked: bool = False) -> int:
    output = Path(args.output_root)
    try:
        requested = int(args.limit)
    except (TypeError, ValueError):
        requested = 0
    progress = {"schema_version": 1, "task_id": args.task_id, "status": "blocked" if blocked else "failed", "stage": "completed", "completed": 0, "requested": requested, "last_url": CHART_URL, "last_title": ""}
    contract = {"schema_version": 1, "run_id": args.task_id, "task_id": args.task_id, "reference_baseline": "6129bb3953d5eebd8dd67f96802b320c723f50ca", "execution_baseline": "6027d703c86d1e8e3798212bf1841422a41903fc", "capability_id": CAPABILITY_ID, "site": "douban", "status": "blocked" if blocked else "failed", "stage": "completed", "result_quality": "none", "requested_count": requested, "collected_count": 0, "access": "public", "strategy_used": "public_http", "fallback_reason": None, "limits": {"max_items": 20, "timeout_seconds": 20}, "artifacts": [], "warnings": [], "failure": {"reason_code": reason_code, "message": message, "retryable": reason_code in {"timeout", "network_error"}}, "progress": progress, "started_at": started_at, "updated_at": now(), "finished_at": now(), "ok": False, "needs_user_action": False, "reason_code": reason_code}
    contract_ref: str | None = "contract/summary.json"
    try:
        validate_contract(contract)
        write_json(output / "contract" / "summary.json", contract)
        write_json(output / "contract" / "progress.json", progress)
    except (OSError, ValueError) as error:
        contract_ref = None
        print(f"contract write failed: {error}", file=sys.stderr)
    print(json.dumps(envelope(args, status="failed", started_at=started_at, contract_ref=contract_ref, failure=contract["failure"]), ensure_ascii=False))
    return 1


def run(args: argparse.Namespace) -> int:
    started_at = now()
    try:
        args.limit = int(args.limit)
    except (TypeError, ValueError):
        return command_failure(args, started_at, "invalid_input", "limit must be an integer")
    if (args.site, args.resource, args.intent) != ("douban", "movie-ranking", "trending"):
        return command_failure(args, started_at, "unsupported_capability", "only douban movie-ranking trending is implemented")
    if not 1 <= args.limit <= 20:
        return command_failure(args, started_at, "invalid_input", "limit must be between 1 and 20")
    try:
        html = Path(args.fixture).read_text(encoding="utf-8") if args.fixture else fetch_chart(timeout=20)
        records, state = parse_movie_chart(html, limit=args.limit)
    except urllib.error.URLError as error:
        return command_failure(args, started_at, "network_error", str(error))
    except TimeoutError as error:
        return command_failure(args, started_at, "timeout", str(error))
    except PageStateError as error:
        code = str(error).split(":", 1)[0]
        return command_failure(args, started_at, code, str(error), blocked=code == "field_gap")
    except OSError as error:
        return command_failure(args, started_at, "config_error", str(error))
    output = Path(args.output_root)
    artifact = {"schema_version": 1, "capability_id": CAPABILITY_ID, "items": records}
    status = "verified_empty" if state == "empty" else "completed"
    progress = {"schema_version": 1, "task_id": args.task_id, "status": status, "stage": "completed", "completed": len(records), "requested": args.limit, "last_url": CHART_URL, "last_title": records[-1]["title"] if records else ""}
    contract = {"schema_version": 1, "run_id": args.task_id, "task_id": args.task_id, "reference_baseline": "6129bb3953d5eebd8dd67f96802b320c723f50ca", "execution_baseline": "6027d703c86d1e8e3798212bf1841422a41903fc", "capability_id": CAPABILITY_ID, "site": "douban", "status": status, "stage": "completed", "result_quality": "empty" if state == "empty" else "full", "requested_count": args.limit, "collected_count": len(records), "access": "public", "strategy_used": "public_http", "fallback_reason": None, "limits": {"max_items": 20, "timeout_seconds": 20}, "artifacts": ["artifacts/movie-ranking.json"], "warnings": [], "failure": None, "progress": progress, "started_at": started_at, "updated_at": now(), "finished_at": now(), "ok": True, "needs_user_action": False, "reason_code": None}
    try:
        validate_artifact(artifact)
        validate_contract(contract)
        write_json(output / "artifacts" / "movie-ranking.json", artifact)
        write_json(output / "contract" / "summary.json", contract)
        write_json(output / "contract" / "progress.json", progress)
    except (OSError, ValueError) as error:
        return command_failure(args, started_at, "storage_failed", str(error))
    print(json.dumps(envelope(args, status=status, started_at=started_at, contract_ref="contract/summary.json", artifact_refs=["artifacts/movie-ranking.json"]), ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("run")
    command.add_argument("--site", required=True)
    command.add_argument("--resource", required=True)
    command.add_argument("--intent", required=True)
    command.add_argument("--limit", required=True)
    command.add_argument("--task-id", required=True)
    command.add_argument("--output-root", required=True)
    command.add_argument("--fixture", default="")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
