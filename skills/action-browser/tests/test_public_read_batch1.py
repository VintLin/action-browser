from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.adapters import google_workflow, hackernews_workflow, stackoverflow_workflow, wikipedia_workflow
from scripts.adapters.public_read_runtime import FetchError, ReadResult, emit_read


RSS = """<rss><channel><item><guid>1</guid><title>Headline</title><link>https://example.com/a</link><pubDate>today</pubDate><description>Summary</description><source>Example</source></item></channel></rss>"""


def test_google_readers_normalize_rss_suggest_and_search(monkeypatch):
    monkeypatch.setattr(google_workflow, "fetch_text", lambda *args, **kwargs: RSS)
    assert google_workflow.load_news(1).records[0]["title"] == "Headline"
    assert google_workflow.load_trends(1).records[0]["traffic"] == "Summary"

    monkeypatch.setattr(google_workflow, "fetch_json", lambda *args, **kwargs: ["OpenAI", ["OpenAI API", "OpenAI docs"]])
    assert [item["query"] for item in google_workflow.load_suggest("OpenAI", 2).records] == ["OpenAI API", "OpenAI docs"]

    monkeypatch.setattr(google_workflow, "fetch_text", lambda *args, **kwargs: '<a href="https://example.com/a"><h3>Example</h3></a>')
    assert google_workflow.load_search("x", 1).records == [{"id": "https://example.com/a", "title": "Example", "url": "https://example.com/a"}]


def test_google_search_interstitial_is_explicit(monkeypatch):
    monkeypatch.setattr(google_workflow, "fetch_text", lambda *args, **kwargs: "httpservice/retry emsg=SG_REL")
    with pytest.raises(FetchError) as error:
        google_workflow.load_search("OpenAI", 1)
    assert error.value.reason_code == "risk_control"


def test_google_search_browser_fallback_preserves_dom_strategy(monkeypatch):
    args = argparse.Namespace(query="OpenAI", count=1, task_id="google", session="s", tab="t")
    monkeypatch.setattr(google_workflow, "load_search", lambda *args, **kwargs: (_ for _ in ()).throw(FetchError("risk_control", "retry")))
    class FakeBook:
        def goto(self, _url):
            return None
    monkeypatch.setattr(google_workflow, "attach_workflow", lambda *args, **kwargs: FakeBook())
    monkeypatch.setattr(google_workflow, "wait_until_stable", lambda *args, **kwargs: {})
    monkeypatch.setattr(google_workflow, "evaluate", lambda *args, **kwargs: {"url": "https://www.google.com/search?q=OpenAI", "title": "OpenAI - Google Search", "results": [{"title": "Example", "url": "https://example.com"}]})
    result = google_workflow.load_search_or_browser(args)
    assert result.strategy_used == "dom"
    assert result.records[0]["url"] == "https://example.com"


def test_stackoverflow_loaders_map_api_items(monkeypatch):
    def fake_fetch(url, **_kwargs):
        parsed = urlparse(url)
        path = parsed.path
        query = parse_qs(parsed.query)
        item = {"question_id": 42, "title": "How?", "link": "https://stackoverflow.com/q/42", "score": 3, "tags": ["python"]}
        if path.endswith("/answers"):
            return {"items": [{"answer_id": 7, "body": "Answer", "score": 2}]}
        if path.endswith("/users"):
            return {"items": [{"user_id": 9, "display_name": "Ada", "reputation": 10}]}
        if path.endswith("/questions/42") and query.get("filter") == ["withbody"]:
            return {"items": [{**item, "body": "Question"}]}
        return {"items": [item], "backoff": 2}

    monkeypatch.setattr(stackoverflow_workflow, "fetch_json", fake_fetch)
    assert stackoverflow_workflow.load_hot(1).records[0]["id"] == 42
    assert stackoverflow_workflow.load_read("42").records[0]["answers"][0]["id"] == 7
    assert stackoverflow_workflow.load_user("Ada").records[0]["name"] == "Ada"


def test_hackernews_loaders_keep_story_identity(monkeypatch):
    def fake_fetch(url, **_kwargs):
        if url.endswith("topstories.json"):
            return [101]
        if url.endswith("/item/101.json"):
            return {"id": 101, "type": "story", "by": "alice", "title": "Story", "kids": [102]}
        if url.endswith("/item/102.json"):
            return {"id": 102, "type": "comment", "by": "bob", "text": "Reply"}
        if "/search?" in url:
            return {"hits": [{"objectID": "101", "title": "Story", "author": "alice"}]}
        return {"id": "alice", "karma": 1}

    monkeypatch.setattr(hackernews_workflow, "fetch_json", fake_fetch)
    assert hackernews_workflow.load_listing("top", 1).records[0]["id"] == 101
    assert hackernews_workflow.load_read("101").records[0]["comments"][0]["id"] == 102
    assert hackernews_workflow.load_search("story", 1).records[0]["id"] == "101"


def test_wikipedia_loaders_normalize_pages(monkeypatch):
    def fake_fetch(url, **_kwargs):
        if "page/summary" in url:
            return {"pageid": 1, "title": "Python", "extract": "A language", "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Python"}}}
        if "metrics/pageviews" in url:
            return {"items": [{"articles": [{"article": "Python", "views": 10, "rank": 1}]}]}
        parsed = parse_qs(urlparse(url).query)
        if parsed.get("list") == ["search"]:
            return {"query": {"search": [{"pageid": 1, "title": "Python", "snippet": "A language"}]}}
        if parsed.get("list") == ["random"]:
            return {"query": {"random": [{"id": 1, "title": "Python"}]}}
        return {"query": {"pages": [{"pageid": 1, "title": "Python", "extract": "A language", "fullurl": "https://en.wikipedia.org/wiki/Python"}]}}

    monkeypatch.setattr(wikipedia_workflow, "fetch_json", fake_fetch)
    assert wikipedia_workflow.load_search("Python", 1).records[0]["id"] == 1
    assert wikipedia_workflow.load_page("Python").records[0]["title"] == "Python"
    assert wikipedia_workflow.load_summary("Python").records[0]["extract"] == "A language"
    assert wikipedia_workflow.load_random(1).records[0]["id"] == 1
    assert wikipedia_workflow.load_trending(1).records[0]["views"] == 10


def test_emit_read_writes_contract_artifact_and_one_envelope(tmp_path, capsys):
    args = argparse.Namespace(output=str(tmp_path), task_id="fixture")
    assert emit_read(args, site="fixture", resource="items", loader=lambda: ReadResult([{"id": 1, "title": "one"}]), requested_count=1) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["status"] == "completed"
    assert (tmp_path / "artifacts/items.json").exists()
    assert json.loads((tmp_path / "contract/summary.json").read_text())["reference_baseline"].startswith("c1ad")


def test_emit_read_rejects_unproven_empty_results(tmp_path, capsys):
    args = argparse.Namespace(output=str(tmp_path), task_id="empty-fixture")
    assert emit_read(args, site="fixture", resource="items", loader=lambda: ReadResult([]), requested_count=1) == 1
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["status"] == "failed"
    assert envelope["failure"]["reason_code"] == "empty_unproven"
