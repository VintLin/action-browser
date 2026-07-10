from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest

from scripts.adapters.chatgpt_workflow import (
    ChatGptTask,
    is_nonfatal_submit_error,
    require_web_search_enabled,
    submission_record,
)


def test_submission_record_tracks_new_chat_defaults() -> None:
    record = submission_record(
        1,
        ChatGptTask(title="Q1", question="Question"),
        "https://chatgpt.com/c/1",
        2,
        "2026-07-02T12:00:00",
        {"search_enabled": True, "search_text": "网页搜索"},
    )

    assert record["mode"] == {
        "surface": "Chat",
        "web_search": True,
        "web_search_state": "网页搜索",
        "intelligence": "极高",
        "model": "latest",
    }


def test_require_web_search_enabled_raises_when_required_but_not_verified() -> None:
    with pytest.raises(RuntimeError, match="web search was required"):
        require_web_search_enabled({"search_enabled": False}, True)


def test_model_settings_failure_is_nonfatal() -> None:
    assert is_nonfatal_submit_error(RuntimeError("model settings control not found: {}"))
