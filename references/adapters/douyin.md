# 抖音 ActionBook 操作说明

本文记录抖音网页在 ActionBook extension 模式下的站点专属经验。通用会话、等待、错误处理规则见 `../SKILL.md`。

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
```

所有命令都支持：

- `--session`: ActionBook session id，默认 `douyin-task`。
- `--tab`: 已确认存在的 ActionBook tab id。
- `--output`: 自定义输出目录。
- `--count`: 输出数量。

## 输出位置

默认输出在 `assets/douyin/` 下：

- `view`: `assets/douyin/views/<channel>/<timestamp>/`

每次运行写入：

- `summary.json`: 结构化结果。
- `summary.md`: 人类可读摘要。
- `failures.json`: 当前实现中为空数组。

当前抖音脚本不提供下载入口，不写入媒体文件，也不上传任何本地文件。

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
