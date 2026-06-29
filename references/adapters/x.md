# X 工作流

本文用于在 `action-browser` skill 中操作 X。流程依赖 ActionBook Chrome extension 模式和用户当前 Chrome 登录态。

## 初始化要求

先确认：

```bash
actionbook extension status --json
```

可用状态应包含：

```json
{
  "bridge": "listening",
  "extension_connected": true
}
```

如果 ActionBook、Chrome extension、session 或 tab 状态不明确，先按 `references/status-check.md` 检查。若环境缺失，按 `references/initialization.md` 初始化。遇到登录、验证码、MFA 或风控页时，保留当前 Chrome 窗口，让用户手动完成后再继续。

## 统一入口

```bash
python3 scripts/adapters/x_workflow.py --help
```

当前 `scripts/` 下只保留一个 X 相关脚本：`x_workflow.py`。它参考 `xiaohongshu_workflow.py` 的子命令形式，并且所有浏览器操作都走同一个 ActionBook session/tab。

通用运行边界、session/tab 生命周期和停止策略见 [references/adapter-operation-boundaries.md](/Users/Vint/Repos/04_Skills/01_通用%20Skills/02_action-browser/references/adapter-operation-boundaries.md)。

## Home

读取 Home 时间线前 N 条帖子：

```bash
python3 scripts/adapters/x_workflow.py home view \
  --count 30

python3 scripts/adapters/x_workflow.py home download \
  --count 30
```

默认输出：

```text
assets/x/views/home/yyyyMMdd-HHmmss/
assets/x/downloads/home/yyyyMMdd-HHmmss/
```

`view` 只写汇总文件：

```text
summary.json
summary.md
failures.json
```

`download` 写汇总文件，并为每条帖子创建目录：

```text
summary.json
summary.md
failures.json
001_tweet_text_handle_statusid/
002_article_image_handle_statusid/
003_quote_tweet_video_handle_statusid/
  metadata.json
  content.md
  raw.txt
  media/
```

单帖目录名包含帖子类型和内容形态：

```text
<index>_<tweet_type>_<content_flags>_<handle>_<statusid>/
```

`tweet_type` 来自 `tweet`、`reply`、`quote_tweet`、`repost`、`article`。`content_flags` 由 `text`、`image`、`video`、`card`、`article` 组合而成；如果 `tweet_type=article`，不会重复写成 `article_article`。

`raw.txt` 不是纯页面行转储。它应包含：

- 基础信息：类型、作者、时间、来源。
- 指标说明：把页面底部独立数字标注为回复、转帖、喜欢、书签、查看等。
- 原始行：保留页面可见文本，方便排查 DOM 解析。
- 文章详情正文：如果文章详情已补全，同步写入详情正文、正文行数、图片数和图片位置标记。

`download` 时，如果列表页帖子包含 `显示更多` / `Show more` 或明显截断，脚本应打开该条详情页，尽量展开完整文本后再写入 `metadata.json`、`content.md` 和 `raw.txt`。`view` 会尽力尝试补全文本，但不创建单帖目录。

## Bookmarks

读取 Bookmarks 前 N 条帖子：

```bash
python3 scripts/adapters/x_workflow.py bookmarks view \
  --count 30

python3 scripts/adapters/x_workflow.py bookmarks download \
  --count 30
```

默认输出：

```text
assets/x/views/bookmarks/yyyyMMdd-HHmmss/
assets/x/downloads/bookmarks/yyyyMMdd-HHmmss/
```

## 单条 Tweet

读取单条 tweet/status URL：

```bash
python3 scripts/adapters/x_workflow.py tweet view \
  --url "https://x.com/<handle>/status/<id>"

python3 scripts/adapters/x_workflow.py tweet download \
  --url "https://x.com/<handle>/status/<id>"
```

默认输出：

```text
assets/x/views/tweet/yyyyMMdd-HHmmss/
assets/x/downloads/tweet/yyyyMMdd-HHmmss/
```

该入口会打开指定详情页，抽取当前可见 tweet。若详情页同时渲染上下文或回复，默认只请求 1 条；需要更多上下文时使用 `thread view` 或 `thread download`。

## Thread

从一个 tweet/status URL 读取当前页面可见线程：

```bash
python3 scripts/adapters/x_workflow.py thread view \
  --url "https://x.com/<handle>/status/<id>" \
  --count 50

python3 scripts/adapters/x_workflow.py thread download \
  --url "https://x.com/<handle>/status/<id>" \
  --count 50
```

默认输出：

```text
assets/x/views/thread/yyyyMMdd-HHmmss/
assets/x/downloads/thread/yyyyMMdd-HHmmss/
```

