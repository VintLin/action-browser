#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOSS Zhipin read-only workflow helper for the action-browser skill.

The workflow uses ActionBook extension mode and the user's existing Chrome
session. It covers read-only expectation/filter inspection, recommendation
list crawls, and slow keyword search crawls with optional client-side filtering
and refill.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

from actionbook_interrupts import install_interrupt_handlers
from actionbook_session import ActionBookSession as ActionBook


ZHIPIN_HOME_URL = "https://www.zhipin.com"
DEFAULT_SESSION = "zhipin-task"
DEFAULT_TAB = ""
SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_DIR / "assets" / "zhipin"
CITY_NAMES = {
    "100010000": "全国",
    "101010100": "北京",
    "101020100": "上海",
    "101280100": "广州",
    "101280600": "深圳",
    "101210100": "杭州",
    "101230100": "福州",
}
IDENTITY_MISMATCH_CODE = 24
TYPE_MAP = {
    1: "文本",
    2: "图片",
    3: "招呼",
    4: "简历",
    5: "系统",
    6: "名片",
    7: "语音",
    8: "视频",
    9: "表情",
}
COOKIE_EXPIRED_CODES = {7, 37}
SALARY_FONT_MAP = str.maketrans({
    "\ue031": "0",
    "\ue032": "1",
    "\ue033": "2",
    "\ue034": "3",
    "\ue035": "4",
    "\ue036": "5",
    "\ue037": "6",
    "\ue038": "7",
    "\ue039": "8",
    "\ue03a": "9",
})


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def normalize_text(value: Any) -> str:
    text = str(value or "").translate(SALARY_FONT_MAP)
    return re.sub(r"\s+", " ", text).strip()


def slugify(value: str, fallback: str = "zhipin") -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value or "").strip("-._")
    return (cleaned or fallback)[:80]


def split_words(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，|/]+", value or "") if item.strip()]


