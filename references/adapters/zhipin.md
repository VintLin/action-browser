# BOSS Zhipin

Use this reference for BOSS Zhipin job list pages such as `https://www.zhipin.com/web/geek/jobs?city=101020100`.

## Browser Mode

- Prefer ActionBook Chrome extension mode so the page can reuse the user's existing login state and cookies.
- Do not rely on opening browser DevTools/debug mode for inspection. BOSS Zhipin may reload repeatedly when debugging is enabled. Prefer `actionbook browser snapshot` and `actionbook browser eval`.
- If login, CAPTCHA, slider verification, or risk-control pages appear, stop automation and ask the user to complete the step in the same Chrome window.

## Useful Selectors

Observed on the job list/detail split view:

- Search input: `input.input[placeholder*="搜索"]`
- Search button: `.search-btn` or link/button text `搜索`
- Map search button: `.search-map-btn`
- Recommended expectation chips: `.c-expect-select a.expect-item`
- Filter bar: `.filter-condition`, `.c-filter-condition`
- Filter dropdown wrapper: `.condition-filter-select`
- Industry dropdown wrapper: `.condition-industry-select`
- Job list cards: `.card-area`
- Card wrapper: `.job-card-wrap`
- Card title/original job URL: `.card-area a.job-name`
- Detail container: `.job-detail-container` or `.job-detail-box`
- Detail title: `.job-detail-info .job-name`
- Detail salary: `.job-detail-info .job-salary`
- Region/experience/education: `.tag-list li`
- Job labels: `.job-label-list li`
- Job description: `p.desc`
- HR block: `.job-boss-info`
- HR name: `.job-boss-info .name` first text line
- Company and HR title: `.job-boss-info .boss-info-attr`, usually `公司名称 · HR title`
- More detail link: `a.more-job-btn`
- Account action buttons in detail: `.op-btn-like` for `收藏`, `.op-btn-chat` for `立即沟通`
- Report/share buttons: `.link-report-new`, `.link-wechat-share`

Do not click account write actions such as `收藏`, `立即沟通`, report, resume upload, or chat unless the user explicitly asks for that exact action. For ordinary extraction and analysis, only record whether those controls exist and any visible state such as `bossOnline`.

## Page Features

The job list page supports these useful read-only features:

- Keyword search through `input.input[placeholder*="搜索"]`, with URL query parameter `query`.
- City selection through `city=<cityCode>`. Shanghai is `101020100`, Hangzhou is `101210100`, Fuzhou is `101230100` in observed pages.
- Recommended expectation chips near `推荐`, backed by the logged-in user's expectation list. These chips may switch both position and city.
- Filters in the top filter bar:
  - `jobType`: `1901` full-time, `1903` part-time.
  - `salary`: `402` 3K以下, `403` 3-5K, `404` 5-10K, `405` 10-20K, `406` 20-50K, `407` 50K以上.
  - `experience`: `108` 在校生, `102` 应届生, `101` 经验不限, `103` 1年以内, `104` 1-3年, `105` 3-5年, `106` 5-10年, `107` 10年以上.
  - `degree`: `202` 大专, `203` 本科, `204` 硕士, `205` 博士, plus lower degrees.
  - `scale`: `301` 0-20人 through `306` 10000人以上.
  - `industry`: industry numeric ids; use the filter condition API or DOM dropdown text to map names.
- Map mode through `.search-map-btn`, usually navigating to `/web/geek/map/jobs?query=<keyword>&cityCode=<cityCode>&from=2&city=<cityCode>`.
- Detail controls include `收藏`, `立即沟通`, `举报`, `微信扫码分享`, `查看更多信息`, and visible HR online state. Treat these as state unless the user requested an account action.

Search caveat:

- When searching from the recommendation page, BOSS may use the currently active recommended expectation city instead of the city in the current URL. If the task requires a specific city, explicitly set or navigate to the desired `city` after search, or use a same-origin JSON request with an explicit `city` parameter.

## Workflow Script

Use the read-only workflow script for repeated BOSS Zhipin operations:

```bash
python3 scripts/adapters/zhipin_workflow.py --help
```

For long runs, wrap it with `actionbook_run.py`:

```bash
python3 scripts/actionbook_run.py run \
  --id zhipin-search-shanghai-ai-agent \
  --cwd "$PWD" \
  -- \
  python3 scripts/adapters/zhipin_workflow.py search \
    --session zhipin-task \
    --city-code 101020100 \
    --query "AI Agent" \
    --count 100 \
    --include-title-any "AI,Agent,智能体" \
    --exclude-title-any "兼职" \
    --match-scope title
```

Supported subcommands:

- `filters`: read filter code lists and the logged-in user's recommendation expectation list.
- `recommend`: keep the old recommendation-list入口; prefer API when available, and fall back to rendered DOM extraction when BOSS blocks the API path.
- `search`: open one keyword page, click visible cards, and extract the rendered detail pane JD text.
- `crawl`: run a multi-city, multi-query DOM crawl with jittered timing and description-length/title-noise filtering.
- `detail`: keep the old detail入口; prefer API when `securityId` works, and fall back to a direct detail page URL / job id when needed.
- `chatlist`: read recruiter-side or job-seeker-side chat list metadata.
- `chatmsg`: read message history for one chat by `uid` from `chatlist`.

Examples:

```bash
# Read filter codes and expectation ids.
python3 scripts/adapters/zhipin_workflow.py filters \
  --session zhipin-task \
  --city-code 101020100 \
  --output-dir "$PWD/assets/zhipin/views/filters/$(date +%Y%m%d-%H%M%S)"

# Recommendation list, with API first and DOM fallback on risk-control.
python3 scripts/adapters/zhipin_workflow.py recommend \
  --session zhipin-task \
  --city-code 101020100 \
  --count 100 \
  --fallback-dom-on-risk

# Single keyword JD crawl with visible detail extraction.
python3 scripts/adapters/zhipin_workflow.py search \
  --session zhipin-task \
  --city-code 101020100 \
  --query "AI Agent" \
  --count 50

# Multi-city crawl with floating delays and title/content exclusion.
python3 scripts/adapters/zhipin_workflow.py crawl \
  --session zhipin-task \
  --city-codes "101020100,101210100,101280600" \
  --queries "AI 工程师,AI 应用工程师,智能体开发,RAG 开发,FDE 工程师" \
  --count 200 \
  --exclude-content-any "兼职,实习,应届,校招" \
  --exclude-title-noise-any "销售,产品经理,运营,市场,客服,讲师,培训,导演" \
  --min-description-length 50

# Detail API first; if blocked, pass a URL or job id for DOM fallback.
python3 scripts/adapters/zhipin_workflow.py detail \
  --session zhipin-task \
  --security-id "<security_id>" \
  --job-id "<encrypt_job_id>"

# Read chat list metadata without sending messages.
python3 scripts/adapters/zhipin_workflow.py chatlist \
  --session zhipin-task \
  --side auto \
  --limit 20

# Read message history for one chat uid returned by chatlist.
python3 scripts/adapters/zhipin_workflow.py chatmsg \
  --session zhipin-task \
  --side auto \
  --uid "<uid>"
```

The workflow writes:

```text
summary.json
summary.md
failures.json
progress.json
filter_config.json
```

For `recommend`, `search`, and `crawl`, `count` means target filtered count. The script continues until the target is reached, the page stops growing, or risk-control/errors appear.

Workflow limitations:

- BOSS job list/detail APIs have shown unstable risk-control behavior such as `code=37` in real runs. The current skill uses rendered DOM extraction for job crawls instead of those APIs.
- `recommend` and `detail` still keep the previous command names. When the API path is blocked, they should switch to the DOM-based fallback instead of failing immediately.
- `search` and `crawl` are DOM-based and depend on the visible split-view detail pane. If BOSS changes the page structure, selectors may need maintenance.
- `chatlist` and `chatmsg` are read-only inspection commands. They do not type into editors, send messages, greet candidates, exchange contact details, invite, mark, upload resumes, or change chat state.
- The workflow is read-only. It does not click `收藏`, `立即沟通`, upload resume, report, or send chat messages.
- Project-specific scoring, resume matching, and salary analytics should be done in downstream scripts using `summary.json`, not inside the workflow script.

## Observed Same-Origin APIs

Prefer DOM extraction for small interactive tasks. For larger read-only crawls, the page can call same-origin JSON endpoints through `actionbook browser eval` and `fetch(..., { credentials: "include" })`. This keeps the user's Chrome login state and usually returns decoded salary text without private-use salary font characters.

