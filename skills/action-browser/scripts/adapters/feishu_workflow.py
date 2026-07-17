#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Feishu Drive workflow helper for the action-browser skill.

The workflow uses ActionBook extension mode for login-state access, then uses
Feishu Drive and export APIs for inventory, direct attachment downloads, cloud
sheet/docx exports, and local verification.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[2]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import quote, urlparse

import requests

from scripts.actionbook_interrupts import install_interrupt_handlers
from scripts.owned_tab_lifecycle import add_workflow_args, attach_workflow, temporary_tab
from scripts.workflow_runtime import wait_until_stable, write_json
from scripts.actionbook_session import ActionBookSession as ActionBook
from scripts.script_common import log, unwrap_eval


DEFAULT_TENANT = "https://www.feishu.cn"
INVALID_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
EXPORT_CONFIGS = {
    "sheets": [{"type": "sheet", "extension": "xlsx"}],
    "docx": [{"type": "docx", "extension": "docx"}],
    "docs": [{"type": "doc", "extension": "docx"}],
    "base": [{"type": "bitable", "extension": "xlsx"}],
    "bitable": [{"type": "bitable", "extension": "xlsx"}],
    "slides": [{"type": "slides", "extension": "pptx"}, {"type": "slides", "extension": "pdf"}],
}
LOCAL_EXTENSION_BY_KIND = {
    "sheets": "xlsx",
    "docx": "docx",
    "docs": "docx",
    "base": "xlsx",
    "bitable": "xlsx",
    "slides": "pptx",
    "mindnotes": "mm",
}
MENU_EXPORT_KIND_HINTS = {
    "mindnotes": "Open the document page, use top-right more menu -> 下载为 -> FreeMind, then save as .mm.",
}
MENU_EXPORT_CONFIGS = {
    "mindnotes": {"menu_text": "FreeMind", "extension": "mm"},
}
def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
def tenant_origin(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return DEFAULT_TENANT


def token_from_url(url: str) -> str:
    return urlparse(url).path.rstrip("/").split("/")[-1]


def kind_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.split("/", 1)[0] if path else ""


def folder_token_from_url(url: str) -> str:
    match = re.search(r"/drive/folder/([^/?#]+)", url)
    return match.group(1) if match else ""


def sanitize_component(value: str, max_len: int = 180) -> str:
    value = INVALID_CHARS.sub("_", str(value or "")).strip().rstrip(".")
    if not value:
        return "_"
    if len(value) <= max_len:
        return value
    stem, suffix = os.path.splitext(value)
    if suffix and len(suffix) < 20:
        return stem[: max_len - len(suffix) - 1].rstrip() + "_" + suffix
    return value[:max_len].rstrip() + "_"


def local_path(output_dir: Path, cloud_path: str) -> Path:
    parts = [sanitize_component(part) for part in cloud_path.split("/") if part]
    return output_dir.joinpath(*parts)


def with_extension(path: str, extension: str) -> str:
    suffix = "." + extension.lower()
    if Path(path).suffix.lower() == suffix:
        return path
    return path + suffix


def parse_root(value: str) -> tuple[str, str]:
    if "=" in value:
        name, url = value.split("=", 1)
    else:
        url = value
        name = Path(urlparse(url).path.rstrip("/")).name or "root"
    name = name.strip() or "root"
    url = url.strip()
    if not folder_token_from_url(url):
        raise ValueError(f"not a Feishu folder URL: {value}")
    return name, url



def chrome_download_dir() -> Path:
    prefs = Path.home() / "Library/Application Support/Google/Chrome/Default/Preferences"
    if prefs.exists():
        try:
            data = json.loads(prefs.read_text(errors="ignore"))
            configured = (data.get("download") or {}).get("default_directory")
            if configured:
                return Path(os.path.expanduser(str(configured)))
        except Exception:
            pass
    return Path.home() / "Downloads"


def run_actionbook_data(args: list[str], timeout: float = 30.0) -> Any:
    proc = subprocess.run(["actionbook", *args, "--json"], text=True, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    envelope = json.loads(proc.stdout)
    if not envelope.get("ok"):
        raise RuntimeError(json.dumps(envelope.get("error") or envelope, ensure_ascii=False))
    data = envelope.get("data")
    if isinstance(data, dict) and "value" in data:
        return data["value"]
    return data


def run_actionbook_ok(args: list[str], timeout: float = 30.0) -> None:
    run_actionbook_data(args, timeout=timeout)


def get_cookies(book: ActionBook, origin_hint: str) -> dict[str, str]:
    value = run_actionbook_data(["browser", "cookies", "list", "--session", book.session], timeout=20.0)
    items = []
    if isinstance(value, dict):
        items = value.get("items") or value.get("cookies", {}).get("items") or []
    origin_host = urlparse(origin_hint).hostname or ""
    cookies: dict[str, str] = {}
    for cookie in items:
        domain = str(cookie.get("domain") or "")
        if "feishu.cn" not in domain and origin_host not in domain:
            continue
        name = cookie.get("name")
        cookie_value = cookie.get("value")
        if name and cookie_value is not None:
            cookies[str(name)] = str(cookie_value)
    return cookies


def cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def request_headers(cookies: dict[str, str], origin: str, referer: str) -> dict[str, str]:
    return {
        "Cookie": cookie_header(cookies),
        "Origin": origin,
        "Referer": referer,
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
    }


def collect_folder_api(book: ActionBook, folder_url: str) -> dict[str, Any]:
    token = folder_token_from_url(folder_url)
    script = f"""(async () => {{
      const token = {json.dumps(token)};
      const all = [];
      const seen = new Set();
      let lastLabel = '';
      let hasMore = true;
      let total = null;
      let pages = 0;
      while (hasMore && pages < 300) {{
        const params = new URLSearchParams({{
          token,
          asc: '0',
          rank: '3',
          length: '200'
        }});
        if (lastLabel) params.set('last_label', lastLabel);
        const resp = await fetch('/space/api/explorer/v3/children/list/?' + params.toString(), {{ credentials: 'include' }});
        const payload = await resp.json();
        if (!resp.ok || payload.code !== 0 || !payload.data) {{
          return {{ ok: false, status: resp.status, code: payload.code, msg: payload.msg || '', pages, item_count: all.length }};
        }}
        const data = payload.data;
        total = data.total ?? total;
        const nodes = data.entities?.nodes || {{}};
        for (const nodeToken of data.node_list || []) {{
          const node = nodes[nodeToken];
          if (!node) continue;
          const href = node.url || '';
          const name = node.name || '';
          const key = href || node.obj_token || node.token || nodeToken;
          if (!key || seen.has(key) || !name) continue;
          seen.add(key);
          all.push({{
            name,
            url: href,
            kind: href.split('/').filter(Boolean)[0] || '',
            type: node.type === 0 ? 'folder' : 'file',
            obj_type: node.type,
            subtype: node.extra?.subtype || node.subtype || '',
            token: node.obj_token || node.token || nodeToken,
            node_token: node.token || nodeToken,
            source: 'api-v3-children-list'
          }});
        }}
        pages += 1;
        hasMore = Boolean(data.has_more);
        lastLabel = data.last_label || '';
        if (hasMore && !lastLabel) break;
      }}
      return {{ ok: true, items: all, total, pages, has_more: hasMore, last_label: lastLabel }};
    }})()"""
    result = unwrap_eval(book.eval(script, timeout=140.0))
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError(f"folder api failed for {folder_url}: {result}")
    return result


def walk_inventory(
    book: ActionBook,
    name: str,
    url: str,
    path: str,
    folders: list[dict[str, Any]],
    files: list[dict[str, Any]],
    folder_status: dict[str, Any],
    visited: set[str],
) -> None:
    if url in visited:
        return
    visited.add(url)
    log(f"folder {path}")
    origin = tenant_origin(url)
    book.goto(origin + "/drive/")
    result = collect_folder_api(book, url)
    folders.append({"path": path, "name": name, "url": url})
    folder_status[path] = {
        "url": url,
        "source": "api-v3-children-list",
        "item_count": len(result.get("items") or []),
        "total": result.get("total"),
        "api_pages": result.get("pages"),
        "api_has_more": result.get("has_more"),
        "reached_bottom": not result.get("has_more") and (result.get("total") is None or len(result.get("items") or []) == result.get("total")),
    }
    for item in result.get("items") or []:
        child_path = f"{path}/{item['name']}"
        if item.get("type") == "folder":
            walk_inventory(book, item["name"], item["url"], child_path, folders, files, folder_status, visited)
        else:
            files.append({
                "path": child_path,
                "name": item["name"],
                "url": item["url"],
                "kind": kind_from_url(item["url"]),
                "token": item.get("token", ""),
                "node_token": item.get("node_token", ""),
                "source": item.get("source", ""),
            })


def write_manifest(output_dir: Path, roots: list[tuple[str, str]], folders: list[dict[str, Any]], files: list[dict[str, Any]], folder_status: dict[str, Any]) -> None:
    payload = {"roots": [{"name": name, "url": url} for name, url in roots], "folders": folders, "files": files, "folder_status": folder_status}
    write_json(output_dir / "feishu_manifest.json", payload)
    lines = ["# Feishu Manifest", "", "## Roots", ""]
    for name, url in roots:
        lines.append(f"- `{name}`: {url}")
    lines.extend(["", "## Summary", "", f"- folders: {len(folders)}", f"- files: {len(files)}", ""])
    for kind, count in sorted(Counter(item.get("kind") or "unknown" for item in files).items()):
        lines.append(f"- {kind}: {count}")
    lines.extend(["", "## Folders", ""])
    for folder in folders:
        status = folder_status.get(folder["path"], {})
        lines.append(f"- `{folder['path']}`")
        lines.append(f"  - URL: {folder['url']}")
        lines.append(f"  - status: source={status.get('source')}, item_count={status.get('item_count')}, reached_bottom={status.get('reached_bottom')}, api_has_more={status.get('api_has_more')}")
    lines.extend(["", "## Files", ""])
    for item in files:
        lines.append(f"- `{item['path']}`")
        lines.append(f"  - URL: {item['url']}")
    (output_dir / "feishu_manifest.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def download_direct_one(item: dict[str, Any], output_dir: Path, headers: dict[str, str], force: bool) -> dict[str, Any]:
    target = local_path(output_dir, item["path"])
    if target.exists() and target.stat().st_size > 0 and not force:
        return {"status": "skipped_exists", "kind": "file", "path": item["path"], "local_path": str(target), "size": target.stat().st_size}
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".part")
    url = f"{tenant_origin(item['url'])}/space/api/box/stream/download/all/{quote(token_from_url(item['url']))}"
    last_error = ""
    for attempt in range(1, 5):
        try:
            with requests.get(url, headers={**headers, "Referer": item["url"]}, stream=True, timeout=(10, 60)) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
                if "application/json" in response.headers.get("content-type", ""):
                    raise RuntimeError(f"unexpected json response: {response.text[:300]}")
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            handle.write(chunk)
            temp.replace(target)
            return {"status": "downloaded", "kind": "file", "path": item["path"], "url": item["url"], "local_path": str(target), "size": target.stat().st_size}
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            time.sleep(min(8, attempt * 1.5))
    if temp.exists():
        temp.unlink()
    return {"status": "failed", "kind": "file", "path": item["path"], "url": item["url"], "local_path": str(target), "error": last_error}


def create_export(item: dict[str, Any], config: dict[str, str], headers: dict[str, str]) -> tuple[str, int]:
    body = {"token": token_from_url(item["url"]), "type": config["type"], "file_extension": config["extension"], "event_source": "1"}
    response = requests.post(f"{tenant_origin(item['url'])}/space/api/export/create/", headers={**headers, "Referer": item["url"], "Content-Type": "application/json"}, json=body, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"create HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if data.get("code") != 0:
        raise RuntimeError(f"create code {data.get('code')}: {data.get('msg')}")
    ticket = (data.get("data") or {}).get("ticket")
    if not ticket:
        raise RuntimeError(f"missing ticket: {data}")
    return str(ticket), int((data.get("data") or {}).get("job_timeout") or 600)


def poll_export(item: dict[str, Any], config: dict[str, str], ticket: str, timeout_seconds: int, headers: dict[str, str]) -> dict[str, Any]:
    deadline = time.time() + min(timeout_seconds + 30, 900)
    last_payload: Any = None
    while time.time() < deadline:
        response = requests.get(
            f"{tenant_origin(item['url'])}/space/api/export/result/{quote(ticket)}",
            headers={**headers, "Referer": item["url"]},
            params={"token": token_from_url(item["url"]), "type": config["type"]},
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError(f"result HTTP {response.status_code}: {response.text[:300]}")
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"result code {data.get('code')}: {data.get('msg')}")
        payload = (data.get("data") or {}).get("result") or data.get("data") or {}
        last_payload = payload
        if payload.get("file_token"):
            return payload
        if payload.get("job_status") not in (1, 2, None):
            raise RuntimeError(f"export failed: {payload}")
        time.sleep(0.8)
    raise RuntimeError(f"export timeout: {last_payload}")


def download_exported(item: dict[str, Any], file_token: str, target: Path, headers: dict[str, str]) -> None:
    url = f"{tenant_origin(item['url'])}/space/api/box/stream/download/all/{quote(file_token)}"
    download_url_to_path(url, item["url"], target, headers)


def download_url_to_path(url: str, referer: str, target: Path, headers: dict[str, str]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".part")
    with requests.get(url, headers={**headers, "Referer": referer}, stream=True, timeout=(10, 90)) as response:
        if response.status_code != 200:
            raise RuntimeError(f"download HTTP {response.status_code}: {response.text[:300]}")
        if "application/json" in response.headers.get("content-type", ""):
            raise RuntimeError(f"unexpected json response: {response.text[:300]}")
        with temp.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    handle.write(chunk)
    temp.replace(target)


def export_one(item: dict[str, Any], output_dir: Path, headers: dict[str, str], force: bool) -> dict[str, Any]:
    kind = kind_from_url(item["url"])
    configs = EXPORT_CONFIGS[kind]
    target = local_path(output_dir, with_extension(item["path"], LOCAL_EXTENSION_BY_KIND.get(kind, configs[0]["extension"])))
    if target.exists() and target.stat().st_size > 0 and not force:
        return {"status": "skipped_exists", "kind": kind, "path": item["path"], "local_path": str(target), "size": target.stat().st_size}
    last_error = ""
    for config in configs:
        export_target = local_path(output_dir, with_extension(item["path"], config["extension"]))
        for attempt in range(1, 3):
            try:
                ticket, timeout_seconds = create_export(item, config, headers)
                payload = poll_export(item, config, ticket, timeout_seconds, headers)
                download_exported(item, payload["file_token"], export_target, headers)
                return {"status": "exported", "kind": kind, "path": item["path"], "url": item["url"], "local_path": str(export_target), "size": export_target.stat().st_size, "export": {"request": config, **payload}}
            except Exception as exc:  # noqa: BLE001
                last_error = f"{config}: {exc}"
                time.sleep(min(8, attempt * 2))
    return {"status": "failed", "kind": kind, "path": item["path"], "url": item["url"], "local_path": str(target), "error": last_error}


def stable_download_files(download_dir: Path) -> dict[Path, tuple[int, int]]:
    files: dict[Path, tuple[int, int]] = {}
    if not download_dir.exists():
        return files
    for path in download_dir.iterdir():
        if not path.is_file() or path.name.endswith((".crdownload", ".tmp", ".part")):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        files[path] = (stat.st_size, int(stat.st_mtime))
    return files


def wait_new_download(download_dir: Path, before: dict[Path, tuple[int, int]], timeout_seconds: int = 90) -> Path:
    deadline = time.time() + timeout_seconds
    last_candidate: Path | None = None
    last_size = -1
    stable_count = 0
    while time.time() < deadline:
        current = stable_download_files(download_dir)
        candidates = [path for path, meta in current.items() if path not in before or before.get(path) != meta]
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            candidate = candidates[0]
            size = candidate.stat().st_size
            if candidate == last_candidate and size == last_size and size > 0:
                stable_count += 1
                if stable_count >= 2:
                    return candidate
            else:
                last_candidate = candidate
                last_size = size
                stable_count = 0
        time.sleep(1)
    raise RuntimeError(f"download did not complete in {download_dir}")


def click_text_menu_item(session: str, tab: str, text: str) -> bool:
    xpath = f"//*[@role='menuitem' and contains(normalize-space(.), {json.dumps(text)})]"
    try:
        run_actionbook_data(["browser", "click", xpath, "--session", session, "--tab", tab], timeout=10.0)
        return True
    except Exception:
        pass
    script = f"""(() => {{
      const wanted = {json.dumps(text)};
      const items = [...document.querySelectorAll('li,div,span,button,[role=menuitem]')];
      const exact = items.find(el => (el.innerText || el.textContent || '').trim() === wanted);
      const loose = exact || items.find(el => (el.innerText || el.textContent || '').trim().includes(wanted));
      if (!loose) return false;
      loose.scrollIntoView?.({{block: 'center', inline: 'center'}});
      const r = loose.getBoundingClientRect();
      const opts = {{bubbles: true, cancelable: true, view: window, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2}};
      for (const type of ['pointerdown','mousedown','pointerup','mouseup','click']) {{
        try {{ loose.dispatchEvent(new PointerEvent(type, opts)); }} catch {{ loose.dispatchEvent(new MouseEvent(type, opts)); }}
      }}
      return true;
    }})()"""
    return bool(run_actionbook_data(["browser", "eval", script, "--session", session, "--tab", tab], timeout=10.0))


def clear_network_requests(session: str, tab: str) -> None:
    run_actionbook_data(["browser", "network", "requests", "--session", session, "--tab", tab, "--clear"], timeout=10.0)


def dump_network_requests(session: str, tab: str) -> list[dict[str, Any]]:
    with TemporaryDirectory(prefix="feishu-network-") as tmp:
        run_actionbook_data(
            ["browser", "network", "requests", "--session", session, "--tab", tab, "--dump", "--out", tmp],
            timeout=20.0,
        )
        path = Path(tmp) / "requests.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        requests_data = data.get("requests") or (data.get("data") or {}).get("requests") or []
    else:
        requests_data = data if isinstance(data, list) else []
    return [item for item in requests_data if isinstance(item, dict)]


def iter_payload_values(value: Any) -> list[Any]:
    values = [value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and stripped[0] in "[{":
            try:
                values.extend(iter_payload_values(json.loads(stripped)))
            except Exception:
                pass
    elif isinstance(value, dict):
        for child in value.values():
            values.extend(iter_payload_values(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(iter_payload_values(child))
    return values


def request_response_payload(request: dict[str, Any]) -> Any:
    for key in ("response_body", "body", "responseBody"):
        if key in request:
            return request.get(key)
    response = request.get("response")
    if isinstance(response, dict):
        for key in ("body", "response_body", "data"):
            if key in response:
                return response.get(key)
    return None


def network_download_candidate(item: dict[str, Any], request: dict[str, Any]) -> dict[str, str] | None:
    url = str(request.get("url") or "")
    if "/space/api/box/stream/download/all/" in url and 200 <= int(request.get("status") or 0) < 400:
        return {"download_url": url, "source_url": url}
    if not any(fragment in url for fragment in ("/space/api/export/result/", "/space/api/export/create/", "download", "export")):
        return None
    origin = tenant_origin(item["url"])
    for value in iter_payload_values(request_response_payload(request)):
        if isinstance(value, dict):
            token = value.get("file_token") or value.get("fileToken")
            if token:
                return {
                    "file_token": str(token),
                    "download_url": f"{origin}/space/api/box/stream/download/all/{quote(str(token))}",
                    "source_url": url,
                }
        if isinstance(value, str):
            match = re.search(r"https?://[^\"'\s]+/space/api/box/stream/download/all/[^\"'\s]+", value)
            if match:
                return {"download_url": match.group(0), "source_url": url}
    return None


def wait_network_download_candidate(session: str, tab: str, item: dict[str, Any], timeout_seconds: int = 30) -> dict[str, str] | None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        for request in reversed(dump_network_requests(session, tab)):
            candidate = network_download_candidate(item, request)
            if candidate:
                return candidate
        time.sleep(1)
    return None


def open_download_submenu(session: str, tab: str, submenu_text: str = "") -> bool:
    try:
        run_actionbook_data(["browser", "click", '[data-e2e="suite-more-btn"], [data-selector="more-menu"]', "--session", session, "--tab", tab], timeout=10.0)
    except Exception:
        script = """(() => {
          const button = document.querySelector('[data-e2e="suite-more-btn"], [data-selector="more-menu"], .more-btn');
          if (!button) return false;
          button.click();
          return true;
        })()"""
        if not run_actionbook_data(["browser", "eval", script, "--session", session, "--tab", tab], timeout=10.0):
            return False
    script = f"""(async () => {{
      const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
      const visible = el => {{
        if (!el) return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      }};
      const findByText = text => {{
        const items = [...document.querySelectorAll('li,div,span,button,[role=menuitem]')].filter(visible);
        return items.find(el => (el.innerText || el.textContent || '').trim() === text)
          || items.find(el => (el.innerText || el.textContent || '').includes(text));
      }};
      let item = null;
      for (let i = 0; i < 20; i++) {{
        item = findByText('下载为');
        if (item) break;
        await sleep(150);
      }}
      if (!item) return {{ok: false, step: 'download-as'}};
      return {{ok: true}};
    }})()"""
    result = run_actionbook_data(["browser", "eval", script, "--session", session, "--tab", tab], timeout=10.0)
    if not (isinstance(result, dict) and bool(result.get("ok"))):
        return False
    try:
        run_actionbook_data(
            [
                "browser",
                "hover",
                "//*[@role='menuitem' and contains(normalize-space(.), '下载为')]",
                "--session",
                session,
                "--tab",
                tab,
            ],
            timeout=10.0,
        )
    except Exception:
        return not submenu_text
    if not submenu_text:
        return True
    wait_script = f"""(async () => {{
      const wanted = {json.dumps(submenu_text)};
      const visible = el => {{
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      }};
      for (let i = 0; i < 20; i++) {{
        const found = [...document.querySelectorAll('li,div,span,button,[role=menuitem]')]
          .filter(visible)
          .some(el => (el.innerText || el.textContent || '').includes(wanted));
        if (found) return true;
        await new Promise(resolve => setTimeout(resolve, 150));
      }}
      return false;
    }})()"""
    return bool(run_actionbook_data(["browser", "eval", wait_script, "--session", session, "--tab", tab], timeout=10.0))


def ui_menu_export_one(book: ActionBook, item: dict[str, Any], output_dir: Path, download_dir: Path, headers: dict[str, str], force: bool) -> dict[str, Any]:
    kind = kind_from_url(item["url"])
    config = MENU_EXPORT_CONFIGS[kind]
    target = local_path(output_dir, with_extension(item["path"], config["extension"]))
    if target.exists() and target.stat().st_size > 0 and not force:
        return {"status": "skipped_exists", "kind": kind, "path": item["path"], "local_path": str(target), "size": target.stat().st_size}
    target.parent.mkdir(parents=True, exist_ok=True)
    before = stable_download_files(download_dir)
    try:
        with temporary_tab(book, item["url"]) as tab:
            wait_until_stable(book)
            if not open_download_submenu(book.session, tab, config["menu_text"]):
                raise RuntimeError("could not open 下载为 submenu")
            time.sleep(0.4)
            clear_network_requests(book.session, tab)
            if not click_text_menu_item(book.session, tab, config["menu_text"]):
                raise RuntimeError(f"could not click menu item {config['menu_text']}")
            candidate = wait_network_download_candidate(book.session, tab, item)
            if candidate and candidate.get("download_url"):
                download_url_to_path(candidate["download_url"], item["url"], target, headers)
                return {
                    "status": "ui_exported_via_network",
                    "kind": kind,
                    "path": item["path"],
                    "url": item["url"],
                    "local_path": str(target),
                    "size": target.stat().st_size,
                    "network": candidate,
                }
            downloaded = wait_new_download(download_dir, before)
            if downloaded.suffix.lower() != "." + config["extension"]:
                target = target.with_suffix(downloaded.suffix)
            downloaded.replace(target)
            return {
                "status": "ui_exported",
                "kind": kind,
                "path": item["path"],
                "url": item["url"],
                "local_path": str(target),
                "size": target.stat().st_size,
                "download_dir": str(download_dir),
                "network_capture": "no_download_url_or_file_token",
            }
    except Exception as exc:
        return {"status": "failed", "kind": kind, "path": item["path"], "url": item["url"], "local_path": str(target), "error": str(exc), "download_dir": str(download_dir)}


def run_workers(label: str, items: list[dict[str, Any]], workers: int, func: Any, status_path: Path) -> Counter:
    counts: Counter = Counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(func, item) for item in items]
        for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            record = future.result()
            counts[record["status"]] += 1
            append_jsonl(status_path, record)
            if index % 50 == 0 or record["status"] == "failed":
                log(f"{label} done={index}/{len(items)} counts={dict(counts)}")
    return counts


def command_inventory(args: argparse.Namespace) -> None:
    roots = [parse_root(value) for value in args.root]
    first_url = roots[0][1]
    book = attach_workflow(args, tenant_origin(first_url) + "/drive/", ActionBook)
    folders: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    folder_status: dict[str, Any] = {}
    visited: set[str] = set()
    for name, url in roots:
        walk_inventory(book, name, url, name, folders, files, folder_status, visited)
        write_manifest(Path(args.output_dir), roots, folders, files, folder_status)
    summary = {"folders": len(folders), "files": len(files), "kinds": dict(Counter(item.get("kind") or "unknown" for item in files)), "output_dir": args.output_dir}
    write_json(Path(args.output_dir) / "inventory_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def command_download(args: argparse.Namespace) -> None:
    manifest = load_manifest(Path(args.manifest))
    files = manifest.get("files") or []
    first_url = next((item["url"] for item in files if item.get("url")), DEFAULT_TENANT)
    book = attach_workflow(args, tenant_origin(first_url) + "/drive/", ActionBook)
    cookies = get_cookies(book, first_url)
    if not cookies:
        raise RuntimeError("missing Feishu cookies from ActionBook session")
    csrf = cookies.get("_csrf_token", "")
    headers = request_headers(cookies, tenant_origin(first_url), first_url)
    if csrf:
        headers["X-CSRFToken"] = csrf
    output_dir = Path(args.output_dir)
    started = time.time()
    direct_items = [item for item in files if kind_from_url(item.get("url", "")) == "file"]
    export_items = [item for item in files if kind_from_url(item.get("url", "")) in EXPORT_CONFIGS]
    unsupported = [item for item in files if kind_from_url(item.get("url", "")) not in ("file", *EXPORT_CONFIGS.keys())]
    ui_items = [item for item in unsupported if args.ui_fallback and kind_from_url(item.get("url", "")) in MENU_EXPORT_CONFIGS]
    unsupported_without_ui = [item for item in unsupported if item not in ui_items]
    if args.limit:
        direct_items = direct_items[: args.limit]
        export_items = export_items[: args.limit]
    direct_counts = run_workers("direct", direct_items, args.direct_workers, lambda item: download_direct_one(item, output_dir, headers, args.force), Path(args.status_dir) / "download_status.jsonl")
    export_counts: Counter = Counter()
    if export_items:
        if not csrf:
            raise RuntimeError("missing _csrf_token cookie for cloud export")
        export_counts = run_workers("export", export_items, args.export_workers, lambda item: export_one(item, output_dir, headers, args.force), Path(args.status_dir) / "cloud_export_status.jsonl")
    ui_counts: Counter = Counter()
    if ui_items:
        download_dir = Path(args.chrome_download_dir).expanduser() if args.chrome_download_dir else chrome_download_dir()
        status_path = Path(args.status_dir) / "ui_export_status.jsonl"
        for index, item in enumerate(ui_items, start=1):
            record = ui_menu_export_one(book, item, output_dir, download_dir, headers, args.force)
            ui_counts[record["status"]] += 1
            append_jsonl(status_path, record)
            if index % 10 == 0 or record["status"] == "failed":
                log(f"ui-export done={index}/{len(ui_items)} counts={dict(ui_counts)}")
    summary = {
        "direct_total": len(direct_items),
        "export_total": len(export_items),
        "ui_export_total": len(ui_items),
        "unsupported_total": len(unsupported_without_ui),
        "unsupported_kinds": dict(Counter(kind_from_url(item.get("url", "")) or "unknown" for item in unsupported_without_ui)),
        "unsupported_hints": {
            kind: MENU_EXPORT_KIND_HINTS[kind]
            for kind in sorted({kind_from_url(item.get("url", "")) for item in unsupported_without_ui})
            if kind in MENU_EXPORT_KIND_HINTS
        },
        "direct_counts": dict(direct_counts),
        "export_counts": dict(export_counts),
        "ui_export_counts": dict(ui_counts),
        "output_dir": str(output_dir),
        "elapsed_seconds": round(time.time() - started, 2),
    }
    write_json(Path(args.status_dir) / "download_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def command_verify(args: argparse.Namespace) -> None:
    manifest = load_manifest(Path(args.manifest))
    files = manifest.get("files") or []
    output_dir = Path(args.output_dir)
    missing = []
    empty = []
    nonempty = 0
    total_bytes = 0
    targets: Counter = Counter()
    for item in files:
        kind = kind_from_url(item.get("url", ""))
        extension = LOCAL_EXTENSION_BY_KIND.get(kind)
        cloud_path = with_extension(item["path"], extension) if extension else item["path"]
        target = local_path(output_dir, cloud_path)
        targets[str(target)] += 1
        if not target.exists():
            missing.append({"path": item["path"], "url": item.get("url"), "local_path": str(target)})
            continue
        size = target.stat().st_size
        if size <= 0:
            empty.append({"path": item["path"], "url": item.get("url"), "local_path": str(target)})
        else:
            nonempty += 1
            total_bytes += size
    collisions = [path for path, count in targets.items() if count > 1]
    summary = {
        "manifest_files": len(files),
        "local_nonempty_files": nonempty,
        "missing_files": len(missing),
        "empty_files": len(empty),
        "path_collisions": len(collisions),
        "total_bytes": total_bytes,
        "kinds": dict(Counter(kind_from_url(item.get("url", "")) or "unknown" for item in files)),
    }
    output = Path(args.output)
    write_json(output, {"summary": summary, "missing": missing, "empty": empty, "collisions": collisions})
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Feishu Drive inventory, download, export, and verification workflow.")
    add_workflow_args(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory", help="Collect recursive Drive folder inventory through the Feishu children-list API.")
    inventory.add_argument("--root", action="append", required=True, help='Root folder as "Name=https://tenant.feishu.cn/drive/folder/<token>" or just the URL. Repeatable.')
    inventory.add_argument("--output-dir", default="records")
    inventory.set_defaults(func=command_inventory)

    download = subparsers.add_parser("download", help="Download /file attachments and export supported cloud docs from a manifest.")
    download.add_argument("--manifest", default="records/feishu_manifest.json")
    download.add_argument("--output-dir", default="downloads")
    download.add_argument("--status-dir", default="records")
    download.add_argument("--direct-workers", type=int, default=6)
    download.add_argument("--export-workers", type=int, default=3)
    download.add_argument("--limit", type=int, default=0)
    download.add_argument("--force", action="store_true")
    download.add_argument("--ui-fallback", action="store_true", help="Try browser menu export for supported non-API document kinds such as mindnotes.")
    download.add_argument("--chrome-download-dir", default="", help="Chrome download directory. Defaults to Chrome preference or ~/Downloads.")
    download.set_defaults(func=command_download)

    verify = subparsers.add_parser("verify", help="Verify manifest files against the local output directory.")
    verify.add_argument("--manifest", default="records/feishu_manifest.json")
    verify.add_argument("--output-dir", default="downloads")
    verify.add_argument("--output", default="records/download_verification.json")
    verify.set_defaults(func=command_verify)
    return parser


def main() -> None:
    install_interrupt_handlers()
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
