from __future__ import annotations

import argparse
from contextlib import redirect_stdout
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
from scripts.adapters import douban_workflow
from scripts.adapters import x_workflow
from scripts.foundation_contracts import validate_adapter_contract as validate_shared_contract, validate_download_manifest, validate_result_envelope, validate_site_artifact, write_json_atomic
from scripts.workflow_runtime import attach_workflow, temporary_tab


CAPABILITY_ID = "douban.movie-ranking.trending.read"
X_TIMELINE_CAPABILITY_ID = "x.timeline.list.read"
X_ARTICLE_CAPABILITY_ID = "x.article.detail.read"
DOUBAN_PHOTO_CAPABILITY_ID = "douban.photo.download.read"
REFERENCE_BASELINE = "6129bb3953d5eebd8dd67f96802b320c723f50ca"
EXECUTION_BASELINE = "6027d703c86d1e8e3798212bf1841422a41903fc"


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def write_json(path: Path, value: object) -> None:
    write_json_atomic(path, value)


def envelope(args: argparse.Namespace, *, status: str, started_at: str, contract_ref: str | None = None, artifact_refs: list[str] | None = None, failure: dict[str, object] | None = None) -> dict[str, object]:
    quality = "empty" if status == "verified_empty" else "full" if status == "completed" else "none"
    result = {"schema_version": 1, "run_id": args.task_id, "task_id": args.task_id, "capability_id": CAPABILITY_ID, "site": args.site, "command": "run", "status": status, "result_quality": quality, "contract_ref": contract_ref, "artifact_refs": artifact_refs or [], "strategy_used": "public_http", "fallback_reason": None, "failure": failure, "started_at": started_at, "finished_at": now()}
    validate_result_envelope(result)
    return result


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
        validate_shared_contract(contract)
        write_json(output / "contract" / "summary.json", contract)
        write_json(output / "contract" / "progress.json", progress)
    except (OSError, ValueError) as error:
        contract_ref = None
        print(f"contract write failed: {error}", file=sys.stderr)
    print(json.dumps(envelope(args, status="failed", started_at=started_at, contract_ref=contract_ref, failure=contract["failure"]), ensure_ascii=False))
    return 1


def run(args: argparse.Namespace) -> int:
    if args.site == "x":
        return run_x(args)
    if (args.site, args.resource, args.intent) == ("douban", "photo", "download"):
        return run_douban_photo_download(args)
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
        validate_site_artifact(artifact)
        validate_shared_contract(contract)
        write_json(output / "artifacts" / "movie-ranking.json", artifact)
        write_json(output / "contract" / "summary.json", contract)
        write_json(output / "contract" / "progress.json", progress)
    except (OSError, ValueError) as error:
        return command_failure(args, started_at, "storage_failed", str(error))
    print(json.dumps(envelope(args, status=status, started_at=started_at, contract_ref="contract/summary.json", artifact_refs=["artifacts/movie-ranking.json"]), ensure_ascii=False))
    return 0


