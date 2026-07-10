#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTube workflow helper for the action-browser skill.

The workflow uses ActionBook extension mode and the user's existing Chrome
session. It covers read-only YouTube search, video metadata, transcripts,
comments, channel videos, playlists, home feed, history, Watch Later, and
subscriptions.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[2]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
from typing import Any

from scripts.actionbook_interrupts import install_interrupt_handlers
from scripts.workflow_runtime import add_workflow_args, attach_workflow, evaluate, wait_until_stable, write_json
from scripts.actionbook_session import ActionBookSession as ActionBook
from scripts.script_common import log


YOUTUBE_HOME_URL = "https://www.youtube.com"
SKILL_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = SKILL_DIR / "assets" / "youtube"


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def sanitize_name(value: str, fallback: str = "item", max_length: int = 80) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "", value or "").strip("._-")
    return (cleaned or fallback)[:max_length]
def read_count(value: Any, default: int = 20, max_value: int = 1000) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = default
    return max(1, min(count, max_value))


def default_action_output_dir(source: str, action: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    action_dir = "downloads" if action == "download" else "views"
    return ASSETS_DIR / action_dir / source / stamp


def write_records(records: list[dict[str, Any]], output_dir: Path, title: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", records)
    lines = [f"# {title}", "", f"- 条目数: {len(records)}", ""]
    for index, item in enumerate(records, start=1):
        heading = item.get("title") or item.get("name") or item.get("author") or item.get("video_id") or item.get("id") or str(index)
        lines.extend([f"## {index}. {heading}", ""])
        for key, value in item.items():
            if value in ("", None, [], {}):
                continue
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(f"- {key}: {value}")
        lines.append("")
    (output_dir / "summary.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    write_json(output_dir / "failures.json", [])



def ensure_youtube_ready(book: ActionBook) -> None:
    state = evaluate(book, """
    (() => ({
      href: location.href,
      title: document.title || '',
      text: (document.body?.innerText || '').slice(0, 1000)
    }))()
    """, "youtube page state", timeout=10.0)
    if not isinstance(state, dict):
        return
    haystack = "\n".join(str(state.get(key) or "") for key in ("href", "title", "text"))
    if re.search(r"signin|accounts\.google|ServiceLogin|captcha|unusual traffic|confirm your age|age-restricted|登录|验证码|异常流量", haystack, re.I):
        raise RuntimeError(f"YouTube requires login or verification: {state.get('href')} title={state.get('title')}")


def parse_video_id(value: str) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{6,}", raw) and not raw.startswith("http"):
        return raw
    parsed = urllib.parse.urlparse(raw)
    if parsed.query:
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("v"):
            return query["v"][0]
    if parsed.hostname == "youtu.be":
        return parsed.path.strip("/").split("/")[0]
    match = re.match(r"^/(shorts|embed|live|v)/([^/?#]+)", parsed.path or "")
    if match:
        return match.group(2)
    raise ValueError(f"Invalid YouTube video URL or ID: {value}")


def parse_playlist_id(value: str) -> str:
    raw = str(value or "").strip()
    if raw.startswith("http"):
        parsed = urllib.parse.urlparse(raw)
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("list"):
            return query["list"][0]
    return raw


def video_url(video_id: str) -> str:
    return f"{YOUTUBE_HOME_URL}/watch?v={video_id}"


def fmt_time(seconds: float) -> str:
    sec = max(0, int(seconds))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def group_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    buffer: list[str] = []
    start = 0.0
    last = 0.0
    sentence_end = re.compile(r"[.!?。！？．][\"'”’)]*$")

    def flush() -> None:
        nonlocal buffer, start
        text = normalize_text(" ".join(buffer))
        if text:
            groups.append({"start": start, "timestamp": fmt_time(start), "text": text})
        buffer = []

    for seg in segments:
        text = normalize_text(seg.get("text"))
        if not text:
            continue
        seg_start = float(seg.get("start") or 0)
        if buffer and (seg_start - last > 20 or seg_start - start > 30):
            flush()
        if not buffer:
            start = seg_start
        buffer.append(text)
        last = seg_start
        if sentence_end.search(text):
            flush()
    flush()
    return groups


JS_HELPERS = r"""
function textOf(value) {
  if (!value) return '';
  if (typeof value === 'string') return value.replace(/\s+/g, ' ').trim();
  if (typeof value.simpleText === 'string') return value.simpleText.replace(/\s+/g, ' ').trim();
  if (Array.isArray(value.runs)) return value.runs.map(run => run?.text || '').join('').replace(/\s+/g, ' ').trim();
  if (typeof value.innerText === 'string' || typeof value.textContent === 'string') return (value.innerText || value.textContent || '').replace(/\s+/g, ' ').trim();
  return '';
}
function absUrl(value) {
  if (!value) return '';
  try { return new URL(value, location.origin).toString(); } catch { return String(value || ''); }
}
function extractJsonAssignmentFromHtml(html, keys) {
  const list = Array.isArray(keys) ? keys : [keys];
  for (const key of list) {
    const markers = [`var ${key} = `, `window["${key}"] = `, `window.${key} = `, `${key} = `];
    for (const marker of markers) {
      const markerIndex = html.indexOf(marker);
      if (markerIndex === -1) continue;
      const jsonStart = html.indexOf('{', markerIndex + marker.length);
      if (jsonStart === -1) continue;
      let depth = 0, inString = false, escaping = false;
      for (let i = jsonStart; i < html.length; i += 1) {
        const ch = html[i];
        if (inString) {
          if (escaping) escaping = false;
          else if (ch === '\\') escaping = true;
          else if (ch === '"') inString = false;
          continue;
        }
        if (ch === '"') { inString = true; continue; }
        if (ch === '{') { depth += 1; continue; }
        if (ch === '}') {
          depth -= 1;
          if (depth === 0) {
            try { return JSON.parse(html.slice(jsonStart, i + 1)); } catch { break; }
          }
        }
      }
    }
  }
  return null;
}
function videoFromRenderer(v, rank) {
  if (!v?.videoId) return null;
  return {
    rank,
    title: textOf(v.title),
    channel: textOf(v.ownerText || v.shortBylineText),
    video_id: v.videoId,
    views: textOf(v.viewCountText || v.shortViewCountText),
    duration: textOf(v.lengthText) || 'LIVE',
    published: textOf(v.publishedTimeText),
    url: 'https://www.youtube.com/watch?v=' + v.videoId,
    thumbnail: v.thumbnail?.thumbnails?.slice(-1)?.[0]?.url || ''
  };
}
function playlistVideoFromRenderer(v, rank) {
  if (!v?.videoId) return null;
  const infoRuns = v.videoInfo?.runs || [];
  return {
    rank,
    title: textOf(v.title),
    channel: textOf(v.shortBylineText),
    video_id: v.videoId,
    duration: textOf(v.lengthText),
    views: infoRuns[0]?.text || '',
    published: infoRuns[2]?.text || '',
    url: 'https://www.youtube.com/watch?v=' + v.videoId,
  };
}
async function fetchBrowse(apiKey, body) {
  const response = await fetch('/youtubei/v1/browse?key=' + apiKey + '&prettyPrint=false', {
    method: 'POST',
    credentials: 'include',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (!response.ok) return { error: 'InnerTube browse API returned HTTP ' + response.status };
  return response.json();
}
"""


def run_search(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=50)
    output_dir = Path(args.output) if args.output else default_action_output_dir("search", "view")
    sp_map = {
        "shorts": "EgIQCQ==",
        "video": "EgIQAQ==",
        "channel": "EgIQAg==",
        "playlist": "EgIQAw==",
        "hour": "EgIIAQ==",
        "today": "EgIIAg==",
        "week": "EgIIAw==",
        "month": "EgIIBA==",
        "year": "EgIIBQ==",
        "date": "CAI=",
        "views": "CAM=",
        "rating": "CAE=",
    }
    sp = sp_map.get(args.type) or sp_map.get(args.upload) or sp_map.get(args.sort) or ""
    url = f"{YOUTUBE_HOME_URL}/results?search_query={urllib.parse.quote(args.query)}"
    if sp:
        url += "&sp=" + urllib.parse.quote(sp)
    book = attach_workflow(args, url, ActionBook)
    book.goto(url)
    wait_until_stable(book)
    ensure_youtube_ready(book)
    data = evaluate(book, f"""
    (() => {{
      {JS_HELPERS}
      const limit = {count};
      const data = window.ytInitialData;
      if (!data) return {{ error: 'YouTube data not found' }};
      const sections = data.contents?.twoColumnSearchResultsRenderer?.primaryContents?.sectionListRenderer?.contents || [];
      const rows = [];
      for (const section of sections) {{
        const items = section.itemSectionRenderer?.contents || section.reelShelfRenderer?.items || [];
        for (const item of items) {{
          if (rows.length >= limit) break;
          if (item.videoRenderer) {{
            const row = videoFromRenderer(item.videoRenderer, rows.length + 1);
            if (row) rows.push(row);
          }} else if (item.reelItemRenderer) {{
            const r = item.reelItemRenderer;
            rows.push({{
              rank: rows.length + 1,
              title: textOf(r.headline),
              channel: textOf(r.navigationEndpoint?.reelWatchEndpoint?.overlay?.reelPlayerOverlayRenderer?.reelPlayerHeaderSupportedRenderers?.reelPlayerHeaderRenderer?.channelTitleText),
              video_id: r.videoId || '',
              views: textOf(r.viewCountText),
              duration: 'SHORT',
              published: textOf(r.publishedTimeText),
              url: 'https://www.youtube.com/shorts/' + (r.videoId || ''),
              thumbnail: r.thumbnail?.thumbnails?.slice(-1)?.[0]?.url || ''
            }});
          }} else if (item.playlistRenderer) {{
            const p = item.playlistRenderer;
            rows.push({{
              rank: rows.length + 1,
              type: 'playlist',
              title: textOf(p.title),
              channel: textOf(p.shortBylineText || p.longBylineText),
              video_id: '',
              playlist_id: p.playlistId || '',
              views: textOf(p.videoCountText),
              duration: 'PLAYLIST',
              published: '',
              url: 'https://www.youtube.com/playlist?list=' + (p.playlistId || ''),
              thumbnail: p.thumbnails?.[0]?.thumbnails?.slice(-1)?.[0]?.url || ''
            }});
          }} else if (item.channelRenderer) {{
            const c = item.channelRenderer;
            const baseUrl = c.navigationEndpoint?.browseEndpoint?.canonicalBaseUrl || '';
            rows.push({{
              rank: rows.length + 1,
              type: 'channel',
              title: textOf(c.title),
              channel: textOf(c.title),
              video_id: '',
              channel_id: c.channelId || c.navigationEndpoint?.browseEndpoint?.browseId || '',
              views: textOf(c.subscriberCountText),
              duration: 'CHANNEL',
              published: textOf(c.videoCountText),
              url: baseUrl ? 'https://www.youtube.com' + baseUrl : 'https://www.youtube.com/channel/' + (c.channelId || ''),
              thumbnail: c.thumbnail?.thumbnails?.slice(-1)?.[0]?.url || ''
            }});
          }}
        }}
      }}
      return rows;
    }})()
    """, "youtube search", timeout=30.0)
    rows = data if isinstance(data, list) else []
    write_records(rows, output_dir, f"YouTube 搜索: {args.query}")
    log(f"写入 {len(rows)} 条搜索结果: {output_dir}")
    return 0


def run_video(args: argparse.Namespace) -> int:
    vid = parse_video_id(args.url)
    output_dir = Path(args.output) if args.output else default_action_output_dir("video", "view")
    book = attach_workflow(args, YOUTUBE_HOME_URL, ActionBook)
    book.goto(YOUTUBE_HOME_URL)
    wait_until_stable(book)
    ensure_youtube_ready(book)
    data = evaluate(book, f"""
    (async () => {{
      {JS_HELPERS}
      const response = await fetch('/watch?v=' + encodeURIComponent({json.dumps(vid)}), {{ credentials: 'include' }});
      if (!response.ok) return {{ error: 'Watch HTML returned HTTP ' + response.status }};
      const html = await response.text();
      const player = extractJsonAssignmentFromHtml(html, 'ytInitialPlayerResponse');
      const yt = extractJsonAssignmentFromHtml(html, 'ytInitialData');
      if (!player) return {{ error: 'ytInitialPlayerResponse not found' }};
      const details = player.videoDetails || {{}};
      const microformat = player.microformat?.playerMicroformatRenderer || {{}};
      const contents = yt?.contents?.twoColumnWatchNextResults?.results?.results?.contents || [];
      let description = details.shortDescription || '';
      let subscribers = '';
      for (const c of contents) {{
        const desc = c.videoSecondaryInfoRenderer?.attributedDescription?.content;
        if (desc) description = desc;
        const sub = c.videoSecondaryInfoRenderer?.owner?.videoOwnerRenderer?.subscriberCountText?.simpleText;
        if (sub) subscribers = sub;
      }}
      return {{
        title: details.title || '',
        channel: details.author || '',
        channel_id: details.channelId || '',
        video_id: details.videoId || {json.dumps(vid)},
        views: details.viewCount || '',
        subscribers,
        duration_seconds: details.lengthSeconds || '',
        publish_date: microformat.publishDate || microformat.uploadDate || '',
        category: microformat.category || '',
        description,
        keywords: details.keywords || [],
        is_live: !!details.isLiveContent,
        thumbnail: details.thumbnail?.thumbnails?.slice(-1)?.[0]?.url || '',
        url: 'https://www.youtube.com/watch?v=' + (details.videoId || {json.dumps(vid)})
      }};
    }})()
    """, "youtube video", timeout=30.0)
    record = data if isinstance(data, dict) else {}
    write_records([record], output_dir, f"YouTube 视频: {record.get('title') or vid}")
    log(f"写入视频信息: {output_dir}")
    return 0


def load_transcript(book: ActionBook, video_id: str, lang: str) -> dict[str, Any]:
    book.goto(video_url(video_id))
    wait_until_stable(book)
    ensure_youtube_ready(book)
    data = evaluate(book, f"""
    (async () => {{
      {JS_HELPERS}
      const videoId = {json.dumps(video_id)};
      const langPref = {json.dumps(lang)};
      const playerElement = document.querySelector('#movie_player');
      const player = window.ytInitialPlayerResponse || (document.querySelector('ytd-watch-flexy')?.playerResponse) || playerElement?.getPlayerResponse?.();
      if (!player) return {{ error: 'ytInitialPlayerResponse not found' }};
      const tracks = player.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
      const details = player.videoDetails || {{}};
      if (!tracks.length) return {{ error: 'No caption tracks found for this video' }};
      const wanted = String(langPref || '').toLowerCase();
      const wantedBase = wanted.split('-')[0];
      const pickByLang = list => {{
        if (!Array.isArray(list) || !list.length) return null;
        if (wanted) {{
          return list.find(t => String(t.languageCode || '').toLowerCase() === wanted)
            || list.find(t => String(t.languageCode || '').toLowerCase().split('-')[0] === wantedBase);
        }}
        return null;
      }};
      let track = pickByLang(tracks);
      let playerTrack = null;
      try {{
        const tracklist = playerElement?.getOption?.('captions', 'tracklist') || [];
        playerTrack = pickByLang(tracklist)
          || tracklist.find(t => String(t.languageCode || '').startsWith('en') && t.kind !== 'asr')
          || tracklist.find(t => String(t.languageCode || '').startsWith('en'))
          || tracklist.find(t => t.kind !== 'asr')
          || tracklist[0]
          || null;
      }} catch {{}}
      if (wanted) {{
        track = tracks.find(t => String(t.languageCode || '').toLowerCase() === wanted)
          || tracks.find(t => String(t.languageCode || '').toLowerCase().split('-')[0] === wantedBase);
      }}
      track = track || tracks.find(t => String(t.languageCode || '').startsWith('en') && t.kind !== 'asr')
        || tracks.find(t => String(t.languageCode || '').startsWith('en'))
        || tracks.find(t => t.kind !== 'asr')
        || tracks[0];
      if (playerElement && playerTrack) {{
        try {{
          playerElement.setOption?.('captions', 'track', playerTrack);
          playerElement.setOption?.('captions', 'reload', true);
          await new Promise(resolve => setTimeout(resolve, 1800));
        }} catch {{}}
      }}
      const findGeneratedTimedtextUrl = () => {{
        const urls = performance.getEntriesByType('resource')
          .map(entry => entry.name || '')
          .filter(url => url.includes('/api/timedtext') && url.includes('fmt=json3'));
        const scoped = urls.filter(raw => {{
          try {{
            const parsed = new URL(raw, location.origin);
            if (parsed.searchParams.get('v') !== videoId) return false;
            if (!track?.languageCode) return true;
            const got = String(parsed.searchParams.get('lang') || '').toLowerCase();
            const gotBase = got.split('-')[0];
            const selected = String(track.languageCode || '').toLowerCase();
            const selectedBase = selected.split('-')[0];
            return got === selected || gotBase === selectedBase || selectedBase === gotBase;
          }} catch {{
            return false;
          }}
        }});
        return scoped.reverse().find(url => url.includes('pot=')) || scoped.reverse()[0] || '';
      }};
      let generatedUrl = findGeneratedTimedtextUrl();
      for (let i = 0; !generatedUrl && i < 5; i += 1) {{
        await new Promise(resolve => setTimeout(resolve, 500));
        generatedUrl = findGeneratedTimedtextUrl();
      }}
      const url = new URL(generatedUrl || track.baseUrl);
      url.searchParams.set('fmt', 'json3');
      const response = await fetch(url.toString(), {{ credentials: 'include' }});
      if (!response.ok) return {{
        error: 'Timedtext returned HTTP ' + response.status,
        selected_track: {{ language_code: track.languageCode || '', name: textOf(track.name) || track.languageCode || '', kind: track.kind || '' }},
        tracks: tracks.map(t => ({{ language_code: t.languageCode || '', name: textOf(t.name) || t.languageCode || '', kind: t.kind || '' }})),
        generated_url_found: !!generatedUrl
      }};
      const text = await response.text();
      const rows = [];
      try {{
        const payload = JSON.parse(text);
        for (const event of payload.events || []) {{
          const line = (event.segs || []).map(seg => seg.utf8 || '').join('').replace(/\\s+/g, ' ').trim();
          if (!line) continue;
          const startMs = Number(event.tStartMs || 0);
          const durMs = Number(event.dDurationMs || 0);
          rows.push({{ start: startMs / 1000, end: (startMs + durMs) / 1000, text: line }});
        }}
      }} catch {{
        const doc = new DOMParser().parseFromString(text, 'text/xml');
        for (const node of [...doc.querySelectorAll('text')]) {{
          const start = Number(node.getAttribute('start') || 0);
          const dur = Number(node.getAttribute('dur') || 0);
          const line = (node.textContent || '').replace(/\\s+/g, ' ').trim();
          if (line) rows.push({{ start, end: start + dur, text: line }});
        }}
      }}
      return {{
        video_id: videoId,
        title: details.title || '',
        channel: details.author || '',
        url: 'https://www.youtube.com/watch?v=' + videoId,
        selected_track: {{
          language_code: track.languageCode || '',
          name: textOf(track.name) || track.languageCode || '',
          kind: track.kind || '',
          is_translatable: !!track.isTranslatable
        }},
        tracks: tracks.map(t => ({{
          language_code: t.languageCode || '',
          name: textOf(t.name) || t.languageCode || '',
          kind: t.kind || '',
          is_translatable: !!t.isTranslatable
        }})),
        segments: rows
      }};
    }})()
    """, "youtube transcript", timeout=45.0)
    if not isinstance(data, dict):
        raise RuntimeError("youtube transcript: malformed payload")
    return data


def transcript_text(segments: list[dict[str, Any]], mode: str) -> str:
    if mode == "raw":
        return "\n".join(f"{fmt_time(float(seg.get('start') or 0))}\t{normalize_text(seg.get('text'))}" for seg in segments)
    groups = group_segments(segments)
    return "\n".join(f"{item['timestamp']} {item['text']}" for item in groups)


def run_transcript_view(args: argparse.Namespace) -> int:
    vid = parse_video_id(args.url)
    output_dir = Path(args.output) if args.output else default_action_output_dir("transcript", "view")
    book = attach_workflow(args, video_url(vid), ActionBook)
    data = load_transcript(book, vid, args.lang)
    segments = data.get("segments") if isinstance(data.get("segments"), list) else []
    rows = segments if args.mode == "raw" else group_segments(segments)
    record = {
        "video_id": data.get("video_id") or vid,
        "title": data.get("title") or "",
        "channel": data.get("channel") or "",
        "url": data.get("url") or video_url(vid),
        "selected_track": data.get("selected_track") or {},
        "track_count": len(data.get("tracks") or []),
        "segment_count": len(segments),
        "mode": args.mode,
        "transcript": rows,
    }
    write_records([record], output_dir, f"YouTube 字幕: {record['title'] or vid}")
    log(f"写入字幕摘要: {output_dir}")
    return 0


def run_transcript_download(args: argparse.Namespace) -> int:
    vid = parse_video_id(args.url)
    output_dir = Path(args.output) if args.output else default_action_output_dir("transcript", "download")
    book = attach_workflow(args, video_url(vid), ActionBook)
    data = load_transcript(book, vid, args.lang)
    segments = data.get("segments") if isinstance(data.get("segments"), list) else []
    text = transcript_text(segments, args.mode)
    title = normalize_text(data.get("title")) or vid
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "transcript.txt").write_text(text + "\n", encoding="utf-8")
    md = [
        f"# {title}",
        "",
        f"- 视频: {data.get('url') or video_url(vid)}",
        f"- 频道: {data.get('channel') or ''}",
        f"- 字幕轨道: {json.dumps(data.get('selected_track') or {}, ensure_ascii=False)}",
        f"- 片段数: {len(segments)}",
        "",
        text,
        "",
    ]
    (output_dir / "transcript.md").write_text("\n".join(md), encoding="utf-8")
    write_json(output_dir / "transcript.json", data)
    write_records([{
        "video_id": data.get("video_id") or vid,
        "title": title,
        "channel": data.get("channel") or "",
        "url": data.get("url") or video_url(vid),
        "selected_track": data.get("selected_track") or {},
        "segment_count": len(segments),
        "mode": args.mode,
        "transcript_path": str(output_dir / "transcript.md"),
    }], output_dir, f"YouTube 字幕下载: {title}")
    log(f"下载字幕: {output_dir}")
    return 0


def run_comments(args: argparse.Namespace) -> int:
    vid = parse_video_id(args.url)
    count = read_count(args.count, default=20, max_value=100)
    output_dir = Path(args.output) if args.output else default_action_output_dir("comments", "view")
    book = attach_workflow(args, video_url(vid), ActionBook)
    book.goto(video_url(vid))
    wait_until_stable(book)
    ensure_youtube_ready(book)
    data = evaluate(book, f"""
    (async () => {{
      {JS_HELPERS}
      const videoId = {json.dumps(vid)};
      const limit = {count};
      const cfg = window.ytcfg?.data_ || {{}};
      const apiKey = cfg.INNERTUBE_API_KEY;
      const context = cfg.INNERTUBE_CONTEXT;
      if (!apiKey || !context) return {{ error: 'YouTube config not found' }};
      let token = null;
      const results = window.ytInitialData?.contents?.twoColumnWatchNextResults?.results?.results?.contents || [];
      const section = results.find(i => i.itemSectionRenderer?.targetId === 'comments-section');
      token = section?.itemSectionRenderer?.contents?.[0]?.continuationItemRenderer?.continuationEndpoint?.continuationCommand?.token;
      if (!token) {{
        const nextResp = await fetch('/youtubei/v1/next?key=' + apiKey + '&prettyPrint=false', {{
          method: 'POST', credentials: 'include', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{context, videoId}})
        }});
        if (!nextResp.ok) return {{ error: 'Failed to get video data: HTTP ' + nextResp.status }};
        const nextData = await nextResp.json();
        const nextResults = nextData.contents?.twoColumnWatchNextResults?.results?.results?.contents || [];
        const nextSection = nextResults.find(i => i.itemSectionRenderer?.targetId === 'comments-section');
        token = nextSection?.itemSectionRenderer?.contents?.[0]?.continuationItemRenderer?.continuationEndpoint?.continuationCommand?.token;
      }}
      if (!token) return {{ error: 'No comment section found' }};
      const resp = await fetch('/youtubei/v1/next?key=' + apiKey + '&prettyPrint=false', {{
        method: 'POST', credentials: 'include', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{context, continuation: token}})
      }});
      if (!resp.ok) return {{ error: 'Failed to fetch comments: HTTP ' + resp.status }};
      const payload = await resp.json();
      const mutations = payload.frameworkUpdates?.entityBatchUpdate?.mutations || [];
      return mutations.filter(m => m.payload?.commentEntityPayload).slice(0, limit).map((m, i) => {{
        const p = m.payload.commentEntityPayload;
        return {{
          rank: i + 1,
          author: p.author?.displayName || '',
          text: (p.properties?.content?.content || '').replace(/\\s+/g, ' ').trim(),
          likes: p.toolbar?.likeCountNotliked || '0',
          replies: p.toolbar?.replyCount || '0',
          time: p.properties?.publishedTime || '',
        }};
      }});
    }})()
    """, "youtube comments", timeout=45.0)
    rows = data if isinstance(data, list) else []
    write_records(rows, output_dir, f"YouTube 评论: {vid}")
    log(f"写入 {len(rows)} 条评论: {output_dir}")
    return 0


def run_feed(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=20, max_value=100)
    output_dir = Path(args.output) if args.output else default_action_output_dir("feed", "view")
    book = attach_workflow(args, YOUTUBE_HOME_URL, ActionBook)
    book.goto(YOUTUBE_HOME_URL)
    wait_until_stable(book)
    ensure_youtube_ready(book)
    data = evaluate(book, f"""
    (() => {{
      {JS_HELPERS}
      const limit = {count};
      const d = window.ytInitialData;
      if (!d) return {{ error: 'YouTube data not found' }};
      const tabs = d.contents?.twoColumnBrowseResultsRenderer?.tabs || [];
      const contents = tabs[0]?.tabRenderer?.content?.richGridRenderer?.contents || [];
      const rows = [];
      for (const item of contents) {{
        if (rows.length >= limit) break;
        const v = item.richItemRenderer?.content?.videoRenderer || item.videoRenderer;
        const row = videoFromRenderer(v, rows.length + 1);
        if (row) rows.push(row);
      }}
      if (!rows.length) {{
        const seen = new Set();
        for (const renderer of document.querySelectorAll('ytd-rich-item-renderer, yt-lockup-view-model, ytd-video-renderer')) {{
          if (rows.length >= limit) break;
          const link = renderer.querySelector('a[href^="/watch?v="]');
          const href = link?.getAttribute('href') || '';
          if (!href) continue;
          const url = absUrl(href);
          if (seen.has(url)) continue;
          seen.add(url);
          const id = new URL(url).searchParams.get('v') || '';
          const title = link?.getAttribute('title') || textOf(renderer.querySelector('#video-title, h3, [class*="title"]')) || textOf(link);
          if (!title || !id) continue;
          const channel = textOf(renderer.querySelector('#channel-name a, ytd-channel-name, [class*="metadata"] a'));
          const metadata = [...renderer.querySelectorAll('#metadata-line span, #metadata span, yt-content-metadata-view-model span, yt-lockup-metadata-view-model span')].map(node => textOf(node)).filter(Boolean);
          rows.push({{
            rank: rows.length + 1,
            title,
            channel,
            video_id: id,
            views: metadata.find(value => /views|观看|次观看|次查看/i.test(value)) || '',
            duration: textOf(renderer.querySelector('ytd-thumbnail-overlay-time-status-renderer, yt-thumbnail-badge-view-model, badge-shape')),
            published: metadata.find(value => /ago|前|前に/i.test(value)) || '',
            url,
            thumbnail: renderer.querySelector('img')?.src || ''
          }});
        }}
      }}
      return rows;
    }})()
    """, "youtube feed", timeout=30.0)
    rows = data if isinstance(data, list) else []
    write_records(rows, output_dir, "YouTube 首页推荐")
    log(f"写入 {len(rows)} 条推荐视频: {output_dir}")
    return 0


def run_playlist_like(args: argparse.Namespace, source: str, url: str, playlist_id: str | None = None) -> int:
    count = read_count(args.count, default=50, max_value=200)
    output_dir = Path(args.output) if args.output else default_action_output_dir(source, "view")
    book = attach_workflow(args, url, ActionBook)
    try:
        book.goto(url)
    except Exception as exc:  # noqa: BLE001
        current_url = str(book.browser("url", timeout=10.0) or "")
        if urllib.parse.urlparse(url).path not in urllib.parse.urlparse(current_url).path and (playlist_id or "") not in current_url:
            raise exc
    wait_until_stable(book)
    ensure_youtube_ready(book)
    data = evaluate(book, f"""
    (async () => {{
      {JS_HELPERS}
      const limit = {count};
      const d = window.ytInitialData;
      if (!d) return {{ error: 'YouTube data not found' }};
      const cfg = window.ytcfg?.data_ || {{}};
      const apiKey = cfg.INNERTUBE_API_KEY;
      const context = cfg.INNERTUBE_CONTEXT;
      let title = textOf(d.header?.playlistHeaderRenderer?.title) || document.title || {json.dumps(source)};
      let contents = d.contents?.twoColumnBrowseResultsRenderer?.tabs?.[0]?.tabRenderer?.content?.sectionListRenderer?.contents?.[0]?.itemSectionRenderer?.contents?.[0]?.playlistVideoListRenderer?.contents || [];
      if (!contents.length && {json.dumps(playlist_id or "")}) {{
        if (!apiKey || !context) return {{ error: 'YouTube config not found' }};
        const browse = await fetchBrowse(apiKey, {{ context, browseId: 'VL' + {json.dumps(playlist_id or "")} }});
        if (browse.error) return browse;
        title = browse.header?.pageHeaderRenderer?.pageTitle || title;
        contents = browse.contents?.twoColumnBrowseResultsRenderer?.tabs?.[0]?.tabRenderer?.content?.sectionListRenderer?.contents?.[0]?.itemSectionRenderer?.contents?.[0]?.playlistVideoListRenderer?.contents || [];
      }}
      let rows = contents.map((item, i) => playlistVideoFromRenderer(item.playlistVideoRenderer, i + 1)).filter(Boolean);
      let cont = contents[contents.length - 1];
      while (rows.length < limit && cont?.continuationItemRenderer && apiKey && context) {{
        const token = cont.continuationItemRenderer?.continuationEndpoint?.continuationCommand?.token;
        if (!token) break;
        const next = await fetchBrowse(apiKey, {{ context, continuation: token }});
        if (next.error) break;
        const newItems = next.onResponseReceivedActions?.[0]?.appendContinuationItemsAction?.continuationItems || [];
        if (!newItems.length) break;
        rows = rows.concat(newItems.map((item, i) => playlistVideoFromRenderer(item.playlistVideoRenderer, rows.length + i + 1)).filter(Boolean));
        cont = newItems[newItems.length - 1];
      }}
      return {{ title, videos: rows.slice(0, limit) }};
    }})()
    """, f"youtube {source}", timeout=45.0)
    videos = data.get("videos") if isinstance(data, dict) and isinstance(data.get("videos"), list) else []
    write_records(videos, output_dir, f"YouTube {source}: {data.get('title') if isinstance(data, dict) else source}")
    log(f"写入 {len(videos)} 条 {source} 视频: {output_dir}")
    return 0


def run_playlist(args: argparse.Namespace) -> int:
    pid = parse_playlist_id(args.id)
    return run_playlist_like(args, "playlist", f"{YOUTUBE_HOME_URL}/playlist?list={urllib.parse.quote(pid)}", pid)


def run_watch_later(args: argparse.Namespace) -> int:
    return run_playlist_like(args, "watch-later", f"{YOUTUBE_HOME_URL}/playlist?list=WL", "WL")


def run_history(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=30, max_value=200)
    output_dir = Path(args.output) if args.output else default_action_output_dir("history", "view")
    book = attach_workflow(args, f"{YOUTUBE_HOME_URL}/feed/history", ActionBook)
    book.goto(f"{YOUTUBE_HOME_URL}/feed/history")
    wait_until_stable(book)
    ensure_youtube_ready(book)
    for _ in range(min(max((count // 20) + 1, 1), 8)):
        book.eval("window.scrollBy(0, Math.max(800, window.innerHeight)); true", timeout=5.0)
        time.sleep(0.8)
    data = evaluate(book, f"""
    (() => {{
      {JS_HELPERS}
      const limit = {count};
      const rows = [];
      const seen = new Set();
      const renderers = document.querySelectorAll('yt-lockup-view-model, ytd-video-renderer, ytd-rich-item-renderer, ytd-grid-video-renderer, ytd-compact-video-renderer');
      for (const renderer of renderers) {{
        if (rows.length >= limit) break;
        const link = renderer.querySelector('a[href^="/watch?v="]');
        const href = link?.getAttribute('href') || '';
        if (!href) continue;
        const url = absUrl(href);
        if (seen.has(url)) continue;
        seen.add(url);
        const title = link?.getAttribute('title') || textOf(renderer.querySelector('#video-title')) || textOf(renderer.querySelector('h3')) || textOf(link);
        const channel = textOf(renderer.querySelector('#channel-name a')) || textOf(renderer.querySelector('ytd-channel-name'));
        const metadata = [...renderer.querySelectorAll('#metadata-line span, #metadata span, yt-content-metadata-view-model span')].map(node => textOf(node)).filter(Boolean);
        rows.push({{
          rank: rows.length + 1,
          title,
          channel,
          views: metadata.find(value => /views|观看|次观看|次查看/i.test(value)) || '',
          duration: textOf(renderer.querySelector('ytd-thumbnail-overlay-time-status-renderer, yt-thumbnail-badge-view-model, badge-shape')),
          published: metadata.find(value => /ago|前|前に/i.test(value)) || '',
          url
        }});
      }}
      return rows;
    }})()
    """, "youtube history", timeout=30.0)
    rows = data if isinstance(data, list) else []
    write_records(rows, output_dir, "YouTube 观看历史")
    log(f"写入 {len(rows)} 条观看历史: {output_dir}")
    return 0


def run_subscriptions(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=50, max_value=1000)
    output_dir = Path(args.output) if args.output else default_action_output_dir("subscriptions", "view")
    book = attach_workflow(args, f"{YOUTUBE_HOME_URL}/feed/channels", ActionBook)
    book.goto(f"{YOUTUBE_HOME_URL}/feed/channels")
    wait_until_stable(book)
    ensure_youtube_ready(book)
    data = evaluate(book, f"""
    (() => {{
      {JS_HELPERS}
      const limit = {count};
      const d = window.ytInitialData;
      if (!d) return {{ error: 'YouTube data not found' }};
      const items = d.contents?.twoColumnBrowseResultsRenderer?.tabs?.[0]?.tabRenderer?.content?.sectionListRenderer?.contents?.[0]?.itemSectionRenderer?.contents?.[0]?.shelfRenderer?.content?.expandedShelfContentsRenderer?.items || [];
      const rows = [];
      for (const item of items) {{
        if (rows.length >= limit) break;
        const ch = item.channelRenderer || {{}};
        const name = textOf(ch.title);
        if (!name) continue;
        const baseUrl = ch.navigationEndpoint?.browseEndpoint?.canonicalBaseUrl || '';
        const channelId = ch.channelId || ch.navigationEndpoint?.browseEndpoint?.browseId || '';
        const subscriberText = textOf(ch.subscriberCountText);
        const videoCountText = textOf(ch.videoCountText);
        const handle = textOf(ch.channelHandleText) || (baseUrl.startsWith('/@') ? baseUrl.slice(1) : '') || (subscriberText.startsWith('@') ? subscriberText : '');
        const subscribers = (!subscriberText.startsWith('@') ? subscriberText : '') || (!videoCountText.startsWith('@') ? videoCountText : '');
        rows.push({{
          rank: rows.length + 1,
          name,
          handle,
          subscribers,
          url: baseUrl ? 'https://www.youtube.com' + baseUrl : (channelId ? 'https://www.youtube.com/channel/' + channelId : '')
        }});
      }}
      return rows;
    }})()
    """, "youtube subscriptions", timeout=30.0)
    rows = data if isinstance(data, list) else []
    write_records(rows, output_dir, "YouTube 订阅频道")
    log(f"写入 {len(rows)} 个订阅频道: {output_dir}")
    return 0


def run_channel(args: argparse.Namespace) -> int:
    count = read_count(args.count, default=10, max_value=30)
    channel_input = str(args.id or "").strip()
    output_dir = Path(args.output) if args.output else default_action_output_dir("channel", "view")
    start_url = f"{YOUTUBE_HOME_URL}/{channel_input}" if channel_input.startswith("@") else f"{YOUTUBE_HOME_URL}/channel/{channel_input}"
    book = attach_workflow(args, YOUTUBE_HOME_URL, ActionBook)
    book.goto(YOUTUBE_HOME_URL)
    wait_until_stable(book)
    ensure_youtube_ready(book)
    data = evaluate(book, f"""
    (async () => {{
      {JS_HELPERS}
      const input = {json.dumps(channel_input)};
      const limit = {count};
      const cfg = window.ytcfg?.data_ || {{}};
      const apiKey = cfg.INNERTUBE_API_KEY;
      const context = cfg.INNERTUBE_CONTEXT;
      if (!apiKey || !context) return {{ error: 'YouTube config not found' }};
      let browseId = input;
      if (input.startsWith('@')) {{
        const resp = await fetch('/youtubei/v1/navigation/resolve_url?key=' + apiKey + '&prettyPrint=false', {{
          method: 'POST', credentials: 'include', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{context, url: 'https://www.youtube.com/' + input}})
        }});
        if (resp.ok) {{
          const resolved = await resp.json();
          browseId = resolved.endpoint?.browseEndpoint?.browseId || input;
        }}
      }}
      let data = await fetchBrowse(apiKey, {{ context, browseId }});
      if (data.error) return data;
      const metadata = data.metadata?.channelMetadataRenderer || {{}};
      const tabs = data.contents?.twoColumnBrowseResultsRenderer?.tabs || [];
      const videosTab = tabs.find(t => {{
        const tr = t.tabRenderer || {{}};
        const url = tr.endpoint?.commandMetadata?.webCommandMetadata?.url || '';
        return tr.tabIdentifier === 'VIDEOS' || tr.title === 'Videos' || url.endsWith('/videos');
      }});
      if (videosTab?.tabRenderer?.endpoint?.browseEndpoint?.params) {{
        const videosData = await fetchBrowse(apiKey, {{ context, browseId, params: videosTab.tabRenderer.endpoint.browseEndpoint.params }});
        if (!videosData.error) data = videosData;
      }}
      const selectedTab = (data.contents?.twoColumnBrowseResultsRenderer?.tabs || []).find(t => t.tabRenderer?.selected)
        || (data.contents?.twoColumnBrowseResultsRenderer?.tabs || []).find(t => t.tabRenderer?.content?.richGridRenderer?.contents?.length);
      const rich = selectedTab?.tabRenderer?.content?.richGridRenderer?.contents || [];
      const videos = [];
      for (const item of rich) {{
        if (videos.length >= limit) break;
        const v = item.richItemRenderer?.content?.videoRenderer || item.videoRenderer;
        const row = videoFromRenderer(v, videos.length + 1);
        if (row) videos.push(row);
      }}
      return {{
        name: metadata.title || '',
        channel_id: metadata.externalId || browseId,
        handle: metadata.vanityChannelUrl?.split('/').pop() || '',
        description: (metadata.description || '').slice(0, 500),
        url: metadata.channelUrl || 'https://www.youtube.com/channel/' + browseId,
        recent_videos: videos
      }};
    }})()
    """, "youtube channel", timeout=45.0)
    record = data if isinstance(data, dict) else {}
    write_records([record], output_dir, f"YouTube 频道: {record.get('name') or channel_input}")
    log(f"写入频道信息: {output_dir}")
    return 0


def add_common(parser: argparse.ArgumentParser, default_count: int = 20) -> None:
    parser.add_argument("--count", type=int, default=default_count, help="Number of records")
    parser.add_argument("--output", default="", help="Output directory")
    add_workflow_args(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YouTube workflow helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="YouTube search")
    search_sub = search.add_subparsers(dest="mode", required=True)
    search_view = search_sub.add_parser("view", help="View YouTube search results")
    search_view.add_argument("--query", required=True)
    search_view.add_argument("--type", choices=("", "shorts", "video", "channel", "playlist"), default="")
    search_view.add_argument("--upload", choices=("", "hour", "today", "week", "month", "year"), default="")
    search_view.add_argument("--sort", choices=("", "relevance", "date", "views", "rating"), default="")
    add_common(search_view, default_count=20)
    search_view.set_defaults(func=run_search)

    video = subparsers.add_parser("video", help="YouTube video metadata")
    video_sub = video.add_subparsers(dest="mode", required=True)
    video_view = video_sub.add_parser("view", help="View video metadata")
    video_view.add_argument("--url", required=True, help="Video URL or ID")
    add_common(video_view, default_count=1)
    video_view.set_defaults(func=run_video)

    transcript = subparsers.add_parser("transcript", help="YouTube transcript workflows")
    transcript_sub = transcript.add_subparsers(dest="mode", required=True)
    transcript_view = transcript_sub.add_parser("view", help="View transcript")
    transcript_view.add_argument("--url", required=True, help="Video URL or ID")
    transcript_view.add_argument("--lang", default="", help="Language code, e.g. en or zh-Hans")
    transcript_view.add_argument("--mode", choices=("grouped", "raw"), default="grouped")
    add_common(transcript_view, default_count=1)
    transcript_view.set_defaults(func=run_transcript_view)
    transcript_download = transcript_sub.add_parser("download", help="Download transcript to Markdown/text/json")
    transcript_download.add_argument("--url", required=True, help="Video URL or ID")
    transcript_download.add_argument("--lang", default="", help="Language code, e.g. en or zh-Hans")
    transcript_download.add_argument("--mode", choices=("grouped", "raw"), default="grouped")
    add_common(transcript_download, default_count=1)
    transcript_download.set_defaults(func=run_transcript_download)

    comments = subparsers.add_parser("comments", help="YouTube comments")
    comments_sub = comments.add_subparsers(dest="mode", required=True)
    comments_view = comments_sub.add_parser("view", help="View video comments")
    comments_view.add_argument("--url", required=True, help="Video URL or ID")
    add_common(comments_view, default_count=20)
    comments_view.set_defaults(func=run_comments)

    channel = subparsers.add_parser("channel", help="YouTube channel")
    channel_sub = channel.add_subparsers(dest="mode", required=True)
    channel_view = channel_sub.add_parser("view", help="View channel info and videos")
    channel_view.add_argument("--id", required=True, help="Channel ID or handle")
    add_common(channel_view, default_count=10)
    channel_view.set_defaults(func=run_channel)

    playlist = subparsers.add_parser("playlist", help="YouTube playlist")
    playlist_sub = playlist.add_subparsers(dest="mode", required=True)
    playlist_view = playlist_sub.add_parser("view", help="View playlist videos")
    playlist_view.add_argument("--id", required=True, help="Playlist URL or ID")
    add_common(playlist_view, default_count=50)
    playlist_view.set_defaults(func=run_playlist)

    feed = subparsers.add_parser("feed", help="YouTube home feed")
    feed_sub = feed.add_subparsers(dest="mode", required=True)
    feed_view = feed_sub.add_parser("view", help="View home feed")
    add_common(feed_view, default_count=20)
    feed_view.set_defaults(func=run_feed)

    history = subparsers.add_parser("history", help="YouTube watch history")
    history_sub = history.add_subparsers(dest="mode", required=True)
    history_view = history_sub.add_parser("view", help="View watch history")
    add_common(history_view, default_count=30)
    history_view.set_defaults(func=run_history)

    watch_later = subparsers.add_parser("watch-later", help="YouTube Watch Later")
    watch_later_sub = watch_later.add_subparsers(dest="mode", required=True)
    watch_later_view = watch_later_sub.add_parser("view", help="View Watch Later queue")
    add_common(watch_later_view, default_count=50)
    watch_later_view.set_defaults(func=run_watch_later)

    subscriptions = subparsers.add_parser("subscriptions", help="YouTube subscriptions")
    subscriptions_sub = subscriptions.add_subparsers(dest="mode", required=True)
    subscriptions_view = subscriptions_sub.add_parser("view", help="View subscriptions")
    add_common(subscriptions_view, default_count=50)
    subscriptions_view.set_defaults(func=run_subscriptions)

    return parser


def main() -> int:
    install_interrupt_handlers()
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