当前实现复用可见 tweet 收集逻辑，保存页面中按滚动顺序出现的帖子。线程父子关系先通过 `source_url`、`reply_to`、`quoted_tweet` 等字段表达，不做额外图结构推断。

## Search

读取搜索结果：

```bash
python3 scripts/adapters/x_workflow.py search view \
  --query "关键词" \
  --filter live \
  --count 30

python3 scripts/adapters/x_workflow.py search download \
  --query "关键词" \
  --filter live \
  --count 30
```

`--filter` 可选：`live`、`top`、`user`、`image`、`video`。默认 `live`。

默认输出：

```text
assets/x/views/search/yyyyMMdd-HHmmss/
assets/x/downloads/search/yyyyMMdd-HHmmss/
```

## Profile 与 Me

读取用户主页或当前账号自身可见帖子：

```bash
python3 scripts/adapters/x_workflow.py profile view \
  --handle "@handle" \
  --count 30

python3 scripts/adapters/x_workflow.py profile download \
  --handle "@handle" \
  --count 30

python3 scripts/adapters/x_workflow.py profile view \
  --profile-url "https://x.com/<handle>" \
  --count 30

python3 scripts/adapters/x_workflow.py profile download \
  --profile-url "https://x.com/<handle>" \
  --count 30

python3 scripts/adapters/x_workflow.py me view \
  --count 30

python3 scripts/adapters/x_workflow.py me download \
  --count 30
```

默认输出：

```text
assets/x/views/profile/yyyyMMdd-HHmmss/
assets/x/downloads/profile/yyyyMMdd-HHmmss/
assets/x/views/me/yyyyMMdd-HHmmss/
assets/x/downloads/me/yyyyMMdd-HHmmss/
```

## Payload 字段

`summary.json` 是 `TweetPayload[]`，每条包含：

- `tweet_id`
- `source_url`
- `source_page`: `home`、`bookmarks`、`tweet`、`thread`、`search`、`profile` 或 `me`
- `author_name`
- `author_handle`
- `author_profile_url`
- `author_avatar_url`
- `text`
- `created_at_text`
- `created_at_iso`
- `tweet_type`: `tweet`、`reply`、`quote_tweet`、`repost`、`article`
- `reply_to`
- `quoted_tweet`
- `media`
- `links`
- `card`
- `article`
- `metrics`
- `social_context`
- `is_bookmarked`
- `raw_text_lines`
- `extraction_warnings`

## 类型识别

- 普通帖子：`tweet_type=tweet`
- 回复帖：识别 `回复 @...` / `Replying to @...`，写入 `reply_to`
- 引用帖：识别引用块或 `引用` marker，写入 `quoted_tweet`
- 转帖：识别 `转帖了` / `Reposted`
- 图片帖：`media[].kind=image`
- 视频帖：`media[].kind=video`，优先保存可读视频 URL 或 poster
- 文章帖：识别 X 文章 marker 或文章链接，写入 `article.title` / `article.preview_text` / `article.url`
- 外链卡片：写入 `card.url` / `card.title` / `card.description` / `card.image_url`

## 文章详情补全

文章帖不能只保存时间线预览。脚本会在收集完成后，对 `tweet_type=article` 或含 `article` 字段的帖子逐条处理：

1. 新标签页打开 `article.url`，没有该字段时打开 `source_url`。
2. 等待详情页出现正文，并滚动详情页直到正文块稳定，避免只获取前半段正文。
3. 按 X 文章 DOM 顺序抽取文本块和图片块，写入 `article.markdown_blocks`、`article.body_text`、`article.body_lines`、`article.links`、`article.detail_url`。
4. 每篇文章处理后关闭新标签页，回到原 Home 或 Bookmarks 标签页继续。

`content.md` 中的文章部分必须以可读 Markdown 正文输出，不要把整个 `article` 对象作为 JSON 塞进正文。文章图片应下载到同条帖子的 `media/` 目录，并按 `article.markdown_blocks` 的顺序插入 Markdown 中。完整结构化字段继续保存在 `metadata.json`。

## 失败处理

- 页面未登录或风控：停止任务，让用户在当前 Chrome 完成验证。
- 文章详情页跳转登录：记录 `article_detail_failed`，保留原预览数据。
- 字段缺失但仍可保存：写入 `extraction_warnings`，并汇总到 `failures.json`。
- 媒体下载失败：保留 metadata 中的原始 URL，并在终端输出失败原因。
- X DOM 变化：优先根据 `raw.txt`、`metadata.json` 和 `failures.json` 调整解析模板。

## 当前不做的操作

当前 X workflow 只做读取和下载。不执行发帖、回复、点赞、收藏、关注、拉黑、删除等写操作。后续若加入写操作，必须默认 dry-run，并由用户显式传 `--execute`。
