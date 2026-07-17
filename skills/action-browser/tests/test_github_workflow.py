from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.adapters import github_workflow
import argparse
import pytest


def test_github_trending_parser_preserves_repository_identity(monkeypatch):
    html = """
    <article class="Box-row">
      <h2><a href="/openai/demo">openai / demo</a></h2>
      <span>1,234 stars</span><span>56 forks</span>
    </article>
    """
    monkeypatch.setattr(github_workflow, "fetch_text", lambda *args, **kwargs: html)
    result = github_workflow.load_trending("", "daily", 1)
    assert result.records == [{
        "id": "openai/demo",
        "rank": 1,
        "name": "openai/demo",
        "url": "https://github.com/openai/demo",
        "stars": "1,234",
        "forks": "56",
    }]


def test_github_help_exposes_only_read_surface():
    text = github_workflow.build_parser().format_help()
    assert "trending" in text
    assert "whoami" in text
    assert "issue" not in text.lower()


def test_github_owned_tab_extension_gate_is_explicit(monkeypatch):
    monkeypatch.setattr(
        github_workflow,
        "attach_workflow",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            github_workflow.ActionBookFailure("CHROME_URL_BLOCKED", "chrome-extension:// mismatch")
        ),
    )
    with pytest.raises(github_workflow.FetchError) as error:
        github_workflow.load_whoami(argparse.Namespace())
    assert error.value.reason_code == "needs_user_action"
