from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
import urllib.request


def _failure(reason: str, message: str = "", partial_path: str = "") -> dict[str, object]:
    return {
        "status": "failed",
        "reason": reason,
        "path": "",
        "partial_path": partial_path,
        "size": 0,
        "content_type": "",
        "checksum": "",
        "message": message,
    }


def download_image(
    url: str,
    target: Path,
    *,
    max_item_bytes: int,
    max_total_bytes: int,
    consumed_bytes: int,
    previous: dict[str, object] | None = None,
    referer: str = "",
) -> dict[str, object]:
    """Download one verified image, or skip a checksum-matching prior result."""
    return download_media(
        url,
        target,
        max_item_bytes=max_item_bytes,
        max_total_bytes=max_total_bytes,
        consumed_bytes=consumed_bytes,
        previous=previous,
        referer=referer,
        allowed_content_types=("image/",),
        fallback_extension=".jpg",
    )


def download_video(
    url: str,
    target: Path,
    *,
    max_item_bytes: int,
    max_total_bytes: int,
    consumed_bytes: int,
    previous: dict[str, object] | None = None,
    referer: str = "",
) -> dict[str, object]:
    """Download one verified direct video URL, or resume a verified result."""
    return download_media(
        url,
        target,
        max_item_bytes=max_item_bytes,
        max_total_bytes=max_total_bytes,
        consumed_bytes=consumed_bytes,
        previous=previous,
        referer=referer,
        allowed_content_types=("video/",),
        fallback_extension=".mp4",
    )


def download_media(
    url: str,
    target: Path,
    *,
    max_item_bytes: int,
    max_total_bytes: int,
    consumed_bytes: int,
    previous: dict[str, object] | None = None,
    referer: str = "",
    allowed_content_types: tuple[str, ...],
    fallback_extension: str,
) -> dict[str, object]:
    """Download one bounded, atomically replaced media file.

    The caller supplies the content-type family so image and direct-video
    downloads share the same limits, checksum resume, and failure envelope.
    """
    expected = str((previous or {}).get("checksum") or "")
    if str((previous or {}).get("status") or "") == "success" and expected and target.is_file():
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual == expected:
            return {"status": "skipped", "reason": "", "path": str(target), "size": target.stat().st_size, "content_type": str((previous or {}).get("content_type") or ""), "checksum": actual, "message": "verified existing file"}
    if max_item_bytes <= 0 or max_total_bytes <= 0:
        return _failure("invalid_limit", "byte limits must be positive")
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f".{target.name}.partial")
    part.unlink(missing_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer})
    try:
        with urllib.request.urlopen(request, timeout=30) as response, part.open("wb") as output:
            content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
            if not any(content_type.startswith(prefix) for prefix in allowed_content_types):
                return _failure("content_type", content_type, str(part))
            digest = hashlib.sha256()
            size = 0
            while chunk := response.read(64 * 1024):
                size += len(chunk)
                if size > max_item_bytes:
                    return _failure("max_item_bytes", partial_path=str(part))
                if consumed_bytes + size > max_total_bytes:
                    return _failure("max_total_bytes", partial_path=str(part))
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            output.seek(0)
        if size == 0:
            return _failure("empty_content", partial_path=str(part))
        checksum = digest.hexdigest()
        part.replace(target)
        extension = mimetypes.guess_extension(content_type) or fallback_extension
        return {
            "status": "success",
            "reason": "",
            "path": str(target),
            "size": size,
            "content_type": content_type,
            "checksum": checksum,
            "extension": extension,
            "message": "",
        }
    except Exception as error:  # urllib failures are normalized for the manifest.
        return _failure("network_error", str(error), str(part))