def run_douban_photo_download(args: argparse.Namespace) -> int:
    started_at = now()
    output = Path(args.output_root)
    try:
        args.count = int(args.limit)
        args.output = str(output)
        args.output_root = str(output)
        with redirect_stdout(sys.stderr):
            result = douban_workflow.run_photos_download(args)
        manifest = json.loads((output / "download-manifest.json").read_text(encoding="utf-8"))
        validate_download_manifest(manifest)
        items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
        successful = [item for item in items if isinstance(item, dict) and item.get("status") in {"success", "skipped"}]
        failed = [item for item in items if isinstance(item, dict) and item.get("status") == "failed"]
        status = "completed" if result == 0 and not failed else "failed"
        failure = None if not failed else {"reason_code": "media_failed", "message": f"{len(failed)} media item(s) failed", "retryable": True}
        progress = {"schema_version": 1, "task_id": args.task_id, "status": status, "stage": "completed", "completed": len(successful), "requested": args.count, "last_url": "https://movie.douban.com", "last_title": ""}
        contract = {"schema_version": 1, "run_id": args.task_id, "task_id": args.task_id, "reference_baseline": REFERENCE_BASELINE, "execution_baseline": EXECUTION_BASELINE, "capability_id": DOUBAN_PHOTO_CAPABILITY_ID, "site": "douban", "status": status, "stage": "completed", "result_quality": "full" if status == "completed" else "partial", "requested_count": args.count, "collected_count": len(successful), "access": "browser", "strategy_used": "dom", "fallback_reason": None, "limits": {"max_items": args.count, "max_item_bytes": args.max_item_bytes, "max_total_bytes": args.max_total_bytes}, "artifacts": ["artifacts/photos.json", "download-manifest.json"], "warnings": [], "failure": failure, "progress": progress, "started_at": started_at, "updated_at": now(), "finished_at": now(), "ok": status == "completed", "needs_user_action": False, "reason_code": None if status == "completed" else "media_failed"}
        validate_shared_contract(contract)
        write_json(output / "contract" / "summary.json", contract)
        write_json(output / "contract" / "progress.json", progress)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        failure = {"reason_code": "page_not_ready", "message": str(error), "retryable": True}
        result_envelope = {"schema_version": 1, "run_id": args.task_id, "task_id": args.task_id, "capability_id": DOUBAN_PHOTO_CAPABILITY_ID, "site": "douban", "command": "run", "status": "failed", "result_quality": "none", "contract_ref": None, "artifact_refs": [], "strategy_used": "dom", "fallback_reason": None, "failure": failure, "started_at": started_at, "finished_at": now()}
        validate_result_envelope(result_envelope)
        print(json.dumps(result_envelope, ensure_ascii=False))
        return 1
    result_envelope = {"schema_version": 1, "run_id": args.task_id, "task_id": args.task_id, "capability_id": DOUBAN_PHOTO_CAPABILITY_ID, "site": "douban", "command": "run", "status": status, "result_quality": "full" if status == "completed" else "partial", "contract_ref": "contract/summary.json", "artifact_refs": ["artifacts/photos.json", "download-manifest.json"], "strategy_used": "dom", "fallback_reason": None, "failure": failure, "started_at": started_at, "finished_at": now()}
    validate_result_envelope(result_envelope)
    print(json.dumps(result_envelope, ensure_ascii=False))
    return 0 if status == "completed" else 1


def x_capability(args: argparse.Namespace) -> str:
    if (args.resource, args.intent) == ("timeline", "list"):
        return X_TIMELINE_CAPABILITY_ID
    if (args.resource, args.intent) == ("article", "detail"):
        return X_ARTICLE_CAPABILITY_ID
    return ""


def x_envelope(args: argparse.Namespace, capability_id: str, started_at: str, *, status: str, contract_ref: str | None = None, artifact_refs: list[str] | None = None, failure: dict[str, object] | None = None) -> dict[str, object]:
    result = {"schema_version": 1, "run_id": args.task_id, "task_id": args.task_id, "capability_id": capability_id, "site": "x", "command": "run", "status": status, "result_quality": "full" if status == "completed" else "none", "contract_ref": contract_ref, "artifact_refs": artifact_refs or [], "strategy_used": "dom", "fallback_reason": None, "failure": failure, "started_at": started_at, "finished_at": now()}
    validate_result_envelope(result)
    return result


def x_failure_reason(error: Exception) -> str:
    message = str(error).lower()
    if isinstance(error, x_workflow.ShowMoreExpansionError):
        return str(error).split(":", 1)[0]
    if "login" in message:
        return "needs_login"
    if "captcha" in message:
        return "captcha"
    if "mfa" in message:
        return "mfa_required"
    if "ownership" in message or "require" in message or "task tab" in message:
        return "invalid_input"
    if "tab" in message or "session" in message:
        return "tab_lost"
    return "page_not_ready"


