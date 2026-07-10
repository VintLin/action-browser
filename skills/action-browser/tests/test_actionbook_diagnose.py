from pathlib import Path
import sys

# `pytest tests/test_actionbook_diagnose.py -v` does not place the repo root on sys.path here.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.diagnostics import actionbook_diagnose


def test_classify_result_handles_session_not_found() -> None:
    result = {
        "returncode": 1,
        "error_code": "SESSION_NOT_FOUND",
        "payload": {"ok": False, "error": {"code": "SESSION_NOT_FOUND"}},
    }

    assert actionbook_diagnose.classify_result(result) == "session_not_found"


def test_summarize_report_tracks_direct_and_shell_visibility() -> None:
    report = {
        "start": {"kind": "ok"},
        "close": {"kind": "ok"},
        "polls": [
            {
                "extension": {"payload": {"data": {"extension_connected": False}}},
                "status_direct": {"kind": "session_not_found"},
                "status_shell": {"kind": "session_not_found"},
                "list_tabs_direct": {"kind": "session_not_found"},
            },
            {
                "extension": {"payload": {"data": {"extension_connected": True}}},
                "status_direct": {"kind": "ok"},
                "status_shell": {"kind": "ok"},
                "list_tabs_direct": {"kind": "ok"},
            },
        ],
    }

    assert actionbook_diagnose.summarize_report(report) == {
        "start_ok": True,
        "extension_connected_after_start": True,
        "session_visible_direct": True,
        "session_visible_in_fresh_shell": True,
        "tabs_visible_direct": True,
        "close_ok": True,
    }


def test_summarize_batch_counts_successes() -> None:
    reports = [
        {
            "summary": {
                "start_ok": True,
                "extension_connected_after_start": True,
                "session_visible_direct": True,
                "session_visible_in_fresh_shell": False,
                "tabs_visible_direct": True,
                "close_ok": True,
            }
        },
        {
            "summary": {
                "start_ok": False,
                "extension_connected_after_start": False,
                "session_visible_direct": False,
                "session_visible_in_fresh_shell": False,
                "tabs_visible_direct": False,
                "close_ok": True,
            }
        },
    ]

    assert actionbook_diagnose.summarize_batch(reports) == {
        "runs": 2,
        "start_ok_runs": 1,
        "extension_connected_runs": 1,
        "session_visible_direct_runs": 1,
        "session_visible_in_fresh_shell_runs": 0,
        "tabs_visible_direct_runs": 1,
        "close_ok_runs": 2,
    }
