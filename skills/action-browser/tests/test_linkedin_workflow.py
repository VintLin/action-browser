from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.adapters import linkedin_workflow


def test_linkedin_parser_exposes_all_reference_read_resources():
    help_text = linkedin_workflow.build_parser().format_help()
    for resource in linkedin_workflow.READ_RESOURCES:
        assert resource in help_text


def test_linkedin_safe_url_rejects_cross_site_targets():
    assert linkedin_workflow.safe_linkedin_url("https://www.linkedin.com/in/example", "profile")
    with pytest.raises(linkedin_workflow.FetchError):
        linkedin_workflow.safe_linkedin_url("https://example.com/in/example", "profile")


def test_linkedin_company_url_and_search_url_are_canonical():
    company = linkedin_workflow.argparse.Namespace(resource="company", company="nvidia")
    assert linkedin_workflow.target_url(company) == "https://www.linkedin.com/company/nvidia/about/"
    company_url = linkedin_workflow.argparse.Namespace(resource="company", company="https://www.linkedin.com/company/nvidia/about/")
    assert linkedin_workflow.target_url(company_url) == "https://www.linkedin.com/company/nvidia/about/"
    search = linkedin_workflow.argparse.Namespace(resource="search", query="python", location="London")
    assert "keywords=python" in linkedin_workflow.target_url(search)
    assert "location=London" in linkedin_workflow.target_url(search)


def test_linkedin_auth_wall_is_never_promoted_to_a_success(monkeypatch):
    monkeypatch.setattr(linkedin_workflow, "evaluate", lambda *args, **kwargs: {"authRequired": True})
    with pytest.raises(linkedin_workflow.FetchError, match="authenticated browser session"):
        linkedin_workflow.extract_visible_page(object(), 1)


def test_linkedin_owned_tab_extension_gate_is_explicit(monkeypatch):
    monkeypatch.setattr(
        linkedin_workflow,
        "attach_workflow",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            linkedin_workflow.ActionBookFailure("CHROME_URL_BLOCKED", "chrome-extension:// mismatch")
        ),
    )
    args = linkedin_workflow.argparse.Namespace(resource="whoami")
    with pytest.raises(linkedin_workflow.FetchError) as error:
        linkedin_workflow.load_resource(args)
    assert error.value.reason_code == "needs_user_action"