def default_output_dir(kind: str, task: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ASSETS_DIR / kind / task / stamp


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_summary_md(path: Path, title: str, jobs: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    lines = [f"# {title}", ""]
    lines.append("## 元数据")
    lines.append("")
    for key, value in meta.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## 职位")
    lines.append("")
    lines.append("| 序号 | 标题 | 薪资 | 地区 | 年限 | 学历 | 公司 | HR | 来源 | 链接 |")
    lines.append("| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for index, job in enumerate(jobs, start=1):
        link = job.get("url") or job.get("more_url") or ""
        title_text = str(job.get("title") or "")
        title_cell = f"[{title_text}]({link})" if link else title_text
        lines.append(
            "| {index} | {title} | {salary} | {region} | {experience} | {degree} | {company} | {hr} | {source} | {link} |".format(
                index=index,
                title=title_cell.replace("|", "\\|"),
                salary=str(job.get("salary") or "").replace("|", "\\|"),
                region=str(job.get("region") or "").replace("|", "\\|"),
                experience=str(job.get("experience") or "").replace("|", "\\|"),
                degree=str(job.get("degree") or "").replace("|", "\\|"),
                company=str(job.get("company") or "").replace("|", "\\|"),
                hr=str(job.get("hr_name") or "").replace("|", "\\|"),
                source=str(job.get("source") or "").replace("|", "\\|"),
                link=link,
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def unwrap_eval(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def api_eval(book: ActionBook, script: str, label: str, timeout: float = 45.0) -> Any:
    value = unwrap_eval(book.eval(script, timeout=timeout))
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(f"{label}: {value.get('error')}")
    return value


def page_state(book: ActionBook) -> dict[str, str]:
    value = api_eval(book, """
    (() => ({
      href: location.href,
      title: document.title || '',
      text: (document.body?.innerText || '').slice(0, 1200)
    }))()
    """, "zhipin page state", timeout=10.0)
    return value if isinstance(value, dict) else {}


def has_login_or_risk(state: dict[str, str]) -> bool:
    haystack = "\n".join([state.get("href", ""), state.get("title", ""), state.get("text", "")])
    return bool(re.search(r"安全验证|验证码|请完成验证|滑块|异常|登录|login|captcha|verify", haystack, re.I))


def ensure_ready(book: ActionBook) -> None:
    state = page_state(book)
    if has_login_or_risk(state):
        raise RuntimeError(f"BOSS Zhipin requires login or verification: {state.get('href')} title={state.get('title')}")


def start_book(args: argparse.Namespace, url: str) -> ActionBook:
    book = ActionBook(args.session, args.tab)
    book.start(url)
    ensure_ready(book)
    return book


def sleep_jitter(args: argparse.Namespace) -> None:
    time.sleep(random.uniform(float(args.delay_min), float(args.delay_max)))


def build_job_url(job_id: str) -> str:
    return f"{ZHIPIN_HOME_URL}/job_detail/{job_id}.html" if job_id else ""


def format_timestamp(value: Any) -> str:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ""
    if timestamp <= 0:
        return ""
    if timestamp > 10_000_000_000:
        timestamp = timestamp // 1000
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def normalize_api_job(raw: dict[str, Any]) -> dict[str, Any]:
    region = "·".join(
        part for part in [
            normalize_text(raw.get("cityName")),
            normalize_text(raw.get("areaDistrict")),
            normalize_text(raw.get("businessDistrict")),
        ]
        if part
    )
    return {
        "source": "list_api",
        "title": normalize_text(raw.get("jobName")),
        "salary": normalize_text(raw.get("salaryDesc")),
        "region": region,
        "experience": normalize_text(raw.get("jobExperience")),
        "degree": normalize_text(raw.get("jobDegree")),
        "company": normalize_text(raw.get("brandName")),
        "company_industry": normalize_text(raw.get("brandIndustry")),
        "company_scale": normalize_text(raw.get("brandScaleName")),
        "company_stage": normalize_text(raw.get("brandStageName")),
        "hr_name": normalize_text(raw.get("bossName")),
        "hr_title": normalize_text(raw.get("bossTitle")),
        "hr_online": bool(raw.get("bossOnline")),
        "labels": [normalize_text(item) for item in raw.get("jobLabels") or [] if normalize_text(item)],
        "skills": [normalize_text(item) for item in raw.get("skills") or [] if normalize_text(item)],
        "welfare": [normalize_text(item) for item in raw.get("welfareList") or [] if normalize_text(item)],
        "job_type": raw.get("jobType"),
        "proxy_job": raw.get("proxyJob"),
        "anonymous": raw.get("anonymous"),
        "contact": raw.get("contact"),
        "ats_direct_post": raw.get("atsDirectPost"),
        "encrypt_job_id": raw.get("encryptJobId") or "",
        "security_id": raw.get("securityId") or "",
        "lid": raw.get("lid") or "",
        "url": build_job_url(str(raw.get("encryptJobId") or "")),
        "gps": raw.get("gps") or {},
        "raw": raw,
    }


def normalize_dom_job(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "dom_list",
        "title": normalize_text(raw.get("title")),
        "salary": normalize_text(raw.get("salary")),
        "region": normalize_text(raw.get("region")),
        "experience": normalize_text(raw.get("experience")),
        "degree": normalize_text(raw.get("degree")),
        "company": normalize_text(raw.get("company")),
        "labels": [normalize_text(item) for item in raw.get("labels") or [] if normalize_text(item)],
        "url": raw.get("url") or "",
        "raw_text": normalize_text(raw.get("raw_text")),
        "raw": raw,
    }


def normalize_detail_payload(payload: dict[str, Any], security_id: str = "") -> dict[str, Any]:
    zp_data = payload.get("zpData") if isinstance(payload, dict) else None
    if not isinstance(zp_data, dict):
        raise RuntimeError("zhipin detail: malformed payload")
    job_info = zp_data.get("jobInfo") or {}
    boss_info = zp_data.get("bossInfo") or {}
    brand_info = zp_data.get("brandComInfo") or {}
    if not isinstance(job_info, dict) or not normalize_text(job_info.get("jobName")):
        raise RuntimeError("zhipin detail: job is offline or missing")
    if not isinstance(boss_info, dict):
        boss_info = {}
    if not isinstance(brand_info, dict):
        brand_info = {}
    encrypt_id = normalize_text(job_info.get("encryptId") or job_info.get("encryptJobId"))
    return {
        "source": "detail_api",
        "title": normalize_text(job_info.get("jobName")),
        "salary": normalize_text(job_info.get("salaryDesc")),
        "experience": normalize_text(job_info.get("experienceName")),
        "degree": normalize_text(job_info.get("degreeName")),
        "city": normalize_text(job_info.get("locationName")),
        "district": "·".join(
            part
            for part in [
                normalize_text(job_info.get("areaDistrict")),
                normalize_text(job_info.get("businessDistrict")),
            ]
            if part
        ),
        "description": normalize_text(job_info.get("postDescription")),
        "skills": [normalize_text(item) for item in job_info.get("showSkills") or [] if normalize_text(item)],
        "welfare": [normalize_text(item) for item in brand_info.get("labels") or [] if normalize_text(item)],
        "boss_name": normalize_text(boss_info.get("name")),
        "boss_title": normalize_text(boss_info.get("title")),
        "boss_active_time": normalize_text(boss_info.get("activeTimeDesc")),
        "company": normalize_text(brand_info.get("brandName") or boss_info.get("brandName")),
        "company_industry": normalize_text(brand_info.get("industryName")),
        "company_scale": normalize_text(brand_info.get("scaleName")),
        "company_stage": normalize_text(brand_info.get("stageName")),
        "address": normalize_text(job_info.get("address")),
        "security_id": normalize_text(security_id),
        "encrypt_job_id": encrypt_id,
        "url": build_job_url(encrypt_id),
        "raw": zp_data,
    }


def map_boss_chat_row(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "boss_chatlist",
        "name": normalize_text(raw.get("name")),
        "company": "",
        "job": normalize_text(raw.get("jobName")),
        "title": "",
        "last_msg": normalize_text((raw.get("lastMessageInfo") or {}).get("text") or raw.get("lastMsg")),
        "last_time": normalize_text(raw.get("lastTime")) or format_timestamp(raw.get("updateTime")),
        "uid": normalize_text(raw.get("encryptUid")),
        "numeric_uid": raw.get("uid"),
        "security_id": normalize_text(raw.get("securityId")),
        "raw": raw,
    }


def map_geek_chat_row(raw: dict[str, Any]) -> dict[str, Any]:
    last_message = raw.get("lastMessageInfo") or {}
    return {
        "source": "geek_chatlist",
        "name": normalize_text(raw.get("name")),
        "company": normalize_text(raw.get("brandName")),
        "job": normalize_text(raw.get("jobName")),
        "title": normalize_text(raw.get("bossTitle")),
        "last_msg": normalize_text(last_message.get("showText") or raw.get("lastMsg")),
        "last_time": normalize_text(raw.get("lastTime")) or format_timestamp(last_message.get("msgTime") or raw.get("updateTime")),
        "uid": normalize_text(raw.get("encryptUid") or raw.get("encryptFriendId") or raw.get("uid") or raw.get("friendId")),
        "numeric_uid": raw.get("uid") or raw.get("friendId"),
        "friend_id": raw.get("friendId"),
        "security_id": normalize_text(raw.get("securityId")),
        "raw": raw,
    }


def message_text(raw: dict[str, Any]) -> str:
    body = raw.get("body") if isinstance(raw.get("body"), dict) else {}
    return normalize_text(
        raw.get("text")
        or body.get("text")
        or body.get("content")
        or body.get("showText")
        or (json.dumps(body, ensure_ascii=False)[:120] if body else "")
    )


def map_boss_chat_messages(messages: list[dict[str, Any]], friend: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    friend_uid = str(friend.get("uid") or "")
    for raw in messages:
        from_obj = raw.get("from") if isinstance(raw.get("from"), dict) else {}
        from_uid = str(from_obj.get("uid") or "")
        rows.append({
            "from": "我" if from_uid and from_uid != friend_uid else normalize_text(from_obj.get("name") or friend.get("name") or "对方"),
            "type": TYPE_MAP.get(raw.get("type"), f"其他({raw.get('type')})"),
            "text": message_text(raw),
            "time": format_timestamp(raw.get("time")),
            "raw": raw,
        })
    return rows


def map_geek_chat_messages(messages: list[dict[str, Any]], friend: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    friend_uid = str(friend.get("uid") or "")
    for raw in messages:
        from_obj = raw.get("from") if isinstance(raw.get("from"), dict) else {}
        from_uid = str(from_obj.get("uid") or "")
        rows.append({
            "from": "对方" if from_uid and from_uid == friend_uid else "我",
            "type": TYPE_MAP.get(raw.get("type"), f"其他({raw.get('type')})"),
            "text": message_text(raw),
            "time": format_timestamp(raw.get("time")),
            "raw": raw,
        })
    return rows


def filter_job(job: dict[str, Any], args: argparse.Namespace) -> bool:
    include = split_words(getattr(args, "include_title_any", ""))
    exclude = split_words(getattr(args, "exclude_title_any", ""))
    scope = getattr(args, "match_scope", "title")
    title = normalize_text(job.get("title"))
    if scope == "title-tags":
        haystack = " ".join([title, " ".join(job.get("labels") or []), " ".join(job.get("skills") or [])])
    else:
        haystack = title
    haystack_l = haystack.lower()
    if include and not any(word.lower() in haystack_l for word in include):
        return False
    if exclude and any(word.lower() in title.lower() for word in exclude):
        return False
    return True


def dedupe_append(target: list[dict[str, Any]], seen: set[str], job: dict[str, Any]) -> bool:
    key = str(job.get("encrypt_job_id") or job.get("url") or job.get("title") + "|" + job.get("company", ""))
    if not key or key in seen:
        return False
    seen.add(key)
    target.append(job)
    return True


def fetch_json(
    book: ActionBook,
    path: str,
    params: dict[str, Any],
    label: str,
    *,
    method: str = "GET",
    body: str = "",
    allow_nonzero: bool = False,
) -> dict[str, Any]:
    request = {
        "path": path,
        "params": {k: str(v) for k, v in params.items()},
        "method": method,
        "body": body,
    }
    script = f"""
    (async () => {{
      const request = {json.dumps(request, ensure_ascii=False)};
      const params = new URLSearchParams(request.params);
      params.set('_', String(Date.now()));
      const url = request.method === 'GET' ? request.path + '?' + params.toString() : request.path;
      const options = {{
        method: request.method,
        credentials: 'include',
        headers: {{ Accept: 'application/json' }}
      }};
      if (request.method === 'POST') {{
        options.headers['Content-Type'] = 'application/x-www-form-urlencoded';
        options.body = request.body;
      }}
      const res = await fetch(url, options);
      const text = await res.text();
      let data;
      try {{ data = JSON.parse(text); }} catch (error) {{
        return {{ error: 'non-json response ' + res.status + ': ' + text.slice(0, 200) }};
      }}
      return {{ status: res.status, url: res.url, data }};
    }})()
    """
    value = api_eval(book, script, label, timeout=30.0)
    if not isinstance(value, dict):
        raise RuntimeError(f"{label}: unexpected response")
    if value.get("error"):
        raise RuntimeError(f"{label}: {value.get('error')}")
    data = value.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"{label}: missing JSON object")
    code = data.get("code")
    if code in COOKIE_EXPIRED_CODES:
        raise RuntimeError(f"{label}: BOSS Zhipin login expired; please re-login in the connected Chrome window")
    if code not in (0, "0", None) and not allow_nonzero:
        raise RuntimeError(f"{label}: code={data.get('code')} message={data.get('message')}")
    return data


def fetch_boss_friend_list(book: ActionBook, page_num: int, job_id: str, allow_nonzero: bool = False) -> Any:
    data = fetch_json(
        book,
        "/wapi/zprelation/friend/getBossFriendListV2.json",
        {"page": page_num, "status": 0, "jobId": job_id},
        "boss chatlist",
        allow_nonzero=allow_nonzero,
    )
    if allow_nonzero and data.get("code") not in (0, "0", None):
        return data
    friend_list = (data.get("zpData") or {}).get("friendList")
    if not isinstance(friend_list, list):
        raise RuntimeError("boss chatlist: missing zpData.friendList")
    return friend_list


def read_encrypt_system_id(book: ActionBook) -> str:
    value = api_eval(book, """
    (() => {
      try {
        const appEl = document.querySelector('#app') || document.querySelector('[data-v-app]');
        const vueApp = appEl && (appEl.__vue_app__ || appEl._vei);
        const pinia = vueApp?.config?.globalProperties?.$pinia;
        if (pinia?.state?.value) {
          for (const store of Object.values(pinia.state.value)) {
            const flat = JSON.stringify(store);
            const match = flat.match(/"encryptSystemId":"([^"]+)"/);
            if (match) return match[1];
          }
        }
        const query = vueApp?.config?.globalProperties?.$router?.currentRoute?.value?.query;
        if (query?.encryptSystemId) return query.encryptSystemId;
      } catch (_) {}
      try {
        for (const entry of performance.getEntriesByType('resource')) {
          if (!entry.name.includes('geekFilterByLabel')) continue;
          const value = new URL(entry.name).searchParams.get('encryptSystemId');
          if (value) return value;
        }
      } catch (_) {}
      return '';
    })()
    """, "read geek encryptSystemId", timeout=10.0)
    return normalize_text(value)


def fetch_geek_friend_label_list(book: ActionBook, encrypt_system_id: str) -> list[dict[str, Any]]:
    data = fetch_json(
        book,
        "/wapi/zprelation/friend/geekFilterByLabel",
        {"labelId": 0, "encryptSystemId": encrypt_system_id},
        "geek chat label list",
    )
    friend_list = (data.get("zpData") or {}).get("friendList")
    if not isinstance(friend_list, list):
        raise RuntimeError("geek chat label list: missing zpData.friendList")
    return friend_list


def fetch_geek_friend_info_list(book: ActionBook, friend_ids: list[Any]) -> list[dict[str, Any]]:
    if not friend_ids:
        return []
    results: list[dict[str, Any]] = []
    for index in range(0, len(friend_ids), 50):
        batch = [normalize_text(item) for item in friend_ids[index:index + 50] if normalize_text(item)]
        if not batch:
            continue
        data = fetch_json(
            book,
            "/wapi/zprelation/friend/getGeekFriendList.json",
            {},
            "geek chat friend info",
            method="POST",
            body=f"friendIds={','.join(batch)}",
        )
        rows = (data.get("zpData") or {}).get("result")
        if not isinstance(rows, list):
            raise RuntimeError("geek chat friend info: missing zpData.result")
        results.extend(row for row in rows if isinstance(row, dict))
    return results


def command_filters(args: argparse.Namespace) -> int:
    book = start_book(args, f"{ZHIPIN_HOME_URL}/web/geek/jobs?city={args.city_code}")
    conditions = fetch_json(book, "/wapi/zpgeek/pc/all/filter/conditions.json", {}, "filter conditions")
    expectations = fetch_json(book, "/wapi/zpgeek/pc/recommend/expect/list.json", {}, "expectation list")
    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir("views", "filters")
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "city_code": args.city_code,
        "conditions": conditions.get("zpData") or conditions,
        "expectations": expectations.get("zpData") or expectations,
    }
    write_json(output_dir / "summary.json", payload)
    write_json(output_dir / "failures.json", [])
    write_json(output_dir / "progress.json", {"status": "done", "output_dir": str(output_dir)})
    lines = ["# BOSS Zhipin Filters", "", f"- output_dir: `{output_dir}`", ""]
    for key, items in (payload.get("conditions") or {}).items():
        if not isinstance(items, list):
            continue
        lines.append(f"## {key}")
        lines.append("")
        for item in items:
            lines.append(f"- {item.get('code')}: {item.get('name')}")
        lines.append("")
    (output_dir / "summary.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    log(f"wrote {output_dir}")
    return 0


def command_recommend(args: argparse.Namespace) -> int:
    book = start_book(args, f"{ZHIPIN_HOME_URL}/web/geek/jobs?city={args.city_code}")
    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir("views", f"recommend-{args.city_code}")
    output_dir.mkdir(parents=True, exist_ok=True)
    filter_config = filter_config_from_args(args)
    write_json(output_dir / "filter_config.json", filter_config)
    failures: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    raw_seen = 0
    page = 1
    has_more = True
    while has_more and page <= args.max_pages and len(jobs) < args.count:
        params = {
            "page": page,
            "pageSize": args.page_size,
            "city": args.city_code,
            "encryptExpectId": args.encrypt_expect_id,
            "mixExpectType": args.mix_expect_type,
            "expectInfo": args.expect_info,
            "jobType": args.job_type,
            "salary": args.salary,
            "experience": args.experience,
            "degree": args.degree,
            "industry": args.industry,
            "scale": args.scale,
        }
        try:
            data = fetch_json(book, "/wapi/zpgeek/pc/recommend/job/list.json", params, f"recommend page {page}")
            zp_data = data.get("zpData") or {}
            raw_items = zp_data.get("jobList") or []
            has_more = bool(zp_data.get("hasMore"))
            for raw in raw_items:
                raw_seen += 1
                job = normalize_api_job(raw)
                if filter_job(job, args):
                    dedupe_append(jobs, seen, job)
                    if len(jobs) >= args.count:
                        break
            progress = {
                "status": "running",
                "mode": "recommend",
                "page": page,
                "raw_seen_count": raw_seen,
                "filtered_count": len(jobs),
                "has_more": has_more,
                "output_dir": str(output_dir),
            }
            write_json(output_dir / "progress.json", progress)
            log(f"page={page} raw_seen={raw_seen} filtered={len(jobs)} has_more={has_more}")
            page += 1
            if len(jobs) < args.count and has_more:
                sleep_jitter(args)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001
            failures.append({"page": page, "error": str(exc)})
            break
    meta = {
        "mode": "recommend",
        "city_code": args.city_code,
        "city_name": CITY_NAMES.get(args.city_code, ""),
        "raw_seen_count": raw_seen,
        "filtered_count": len(jobs),
        "target_count": args.count,
        "status": "done" if len(jobs) >= args.count or not has_more else "partial",
        "stop_reason": "target_reached" if len(jobs) >= args.count else ("no_more" if not has_more else "error_or_max_pages"),
        "filter_config": filter_config,
    }
    write_outputs(output_dir, "BOSS Zhipin Recommend Jobs", jobs, meta, failures)
    log(f"wrote {len(jobs)} jobs to {output_dir}")
    return 0 if not failures else 1


def extract_dom_jobs(book: ActionBook) -> list[dict[str, Any]]:
    script = """
    (() => {
      const norm = value => String(value || '').replace(/\\s+/g, ' ').trim();
      return [...document.querySelectorAll('.job-card-wrap')].map((wrap, index) => {
        const area = wrap.querySelector('.card-area') || wrap;
        const titleEl = area.querySelector('a.job-name, .job-name');
        const salaryEl = area.querySelector('.salary, .job-salary, [class*=salary]');
        const tagNodes = [...area.querySelectorAll('.tag-list li, .job-card-tag, .job-info-tag, .info-desc')].map(el => norm(el.innerText || el.textContent)).filter(Boolean);
        const lines = norm(area.innerText || area.textContent).split(' ').filter(Boolean);
        return {
          index,
          title: norm(titleEl?.innerText || titleEl?.textContent || lines[0] || ''),
          url: titleEl?.href || '',
          salary: norm(salaryEl?.innerText || salaryEl?.textContent || ''),
          labels: tagNodes,
          raw_text: norm(area.innerText || area.textContent)
        };
      });
    })()
    """
    raw_jobs = api_eval(book, script, "extract dom jobs", timeout=15.0)
    if not isinstance(raw_jobs, list):
        return []
    jobs: list[dict[str, Any]] = []
    for raw in raw_jobs:
        job = normalize_dom_job(raw)
        infer_dom_fields(job)
        jobs.append(job)
    return jobs


def infer_dom_fields(job: dict[str, Any]) -> None:
    if job.get("salary"):
        return
    parts = normalize_text(job.get("raw_text")).split(" ")
    if len(parts) >= 2:
        job["salary"] = parts[1]
    if len(parts) >= 4:
        job["experience"] = parts[2]
        job["degree"] = parts[3]
    if len(parts) >= 2:
        job["region"] = parts[-1]
        job["company"] = parts[-2]


def command_search(args: argparse.Namespace) -> int:
    query = urllib.parse.quote(args.query)
    url = f"{ZHIPIN_HOME_URL}/web/geek/jobs?city={args.city_code}&query={query}"
    book = start_book(args, url)
    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir("views", f"search-{slugify(args.query)}-{args.city_code}")
    output_dir.mkdir(parents=True, exist_ok=True)
    filter_config = filter_config_from_args(args)
    write_json(output_dir / "filter_config.json", filter_config)
    jobs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen: set[str] = set()
    raw_seen = 0
    stable_rounds = 0
    last_raw_seen = 0
    for round_index in range(1, args.max_scroll_rounds + 1):
        state = page_state(book)
        if has_login_or_risk(state):
            failures.append({"round": round_index, "error": "login_or_risk_control", "url": state.get("href")})
            break
        dom_jobs = extract_dom_jobs(book)
        raw_seen = max(raw_seen, len(dom_jobs))
        for job in dom_jobs:
            if filter_job(job, args):
                dedupe_append(jobs, seen, job)
                if len(jobs) >= args.count:
                    break
        write_json(output_dir / "progress.json", {
            "status": "running",
            "mode": "search",
            "round": round_index,
            "raw_seen_count": raw_seen,
            "filtered_count": len(jobs),
            "output_dir": str(output_dir),
            "url": state.get("href"),
        })
        log(f"round={round_index} raw_seen={raw_seen} filtered={len(jobs)}")
        if len(jobs) >= args.count:
            break
        if raw_seen <= last_raw_seen:
            stable_rounds += 1
        else:
            stable_rounds = 0
        if stable_rounds >= args.max_stable_rounds:
            break
        last_raw_seen = raw_seen
        book.browser("scroll", "down", "800", timeout=10.0)
        sleep_jitter(args)
    meta = {
        "mode": "search",
        "query": args.query,
        "city_code": args.city_code,
        "city_name": CITY_NAMES.get(args.city_code, ""),
        "raw_seen_count": raw_seen,
        "filtered_count": len(jobs),
        "target_count": args.count,
        "status": "done" if len(jobs) >= args.count else "partial",
        "stop_reason": "target_reached" if len(jobs) >= args.count else ("risk_or_error" if failures else "page_stopped_adding"),
        "filter_config": filter_config,
        "source_url": url,
    }
    write_outputs(output_dir, "BOSS Zhipin Search Jobs", jobs, meta, failures)
    log(f"wrote {len(jobs)} jobs to {output_dir}")
    return 0 if not failures else 1


def command_detail(args: argparse.Namespace) -> int:
    book = start_book(args, f"{ZHIPIN_HOME_URL}/web/geek/job")
    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir("views", f"detail-{slugify(args.security_id)}")
    failures: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    try:
        data = fetch_json(
            book,
            "/wapi/zpgeek/job/detail.json",
            {"securityId": args.security_id},
            "zhipin detail",
        )
        records.append(normalize_detail_payload(data, security_id=args.security_id))
    except Exception as exc:  # noqa: BLE001
        failures.append({"security_id": args.security_id, "error": str(exc)})
    meta = {
        "mode": "detail",
        "security_id": args.security_id,
        "record_count": len(records),
        "status": "done" if records else "failed",
    }
    write_records_outputs(output_dir, "BOSS Zhipin Job Detail", records, meta, failures, record_key="records")
    log(f"wrote {len(records)} detail records to {output_dir}")
    return 0 if records and not failures else 1


def merge_geek_chat_rows(labels: list[dict[str, Any]], enriched: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    enriched_by_id = {normalize_text(row.get("friendId") or row.get("uid")): row for row in enriched}
    rows: list[dict[str, Any]] = []
    for label in labels[:limit]:
        key = normalize_text(label.get("friendId") or label.get("uid"))
        raw = {**label, **enriched_by_id.get(key, {})}
        rows.append(map_geek_chat_row(raw))
    return rows


def command_chatlist(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir("views", f"chatlist-{args.side}")
    failures: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    try:
        if args.side == "boss":
            book = start_book(args, f"{ZHIPIN_HOME_URL}/web/chat/index")
            friends = fetch_boss_friend_list(book, args.page, args.job_id)
            records = [map_boss_chat_row(item) for item in friends[:args.limit]]
        elif args.side == "geek":
            book = start_book(args, f"{ZHIPIN_HOME_URL}/web/geek/chat")
            labels = fetch_geek_friend_label_list(book, read_encrypt_system_id(book))
            enriched = fetch_geek_friend_info_list(book, [item.get("friendId") for item in labels[:args.limit]])
            records = merge_geek_chat_rows(labels, enriched, args.limit)
        else:
            book = start_book(args, f"{ZHIPIN_HOME_URL}/web/chat/index")
            boss_result = fetch_boss_friend_list(book, args.page, args.job_id, allow_nonzero=True)
            if isinstance(boss_result, list):
                records = [map_boss_chat_row(item) for item in boss_result[:args.limit]]
            elif boss_result.get("code") == IDENTITY_MISMATCH_CODE:
                book.start(f"{ZHIPIN_HOME_URL}/web/geek/chat")
                ensure_ready(book)
                labels = fetch_geek_friend_label_list(book, read_encrypt_system_id(book))
                enriched = fetch_geek_friend_info_list(book, [item.get("friendId") for item in labels[:args.limit]])
                records = merge_geek_chat_rows(labels, enriched, args.limit)
            else:
                raise RuntimeError(f"boss chatlist: code={boss_result.get('code')} message={boss_result.get('message')}")
    except Exception as exc:  # noqa: BLE001
        failures.append({"side": args.side, "page": args.page, "error": str(exc)})
    meta = {
        "mode": "chatlist",
        "side": args.side,
        "page": args.page,
        "limit": args.limit,
        "record_count": len(records),
        "status": "done" if records else "failed",
    }
    write_records_outputs(output_dir, "BOSS Zhipin Chat List", records, meta, failures, record_key="records")
    log(f"wrote {len(records)} chat records to {output_dir}")
    return 0 if records and not failures else 1


def find_boss_friend_by_uid(book: ActionBook, uid: str, max_pages: int) -> dict[str, Any] | None:
    for page_num in range(1, max_pages + 1):
        friends = fetch_boss_friend_list(book, page_num, "0")
        for friend in friends:
            if normalize_text(friend.get("encryptUid")) == uid or normalize_text(friend.get("uid")) == uid:
                return friend
        if not friends:
            break
    return None


def find_geek_friend_by_uid(book: ActionBook, uid: str) -> dict[str, Any] | None:
    labels = fetch_geek_friend_label_list(book, read_encrypt_system_id(book))
    candidates = [
        item for item in labels
        if uid in {
            normalize_text(item.get("encryptFriendId")),
            normalize_text(item.get("encryptUid")),
            normalize_text(item.get("uid")),
            normalize_text(item.get("friendId")),
        }
    ]
    if not candidates:
        return None
    enriched = fetch_geek_friend_info_list(book, [candidates[0].get("friendId")])
    return {**candidates[0], **(enriched[0] if enriched else {})}


def fetch_boss_messages(book: ActionBook, friend: dict[str, Any], page_num: int) -> list[dict[str, Any]]:
    if not friend.get("securityId"):
        raise RuntimeError("boss chatmsg: missing securityId")
    data = fetch_json(
        book,
        "/wapi/zpchat/boss/historyMsg",
        {
            "gid": friend.get("uid"),
            "securityId": friend.get("securityId"),
            "page": page_num,
            "c": 20,
            "src": 0,
        },
        "boss chatmsg",
    )
    messages = (data.get("zpData") or {}).get("messages") or (data.get("zpData") or {}).get("historyMsgList")
    if not isinstance(messages, list):
        raise RuntimeError("boss chatmsg: missing message list")
    return messages


def fetch_geek_messages(book: ActionBook, friend: dict[str, Any], page_num: int) -> list[dict[str, Any]]:
    if not friend.get("securityId"):
        raise RuntimeError("geek chatmsg: missing securityId")
    data = fetch_json(
        book,
        "/wapi/zpchat/geek/historyMsg",
        {
            "bossId": friend.get("uid"),
            "securityId": friend.get("securityId"),
            "page": page_num,
            "c": 20,
            "src": 0,
        },
        "geek chatmsg",
    )
    messages = (data.get("zpData") or {}).get("messages") or (data.get("zpData") or {}).get("historyMsgList")
    if not isinstance(messages, list):
        raise RuntimeError("geek chatmsg: missing message list")
    return messages


def command_chatmsg(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir("views", f"chatmsg-{args.side}-{slugify(args.uid)}")
    failures: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    try:
        if args.side == "boss":
            book = start_book(args, f"{ZHIPIN_HOME_URL}/web/chat/index")
            friend = find_boss_friend_by_uid(book, args.uid, args.max_pages)
            if not friend:
                raise RuntimeError("boss chatmsg: uid not found")
            records = map_boss_chat_messages(fetch_boss_messages(book, friend, args.page), friend)
        elif args.side == "geek":
            book = start_book(args, f"{ZHIPIN_HOME_URL}/web/geek/chat")
            friend = find_geek_friend_by_uid(book, args.uid)
            if not friend:
                raise RuntimeError("geek chatmsg: uid not found")
            records = map_geek_chat_messages(fetch_geek_messages(book, friend, args.page), friend)
        else:
            book = start_book(args, f"{ZHIPIN_HOME_URL}/web/chat/index")
            friend = find_boss_friend_by_uid(book, args.uid, args.max_pages)
            if friend:
                records = map_boss_chat_messages(fetch_boss_messages(book, friend, args.page), friend)
            else:
                book.start(f"{ZHIPIN_HOME_URL}/web/geek/chat")
                ensure_ready(book)
                geek_friend = find_geek_friend_by_uid(book, args.uid)
                if not geek_friend:
                    raise RuntimeError("chatmsg: uid not found on boss or geek side")
                records = map_geek_chat_messages(fetch_geek_messages(book, geek_friend, args.page), geek_friend)
    except Exception as exc:  # noqa: BLE001
        failures.append({"side": args.side, "uid": args.uid, "page": args.page, "error": str(exc)})
    meta = {
        "mode": "chatmsg",
        "side": args.side,
        "uid": args.uid,
        "page": args.page,
        "record_count": len(records),
        "status": "done" if records else "failed",
    }
    write_records_outputs(output_dir, "BOSS Zhipin Chat Messages", records, meta, failures, record_key="records")
    log(f"wrote {len(records)} messages to {output_dir}")
    return 0 if records and not failures else 1


def filter_config_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "include_title_any": split_words(getattr(args, "include_title_any", "")),
        "exclude_title_any": split_words(getattr(args, "exclude_title_any", "")),
        "match_scope": getattr(args, "match_scope", "title"),
        "city_code": getattr(args, "city_code", ""),
        "job_type": getattr(args, "job_type", ""),
        "salary": getattr(args, "salary", ""),
        "experience": getattr(args, "experience", ""),
        "degree": getattr(args, "degree", ""),
        "industry": getattr(args, "industry", ""),
        "scale": getattr(args, "scale", ""),
    }


def write_outputs(
    output_dir: Path,
    title: str,
    jobs: list[dict[str, Any]],
    meta: dict[str, Any],
    failures: list[dict[str, Any]],
) -> None:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "meta": meta,
        "jobs": jobs,
    }
    write_json(output_dir / "summary.json", payload)
    write_summary_md(output_dir / "summary.md", title, jobs, meta)
    write_json(output_dir / "failures.json", failures)
    write_json(output_dir / "progress.json", {**meta, "output_dir": str(output_dir)})


def write_records_summary_md(path: Path, title: str, records: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    lines = [f"# {title}", ""]
    lines.append("## 元数据")
    lines.append("")
    for key, value in meta.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## 记录")
    lines.append("")
    for index, record in enumerate(records, start=1):
        heading = record.get("title") or record.get("name") or record.get("from") or str(index)
        lines.extend([f"### {index}. {heading}", ""])
        for key, value in record.items():
            if key == "raw" or value in ("", None, [], {}):
                continue
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(f"- {key}: {value}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_records_outputs(
    output_dir: Path,
    title: str,
    records: list[dict[str, Any]],
    meta: dict[str, Any],
    failures: list[dict[str, Any]],
    *,
    record_key: str,
) -> None:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "meta": meta,
        record_key: records,
    }
    write_json(output_dir / "summary.json", payload)
    write_records_summary_md(output_dir / "summary.md", title, records, meta)
    write_json(output_dir / "failures.json", failures)
    write_json(output_dir / "progress.json", {**meta, "output_dir": str(output_dir)})


def add_common_browser_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--session", default=DEFAULT_SESSION, help="ActionBook session id")
    parser.add_argument("--tab", default=DEFAULT_TAB, help="ActionBook tab id")
    parser.add_argument("--output-dir", default="", help="Output directory override")
    parser.add_argument("--delay-min", type=float, default=1.2, help="Minimum delay between pages/scrolls")
    parser.add_argument("--delay-max", type=float, default=2.8, help="Maximum delay between pages/scrolls")


def add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--count", type=int, default=20, help="Target filtered job count")
    parser.add_argument("--include-title-any", default="", help="Comma-separated title inclusion keywords")
    parser.add_argument("--exclude-title-any", default="", help="Comma-separated title exclusion keywords")
    parser.add_argument("--match-scope", choices=["title", "title-tags"], default="title")


def add_condition_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--city-code", default="101020100", help="BOSS city code, e.g. Shanghai 101020100")
    parser.add_argument("--job-type", default="", help="jobType code, e.g. 1901 full-time, 1903 part-time")
    parser.add_argument("--salary", default="", help="salary code, e.g. 406 for 20-50K")
    parser.add_argument("--experience", default="", help="experience code, e.g. 105 for 3-5 years")
    parser.add_argument("--degree", default="", help="degree code, e.g. 203 for bachelor")
    parser.add_argument("--industry", default="", help="industry code")
    parser.add_argument("--scale", default="", help="company scale code")


def add_chat_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--side", choices=["auto", "boss", "geek"], default="auto", help="Identity side")
    parser.add_argument("--page", type=int, default=1, help="Page number")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BOSS Zhipin read-only workflow helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    filters = subparsers.add_parser("filters", help="Read filter code lists and expectation list")
    add_common_browser_args(filters)
    filters.add_argument("--city-code", default="101020100")
    filters.set_defaults(func=command_filters)

    recommend = subparsers.add_parser("recommend", help="Read recommendation list via same-origin API")
    add_common_browser_args(recommend)
    add_condition_args(recommend)
    add_filter_args(recommend)
    recommend.add_argument("--page-size", type=int, default=15)
    recommend.add_argument("--max-pages", type=int, default=30)
    recommend.add_argument("--encrypt-expect-id", default="", help="Optional recommended expectation encryptId")
    recommend.add_argument("--mix-expect-type", default="")
    recommend.add_argument("--expect-info", default="")
    recommend.set_defaults(func=command_recommend)

    search = subparsers.add_parser("search", help="Open keyword search page and crawl visible list slowly")
    add_common_browser_args(search)
    add_condition_args(search)
    add_filter_args(search)
    search.add_argument("--query", required=True)
    search.add_argument("--max-scroll-rounds", type=int, default=30)
    search.add_argument("--max-stable-rounds", type=int, default=4)
    search.set_defaults(func=command_search)

    detail = subparsers.add_parser("detail", help="Read one job detail via same-origin API")
    add_common_browser_args(detail)
    detail.add_argument("--security-id", required=True, dest="security_id", help="securityId from search or recommend output")
    detail.set_defaults(func=command_detail)

    chatlist = subparsers.add_parser("chatlist", help="Read chat list without writing messages")
    add_common_browser_args(chatlist)
    add_chat_args(chatlist)
    chatlist.add_argument("--limit", type=int, default=20, help="Maximum records to output")
    chatlist.add_argument("--job-id", default="0", dest="job_id", help="Recruiter-side job filter, 0 means all")
    chatlist.set_defaults(func=command_chatlist)

    chatmsg = subparsers.add_parser("chatmsg", help="Read chat message history without writing messages")
    add_common_browser_args(chatmsg)
    add_chat_args(chatmsg)
    chatmsg.add_argument("--uid", required=True, help="Encrypted uid from chatlist output")
    chatmsg.add_argument("--max-pages", type=int, default=3, help="Recruiter-side chatlist pages to scan in auto/boss mode")
    chatmsg.set_defaults(func=command_chatmsg)

    return parser


def main(argv: list[str] | None = None) -> int:
    install_interrupt_handlers()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.delay_min > args.delay_max:
        parser.error("--delay-min must be <= --delay-max")
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        log("interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
