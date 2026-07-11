from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.adapters.reddit_workflow import (
    build_parser,
    extract_media,
    normalize_post_id,
    normalize_subreddit,
    post_record,
)


def test_reddit_normalizers_keep_opencli_identity_inputs() -> None:
    assert normalize_subreddit("/r/python") == "python"
    assert normalize_post_id("t3_ABC123") == "abc123"
    assert normalize_post_id("https://www.reddit.com/r/python/comments/ABC123/title/") == "abc123"
    with pytest.raises(ValueError, match="subreddit"):
        normalize_subreddit("r/invalid-name")


def test_reddit_post_record_preserves_media_semantics() -> None:
    record = post_record({
        "id": "abc123",
        "title": "Post",
        "subreddit_name_prefixed": "r/python",
        "author": "alice",
        "permalink": "/r/python/comments/abc123/post/",
        "preview": {"images": [{"source": {"url": "https://img/?a=1&amp;b=2"}}]},
        "gallery_data": {"items": [{"media_id": "m1"}]},
        "media_metadata": {"m1": {"s": {"u": "https://img/gallery.jpg"}}},
    }, rank=1)

    assert record["id"] == "abc123"
    assert record["rank"] == 1
    assert record["preview_image_url"] == "https://img/?a=1&b=2"
    assert record["gallery_urls"] == ["https://img/gallery.jpg"]


def test_reddit_parser_exposes_read_only_opencli_surface() -> None:
    help_text = build_parser().format_help()
    for command in ("hot", "search", "read", "subreddit-info", "whoami"):
        assert command in help_text
