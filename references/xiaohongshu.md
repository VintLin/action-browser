# 小红书 ActionBook 操作说明

本文记录小红书网页在 ActionBook extension 模式下的站点专属经验。通用会话、等待、错误处理规则见 `../SKILL.md`。

如果用户要处理多个搜索结果或多个博主帖子，优先使用脚本：

建议先跑一次通用 bootstrap，拿到当前可用的 `session_id` / `tab_id`，再决定是否手工带上 `--tab`：

```bash
python3 scripts/actionbook_session.py \
  --session xhs-task \
  --url "https://www.xiaohongshu.com" \
  --json
```

长时间下载、博主主页全量抓取、批量导出必须通过通用运行器启动，方便用户说“中断/停止”时按 run id 停掉实际脚本：

```bash
python3 scripts/actionbook_run.py run \
  --id xhs-profile-download \
  --cwd "$PWD" \
  -- \
  python3 scripts/xiaohongshu_workflow.py profile download \
    --session xhs-profile-download \
    --tab "<real-tab-id>" \
    --profile-url "https://www.xiaohongshu.com/user/profile/..." \
    --count all \
    --output-dir "$PWD/资源" \
    --folder-template "{author}/{index:03d}_{title}" \
    --media-layout media
```

停止当前下载：

```bash
python3 scripts/actionbook_run.py stop --id xhs-profile-download
python3 scripts/actionbook_run.py list --active
```

普通短任务或小样本验证可以直接调用 `xiaohongshu_workflow.py`：

```bash
python3 scripts/xiaohongshu_workflow.py note view \
  --url "https://www.xiaohongshu.com/explore/..."

python3 scripts/xiaohongshu_workflow.py note download \
  --url "https://www.xiaohongshu.com/explore/..."

python3 scripts/xiaohongshu_workflow.py search view \
  --keyword "关键词" \
  --count 20

python3 scripts/xiaohongshu_workflow.py search view \
  --keyword "关键词" \
  --entry ai \
  --include-ai-answer \
  --count 20

python3 scripts/xiaohongshu_workflow.py search download \
  --keyword "关键词" \
  --count 20

python3 scripts/xiaohongshu_workflow.py feed view \
  --count 30

python3 scripts/xiaohongshu_workflow.py feed download \
  --count 30

python3 scripts/xiaohongshu_workflow.py profile view \
  --profile-url "https://www.xiaohongshu.com/user/profile/..." \
  --count all

python3 scripts/xiaohongshu_workflow.py profile download \
  --profile-url "https://www.xiaohongshu.com/user/profile/..." \
  --count 30 \
  --output-dir "$PWD" \
  --folder-template "{author}/{index:03d}_{title}" \
  --media-layout media

python3 scripts/xiaohongshu_workflow.py me view \
  --count 30

python3 scripts/xiaohongshu_workflow.py me download \
  --count 30

python3 scripts/xiaohongshu_workflow.py favorites view \
  --profile-url "https://www.xiaohongshu.com/user/profile/..." \
  --count 30

python3 scripts/xiaohongshu_workflow.py favorites download \
  --profile-url "https://www.xiaohongshu.com/user/profile/..." \
  --count 30

python3 scripts/xiaohongshu_workflow.py likes view \
  --profile-url "https://www.xiaohongshu.com/user/profile/..." \
  --count 30

python3 scripts/xiaohongshu_workflow.py likes download \
  --profile-url "https://www.xiaohongshu.com/user/profile/..." \
  --count 30
```

脚本输出默认在 `assets/xiaohongshu/` 下：

- `summary.md`：每条帖子的标题、作者、日期、来源、标签、图片数、评论数、正文摘录。
- `summary.json`：结构化帖子数据。
- `ai_answer.json` / `ai_answer.md`：仅在 `search --entry ai --include-ai-answer` 时写入，记录点点 AI 回答、总结笔记数、状态和来源 URL。
- `failures.json`：失败记录。当前无失败时写入空数组。
- `profile.json`：主页元数据，`profile` 与 `me` 模式产生。
- `view` 默认写入 `assets/xiaohongshu/views/<channel>/...`。
- `download` 默认写入 `assets/xiaohongshu/downloads/<channel>/...`。
- `download` 模式会为每条帖子保存 `content.md`、`content.txt`、`raw.txt`、`metadata.json`、`media/img-*` 图片。
- 下载目录名采用 `<index>_<note|video>_<media_flags>_<author>_<note_id>`，便于从文件名判断图文、视频、评论配图等类型。
- 如需指定每条笔记的目录格式，传 `--folder-template`。模板相对 `--output-dir` 生效，支持字段：`index`、`index3`、`author`、`title`、`note_id`、`type`、`media_flags`。例如用户要求 `/博主名称/00x_笔记标题/` 时，使用 `--output-dir "$PWD" --folder-template "{author}/{index:03d}_{title}"`。
- 如需控制图片保存位置，传 `--media-layout media|flat`。默认 `media` 会保存为 `media/img-*`；`flat` 会把 `img-*` 和 `content.md`、`metadata.json` 放在同一个笔记目录下。
- `feed` 读取发现/推荐流；`me` 读取当前登录账号自身发布的帖子；`favorites` 读取当前登录用户或指定 `--profile-url` 的收藏 tab；`likes` 读取当前登录用户或指定 `--profile-url` 的赞过/点赞 tab。四者都是只读流程，不点击单帖点赞或收藏按钮。

