from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.diagnostics import actionbook_bootstrap_stability


def test_summarize_counts_successes_and_failures() -> None:
    reports = [
        {"status": "success"},
        {"status": "failed", "error": "EXTENSION_NOT_CONNECTED"},
        {"status": "failed", "error": "EXTENSION_NOT_CONNECTED"},
        {"status": "failed", "error": "SESSION_NOT_FOUND"},
    ]

    assert actionbook_bootstrap_stability.summarize(reports) == {
        "runs": 4,
        "successes": 1,
        "failures": 3,
        "failure_counts": {
            "EXTENSION_NOT_CONNECTED": 2,
            "SESSION_NOT_FOUND": 1,
        },
    }


def test_parse_mixed_output_handles_log_prefix_before_json() -> None:
    text = '[23:24:44] ActionBook extension 尚未连接\\n{"session_id":"s1","tab_id":"t1"}'

    assert actionbook_bootstrap_stability.parse_mixed_output(text) == {
        "session_id": "s1",
        "tab_id": "t1",
    }


def test_normalize_output_decodes_timeout_bytes() -> None:
    assert actionbook_bootstrap_stability.normalize_output(b"hello") == "hello"
    assert actionbook_bootstrap_stability.normalize_output("world") == "world"
    assert actionbook_bootstrap_stability.normalize_output(None) == ""


def test_matching_session_ids_filters_to_prefix() -> None:
    payload = {
        "data": {
            "sessions": [
                {"session_id": "bootstrap-stability-01"},
                {"session_id": "bootstrap-stability-02"},
                {"session_id": "other-session"},
            ]
        }
    }

    assert actionbook_bootstrap_stability.matching_session_ids(payload, "bootstrap-stability-") == [
        "bootstrap-stability-01",
        "bootstrap-stability-02",
    ]


def test_load_verified_tabs_retries_after_empty_list(monkeypatch) -> None:
    events: list[str] = []

    monkeypatch.setattr(actionbook_bootstrap_stability, "run_diagnose", lambda *args, **kwargs: events.append("diagnose"))
    monkeypatch.setattr(actionbook_bootstrap_stability, "restart_daemon", lambda *args, **kwargs: events.append("restart"))
    monkeypatch.setattr(
        actionbook_bootstrap_stability,
        "ensure_session",
        lambda report, session_id: {"returncode": 0, "payload": {"tab_id": "t2"}},
    )
    monkeypatch.setattr(
        actionbook_bootstrap_stability,
        "reconnect_session",
        lambda report, session_id, tab_id: events.append(f"reconnect:{tab_id}"),
    )
    responses = iter(
        [
            {"payload": {"tabs": []}},
            {"payload": {"tabs": [{"tab_id": "t2"}]}},
        ]
    )
    monkeypatch.setattr(actionbook_bootstrap_stability, "list_tabs", lambda report, session_id: next(responses))

    base_tab, tabs = actionbook_bootstrap_stability.load_verified_tabs({}, Path("."), "round-01", "s1")

    assert base_tab == "t2"
    assert tabs == [{"tab_id": "t2"}]
    assert events == ["diagnose", "restart", "reconnect:t2"]
