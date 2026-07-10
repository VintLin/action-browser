# 微博工作流

> 所有 `*_workflow.py` 示例都假定当前 task 已通过 `acquire-tab` 领取 tab，并设置 `ACTIONBOOK_TASK_ID`、`ACTIONBOOK_SESSION_ID`、`ACTIONBOOK_TAB_ID`；也可在命令中显式传入同名参数。并行 task 不得共享同一组环境变量。

本文用于在 `action-browser` skill 中操作微博。流程依赖 ActionBook Chrome extension 模式和用户当前 Chrome 登录态。

通用入口见 `../../SKILL.md`，适配脚本运行边界见 `../adapter-operation-boundaries.md`。

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

如果 ActionBook、Chrome extension、session 或 tab 状态不明确，先按 `../status-check.md` 检查。若环境缺失，按 `../initialization.md` 初始化。遇到登录、验证码、短信验证、安全验证或风控页时，保留当前 Chrome 窗口，让用户手动完成后再继续。

## 统一入口

```bash
python3 scripts/adapters/weibo_workflow.py --help
```

所有浏览器操作都走同一个 ActionBook session/tab。默认输出在 `assets/weibo/` 下。

当前支持只读能力：`hot`、`search`、`feed`、`user`、`user-posts`、`me`、`post`、`comments`、`favorites`、`home`、`profile`。`publish` 和 `delete` 属于账号写操作，第一版不启用。

批量或长时间的 `feed`、`search`、`user-posts`、`favorites`、`download` 任务必须通过通用运行器启动，方便用户说“中断/停止”时按 run id 停掉实际脚本：

```bash
python3 scripts/actionbook_run.py run \
  --id weibo-user-posts \
  --cwd "$PWD" \
  -- \
  python3 scripts/adapters/weibo_workflow.py user-posts download \
    --profile-url "https://weibo.com/u/2619244577" \
    --count 100
```

## Hot

读取微博热搜：

```bash
python3 scripts/adapters/weibo_workflow.py hot view \
  --count 30
```

默认输出：

```text
assets/weibo/views/hot/yyyyMMdd-HHmmss/
```

## Feed

读取推荐或关注信息流：

```bash
python3 scripts/adapters/weibo_workflow.py feed view \
  --type for-you \
  --count 30

python3 scripts/adapters/weibo_workflow.py feed download \
  --type following \
  --count 30
```

`--type` 可选 `for-you` 和 `following`。

## 单条微博

读取单条微博 URL：

```bash
python3 scripts/adapters/weibo_workflow.py post view \
  --url "https://weibo.com/<uid>/<bid>"

python3 scripts/adapters/weibo_workflow.py post download \
  --id "<idstr-or-mblogid>"
```

默认输出：

```text
assets/weibo/views/post/yyyyMMdd-HHmmss/
assets/weibo/downloads/post/yyyyMMdd-HHmmss/
```

## Profile

读取用户主页前 N 条微博：

```bash
python3 scripts/adapters/weibo_workflow.py profile view \
  --profile-url "https://weibo.com/u/<uid>" \
  --count 30

python3 scripts/adapters/weibo_workflow.py profile download \
  --profile-url "https://weibo.com/u/<uid>" \
  --count 30
```

`profile` 是页面 DOM 流程，适合按主页视觉顺序抽取。需要更稳定的 API 读取、日期过滤或是否包含转发时，优先用 `user-posts`。

## User 与 Me

读取用户资料：

```bash
python3 scripts/adapters/weibo_workflow.py user view \
  --id "2619244577"

python3 scripts/adapters/weibo_workflow.py user view \
  --profile-url "https://weibo.com/u/2619244577"
```

读取当前登录账号资料：

```bash
python3 scripts/adapters/weibo_workflow.py me view
```

## User Posts

按 uid、昵称或主页 URL 读取用户微博，支持日期过滤和是否包含转发：

```bash
python3 scripts/adapters/weibo_workflow.py user-posts view \
  --id "2619244577" \
  --count 30

python3 scripts/adapters/weibo_workflow.py user-posts download \
  --profile-url "https://weibo.com/u/2619244577" \
  --start 2026-05-01 \
  --end 2026-05-19 \
  --include-retweets \
  --count 30
```

## Search

读取搜索结果：

```bash
python3 scripts/adapters/weibo_workflow.py search view \
  --keyword "关键词" \
  --count 30

python3 scripts/adapters/weibo_workflow.py search download \
  --keyword "关键词" \
  --count 30
```

