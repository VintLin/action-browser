# Bilibili ActionBook 操作说明

> 所有 `*_workflow.py` 示例都假定当前 task 已通过 `acquire-tab` 领取 tab，并设置 `ACTIONBOOK_TASK_ID`、`ACTIONBOOK_SESSION_ID`、`ACTIONBOOK_TAB_ID`；也可在命令中显式传入同名参数。并行 task 不得共享同一组环境变量。

本文记录 Bilibili 网页在 ActionBook extension 模式下的站点专属经验。通用入口见 `../../SKILL.md`，适配脚本运行边界见 `../adapter-operation-boundaries.md`。

## 支持范围

当前参考 OpenCLI Bilibili 适配器，只启用低风险只读入口：

- `hot`: B 站热门视频。
- `ranking`: 视频排行榜。
- `search`: 搜索视频或用户。
- `video`: 读取单个视频元数据。
- `comments`: 读取视频一级评论。
- `dynamic`: 读取当前关注动态的简化入口。
- `feed`: 读取当前关注动态，或读取指定用户动态。
- `history`: 读取当前账号观看历史，需要登录态。
- `me`: 读取当前账号公开资料和统计，需要登录态。
- `following`: 读取关注列表；不传 `--uid` 时读取当前账号关注列表。
- `user-videos`: 读取指定用户投稿视频。
- `subtitle`: 读取视频字幕轨道。
- `summary`: 读取 B 站官方 AI 总结。

暂不启用这些 OpenCLI / 站点边界能力：

- `download`: 会调用 `yt-dlp` 下载视频文件，当前不接入。
- `favorite`: OpenCLI 中标记为 `access: write`，当前不接入收藏夹读取或变更。
- 点赞、取消点赞、投币、收藏、取消收藏、关注、取消关注、评论、弹幕、发布动态、投稿发布等账号写操作。

若后续需要写操作，应单独设计 `dry-run` / `--execute`、明确二次确认和失败恢复边界。

## 常用命令

```bash
python3 scripts/adapters/bilibili_workflow.py hot view --count 10

python3 scripts/adapters/bilibili_workflow.py ranking view --count 20

python3 scripts/adapters/bilibili_workflow.py search view \
  --query "OpenAI" \
  --type video \
  --count 10

python3 scripts/adapters/bilibili_workflow.py search view \
  --query "影视飓风" \
  --type user \
  --count 5

python3 scripts/adapters/bilibili_workflow.py video view \
  --url "BV1xx411c7mD"

python3 scripts/adapters/bilibili_workflow.py comments view \
  --url "https://www.bilibili.com/video/BV1xx411c7mD" \
  --count 20

python3 scripts/adapters/bilibili_workflow.py dynamic view --count 15

python3 scripts/adapters/bilibili_workflow.py feed view \
  --uid 123456 \
  --type all \
  --count 20

python3 scripts/adapters/bilibili_workflow.py history view --count 20

python3 scripts/adapters/bilibili_workflow.py me view

python3 scripts/adapters/bilibili_workflow.py following view --count 50

python3 scripts/adapters/bilibili_workflow.py user-videos view \
  --uid 123456 \
  --order pubdate \
  --count 20

python3 scripts/adapters/bilibili_workflow.py subtitle view \
  --url "BV1xx411c7mD" \
  --lang zh-CN

python3 scripts/adapters/bilibili_workflow.py summary view \
  --url "BV1xx411c7mD"
```

所有命令都支持：

- `--session`: ActionBook session id，默认 `bilibili-task`。
- `--tab`: 已确认存在的 ActionBook tab id。
- `--output`: 自定义输出目录。

列表类命令支持：

- `--count`: 输出数量。

批量或长时间读取 `history`、`following`、`user-videos`、`comments`、`feed` 时，必须通过通用运行器启动：

```bash
python3 scripts/actionbook_run.py run \
  --id bilibili-user-videos \
  --cwd "$PWD" \
  -- \
  python3 scripts/adapters/bilibili_workflow.py user-videos view \
    --uid 123456 \
    --count 100
```

## 输出位置

默认输出在 `assets/bilibili/` 下：

- `view`: `assets/bilibili/views/<channel>/<timestamp>/`

每次运行写入：

- `summary.json`: 结构化结果。
- `summary.md`: 人类可读摘要。
- `failures.json`: 当前实现中为空数组。

当前不提供 `download` 命令，因此不会创建视频下载目录或媒体文件。

## 登录和风控

公开热门、排行榜、视频元数据和部分搜索通常可读。以下能力通常需要 Chrome 中已有 B 站登录态：

- `history`
- `me`
- `following` 不传 `--uid` 时
- 当前关注 `dynamic` / `feed`
- 部分字幕、评论、AI 总结或用户空间数据

脚本检测到验证码、安全验证、风控、访问异常、请求过于频繁或账号登录页时会停止。应在同一 Chrome 窗口完成登录或验证，然后重新运行命令。

B 站部分 API 使用 WBI 签名。脚本会从 `x/web-interface/nav` 读取 WBI key，在本地计算签名，再通过当前浏览器 Cookie 发起只读请求。

## 数据边界

- `hot` 使用 `x/web-interface/popular`。
- `ranking` 使用 `x/web-interface/ranking/v2`。
- `search` 使用 `x/web-interface/wbi/search/type`，支持 `video` 和 `user`。
- `video` 使用 `x/web-interface/view`。
- `comments` 先用 `view` 解析 `aid`，再使用 `x/v2/reply/main`。
- `dynamic` / `feed` 使用 `x/polymer/web-dynamic/v1/feed/all` 或 `feed/space`。
- `history` 使用 `x/web-interface/history/cursor`。
- `me` 使用 `x/web-interface/nav` 和 `x/space/wbi/acc/info`。
- `following` 使用 `x/relation/followings`。
- `user-videos` 使用 `x/space/wbi/arc/search`。
- `subtitle` 使用 `x/player/wbi/v2` 获取字幕轨道，再读取字幕 JSON。
- `summary` 使用 `x/web-interface/view/conclusion/get`。

## 修改后验证

修改 Bilibili 脚本或流程说明后，优先运行：

```bash
python3 -m py_compile scripts/adapters/bilibili_workflow.py
python3 scripts/adapters/bilibili_workflow.py --help
python3 scripts/adapters/bilibili_workflow.py hot view --count 3
python3 scripts/adapters/bilibili_workflow.py search view --query "OpenAI" --type video --count 3
python3 scripts/adapters/bilibili_workflow.py video view --url "BV1xx411c7mD"
```
