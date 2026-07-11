from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import json


CURRENT_SITES = (
    "bilibili", "chatgpt", "douban", "douyin", "feishu", "jd", "taobao",
    "weibo", "x", "xiaohongshu", "youtube", "zhihu", "zhipin", "reddit",
)
ALIASES = {"twitter": "x", "boss": "zhipin"}
READ_INTENTS = ("list", "search", "recommend", "trending", "detail", "comments", "profile", "whoami", "history", "notifications", "stats", "download", "export")
WRITE_INTENTS = ("create", "update", "delete", "react", "follow", "message", "publish")
TOP_LEVEL_FIELDS = {"schema_version", "reference_baseline", "execution_baseline", "generated_at", "sites", "capabilities", "exclusions", "conflicts", "maintenance"}
CAPABILITY_FIELDS = {"id", "site", "reference_aliases", "resource", "intent", "effect", "local_effect", "description", "source_commands", "native", "access_requirement", "primary_strategy", "fallbacks", "parameters", "equivalence_classes", "semantic_fields", "identity", "limits", "risk_tier", "idempotency", "status", "priority_score", "evidence", "tests", "docs", "exclusion_reason", "conflict_reason"}
LIFECYCLE = {"discovered", "specified", "implemented", "verified", "verified_empty", "waiting_user", "blocked", "excluded", "deprecated"}
FOCUSED_TEST_SITES = {"chatgpt", "taobao", "x"}


def normalize_site(site: str) -> str:
    return ALIASES.get(site, site)


def _intent(name: str, access: str) -> str:
    value = name.replace("_", "-").lower()
    if value in {"me", "status"}:
        return "whoami"
    # ponytail: explicit order keeps overlapping names such as list-create stable.
    for intent in WRITE_INTENTS + READ_INTENTS:
        if intent in value:
            return intent
    return "detail" if access == "read" else "update"


def _capability(command: dict[str, Any], site: str, native: bool = False) -> dict[str, Any]:
    access = str(command.get("access", "read"))
    name = str(command.get("name", "unknown"))
    if name == "login":
        intent, effect = "login", "login_assistance"
    elif access == "utility":
        intent, effect = "utility", "local_utility"
    else:
        intent = _intent(name, access)
        effect = "remote_write" if access == "write" and intent != "whoami" else "read"
    resource = str(command.get("name", "item")).replace("_", "-")
    columns = [str(column) for column in command.get("columns", [])]
    fields = [{"semantic": field, "reference_fields": [field], "target_field": field if native else "", "required": not native} for field in columns]
    return {
        "id": f"{site}.{resource}.{intent}.{effect}", "site": site,
        "reference_aliases": [] if native else [str(command["site"])], "resource": resource,
        "intent": intent, "effect": effect, "local_effect": "none",
        "description": str(command.get("description", "")), "source_commands": [] if native else [f"{command['site']} {command['name']}"],
        "native": native, "access_requirement": "public" if not command.get("browser") else "browser",
        "primary_strategy": str(command.get("strategy", "dom")), "fallbacks": [], "parameters": [],
        "equivalence_classes": [], "semantic_fields": fields, "identity": {"field": "id"},
        "limits": {"max_items": 20}, "risk_tier": "read" if effect in {"read", "local_utility", "login_assistance"} else "communication",
        "idempotency": "not_applicable" if effect in {"read", "local_utility", "login_assistance"} else "verify_before_retry",
        "status": "discovered", "priority_score": None, "evidence": [], "tests": [], "docs": [],
        "exclusion_reason": None, "conflict_reason": None,
    }


def build_catalog(reference: list[dict[str, Any]], target: dict[str, Any], *, reference_baseline: str, execution_baseline: str) -> dict[str, Any]:
    aliases_by_site: dict[str, list[str]] = defaultdict(list)
    for command in reference:
        canonical = normalize_site(str(command.get("site", "")))
        if canonical in CURRENT_SITES and str(command["site"]) not in aliases_by_site[canonical]:
            aliases_by_site[canonical].append(str(command["site"]))
    sites = []
    for site in CURRENT_SITES:
        aliases = sorted(aliases_by_site[site])
        sites.append({"id": site, "reference_aliases": aliases, "support_state": "native" if site == "feishu" else "overlap", "reason": "action-browser-only" if site == "feishu" else None})
    capabilities = [_capability(command, normalize_site(str(command["site"]))) for command in reference if normalize_site(str(command.get("site", ""))) in CURRENT_SITES]
    for site in target.get("sites", []):
        if site == "feishu":
            capabilities.append(_capability({"site": site, "name": "inventory", "access": "read", "strategy": "ui", "browser": True, "columns": ["id", "title"]}, site, native=True))
    return {
        "schema_version": 1,
        "reference_baseline": {"repo": "opencli", "commit": reference_baseline, "version": None, "captured_at": None},
        "execution_baseline": {"commit": execution_baseline, "worktree_status": "clean", "captured_at": None},
        "generated_at": None, "sites": sites, "capabilities": sorted(capabilities, key=lambda item: item["id"]),
        "exclusions": [], "conflicts": [], "maintenance": {"previous_baseline": None, "next_due": None, "trigger": "foundation"},
    }


