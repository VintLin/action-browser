from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.catalog.core import build_catalog, normalize_site, render_markdown, validate_catalog


def command(site: str, name: str, access: str = "read") -> dict[str, object]:
    return {"site": site, "name": name, "access": access, "strategy": "dom", "browser": True, "columns": ["id", "title"]}


def target() -> dict[str, object]:
    return {"sites": ["x", "zhipin", "feishu"], "evidence": {"x": {"script": "x_workflow.py", "reference": "x.md"}}}


def test_normalizes_reference_aliases() -> None:
    assert normalize_site("twitter") == "x"
    assert normalize_site("boss") == "zhipin"
    assert normalize_site("douban") == "douban"


def test_write_token_wins_when_a_command_name_contains_read_and_write_words() -> None:
    catalog = build_catalog([command("twitter", "list-create", "write")], target(), reference_baseline="ref", execution_baseline="exec")

    assert next(record for record in catalog["capabilities"] if record["site"] == "x")["intent"] == "create"


def test_login_and_utility_are_not_classified_as_writes() -> None:
    catalog = build_catalog(
        [command("twitter", "login", "write"), command("twitter", "format", "utility")],
        target(),
        reference_baseline="ref",
        execution_baseline="exec",
    )

    records = {record["resource"]: record for record in catalog["capabilities"] if record["site"] == "x"}
    assert records["login"]["effect"] == "login_assistance"
    assert records["format"]["effect"] == "local_utility"


def test_unresolved_conflict_blocks_validation() -> None:
    catalog = build_catalog([], target(), reference_baseline="ref", execution_baseline="exec")
    catalog["conflicts"] = [{"id": "x.conflict", "type": "reference_conflict", "resolution_state": "open"}]

    errors = validate_catalog(catalog)

    assert {error["reason_code"] for error in errors} == {"reference_conflict"}


def test_builds_one_record_per_canonical_site_and_marks_native_feishu() -> None:
    catalog = build_catalog(
        [command("twitter", "timeline"), command("boss", "joblist")],
        target(),
        reference_baseline="ref",
        execution_baseline="exec",
    )

    assert len(catalog["sites"]) == 13
    assert next(site for site in catalog["sites"] if site["id"] == "x")["reference_aliases"] == ["twitter"]
    assert any(record["site"] == "feishu" and record["native"] for record in catalog["capabilities"])


def test_required_field_gap_blocks_validation() -> None:
    catalog = build_catalog([command("twitter", "timeline")], target(), reference_baseline="ref", execution_baseline="exec")

    errors = validate_catalog(catalog)

    assert any(error["reason_code"] == "field_gap" for error in errors)


def test_duplicate_capability_id_and_unknown_field_block_validation() -> None:
    catalog = build_catalog([command("twitter", "timeline")], target(), reference_baseline="ref", execution_baseline="exec")
    catalog["capabilities"].append(catalog["capabilities"][0].copy())
    catalog["unexpected"] = True

    errors = validate_catalog(catalog)

    assert "schema_mismatch" in {error["reason_code"] for error in errors}


def test_markdown_is_deterministic() -> None:
    catalog = build_catalog([command("twitter", "timeline")], target(), reference_baseline="ref", execution_baseline="exec")

    assert render_markdown(catalog) == render_markdown(catalog)


def test_cli_writes_one_json_object_to_stdout(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    inventory = tmp_path / "inventory.json"
    source = tmp_path / "catalog.json"
    manifest.write_text(json.dumps([command("twitter", "timeline")]), encoding="utf-8")
    inventory.write_text(json.dumps(target()), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "scripts.catalog", "diff", "--reference", str(manifest), "--target", str(inventory), "--output", str(source), "--reference-baseline", "ref", "--execution-baseline", "exec"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert list(json.loads(result.stdout)) == ["artifact_refs", "capability_id", "command", "contract_ref", "failure", "fallback_reason", "finished_at", "result_quality", "run_id", "schema_version", "site", "started_at", "status", "strategy_used", "task_id"]
    assert source.is_file()


def test_validate_malformed_catalog_writes_a_failure_envelope(tmp_path: Path) -> None:
    source = tmp_path / "bad.json"
    source.write_text('{"capabilities":"not-a-list"}', encoding="utf-8")

    result = subprocess.run([sys.executable, "-m", "scripts.catalog", "validate", "--source", str(source)], cwd=ROOT, text=True, capture_output=True, check=False)

    assert result.returncode == 1
    assert json.loads(result.stdout)["failure"]["reason_code"] == "schema_mismatch"
    assert "Traceback" not in result.stderr


def test_capture_failure_keeps_the_canonical_capability_id(tmp_path: Path) -> None:
    result = subprocess.run([sys.executable, "-m", "scripts.catalog", "capture-reference", "--repo", str(tmp_path), "--commit", "missing", "--output", str(tmp_path / "snapshot.json")], cwd=ROOT, text=True, capture_output=True, check=False)

    assert result.returncode == 1
    assert json.loads(result.stdout)["capability_id"] == "programme.catalog.capture.read"
