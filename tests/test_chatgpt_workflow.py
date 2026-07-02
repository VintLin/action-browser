from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.adapters.chatgpt_workflow import ChatGptTask, is_nonfatal_submit_error, latest_model_label, submission_record


def test_submission_record_tracks_ultra_high_model() -> None:
    record = submission_record(
        1,
        ChatGptTask(title="Q1", question="Question"),
        "https://chatgpt.com/c/1",
        2,
        "2026-07-02T12:00:00",
        {"text": "超高"},
    )

    assert record["mode"] == {
        "web_search": True,
        "model": "ultra_high",
        "model_text": "超高",
        "latest_model": "",
    }


def test_ultra_high_model_selection_failure_is_nonfatal() -> None:
    assert is_nonfatal_submit_error(RuntimeError("ultra high model control not found: {}"))


def test_latest_model_label_uses_highest_gpt_version() -> None:
    assert latest_model_label(["GPT-5.3", "o3", "GPT-5.5", "GPT-5.4"]) == "GPT-5.5"
