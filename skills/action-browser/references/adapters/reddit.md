# Reddit ActionBook 操作说明

Reddit 适配器参考 opencli 的同源 JSON 读取方式：浏览器 tab 负责复用当前登录态，脚本通过 Reddit 页面内的 `fetch` 读取 JSON。通用入口见 `../../SKILL.md`，脚本运行边界见 `../adapter-operation-boundaries.md`。

## 当前支持

只读能力：

- 热门与公共列表：`hot`、`frontpage`、`popular`、`subreddit`。
- 搜索：`search`，支持版块、排序和时间范围。
- 帖子详情：`read`，读取帖子和有限深度的评论树。
- 用户与版块：`user`、`user-posts`、`user-comments`、`subreddit-info`。
- 登录态读取：`home`、`saved`、`upvoted`、`subscribed`、`whoami`。

为了保持现有写入安全边界，暂不加入 opencli 的 `comment`、`reply`、`upvote`、`save`、`subscribe` 和 `login` 写流程。

## 常用命令

先领取 Reddit tab：

```bash
python3 scripts/actionbook_session.py acquire-tab \
  --task reddit-read \
  --session shared \
  --url https://www.reddit.com \
  --adopt-running-session \
  --json
```

读取热门、搜索和帖子：

```bash
python3 scripts/adapters/reddit_workflow.py hot view \
  --count 20 --task-id reddit-read --session <session> --tab <tab>

python3 scripts/adapters/reddit_workflow.py search view \
  --query "RAG chatbot" --count 15 \
  --task-id reddit-read --session <session> --tab <tab>

python3 scripts/adapters/reddit_workflow.py read view \
  --post "https://www.reddit.com/r/rag/comments/<post-id>/<slug>/" \
  --count 25 --depth 2 \
  --task-id reddit-read --session <session> --tab <tab>
```

读取版块、用户和登录态内容：

```bash
python3 scripts/adapters/reddit_workflow.py subreddit view \
  --name LangChain --count 20 \
  --task-id reddit-read --session <session> --tab <tab>

python3 scripts/adapters/reddit_workflow.py user-posts view \
  --username spez --count 15 \
  --task-id reddit-read --session <session> --tab <tab>

python3 scripts/adapters/reddit_workflow.py home view \
  --count 25 --task-id reddit-read --session <session> --tab <tab>
```

## 输出

默认写入 `assets/reddit/views/<command>/<timestamp>/`：

- `summary.json`：结构化结果。
- `summary.md`：可读摘要。
- `failures.json`：当前运行失败项，成功时为空数组。

列表帖子统一保留 `id`、`title`、`subreddit`、`author`、`score`、`comments`、`url`、`created_utc`、`selftext` 与 Reddit 媒体字段。`read` 额外输出 `type`、`depth`、`text`。

## 登录、风控与静态抓取边界

- `hot`、`frontpage`、`popular`、`search`、`subreddit`、公开用户信息通常可匿名读取。
- `home`、`saved`、`upvoted`、`subscribed`、`whoami` 需要当前 Chrome tab 已登录 Reddit。
- Reddit 返回 `401`、`403`、登录墙或非 JSON 页面时，脚本停止并报告错误；不要重试写操作。
- 只做公开页面归档且不需要登录态时，优先使用通用静态抓取路径；这个适配器用于复用浏览器登录态和 opencli 的 Reddit JSON 语义。

## 修改后验证

```bash
python3 -m py_compile scripts/adapters/reddit_workflow.py
python3 scripts/adapters/reddit_workflow.py --help
pytest -q tests/test_reddit_workflow.py
```
