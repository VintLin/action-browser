# 抖音 ActionBook 操作说明

> 所有 `*_workflow.py` 示例都假定当前 task 已通过 `acquire-tab` 领取 tab，并设置 `ACTIONBOOK_TASK_ID`、`ACTIONBOOK_SESSION_ID`、`ACTIONBOOK_TAB_ID`；也可在命令中显式传入同名参数。并行 task 不得共享同一组环境变量。

本文记录抖音网页在 ActionBook extension 模式下的站点专属经验。通用入口见 `../../SKILL.md`，适配脚本运行边界见 `../adapter-operation-boundaries.md`。

## 支持范围

当前参考 OpenCLI 抖音命令，只启用低风险只读入口：

- `profile`: 读取当前创作者账号信息，需要 `creator.douyin.com` 登录态。
- `videos`: 读取创作者后台作品列表，可按 `all`、`published`、`reviewing`、`scheduled` 过滤。
- `drafts`: 读取草稿列表，不上传、不编辑、不保存。
- `collections`: 读取合集列表。
- `activities`: 读取官方活动列表。
- `hashtag`: 话题搜索、AI 推荐或热点词读取。
- `location`: 地理位置 POI 搜索。
- `stats`: 读取指定作品近 7 天指标趋势。
- `user-videos`: 读取指定公开用户的视频列表，可选读取热门评论。

未启用写操作：

- `publish`: 上传并定时发布视频。
- `delete`: 删除作品。
- `draft`: 上传视频并保存为草稿。
- `update`: 更新发布时间或正文。

这些操作会改变账号状态、上传本地文件、删除内容或修改作品信息。若后续需要，应单独设计 `dry-run` / `--execute`、明确账号和作品 ID，并在运行前显式确认。

## 常用命令

```bash
python3 scripts/adapters/douyin_workflow.py profile view

python3 scripts/adapters/douyin_workflow.py videos view \
  --status all \
  --page 1 \
  --count 20

python3 scripts/adapters/douyin_workflow.py drafts view --count 20

python3 scripts/adapters/douyin_workflow.py collections view --count 20

python3 scripts/adapters/douyin_workflow.py activities view

python3 scripts/adapters/douyin_workflow.py hashtag view \
  --action search \
  --keyword "AI" \
  --count 10

python3 scripts/adapters/douyin_workflow.py hashtag view \
  --action hot \
  --count 10

python3 scripts/adapters/douyin_workflow.py location view \
  --query "北京" \
  --count 10

python3 scripts/adapters/douyin_workflow.py stats view \
  --aweme-id 1234567890123456789

python3 scripts/adapters/douyin_workflow.py user-videos view \
  --sec-uid "MS4wLjABAAAA..." \
  --count 10

python3 scripts/adapters/douyin_workflow.py user-videos view \
  --sec-uid "MS4wLjABAAAA..." \
  --count 5 \
  --with-comments \
  --comment-limit 3

python3 scripts/adapters/douyin_workflow.py user-videos view \
  --sec-uid "MS4wLjABAAAA..." \
  --count 5 \
  --download-media \
  --max-media-mb 50
```

所有命令都支持：

- `--session`: ActionBook session id，默认 `douyin-task`。
- `--tab`: 已确认存在的 ActionBook tab id。
- `--output`: 自定义输出目录。
- `--count`: 输出数量。

批量或长时间读取 `videos`、`user-videos`，或启用 `--download-media` 时，必须通过通用运行器启动：

```bash
python3 scripts/actionbook_run.py run \
  --id douyin-user-videos \
  --cwd "$PWD" \
  -- \
  python3 scripts/adapters/douyin_workflow.py user-videos view \
    --sec-uid "MS4wLjABAAAA..." \
    --count 50 \
    --download-media
```

## 输出位置

默认输出在 `assets/douyin/` 下：

- `view`: `assets/douyin/views/<channel>/<timestamp>/`

每次运行写入：

- `summary.json`: 结构化结果。
- `summary.md`: 人类可读摘要。
- `failures.json`: 当前实现中为空数组。

当前抖音脚本不提供通用 `download` 子命令，也不会上传任何本地文件。`user-videos view --download-media` 是只读媒体落盘能力：仅当页面/API 暴露 `video/mp4` 播放地址且未超过 `--max-media-mb` 时，写入 `media/<index>_<aweme_id>.mp4`，并在每条记录的 `media_download` 字段中记录 `downloaded`、`skipped` 或 `failed`。

## 登录和风控

`profile`、`videos`、`drafts`、`collections`、`activities`、`hashtag`、`location`、`stats` 依赖 `creator.douyin.com` 登录态。`user-videos` 依赖 `www.douyin.com` 页面和 Cookie，未登录也可能被风控。

脚本检测到以下状态会停止：

- URL、标题或正文出现登录、扫码登录。
- 页面出现验证码、安全验证、访问频繁、风险提示。
- 接口返回非 0 `status_code` 或浏览器内 `fetch` 失败。

遇到这些状态时，应在同一 Chrome 窗口完成登录或验证，然后重新运行命令。

## 数据边界

- `profile` 读取 `web/api/media/user/info`。
- `videos` 读取 `janus/douyin/creator/pc/work_list`。
- `drafts` 读取 `web/api/media/aweme/draft`。
- `collections` 读取 `web/api/mix/list`。
- `activities` 读取 `web/api/media/activity/get`。
- `hashtag search` 读取 `aweme/v1/challenge/search`。
- `hashtag suggest` 读取 `web/api/media/hashtag/rec`，需要 `--cover` 传封面 URI。
- `hashtag hot` 读取 `aweme/v1/hotspot/recommend`。
- `location` 读取 `aweme/v1/life/video_api/search/poi`。
- `stats` 读取 `janus/douyin/creator/data/item_analysis/metrics_trend`，只读 POST。
- `user-videos` 读取 `www.douyin.com/aweme/v1/web/aweme/post`；使用 `--with-comments` 时额外读取评论列表接口。

## 修改后验证

修改抖音脚本或流程说明后，优先运行：

```bash
python3 -m py_compile scripts/adapters/douyin_workflow.py
python3 scripts/adapters/douyin_workflow.py --help
python3 scripts/adapters/douyin_workflow.py profile view --count 1
python3 scripts/adapters/douyin_workflow.py videos view --count 3
python3 scripts/adapters/douyin_workflow.py hashtag view --action hot --count 3
```