`view` 指结构化汇总和正文摘录，不下载图片，不调用模型做语义归纳。如果用户需要模型归纳，先用脚本生成 `summary.json`，再基于该文件单独总结。

`note` 入口用于已知单篇笔记 URL，适合用户给出 `https://www.xiaohongshu.com/explore/...` 时直接读取或下载，不需要先走搜索或博主主页。

小红书现在会对裸 `https://www.xiaohongshu.com/explore/<note_id>` 直接访问返回 `error_code=300031`。`note` 入口遇到裸 URL 时不会直接 `goto`，会优先在当前 tab 中按 `note_id` 点击可见卡片来触发站内跳转；因此仅有裸 `note_id` 时，应先打开搜索、推荐流或博主主页并确保目标卡片可见，再带同一个 `--session/--tab` 调用 `note view/download`。若当前页没有可见卡片，则需要提供从搜索页、推荐页或详情页复制出的完整 URL，保留 `xsec_token`、`xsec_source`、`source` 等查询参数。

`me` 入口会从当前登录态识别个人主页，然后复用博主主页处理逻辑读取自己的帖子。若自动识别失败，应先打开小红书首页并确认左侧“我”入口可用。

`favorites` 与 `likes` 属于登录态个人数据读取。若未传 `--profile-url`，脚本会尝试从当前登录态识别个人主页；识别失败时应显式传入自己的主页 URL。若页面提示收藏或点赞内容不可见、需要登录、验证码或风控，保持当前 Chrome 窗口，让用户手动处理后再重试。

脚本在未传 `--tab` 时会自动探测当前可用 tab；如果遇到“session 存在但没有 tab”或指定 tab 已失效，会先尝试在当前 session 补开新 tab，再尝试复用其他健康的扩展 session，最后才重建 session。首次调用优先直接运行脚本，不要先手工假设 `t1` 可用。

## 固定数据格式

小红书详情弹窗的帖子数据，统一按下列 schema 输出到 `summary.json` 与每条帖子的 `metadata.json`：

```json
{
  "note_id": "帖子 ID",
  "source_url": "详情实际来源 URL",
  "candidate_href": "列表页点击时的候选 URL",
  "author": "用户名称",
  "author_avatar_url": "用户头像 URL",
  "author_profile_url": "用户主页 URL",
  "title": "帖子标题",
  "content": "帖子正文",
  "tags": ["帖子标签1", "帖子标签2"],
  "date_text": "帖子发布时间文本",
  "image_urls": ["帖子图片 URL 1", "帖子图片 URL 2"],
  "comment_image_urls": ["评论图片 URL 1"],
  "video_url": "视频地址，可能是 blob: 或真实媒体地址",
  "video_cover_url": "视频封面地址",
  "comment_count": 12,
  "comments": [
    {
      "author": "评论用户名称",
      "avatar_url": "评论用户头像 URL",
      "content": "评论正文",
      "date_text": "评论时间文本",
      "image_urls": ["该评论自己的图片 URL"]
    }
  ],
  "is_video": false
}
```

字段边界：

- `image_urls` 只保留帖子内容图，不包含作者头像、评论头像、评论配图、平台图标。
- `comment_image_urls` 只保留评论区图片，不混入帖子主图。
- `video_url` 为尽力提取值。当前优先取页面 `video.currentSrc/src`。若页面播放器只暴露 `blob:`，则该值仅在当前浏览器会话内可用，不是长期可复用直链。
- `video_cover_url` 优先取 `video.poster`；若为空，再尝试从视频区域图片里兜底提取。
- `content` 只保留帖子正文，不混入 `关注`、`评论`、`发送`、页码、评论计数等界面文本。
- `tags` 优先取详情正文区域的标签节点，再补正文中的 `#标签` 文本。
- `comments` 只取详情弹窗当前已渲染、当前可见 DOM 中可读到的评论。默认最多保留前 20 条，不主动滚动加载更多楼层。
- `comments[].image_urls` 只保留该条评论自己的图片。
- `comment_count` 优先取页面显示的总评论数；读不到时退化为 `comments` 当前抽取条数。
- `date_text` 保留页面原始发布时间文本，不做时区换算和标准化。