微博搜索使用 `https://s.weibo.com/weibo?q=...`，这是微博网页的稳定搜索入口；若页面跳转到登录、验证码或安全验证，保持当前 Chrome 窗口让用户处理后重试。

## Home

读取首页当前可见信息流：

```bash
python3 scripts/adapters/weibo_workflow.py home view --count 30
python3 scripts/adapters/weibo_workflow.py home download --count 30
```

`home` 是页面 DOM 流程，读取当前首页可见卡片。需要明确推荐流或关注流时，优先用 `feed --type for-you|following`。

## Comments

读取单条微博评论。推荐传入数字 `mid/idstr`，也可从已读取的 `summary.json` 里取 `mid`：

```bash
python3 scripts/adapters/weibo_workflow.py comments view \
  --id "5300256976933486" \
  --count 20
```

## Favorites

读取当前登录账号收藏：

```bash
python3 scripts/adapters/weibo_workflow.py favorites view \
  --count 20

python3 scripts/adapters/weibo_workflow.py favorites download \
  --count 20
```

## 输出文件

`view` 只写汇总文件：

```text
summary.json
summary.md
failures.json
```

`download` 写汇总文件，并为每条微博创建目录：

```text
summary.json
summary.md
failures.json
001_post_image_author_mid/
002_repost_text_author_mid/
  metadata.json
  content.md
  raw.txt
  media/
```

单条目录名：

```text
<index>_<post_type>_<content_flags>_<author>_<mid-or-id>/
```

`post_type` 当前为 `post` 或 `repost`。`content_flags` 由 `text`、`image`、`video`、`link`、`topic` 组合而成。

## API 与 DOM 边界

- `hot`、`feed`、`user`、`user-posts`、`me`、`post`、`comments` 优先使用微博登录态下的 `/ajax/...` 接口。
- `post` 会在 API 标记长文时补读 `/ajax/statuses/longtext`。
- `home`、`profile`、`favorites` 使用当前页面 DOM 卡片抽取，适合视觉顺序读取。
- `search` 当前使用搜索结果页面 DOM 抽取。

## Payload 字段

`summary.json` 是 `WeiboPayload[]`，每条包含：

- `weibo_id`
- `mid`
- `source_url`
- `source_page`: `post`、`profile`、`search` 或 `home`
- `author_name`
- `author_id`
- `author_profile_url`
- `author_avatar_url`
- `text`
- `created_at_text`
- `source_device`
- `post_type`: `post` 或 `repost`
- `reposted_weibo`
- `media`
- `links`
- `topics`
- `mentions`
- `metrics`
- `raw_text_lines`
- `extraction_warnings`

字段边界：

- `text` 只保留微博正文，尽量排除转发、评论、点赞、关注、展开、广告等界面文本。
- `media[].kind=image` 只保留正文图片，排除头像、表情、平台图标和小尺寸占位图。
- `media[].kind=video` 优先保存可见播放器的 `src/currentSrc` 或封面 `poster`。如果页面只暴露 `blob:`，该值只适合当前浏览器会话排查，不作为长期直链。
- `reposted_weibo` 保存页面中可读到的被转发微博作者、正文、链接和图片，不主动递归打开原微博。
- `topics` 保存正文中的 `#话题#`。
- `mentions` 保存正文中的 `@用户名`。
- `metrics` 从按钮文案或可见数字中尽力抽取 `reposts`、`comments`、`likes`。
- `created_at_text` 保留页面原始发布时间，不做时区换算。

## 登录与风控

微博经常出现登录弹窗、验证码、短信验证、账号安全验证或访问频率限制。处理规则：

- 不关闭当前 Chrome 窗口。
- 不切换到无登录态浏览器。
- 不反复重建 session 规避验证。
- 暂停自动化，让用户在当前 Chrome 窗口完成验证。
- 用户确认后，用同一个 session/tab 继续运行。

## DOM 约束

微博桌面版和移动版 DOM 差异较大。脚本采用宽松候选：

- 桌面版优先识别 `article`、`[mid]`、`[data-mid]`、`[action-type="feed_list_item"]`、`.card-wrap`。
- 移动版优先识别 `.m-panel.card`、`.weibo-og`、`.weibo-rp`、`[data-card]`。
- 图片会按尺寸和 URL 排除头像、表情、icon、badge。
- 若页面只出现登录或验证内容，脚本应报出当前 URL 与页面标题，不写空成功结果。

第一版不主动抓取评论楼层，也不做语义分类、数据库写入或项目台账更新。
