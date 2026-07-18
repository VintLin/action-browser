import json
from pathlib import Path
import sys

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.adapters import xiaohongshu_workflow as workflow


def test_note_download_writes_direct_video_and_manifest(monkeypatch, tmp_path: Path) -> None:
    def fake_download(url: str, target: Path, **_kwargs):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"media")
        return {
            "status": "success",
            "reason": "",
            "path": str(target),
            "size": 5,
            "content_type": "video/mp4" if "video" in target.name else "image/jpeg",
            "checksum": "fixture",
            "message": "",
        }

    monkeypatch.setattr(workflow, "download_image", fake_download)
    monkeypatch.setattr(workflow, "download_video", fake_download)
    monkeypatch.setattr(workflow, "sleep_between", lambda *_args, **_kwargs: None)

    payload = workflow.NotePayload(
        note_id="69f000000000000000000001",
        source_url="https://www.xiaohongshu.com/explore/69f000000000000000000001?xsec_token=test",
        candidate_href="",
        author="作者",
        author_avatar_url="",
        author_profile_url="",
        title="视频笔记",
        content="正文",
        tags=[],
        date_text="",
        image_urls=["https://sns-img-bd.xhscdn.com/cover.jpg"],
        comment_image_urls=[],
        video_url="https://sns-video-bd.xhscdn.com/example.mp4",
        video_cover_url="",
        comment_count=0,
        comments=[],
        is_video=True,
    )

    folder = workflow.write_note_download(payload, tmp_path, 1, max_item_bytes=100, max_total_bytes=100)

    assert (folder / "media" / "img-01.jpg").read_bytes() == b"media"
    assert (folder / "media" / "video-01.mp4").read_bytes() == b"media"
    manifest = json.loads((folder / "download_manifest.json").read_text(encoding="utf-8"))
    assert [item["type"] for item in manifest] == ["image", "video"]
    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["saved_videos"] == ["media/video-01.mp4"]


def test_note_download_keeps_partial_manifest_for_resume(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, dict | None]] = []
    interrupted = {"value": True}

    def fake_download(url: str, target: Path, **kwargs):
        previous = kwargs.get("previous")
        calls.append((target.name, previous))
        if target.name == "video-01.mp4" and interrupted["value"]:
            raise KeyboardInterrupt()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"media")
        return {
            "status": "success",
            "reason": "",
            "path": str(target),
            "size": 5,
            "content_type": "video/mp4" if "video" in target.name else "image/jpeg",
            "checksum": "fixture",
            "message": "",
        }

    monkeypatch.setattr(workflow, "download_image", fake_download)
    monkeypatch.setattr(workflow, "download_video", fake_download)
    monkeypatch.setattr(workflow, "sleep_between", lambda *_args, **_kwargs: None)
    payload = workflow.NotePayload(
        note_id="69f000000000000000000002",
        source_url="https://www.xiaohongshu.com/explore/69f000000000000000000002?xsec_token=test",
        candidate_href="",
        author="作者",
        author_avatar_url="",
        author_profile_url="",
        title="可恢复视频笔记",
        content="正文",
        tags=[],
        date_text="",
        image_urls=["https://sns-img-bd.xhscdn.com/cover.jpg"],
        comment_image_urls=[],
        video_url="https://sns-video-bd.xhscdn.com/example.mp4",
        video_cover_url="",
        comment_count=0,
        comments=[],
        is_video=True,
    )

    with pytest.raises(KeyboardInterrupt):
        workflow.write_note_download(payload, tmp_path, 1, max_item_bytes=100, max_total_bytes=100)

    folder_name = workflow.format_download_folder(payload, 1).name
    partial = tmp_path / f".{folder_name}.partial"
    assert partial.exists()
    manifest = json.loads((partial / "download_manifest.json").read_text(encoding="utf-8"))
    assert manifest[0]["status"] == "success"

    interrupted["value"] = False
    folder = workflow.write_note_download(payload, tmp_path, 1, max_item_bytes=100, max_total_bytes=100)
    assert folder.exists()
    assert any(name == "img-01.jpg" and previous and previous.get("status") == "success" for name, previous in calls[2:])


def test_summary_includes_media_failures_from_download_manifest(tmp_path: Path) -> None:
    folder = tmp_path / "001_video_video_author_note"
    folder.mkdir(parents=True)
    (folder / "download_manifest.json").write_text(
        json.dumps(
            [
                {
                    "type": "video",
                    "url": "https://example.test/video.mp4",
                    "status": "failed",
                    "reason": "content_type",
                    "message": "text/html",
                    "partial_path": str(folder / "media" / ".video-01.mp4.partial"),
                }
            ]
        ),
        encoding="utf-8",
    )

    workflow.write_summary([], tmp_path, "下载结果")

    failures = json.loads((tmp_path / "failures.json").read_text(encoding="utf-8"))
    assert failures[0]["type"] == "download"
    assert failures[0]["reason"] == "content_type"