## 1. 打开页面

推荐入口：

```bash
actionbook browser start \
  --mode extension \
  --session xhs-task \
  --open-url "https://www.xiaohongshu.com/explore" \
  --timeout 30000
```

启动后检查：

```bash
actionbook extension status --json
actionbook browser list-tabs --session xhs-task --json
actionbook browser url --session xhs-task --tab <real-tab-id> --json
actionbook browser title --session xhs-task --tab <real-tab-id> --json
```

可操作页面通常满足：

- URL 为 `https://www.xiaohongshu.com/explore` 或具体笔记详情 URL。
- 标题包含 `小红书`。
- `snapshot` 中能看到 `推荐`、`发现`、搜索框或笔记列表项。

插件模式任务开始前可能显示：

```json
{"bridge":"not_listening","extension_connected":false}
```

这不一定是故障。先用 `browser start --mode extension --session ...` 触发 bridge，再检查 extension 状态。不要因为初始 `not_listening` 直接重启 daemon；重启 daemon 可能清空 session，并让已连接的 Chrome extension 暂时断开。只有 `browser start` 触发后仍无法连接，或反复出现 `SESSION_NOT_FOUND` / session 列表异常时，再按 `../SKILL.md` 的 Daemon Recovery 处理。

## 2. 推荐页帖子

进入推荐页后先取快照：

```bash
actionbook browser snapshot --session xhs-task --tab t1
```

推荐流里的帖子通常会同时出现图片链接、标题链接、作者链接和点赞区域。打开详情时优先选择标题链接；图片链接有时会因为加载、遮罩或媒体状态导致点击超时。

建议顺序：

1. 优先点击标题链接。
2. 标题链接不可用时，再尝试图片链接。
3. 不要点击作者链接，否则会进入用户主页。
4. 不要点击点赞区域，除非任务明确要求点赞。

普通点击建议使用 `5000-8000ms` 上限。点击超时后应换入口或刷新 ref，不要直接把每步 timeout 拉到 `30000ms`。

## 3. 搜索流程

完整搜索流程：

1. 打开搜索结果 URL：`https://www.xiaohongshu.com/search_result/?keyword=<urlencoded_keyword>&source=web_search_result_notes`。
2. 等待搜索结果页稳定。
3. 验证页面仍处于搜索上下文。
4. 按 `.note-item` 收集候选，数量不够时滚动加载。
5. 逐条打开详情，抽取正文和图片链接。
6. 按用户要求执行 `view` 或 `download`。

小红书新版首页的可见输入框可能是“点点 ai”入口，placeholder 为“搜索或输入任何问题”，处于推荐流布局。不要把首页 `/explore` 内已有 `.note-item` 视为搜索结果；否则会混入推荐流数据。

搜索结果页必须满足以下可验证状态：

- URL 包含 `/search_result`。
- 页面标题为 `<关键词> - 小红书搜索`。
- `#search-input` 或 `input.search-input` 的值等于关键词。
- 页面出现搜索 tab：`全部 / 图文 / 视频 / 用户 / 筛选 / 综合`。
- 详情页来源 URL 包含 `xsec_source=pc_search` 和 `source=web_search_result_notes`。

如果搜索结果页加载不稳定，重新打开上述搜索结果 URL；不要回到新版首页 textarea 里派发 Enter 事件。

点点 AI 搜索入口：

```bash
python3 scripts/xiaohongshu_workflow.py search view \
  --keyword "北京周末去哪玩" \
  --entry ai \
  --include-ai-answer \
  --count 5
```

AI 入口打开 `https://www.xiaohongshu.com/search_result_ai?keyword=<urlencoded_keyword>&source=web_explore_feed`。页面会展示普通 `.note-item` 搜索结果，同时在右侧展示点点 AI 回答。AI 回答抽取边界：

- AI 面板：`.ai-chat-section`。
- 完成态消息：`.ai-message.ai-message-finished`。
- 回答正文：多个 `.markdown-block` 拼接。
- 总结笔记数：从 `ai总结<数量>篇笔记生成` 解析。
- 输出文件：`ai_answer.json` 与 `ai_answer.md`。

