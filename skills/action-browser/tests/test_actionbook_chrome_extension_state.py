from pathlib import Path
import json
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.diagnostics import actionbook_chrome_extension_state


def test_classify_record_handles_missing_manifest_metadata() -> None:
    item = {"path": "/tmp/demo"}

    assert actionbook_chrome_extension_state.classify_record(item, path_exists=True) == "missing_manifest_metadata"


def test_profile_report_reads_preferences_and_secure_preferences(tmp_path: Path) -> None:
    profile = tmp_path / "Default"
    profile.mkdir()
    (profile / "Preferences").write_text(
        json.dumps(
            {
                "extensions": {
                    "settings": {
                        "dpfioflkmnkklgjldmaggkodhlidkdcd": {
                            "path": str(tmp_path / "actionbook-extension-v0.5.0"),
                            "manifest": {"name": "Actionbook", "version": "0.5.0"},
                            "state": 1,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (profile / "Secure Preferences").write_text(
        json.dumps(
            {
                "extensions": {
                    "settings": {
                        "dpfioflkmnkklgjldmaggkodhlidkdcd": {
                            "path": str(tmp_path / "actionbook-extension-v0.5.0"),
                            "manifest": {"name": "Actionbook", "version": "0.5.0"},
                            "state": 1,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "actionbook-extension-v0.5.0").mkdir()

    report = actionbook_chrome_extension_state.profile_report(profile)

    assert report["profile"] == "Default"
    assert len(report["records"]) == 1
    secure = report["records"][0]["secure_preferences"]
    assert secure["record_status"] == "enabled"
    assert secure["path_exists"] is True


def test_profile_report_finds_actionbook_record_without_fixed_extension_id(tmp_path: Path) -> None:
    profile = tmp_path / "Default"
    profile.mkdir()
    (profile / "Preferences").write_text(
        json.dumps(
            {
                "extensions": {
                    "settings": {
                        "some-random-id": {
                            "path": str(tmp_path / "actionbook-extension-v0.5.0"),
                            "state": 1,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "actionbook-extension-v0.5.0").mkdir()

    report = actionbook_chrome_extension_state.profile_report(profile)

    assert len(report["records"]) == 1
    assert report["records"][0]["extension_id"] == "some-random-id"


def test_inspect_profiles_uses_local_state_selected_profile(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "Chrome"
    root.mkdir()
    (root / "Local State").write_text(
        json.dumps({"profile": {"last_used": "Profile 3", "last_active_profiles": ["Profile 3"]}}),
        encoding="utf-8",
    )
    profile = root / "Profile 3"
    profile.mkdir()
    (profile / "Preferences").write_text(json.dumps({}), encoding="utf-8")

    monkeypatch.setattr(actionbook_chrome_extension_state, "chrome_root", lambda: root)

    report = actionbook_chrome_extension_state.inspect_profiles(root)

    assert report["selected_profile_directory"] == "Profile 3"
    assert report["last_active_profiles"] == ["Profile 3"]
    assert report["profiles"][0]["profile"] == "Profile 3"