def validate_catalog(catalog: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(catalog, dict):
        return [{"reason_code": "schema_mismatch", "message": "catalog must be an object"}]
    unknown = sorted(set(catalog) - TOP_LEVEL_FIELDS)
    if unknown or set(catalog) != TOP_LEVEL_FIELDS:
        errors.append({"reason_code": "schema_mismatch", "message": f"top-level schema mismatch: {unknown}"})
    if not isinstance(catalog.get("capabilities"), list):
        return errors + [{"reason_code": "schema_mismatch", "message": "capabilities must be a list"}]
    seen: set[str] = set()
    for record in catalog.get("capabilities", []):
        if set(record) != CAPABILITY_FIELDS:
            errors.append({"reason_code": "schema_mismatch", "message": f"capability schema mismatch: {record.get('id', '?')}"})
            continue
        if record["id"] in seen:
            errors.append({"reason_code": "schema_mismatch", "message": f"duplicate capability id: {record['id']}"})
        seen.add(record["id"])
        if record["status"] not in LIFECYCLE:
            errors.append({"reason_code": "schema_mismatch", "message": f"invalid status: {record['id']}"})
        for field in record["semantic_fields"]:
            if set(field) != {"semantic", "reference_fields", "target_field", "required"}:
                errors.append({"reason_code": "schema_mismatch", "message": f"field schema mismatch: {record['id']}"})
            elif field["required"] and not field["target_field"]:
                errors.append({"reason_code": "field_gap", "message": f"missing required target field: {record['id']}"})
    if not isinstance(catalog.get("conflicts"), list):
        errors.append({"reason_code": "schema_mismatch", "message": "conflicts must be a list"})
    else:
        for conflict in catalog["conflicts"]:
            if not isinstance(conflict, dict) or conflict.get("type") not in {"reference_conflict", "native_conflict"}:
                errors.append({"reason_code": "schema_mismatch", "message": "invalid conflict"})
            elif conflict.get("resolution_state") != "resolved":
                errors.append({"reason_code": str(conflict["type"]), "message": str(conflict.get("id", "unresolved conflict"))})
    return errors


def render_markdown(catalog: dict[str, Any]) -> str:
    lines = ["# Capability Catalog", "", f"Reference Baseline: `{catalog['reference_baseline']['commit']}`", f"Execution Baseline: `{catalog['execution_baseline']['commit']}`", "", "| Site | Reference aliases | Capabilities | Field gaps | Focused test |", "|---|---|---:|---:|---|"]
    counts: dict[str, int] = defaultdict(int)
    for record in catalog["capabilities"]:
        counts[record["site"]] += 1
    for site in catalog["sites"]:
        gaps = sum(1 for record in catalog["capabilities"] if record["site"] == site["id"] for field in record["semantic_fields"] if field["required"] and not field["target_field"])
        focused = "existing" if site["id"] in FOCUSED_TEST_SITES else "missing"
        lines.append(f"| {site['id']} | {', '.join(site['reference_aliases']) or '-'} | {counts[site['id']]} | {gaps} | {focused} |")
    return "\n".join(lines) + "\n"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def envelope(command: str, status: str, *, artifact_refs: list[str] | None = None, failure: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"schema_version": 1, "run_id": "catalog", "task_id": "catalog", "capability_id": f"programme.catalog.{command}.read", "site": "programme", "command": command, "status": status, "result_quality": "deterministic", "contract_ref": None, "artifact_refs": artifact_refs or [], "strategy_used": "local", "fallback_reason": None, "failure": failure, "started_at": None, "finished_at": None}
