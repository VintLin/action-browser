from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import download_primitive


PNG = b"\x89PNG\r\n\x1a\nfixture-image"


class Response(BytesIO):
    def __init__(self, body: bytes, content_type: str = "image/png") -> None:
        super().__init__(body)
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_download_is_atomic_and_resumes_verified_file(monkeypatch, tmp_path: Path) -> None:
    calls = 0

    def open_url(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return Response(PNG)

    monkeypatch.setattr(download_primitive.urllib.request, "urlopen", open_url)
    target = tmp_path / "image.png"

    first = download_primitive.download_image("https://example.test/image.png", target, max_item_bytes=100, max_total_bytes=100, consumed_bytes=0)
    second = download_primitive.download_image("https://example.test/image.png", target, max_item_bytes=100, max_total_bytes=100, consumed_bytes=0, previous=first)

    assert first["status"] == "success"
    assert second["status"] == "skipped"
    assert calls == 1
    assert target.read_bytes() == PNG
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize(("body", "content_type", "limit", "reason"), [
    (b"<html>blocked</html>", "text/html", 100, "content_type"),
    (PNG, "image/png", 4, "max_item_bytes"),
])
def test_download_rejects_invalid_content_without_final_file(monkeypatch, tmp_path: Path, body: bytes, content_type: str, limit: int, reason: str) -> None:
    monkeypatch.setattr(download_primitive.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(body, content_type))

    result = download_primitive.download_image("https://example.test/image", tmp_path / "image.png", max_item_bytes=limit, max_total_bytes=100, consumed_bytes=0)

    assert result["status"] == "failed"
    assert result["reason"] == reason
    assert not (tmp_path / "image.png").exists()
    assert not list(tmp_path.glob("*.part"))


def test_download_rejects_total_limit_and_checksum_mismatch_retries(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(download_primitive.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(PNG))
    target = tmp_path / "image.png"

    limited = download_primitive.download_image("https://example.test/image", target, max_item_bytes=100, max_total_bytes=4, consumed_bytes=0)
    assert limited["reason"] == "max_total_bytes"

    target.write_bytes(b"wrong")
    retry = download_primitive.download_image("https://example.test/image", target, max_item_bytes=100, max_total_bytes=100, consumed_bytes=0, previous={"status": "success", "path": "image.png", "checksum": "wrong"})
    assert retry["status"] == "success"
    assert retry["checksum"] != "wrong"


def test_download_video_accepts_direct_video_content_type(monkeypatch, tmp_path: Path) -> None:
    body = b"fake-mp4-bytes"
    monkeypatch.setattr(
        download_primitive.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(body, "video/mp4"),
    )

    target = tmp_path / "video-01.mp4"
    result = download_primitive.download_video(
        "https://sns-video-bd.xhscdn.com/example.mp4",
        target,
        max_item_bytes=100,
        max_total_bytes=100,
        consumed_bytes=0,
        referer="https://www.xiaohongshu.com/",
    )

    assert result["status"] == "success"
    assert result["content_type"] == "video/mp4"
    assert target.read_bytes() == body
    assert not list(tmp_path.glob("*.part"))