def x_contract(args: argparse.Namespace, capability_id: str, started_at: str, *, status: str, requested: int, records: list[dict[str, object]], artifact: str | None, last_url: str, last_title: str, failure: dict[str, object] | None = None) -> dict[str, object]:
    progress = {"schema_version": 1, "task_id": args.task_id, "status": status, "stage": "completed", "completed": len(records), "requested": requested, "last_url": last_url, "last_title": last_title}
    return {"schema_version": 1, "run_id": args.task_id, "task_id": args.task_id, "reference_baseline": REFERENCE_BASELINE, "execution_baseline": EXECUTION_BASELINE, "capability_id": capability_id, "site": "x", "status": status, "stage": "completed", "result_quality": "full" if status == "completed" else "none", "requested_count": requested, "collected_count": len(records), "access": "browser", "strategy_used": "dom", "fallback_reason": None, "limits": {"max_items": 5, "max_scrolls": args.max_scrolls, "max_expansions": 2}, "artifacts": [artifact] if artifact else [], "warnings": [], "failure": failure, "progress": progress, "started_at": started_at, "updated_at": now(), "finished_at": now(), "ok": status == "completed", "needs_user_action": bool(failure and failure["reason_code"] in {"needs_login", "captcha", "mfa_required"}), "reason_code": None if status == "completed" else failure["reason_code"] if failure else "page_not_ready"}


def x_timeline_record(payload: x_workflow.TweetPayload) -> dict[str, object]:
    return {"id": payload.tweet_id, "url": payload.source_url, "author": {"id": payload.author_handle.removeprefix("@"), "handle": payload.author_handle, "name": payload.author_name}, "text_preview": payload.text, "published_at": payload.created_at_iso or payload.created_at_text, "engagement": payload.metrics, "has_media": bool(payload.media), "media": payload.media, "card": payload.card, "quoted_tweet": payload.quoted_tweet, "content_type": payload.tweet_type, "long_form": x_workflow.needs_show_more_expansion(payload)}


def x_article_record(payload: x_workflow.TweetPayload) -> dict[str, object]:
    return {"id": payload.tweet_id, "url": payload.source_url, "title": payload.article.get("title") or "", "author": {"id": payload.author_handle.removeprefix("@"), "handle": payload.author_handle, "name": payload.author_name}, "published_at": payload.created_at_iso or payload.created_at_text, "full_text": payload.text, "full_text_tail": payload.text[-240:], "media": payload.media, "links": payload.links, "expanded": not x_workflow.needs_show_more_expansion(payload)}


def write_x_failure(args: argparse.Namespace, capability_id: str, started_at: str, error: Exception) -> int:
    reason_code = x_failure_reason(error)
    failure = {"reason_code": reason_code, "message": str(error), "retryable": reason_code in {"page_not_ready", "tab_lost"}}
    status = "blocked" if reason_code in {"needs_login", "captcha", "mfa_required"} else "failed"
    contract_ref: str | None = "contract/summary.json"
    try:
        contract = x_contract(args, capability_id, started_at, status=status, requested=int(args.limit) if str(args.limit).isdigit() else 0, records=[], artifact=None, last_url=x_workflow.HOME_URL, last_title="", failure=failure)
        validate_shared_contract(contract)
        write_json(Path(args.output_root) / "contract" / "summary.json", contract)
        write_json(Path(args.output_root) / "contract" / "progress.json", contract["progress"])
    except OSError as write_error:
        contract_ref = None
        print(f"contract write failed: {write_error}", file=sys.stderr)
    print(json.dumps(x_envelope(args, capability_id, started_at, status=status, contract_ref=contract_ref, failure=failure), ensure_ascii=False))
    return 1


def collect_x_timeline(book: x_workflow.ActionBook, limit: int, max_scrolls: int) -> list[x_workflow.TweetPayload]:
    with redirect_stdout(sys.stderr):
        current_url = str(book.describe().get("url") or "").rstrip("/")
        if current_url != x_workflow.HOME_URL:
            book.goto(x_workflow.HOME_URL)
        x_workflow.wait_page_ready(book, "home")
        x_workflow.wait_for_visible_tweets(book, "home")
        return x_workflow.collect_tweets(book, "home", limit, max_scrolls)


