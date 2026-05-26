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
    "101020100": "上海",
    "101210100": "杭州",
    "101230100": "福州",
}
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


def fetch_json(book: ActionBook, path: str, params: dict[str, Any], label: str) -> dict[str, Any]:
    script = f"""
    (async () => {{
      const params = new URLSearchParams({json.dumps({k: str(v) for k, v in params.items()}, ensure_ascii=False)});
      params.set('_', String(Date.now()));
      const res = await fetch({json.dumps(path)} + '?' + params.toString(), {{ credentials: 'include' }});
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
    if data.get("code") not in (0, "0", None):
        raise RuntimeError(f"{label}: code={data.get('code')} message={data.get('message')}")
    return data


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
