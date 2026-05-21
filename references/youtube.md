# YouTube ActionBook 操作说明

本文记录 YouTube 网页在 ActionBook extension 模式下的站点专属经验。通用会话、等待、错误处理规则见 `../SKILL.md`。

## 支持范围

当前对齐 OpenCLI YouTube 只读能力：

- `search`: 搜索视频，可按视频、Shorts、频道、播放列表等过滤。
- `video`: 读取单个视频元数据。
- `transcript`: 提取视频字幕，支持 `view` 和 `download`。
- `comments`: 读取视频评论。
- `channel`: 读取频道信息和近期视频。
- `playlist`: 读取播放列表视频。
- `feed`: 读取首页推荐。
- `history`: 读取观看历史，需要登录态。
- `watch-later`: 读取稍后观看，需要登录态。
- `subscriptions`: 读取订阅频道，需要登录态。

暂不启用账号写操作：

- `like`
- `unlike`
- `subscribe`
- `unsubscribe`

这些操作会修改账号状态。若后续需要，应单独设计 `dry-run` / `--execute` 和显式确认边界。

## 字幕支持

支持视频字幕提取：

```bash
python3 scripts/youtube_workflow.py transcript view \
  --url "https://www.youtube.com/watch?v=VIDEO_ID" \
  --lang en

python3 scripts/youtube_workflow.py transcript download \
  --url "https://www.youtube.com/watch?v=VIDEO_ID" \
  --lang en \
  --mode grouped
```

`transcript download` 会写入：

- `summary.json`
- `summary.md`
- `failures.json`
- `transcript.json`: 原始字幕轨道和片段。
- `transcript.txt`: 纯文本字幕。
- `transcript.md`: 带视频信息的 Markdown 字幕。

字幕限制：

- 视频必须公开且当前地区可访问。
- 视频必须有手动字幕或自动字幕轨道。
- `--lang` 不传时，优先英文，再选非自动字幕，最后选第一个轨道。
- 某些视频需要年龄验证或地区权限，脚本会停止并报告当前页面。

## 常用命令

```bash
python3 scripts/youtube_workflow.py search view \
  --query "OpenAI" \
  --type video \
  --count 5

python3 scripts/youtube_workflow.py video view \
  --url "https://www.youtube.com/watch?v=VIDEO_ID"

python3 scripts/youtube_workflow.py comments view \
  --url "https://www.youtube.com/watch?v=VIDEO_ID" \
  --count 20

python3 scripts/youtube_workflow.py channel view \
  --id "@OpenAI" \
  --count 10

python3 scripts/youtube_workflow.py playlist view \
  --id "https://www.youtube.com/playlist?list=PLAYLIST_ID" \
  --count 20

python3 scripts/youtube_workflow.py feed view --count 20

python3 scripts/youtube_workflow.py history view --count 20

python3 scripts/youtube_workflow.py watch-later view --count 20

python3 scripts/youtube_workflow.py subscriptions view --count 20
```

所有命令都支持：

- `--session`: ActionBook session id，默认 `youtube-task`。
- `--tab`: 已确认存在的 ActionBook tab id。
- `--output`: 自定义输出目录。
- `--count`: 输出数量。

## 输出位置

默认输出在 `assets/youtube/` 下：

- `view`: `assets/youtube/views/<channel>/<timestamp>/`
- `download`: `assets/youtube/downloads/<channel>/<timestamp>/`

每次运行写入：

- `summary.json`: 结构化结果。
- `summary.md`: 人类可读摘要。
- `failures.json`: 当前实现中为空数组。

## 登录和风控

公开搜索、视频信息、公开播放列表、频道和部分字幕通常不需要登录。以下能力通常需要登录态：

- `feed`
- `history`
- `watch-later`
- `subscriptions`

脚本检测到 Google 登录、验证码、异常流量、年龄验证或地区限制时会停止。应在同一 Chrome 窗口完成登录或验证，然后重新运行命令。

## 修改后验证

修改 YouTube 脚本或流程说明后，优先运行：

```bash
python3 -m py_compile scripts/youtube_workflow.py
python3 scripts/youtube_workflow.py --help
python3 scripts/youtube_workflow.py search view --query "OpenAI" --type video --count 3
python3 scripts/youtube_workflow.py video view --url "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
python3 scripts/youtube_workflow.py transcript download --url "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --mode grouped
```