def run_x(args: argparse.Namespace) -> int:
    started_at = now()
    capability_id = x_capability(args)
    if not capability_id:
        return write_x_failure(args, "x.unsupported.read", started_at, ValueError("unsupported X capability"))
    try:
        args.limit = int(args.limit)
        if not 1 <= args.limit <= 5:
            raise ValueError("limit must be between 1 and 5")
        if not all(str(value or "").strip() for value in (args.task_id, args.session, args.tab)):
            raise ValueError("X browser commands require task id, session, and owned tab")
        book = attach_workflow(args, x_workflow.HOME_URL, x_workflow.ActionBook)
        payloads = collect_x_timeline(book, 5 if capability_id == X_ARTICLE_CAPABILITY_ID else args.limit, args.max_scrolls)
        if capability_id == X_TIMELINE_CAPABILITY_ID:
            records = [x_timeline_record(payload) for payload in payloads]
            if len(records) != args.limit or len({str(record["id"]) for record in records}) != len(records) or any(not record["id"] or not record["url"] for record in records):
                raise RuntimeError("page_not_ready: timeline identities are not stable")
            artifact_path = "artifacts/timeline.json"
        else:
            payload = next((item for item in payloads if item.tweet_id == args.item_id), None)
            if payload is None:
                raise RuntimeError("page_not_ready: item identity was not found in the owned timeline")
            with redirect_stdout(sys.stderr):
                if x_workflow.needs_show_more_expansion(payload):
                    x_workflow.expand_show_more_payloads(book, [payload], max_expansions=1)
                else:
                    with temporary_tab(book, payload.source_url) as tab_id:
                        x_workflow.wait_tab_articles(book, tab_id)
                        detail = x_workflow.wait_for_expanded_payload(book, payload, tab_id)
                        if detail is None:
                            raise x_workflow.ShowMoreExpansionError("page_not_ready: article detail was not found")
                        x_workflow.merge_expanded_payload(payload, detail)
            if not payload.text or x_workflow.needs_show_more_expansion(payload):
                raise x_workflow.ShowMoreExpansionError("page_not_ready: article full text is unavailable")
            records = [x_article_record(payload)]
            if not records[0]["full_text_tail"]:
                raise x_workflow.ShowMoreExpansionError("page_not_ready: article text tail is unavailable")
            artifact_path = "artifacts/article.json"
        artifact = {"schema_version": 1, "capability_id": capability_id, "items": records}
        contract = x_contract(args, capability_id, started_at, status="completed", requested=args.limit, records=records, artifact=artifact_path, last_url=str(records[-1]["url"]), last_title=str(records[-1].get("title") or ""))
        validate_site_artifact(artifact)
        validate_shared_contract(contract)
        output = Path(args.output_root)
        write_json(output / artifact_path, artifact)
        write_json(output / "contract" / "summary.json", contract)
        write_json(output / "contract" / "progress.json", contract["progress"])
    except (OSError, ValueError, RuntimeError) as error:
        return write_x_failure(args, capability_id, started_at, error)
    print(json.dumps(x_envelope(args, capability_id, started_at, status="completed", contract_ref="contract/summary.json", artifact_refs=[artifact_path]), ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("run")
    command.add_argument("--site", required=True)
    command.add_argument("--resource", required=True)
    command.add_argument("--intent", required=True)
    command.add_argument("--limit", default="5")
    command.add_argument("--task-id", required=True)
    command.add_argument("--output-root", required=True)
    command.add_argument("--fixture", default="")
    command.add_argument("--session", default="")
    command.add_argument("--tab", default="")
    command.add_argument("--item-id", default="")
    command.add_argument("--max-scrolls", type=int, default=5)
    command.add_argument("--id", default="")
    command.add_argument("--type", default="Rb")
    command.add_argument("--photo-id", default="")
    command.add_argument("--max-item-bytes", type=int, default=10 * 1024 * 1024)
    command.add_argument("--max-total-bytes", type=int, default=20 * 1024 * 1024)
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