Observed endpoints:

```text
GET /wapi/zpgeek/pc/recommend/expect/list.json
GET /wapi/zpgeek/pc/all/filter/conditions.json
GET /wapi/zpgeek/pc/recommend/job/list.json
GET /wapi/zpgeek/search/joblist.json
GET /wapi/zpgeek/job/detail.json
GET /wapi/zpgeek/search/job/condition.json
GET /wapi/zpgeek/search/job/sidebar.json
GET /wapi/zpgeek/search/job/seo/data.json
GET /wapi/zpgeek/search/job/tdk.json
GET /wapi/zprelation/friend/getBossFriendListV2.json
GET /wapi/zprelation/friend/geekFilterByLabel
POST /wapi/zprelation/friend/getGeekFriendList.json
GET /wapi/zpchat/boss/historyMsg
GET /wapi/zpchat/geek/historyMsg
```

Observed recommendation list parameters:

```text
page=1
pageSize=15
city=101020100
encryptExpectId=
mixExpectType=
expectInfo=
jobType=
salary=
experience=
degree=
industry=
scale=
```

The recommendation list response contains `zpData.hasMore`, `zpData.jobList`, `zpData.type`, and `zpData.lid`. `jobList` records include useful fields such as:

- `securityId`, `encryptJobId`, `lid`
- `jobName`, `salaryDesc`, `jobLabels`, `skills`
- `jobExperience`, `jobDegree`, `cityName`, `areaDistrict`, `businessDistrict`
- `bossName`, `bossTitle`, `bossOnline`, `encryptBossId`
- `brandName`, `brandIndustry`, `brandScaleName`, `brandStageName`, `welfareList`
- `gps.longitude`, `gps.latitude`
- `jobType`, `proxyJob`, `anonymous`, `contact`, `atsDirectPost`

For detail API calls, use the `securityId` and `lid` from the corresponding list item when available. If an endpoint returns a risk-control response, login page, empty list, or non-JSON HTML, stop the workflow and fall back to visible DOM extraction or ask the user to complete verification.

Use API calls conservatively:

- Keep delays between pages.
- Record request parameters and response counts in `progress.json`.
- Stop on CAPTCHA, `安全验证`, abnormal redirects, or repeated non-zero codes.
- Do not call account-write endpoints for chat, collect, upload, or report.

## Job Card Extraction Flow

1. Confirm the extension connection and real tab id.
2. Open or reuse the job list URL.
3. Run `snapshot` or an `eval` selector probe before clicking.
4. Scroll to the bottom until enough `.card-area` nodes are loaded, then return to the top if extracting from the first card.
5. For each card:
   - `scrollIntoView({ block: "center" })`
   - click `.card-area a.job-name` or the card itself
   - wait until `.job-detail-info .job-name` matches the clicked card title
   - extract the detail fields from `.job-detail-box`
6. Keep the card URL from `.card-area a.job-name` as `原址`; keep `a.more-job-btn.href` separately as `查看更多信息的链接`.

For large list-only crawls, use the observed list API first and use DOM/detail clicks only for fields not available in the list API. Store both sources when mixing them:

- `source=list_api` for list API fields.
- `source=dom_detail` for fields read from the visible detail pane.
- `source=detail_api` for fields read from `job/detail.json`.

## Search And Filter Flow

When the user asks for keyword or condition-based search:

1. Confirm the intended city, keyword, and filters. Do not inherit a visible recommendation chip silently.
2. Navigate to a URL with explicit query and city, for example:

```text
https://www.zhipin.com/web/geek/jobs?city=101020100&query=AI%20Agent
```

3. Confirm the page title and body reflect the requested city. If it switches to another city, correct the URL or API parameters.
4. Read available filter codes through:

```javascript
await fetch('/wapi/zpgeek/pc/all/filter/conditions.json?_=' + Date.now(), { credentials: 'include' }).then(r => r.json())
```

5. Apply filters either by UI or by explicit API parameters. For reproducibility, prefer explicit API parameters when doing a crawl.
6. Record the filter config with both human labels and numeric codes in `filter_config.json`.

Recommended search output extras:

- `query`
- `city_code`, `city_name`
- `filter_codes`
- `filter_labels`
- `source_url`
- `api_endpoint` and parameters, when API extraction is used

## Map Mode

Map mode is useful for commute and district analysis:

```text
https://www.zhipin.com/web/geek/map/jobs?query=<keyword>&cityCode=<cityCode>&from=2&city=<cityCode>
```

Observed DOM markers:

- Page wrapper: `.page-map-job`
- Search panel: `.search-job-panel.map-search-job`
- Map container: `.job-map-container.bmap-container`
- Baidu map mask/canvas: `.BMap_mask`, `canvas`

Map mode may load Baidu map/proxy resources and a separate `search/joblist.json` request. It is less convenient than the standard list page for stable text extraction, but it can expose district clusters and commute-related UI. For crawls, prefer the standard list/API path and use map mode only when the user asks for location or commute analysis.

## Filtering And Refill

When the user asks to filter jobs and refill the list to a target count, confirm the filter configuration before crawling unless it is already explicit in the current user message or recent context. Do not treat examples as default rules.

At minimum, identify these settings:

- Target count per entry, such as `100`.
- Source entries, such as the three recommended chips near `推荐`.
- Inclusion rules, such as title contains any of `AI`, `Agent`, `智能体`.
- Exclusion rules, such as title does not contain `兼职`.
- Match scope: title only, or title plus labels, company, region, description.
- Case handling for English keywords, usually case-insensitive unless the user says otherwise.
- Refill behavior: continue loading more cards until filtered results reach the target, page stops adding cards, or risk-control appears.

If any of these are ambiguous and a reasonable assumption could change the output materially, ask the user to confirm the configuration first. A concise question is usually enough, for example:

```text
请确认过滤配置：是否按“标题包含 AI/Agent/智能体，且标题不含兼职”，只匹配标题，每个推荐入口补齐到 100 条？
```

For refill runs, maintain a progress file and record both `raw_seen_count` and `filtered_count`. If the page stops adding cards before the target is reached, save a partial result with the stop reason instead of padding with non-matching jobs.

## Output Paths

Follow the same output convention as the other ActionBook workflows: default to `assets/<site>/...`, support an explicit `--output` or `--output-dir` override, and keep machine-readable JSON next to human-readable Markdown.

Default output root:

```text
assets/zhipin/
```

Recommended list-only outputs:

```text
assets/zhipin/views/<task>/<yyyyMMdd-HHmmss>/
  summary.json
  summary.md
  failures.json
  progress.json
```

Recommended filtered refill outputs:

```text
assets/zhipin/filtered/<task>/<yyyyMMdd-HHmmss>/
  summary.json
  summary.md
  failures.json
  progress.json
  filter_config.json
  <entry_slug>_summary.json
  <entry_slug>_summary.md
```

Use stable, filesystem-safe path components:

- `<task>`: short task name, such as `recommend-jobs`, `search-jobs`, or `city-jobs`.
- `<entry_slug>`: source entry or city chip normalized for paths, such as `fuzhou`, `hangzhou`, `shanghai`, or `algorithm-fuzhou`.
- `<yyyyMMdd-HHmmss>`: local run timestamp used to keep each run immutable and resumable.

When the user gives an output location, treat it as the output root and preserve the same internal file layout under that root. Do not scatter result files in the workspace root unless the user explicitly asks for that.

For exploratory one-off work in a projectless agent workspace, an acceptable fallback is:

```text
<cwd>/zhipin_<task>/
```

but document the actual output root in the final response and in `progress.json`.

`summary.json` should contain the final result set and run metadata. `summary.md` should be the readable report. `failures.json` should be an array, empty when no failures occurred. `progress.json` should be durable and updated during long runs, including per-entry `raw_seen_count`, `filtered_count`, status, stop reason, and output file paths.

## Salary Font

BOSS Zhipin may obfuscate salary digits with private-use characters. In one observed session the mapping was sequential:

```text
\ue031 -> 0
\ue032 -> 1
\ue033 -> 2
\ue034 -> 3
\ue035 -> 4
\ue036 -> 5
\ue037 -> 6
\ue038 -> 7
\ue039 -> 8
\ue03a -> 9
```

When extracting salary, store both decoded text and the original salary text if the output needs to be auditable.
