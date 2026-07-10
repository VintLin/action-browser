#!/usr/bin/env python3
"""
Inspect Chrome profile records for ActionBook extension installs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ACTIONBOOK_NAME = "actionbook"
ACTIONBOOK_PATH_MARKER = "actionbook-extension"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def chrome_root() -> Path:
    return Path.home() / "Library/Application Support/Google/Chrome"


def looks_like_actionbook_extension(extension_id: str, item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    manifest = item.get("manifest") if isinstance(item.get("manifest"), dict) else {}
    manifest_name = str(manifest.get("name") or "").strip().casefold()
    if manifest_name == ACTIONBOOK_NAME:
        return True
    path_value = str(item.get("path") or "").strip().casefold()
    if ACTIONBOOK_PATH_MARKER in path_value:
        return True
    return ACTIONBOOK_NAME in str(extension_id or "").strip().casefold()


def extract_extension_record(settings: dict[str, Any], extension_id: str) -> dict[str, Any] | None:
    item = settings.get(extension_id)
    if not isinstance(item, dict):
        return None
    manifest = item.get("manifest") if isinstance(item.get("manifest"), dict) else {}
    path_value = str(item.get("path") or "").strip()
    resolved_path = Path(path_value).expanduser() if path_value else None
    path_exists = resolved_path.exists() if resolved_path else False
    return {
        "extension_id": extension_id,
        "state": item.get("state"),
        "location": item.get("location"),
        "creation_flags": item.get("creation_flags"),
        "from_webstore": item.get("from_webstore"),
        "path": path_value or None,
        "path_exists": path_exists,
        "manifest_name": manifest.get("name"),
        "manifest_version": manifest.get("version"),
        "manifest_present": bool(manifest),
        "record_status": classify_record(item, path_exists),
    }


def classify_record(item: dict[str, Any], path_exists: bool) -> str:
    manifest = item.get("manifest") if isinstance(item.get("manifest"), dict) else {}
    state = item.get("state")
    if not path_exists:
        return "broken_path"
    if not manifest:
        return "missing_manifest_metadata"
    if state in (0, "0"):
        return "disabled"
    if state in (1, "1"):
        return "enabled"
    return "unknown_state"


def profile_report(profile_dir: Path) -> dict[str, Any]:
    preferences = load_json(profile_dir / "Preferences")
    secure_preferences = load_json(profile_dir / "Secure Preferences")
    pref_settings = ((preferences.get("extensions") or {}).get("settings") or {}) if preferences else {}
    secure_settings = ((secure_preferences.get("extensions") or {}).get("settings") or {}) if secure_preferences else {}

    records: list[dict[str, Any]] = []
    candidate_ids = sorted(
        extension_id
        for extension_id in set(pref_settings) | set(secure_settings)
        if looks_like_actionbook_extension(
            extension_id,
            pref_settings.get(extension_id) or secure_settings.get(extension_id),
        )
    )
    for extension_id in candidate_ids:
        pref_record = extract_extension_record(pref_settings, extension_id)
        secure_record = extract_extension_record(secure_settings, extension_id)
        if pref_record is None and secure_record is None:
            continue
        records.append(
            {
                "extension_id": extension_id,
                "preferences": pref_record,
                "secure_preferences": secure_record,
            }
        )

    return {
        "profile": profile_dir.name,
        "preferences_exists": (profile_dir / "Preferences").exists(),
        "secure_preferences_exists": (profile_dir / "Secure Preferences").exists(),
        "records": records,
    }


def inspect_profiles(root: Path) -> dict[str, Any]:
    local_state = load_json(root / "Local State")
    profile_meta = local_state.get("profile") if isinstance(local_state.get("profile"), dict) else {}
    last_used = profile_meta.get("last_used")
    last_active = profile_meta.get("last_active_profiles") or []
    candidates = sorted(path for path in root.iterdir() if path.is_dir() and (path / "Preferences").exists())
    profiles = [profile_report(path) for path in candidates]
    return {
        "chrome_root": str(root),
        "selected_profile_directory": last_used,
        "last_active_profiles": last_active,
        "profiles": profiles,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Chrome ActionBook extension records.")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report = inspect_profiles(chrome_root())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(f"selected_profile_directory={report['selected_profile_directory']}")
    for profile in report["profiles"]:
        print(f"[{profile['profile']}]")
        if not profile["records"]:
            print("  actionbook_records=none")
            continue
        for record in profile["records"]:
            secure = record["secure_preferences"]
            prefs = record["preferences"]
            active = secure or prefs or {}
            print(
                "  "
                + f"id={record['extension_id']} "
                + f"status={active.get('record_status')} "
                + f"path={active.get('path')} "
                + f"path_exists={active.get('path_exists')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