搜索输入推荐用真实事件：

```bash
actionbook browser eval "(() => {
  const keyword = '关键词';
  const candidates = [
    document.getElementById('search-input'),
    ...document.querySelectorAll('input.search-input, input[placeholder*=\"搜索\"], input[type=\"search\"]')
  ].filter(Boolean);
  const input = candidates.find(el => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return el.getAttribute('aria-hidden') !== 'true' &&
      String(el.getAttribute('tabindex') || '') !== '-1' &&
      style.display !== 'none' &&
      style.visibility !== 'hidden' &&
      style.pointerEvents !== 'none' &&
      rect.width > 0 &&
      rect.height > 0;
  }) || candidates[0] || null;
  if (!input) return false;
  input.focus();
  input.value = keyword;
  input.dispatchEvent(new InputEvent('input', { bubbles: true, data: keyword, inputType: 'insertText' }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  for (const type of ['keydown', 'keypress', 'keyup']) {
    input.dispatchEvent(new KeyboardEvent(type, { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
  }
  return true;
})()" --session xhs-task --tab t1 --json
```

候选抽取优先读取 `.note-item` 内的 `/explore/<note_id>` 链接；如果在博主页，也要识别 `/user/profile/<profile_id>/<note_id>`。保存 `note_id`、标题、href、卡片绝对位置，用于后续重新定位。

## 4. 博主主页、收藏与点赞流程

完整博主主页流程：

1. 打开 `https://www.xiaohongshu.com/user/profile/<profile_id>`。
2. 等待 URL 仍在目标 profile，且页面出现昵称或 `.note-item`。
3. 通过 `window.__INITIAL_STATE__.user` 读取 `profileId`、`nickname`、`desc`、`redId`、可见笔记数。
4. 按当前可视 `.note-item` 批次收集帖子引用。
5. 数量不够时滚动，直到达到 `--count`，或 `--count all` 场景下连续多轮没有新增。
6. 处理每条帖子前先确认仍在目标 profile；如果不在，重新 `goto` profile 并等待主页恢复。
7. 优先用收集到的 `note_id + abs_top` 在附近重新定位卡片；找不到时从主页顶部开始按标题或 `note_id` 滚动查找。
8. 打开详情后抽取正文和图片链接。
9. 关闭详情后确认回到目标 profile；如果关闭后仍停在详情态或跳走，重新恢复 profile 上下文，再处理下一条。

收藏和点赞读取复用博主主页的列表采集与详情抽取能力：

1. 打开 `https://www.xiaohongshu.com/user/profile/<profile_id>`。
2. 点击 `收藏` 或 `赞过/点赞/喜欢` tab。
3. 等待 `.note-item` 出现。
4. 按 `--count` 和 `--max-scrolls` 收集可见候选。
5. 逐条打开详情，复用同一套 `extract_payload` 字段。
6. 输出 `summary.json`、`summary.md`、`failures.json`，下载模式额外输出每帖目录。

收藏/点赞 tab 只做只读浏览。不要点击单帖详情里的点赞、收藏、关注等写操作按钮。

博主页不要只按卡片 index 点击。小红书瀑布流会重排或复用节点，推荐用评分定位：

- `note_id` 命中同卡片链接，权重最高。
- `profile_href` 或 `explore_href` 命中次之。
- 标题完全一致作为辅助。
- 当前位置 `top/left` 只作为校验，不单独作为身份。

博主页全量抓取时，不要在收集完所有帖子后持续复用旧 DOM 节点或旧可视位置。详情页关闭可能通过 `Escape`、关闭按钮或 `history.back()` 回到不同滚动位置；瀑布流也会懒加载和重排。可靠策略是“每条帖子处理前恢复 profile 上下文，再按身份重新定位当前卡片”。

## 5. 详情弹窗

点击帖子后，小红书桌面网页通常以遮罩弹窗展示详情，同时 URL 会变成 `/explore/<note_id>...`。

确认详情已打开：

```bash
actionbook browser url --session xhs-task --tab t1 --json
actionbook browser title --session xhs-task --tab t1 --json
```

更可靠的详情就绪判定：

- `#noteContainer` 存在。
- `.note-detail-mask` 存在。
- 页面 iframe 的 `src` 包含 `/explore/`。
- 当前 URL 包含 `/explore/`。

抽取数据时把范围限制在 `#noteContainer`。若详情在 iframe 中，先遍历可访问 iframe 的 `contentDocument`。正文要排除 `关注`、`评论`、`发送`、页码、评论数等界面文本。图片只保留 `xhscdn.com` 内容图，排除头像和平台图标。

