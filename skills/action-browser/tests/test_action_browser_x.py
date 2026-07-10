from __future__ import annotations

from argparse import Namespace
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import action_browser
from scripts.adapters import x_workflow


def payload(*, text: str = "preview", show_more: bool = False) -> x_workflow.TweetPayload:
    return x_workflow.TweetPayload(
        tweet_id="2075342549351297525", source_url="https://x.com/dotey/status/2075342549351297525", source_page="home",
        author_name="Author", author_handle="@author", author_profile_url="https://x.com/author", author_avatar_url="",
        text=text, created_at_text="", created_at_iso="2026-07-10T00:00:00.000Z", tweet_type="tweet",
        reply_to={}, quoted_tweet={}, media=[], links=[], card={}, article={}, metrics={"likes": "48"}, social_context={},
        is_bookmarked=False, raw_text_lines=[text, "显示更多"] if show_more else [text], extraction_warnings=[],
    )


def args(tmp_path: Path, **overrides: object) -> Namespace:
    values: dict[str, object] = {
        "site": "x", "resource": "timeline", "intent": "list", "limit": "1", "task_id": "t3-test",
        "session": "s1", "tab": "t1", "item_id": "", "max_scrolls": 2, "output_root": str(tmp_path), "fixture": "",
    }
    values.update(overrides)
    return Namespace(**values)


def test_x_timeline_command_writes_one_envelope_and_stable_identity(monkeypatch, tmp_path: Path, capsys) -> None:
    item = payload()
    monkeypatch.setattr(action_browser, "attach_workflow", lambda *_args: object())
    monkeypatch.setattr(action_browser, "collect_x_timeline", lambda *_args: [item])

    assert action_browser.run_x(args(tmp_path)) == 0

    output = capsys.readouterr().out.strip().splitlines()
    assert len(output) == 1
    envelope = json.loads(output[0])
    assert envelope["capability_id"] == "x.timeline.list.read"
    artifact = json.loads((tmp_path / "artifacts" / "timeline.json").read_text(encoding="utf-8"))
    assert artifact["items"][0]["id"] == item.tweet_id
    assert artifact["items"][0]["url"] == item.source_url
    assert artifact["items"][0]["has_media"] is False
    assert artifact["items"][0]["media"] == []
    assert artifact["items"][0]["card"] == {}
    assert artifact["items"][0]["quoted_tweet"] == {}


def test_x_article_command_writes_expanded_full_text_tail(monkeypatch, tmp_path: Path, capsys) -> None:
    item = payload(show_more=True)
    full_text = "The full expanded post ends with this exact final sentence."
    monkeypatch.setattr(action_browser, "attach_workflow", lambda *_args: object())
    monkeypatch.setattr(action_browser, "collect_x_timeline", lambda *_args: [item])

    def expand(_book, payloads, *, max_expansions: int) -> None:
        assert max_expansions == 1
        payloads[0].text = full_text
        payloads[0].raw_text_lines = [full_text]

    monkeypatch.setattr(x_workflow, "expand_show_more_payloads", expand)

    assert action_browser.run_x(args(tmp_path, resource="article", intent="detail", item_id=item.tweet_id)) == 0

    output = capsys.readouterr().out.strip().splitlines()
    assert len(output) == 1
    artifact = json.loads((tmp_path / "artifacts" / "article.json").read_text(encoding="utf-8"))
    assert artifact["items"][0]["full_text"] == full_text
    assert artifact["items"][0]["full_text_tail"].endswith("final sentence.")
    assert artifact["items"][0]["expanded"] is True


def test_x_command_ownership_failure_is_one_result_envelope(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/action_browser.py", "run", "--site", "x", "--resource", "timeline", "--intent", "list", "--task-id", "missing", "--session", "missing", "--tab", "missing", "--output-root", str(tmp_path)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )

    assert result.returncode == 1
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["failure"]["reason_code"] == "invalid_input"