有些详情页标题节点为空，但卡片标题可用。连续处理时应保留候选卡片标题，并在详情标题为空时用卡片标题兜底；否则 `summary.md` 可能只显示 `note_id`。

详情弹窗中当前已固化识别的字段：

- 帖子主图：`image_urls`
- 帖子正文：`content`
- 用户头像：`author_avatar_url`
- 用户名称：`author`
- 用户主页：`author_profile_url`
- 帖子标题：`title`
- 帖子标签：`tags`
- 帖子发布时间：`date_text`
- 评论图片：`comment_image_urls`
- 视频地址：`video_url`
- 视频封面：`video_cover_url`
- 帖子评论：`comments`
- 帖子评论总数：`comment_count`

## 5.1 实操补充

这次实操里，下面几条需要固化到使用习惯里：

- 优先从推荐流或搜索流点击进入详情弹窗，再抽取。直接 `goto` 详情 URL 时，页面结构有时会退化，导致头像、主图、评论区不完整。
- 从详情关闭回列表后，不要复用旧 ref。必须重新 `snapshot`，否则很容易遇到 `REF_STALE`，或者点击命中了旧节点。
- 博主页批量处理时，不要只按一次性收集到的 `top/left` 点击。旧位置只能用来快速滚到附近；真正点击前必须重新在当前 DOM 中按 `note_id`、`profile_href/explore_href` 或标题匹配卡片。
- 评论图片应按 DOM 区域区分，不要只按 `xhscdn.com` 统一收集。当前可用规则是：
  `#noteContainer .comment-picture img` 视为评论图片；
  `#noteContainer .note-slider-img img`、`.swiper-slide img`、`.carousel-container img`、`.note-image-box img` 视为帖子主图。
- 评论区里还会混入头像和正文 emoji。抽取评论图片时要排除 `avatar`、`fe-platform`、正文 emoji 资源。

关闭详情优先用 Escape：

```bash
actionbook browser press Escape --session xhs-task --tab t1 --timeout 5000
actionbook browser url --session xhs-task --tab t1 --json
```

关闭成功后，URL 应回到：

```text
https://www.xiaohongshu.com/explore
```

关闭详情建议顺序：

1. 点击关闭按钮：`button.close-icon`、`.close-icon`、`[aria-label="关闭"]`、`[title="关闭"]`。
2. 派发 `Escape` 的 `keydown/keyup`。
3. 执行 `window.history.back()`。

每一步后都要确认详情已关闭。不要在 `#noteContainer`、`.note-detail-mask` 或 `/explore/` 仍存在时继续点击旧卡片。

## 6. 登录、风控与不可用页

遇到登录、验证码、安全验证或内容无法加载时：

- 保持当前 Chrome、session 和 tab。
- 让用户在同一个窗口中手动处理。
- 用户确认后重新 `snapshot`。
- 不要切换浏览器模式或重建会话。

常见阻塞信号：

- `/login`
- `登录探索更多内容`
- `website-login/error`
- `error_code=300012`
- `IP存在风险`
- `安全限制`

常见不可用页：

- `/404?source=/404/sec_`
- `error_code=300031`
- `Sorry, This Page Isn't Available Right Now.`
- `你访问的页面不见了`

## 7. 验证方式

修改小红书脚本或流程说明后，优先做小样本验证：

```bash
python3 scripts/xiaohongshu_workflow.py search view \
  --keyword "汉服" \
  --count 5 \
  --output-dir /tmp/xhs-search-check

python3 scripts/xiaohongshu_workflow.py profile view \
  --profile-url "https://www.xiaohongshu.com/user/profile/..." \
  --count 5 \
  --output-dir /tmp/xhs-profile-check
```

需要验证下载链路时，用最小下载样本：

```bash
python3 scripts/xiaohongshu_workflow.py search download \
  --keyword "汉服" \
  --count 1 \
  --output-dir /tmp/xhs-download-check
```

验证标准：

- `summary.json` 中帖子数达到请求数量，或日志说明候选不足。
- 每条记录应有 `source_url`、正文或标题、`image_urls` 数量。
- 博主页模式应生成 `profile.json`。
- 下载模式应生成每帖目录、`content.md`、`content.txt`、`raw.txt`、`metadata.json`；`--media-layout media` 有图片时应生成 `media/img-*`，`--media-layout flat` 有图片时应生成同级 `img-*`。
- 详情关闭后不能停留在 `/explore/` 详情态。
- 验证完成后检查 `actionbook browser list-sessions --json`，必要时关闭测试 session。
