# OpenCLI 与当前 Action Browser Skill 站点支持差异

## 结论

当前 Action Browser skill 是少量站点的 ActionBook 实操工作流集合；OpenCLI 是更大范围的网站命令适配器集合。

- 当前 skill 明确支持 10 个站点/产品级工作流，加 1 个通用网页转 Markdown 能力。
- 在 OpenCLI 当前 manifest 中，按中国大陆/中国公司/中国常用网站产品口径统计到 60 个中国站点/产品适配器。
- 两者在中国站点上的重叠只有 7 个：`bilibili`、`boss`、`douban`、`douyin`、`weibo`、`xiaohongshu`、`zhihu`。
- 当前 skill 独有或明显更强的方向是 Feishu / Lark Drive 的目录盘点、下载、导出和校验；OpenCLI 当前 manifest 没有 `feishu` 站点。
- OpenCLI 的重叠站点通常命令更全，尤其覆盖账号写操作；当前 skill 更保守，默认只做只读、下载、导出、长任务恢复和中断处理。

## 核对来源

- 当前 skill：`SKILL.md` 的 References 表、`README.md` 的 Included Workflows、`references/*.md`、`scripts/*_workflow.py --help`。
- OpenCLI：`/Users/Vint/Repos/03_Project_Reference/03_Tools/opencli/cli-manifest.json`。
- OpenCLI 中国站点口径：按站点品牌、主域和常用产品属性人工归类；这不是 OpenCLI manifest 中的结构化字段。

## 当前 Skill 支持范围

| 站点 / 能力 | 脚本 | 当前支持 |
| --- | --- | --- |
| 小红书 | `scripts/xiaohongshu_workflow.py` | `note`、`search`、`feed`、`profile`、`me`、`favorites`、`likes`，支持 `view` / `download` 类流程 |
| X / Twitter | `scripts/x_workflow.py` | `home`、`bookmarks`、`tweet`、`thread`、`search`、`profile`、`me`，偏读取和下载 |
| 微博 | `scripts/weibo_workflow.py` | `post`、`profile`、`search`、`home`、`hot`、`feed`、`user`、`user-posts`、`me`、`comments`、`favorites` |
| 豆瓣 | `scripts/douban_workflow.py` | `search`、`top250`、`movie-hot`、`book-hot`、`subject`、`photos`、`download`、`marks`、`reviews` |
| 知乎 | `scripts/zhihu_workflow.py` | `hot`、`recommend`、`search`、`question`、`answer-detail`、`collections`、`collection`、`download` |
| YouTube | `scripts/youtube_workflow.py` | `search`、`video`、`transcript`、`comments`、`channel`、`playlist`、`feed`、`history`、`watch-later`、`subscriptions` |
| 抖音 | `scripts/douyin_workflow.py` | `profile`、`videos`、`drafts`、`collections`、`activities`、`hashtag`、`location`、`stats`、`user-videos` |
| Bilibili | `scripts/bilibili_workflow.py` | `hot`、`ranking`、`search`、`video`、`comments`、`dynamic`、`feed`、`history`、`me`、`following`、`user-videos`、`subtitle`、`summary` |
| BOSS 直聘 | `scripts/zhipin_workflow.py` | `filters`、`recommend`、`search`，只读职位与筛选数据 |
| 飞书 / Lark Drive | `scripts/feishu_workflow.py` | `inventory`、`download`、`verify`，覆盖云盘目录、文件下载、云文档导出和本地校验 |
| 通用网页 Markdown | `scripts/webpage_markdown.py` | `capture`、`current`、`convert` |

## OpenCLI 中国站点覆盖

OpenCLI 当前中国站点 / 产品适配器共 60 个：

`12306`、`1688`、`36kr`、`51job`、`aibase`、`baidu-scholar`、`bilibili`、`boss`、`chaoxing`、`cnki`、`ctrip`、`deepseek`、`dianping`、`douban`、`doubao`、`douyin`、`eastmoney`、`flomo`、`gitee`、`gov-law`、`gov-policy`、`hupu`、`jd`、`jianyu`、`jike`、`jimeng`、`ke`、`kimi`、`maimai`、`mubu`、`nowcoder`、`ones`、`powerchina`、`quark`、`qwen`、`rednote`、`sinablog`、`sinafinance`、`smzdm`、`taobao`、`tdx`、`ths`、`tieba`、`toutiao`、`uisdc`、`wanfang`、`wechat-channels`、`weibo`、`weixin`、`weread`、`weread-official`、`xianyu`、`xiaoe`、`xiaohongshu`、`xiaoyuzhou`、`xueqiu`、`youdao`、`yuanbao`、`zhihu`、`zsxq`。

边界项：`1point3acres`、`linux-do`、`v2ex` 是中文/华人社区或中文技术社区，是否算中国站点取决于口径；本轮没有计入 60 个主清单。`trae-cn`、`doubao-app`、`qoder` 更偏本地应用/客户端控制，也未按普通网站计入。

## 重叠站点功能差异

| 站点 | 当前 skill | OpenCLI 当前能力 | 主要差异 |
| --- | --- | --- | --- |
| Bilibili | 13 个只读入口：热门、排行、搜索、视频、评论、动态、历史、账号、关注、投稿、字幕、AI 总结 | 19 个命令，额外有 `login`、`whoami`、`feed-detail`、`download`、`favorite`、`comment` | OpenCLI 覆盖下载、收藏夹和评论写入；skill 暂不接入下载和账号写操作 |
| BOSS 直聘 | 3 个只读入口：筛选项、推荐职位、搜索职位 | 16 个命令，含职位详情、聊天、简历、统计、打招呼、交换联系方式、邀请、标记等 | OpenCLI 覆盖招聘沟通链路；skill 只做职位读取与筛选，不做沟通和账号动作 |
| 豆瓣 | 9 个入口，覆盖搜索、榜单、条目、图片、个人标记和影评 | 11 个命令，额外有 `login`、`whoami` | 能力基本接近；skill 更强调图片落盘、输出结构和异常页处理 |
| 抖音 | 9 个只读入口，覆盖创作者资料、作品、草稿、合集、活动、话题、位置、数据和公开用户视频 | 16 个命令，额外有 `login`、`whoami`、`search`、`draft`、`publish`、`delete`、`update` | OpenCLI 覆盖创作者发布、更新、删除；skill 刻意不做上传、发布、删除和更新 |
| 微博 | 11 个只读入口，覆盖单条、主页、搜索、首页、热搜、用户、评论、收藏等 | 13 个命令，额外有 `login`、`whoami`、`publish`、`delete` | OpenCLI 支持发布和删除；skill 当前不做写操作 |
| 小红书 | 7 个入口，支持单笔记、搜索、feed、主页、我的、收藏、点赞的 view/download | 20 个命令，含评论、通知、创作者数据、草稿、发布、删除等 | OpenCLI 覆盖创作者后台和写操作；skill 更偏内容下载、主页批量抓取和长任务恢复 |
| 知乎 | 8 个只读入口，覆盖热榜、推荐、搜索、问题、回答详情、收藏夹和专栏下载 | 16 个命令，额外有 `login`、`whoami`、`answer-comments`、`follow`、`like`、`favorite`、`comment`、`answer` | OpenCLI 覆盖评论、关注、点赞、收藏和回答发布；skill 当前只读和文章导出 |

## Skill 独有或更强的能力

- Feishu / Lark Drive：当前 skill 已有递归目录 inventory、附件下载、云文档导出、manifest 校验和下载恢复说明；OpenCLI 当前没有 `feishu` manifest 命令。
- 通用网页 Markdown：当前 skill 可对任意渲染网页做 `capture/current/convert`，更适合没有站点适配器时临时抽取内容。
- 长任务控制：当前 skill 有 `actionbook_run.py`，支持跟踪长流程和按 run id 停止，适合小红书主页下载、飞书批量下载等耗时任务。
- 浏览器会话恢复：当前 skill 对 session/tab 空状态、扩展连接、登录态和风控有统一操作规范。

## OpenCLI 明显领先的覆盖面

OpenCLI 已有而当前 skill 没有的中国站点包括：

- 电商/交易：`12306`、`1688`、`jd`、`taobao`、`xianyu`、`dianping`、`ctrip`、`ke`。
- 金融财经：`eastmoney`、`sinafinance`、`xueqiu`、`tdx`、`ths`。
- 知识教育：`cnki`、`wanfang`、`chaoxing`、`baidu-scholar`、`weread`、`weread-official`、`youdao`。
- AI 与工具：`deepseek`、`doubao`、`kimi`、`qwen`、`yuanbao`、`jimeng`、`gitee`、`ones`、`quark`、`flomo`、`xiaoe`。
- 内容社区：`36kr`、`aibase`、`hupu`、`jike`、`tieba`、`toutiao`、`weixin`、`wechat-channels`、`xiaoyuzhou`、`zsxq`、`smzdm`、`sinablog`、`uisdc`。
- 职场/政务/招投标：`51job`、`maimai`、`nowcoder`、`jianyu`、`powerchina`、`gov-law`、`gov-policy`。

## 设计取舍

当前 skill 不应简单复制 OpenCLI 的所有命令。两者定位不同：

- OpenCLI 适合把站点变成命令，命令面广，可以包含写操作。
- Action Browser skill 适合把真实浏览器中的可恢复任务流程固化，重点是登录态复用、可观察页面状态、批量下载、输出目录、失败恢复和中断停止。

因此新增站点时应优先选择高价值、长流程、强登录态、需要下载或需要恢复的场景；简单公开 API 查询不一定值得搬进 skill。

## 下一步计划

### P0：整理现有能力边界

1. 为当前 10 个站点补齐一张 `supported-sites` 索引表，放在 `SKILL.md` 或单独 reference 中。
2. 每个站点统一标注：只读、下载、写操作、是否需要登录态、默认输出目录、是否支持中断恢复。
3. 对重叠站点确认是否要继续保持“默认只读”策略；写操作必须单独走 `--execute` 和二次确认设计。

### P1：补 OpenCLI 重叠站点中的低风险缺口

优先补只读且价值明显的差异：

1. Bilibili：`feed-detail`、收藏夹只读。如果要做 `download`，先明确是否依赖 `yt-dlp` 和输出目录契约。
2. 知乎：`answer-comments`。
3. 小红书：`comments`、`notifications`、创作者只读数据。
4. 抖音：`search`，以及公开视频下载是否进入 skill 的下载契约。
5. BOSS 直聘：`detail`、`chatlist`、`chatmsg` 只读；继续禁止主动打招呼、交换联系方式、投递或发送消息。

### P2：新增中国站点优先队列

按 skill 定位，优先考虑这些 OpenCLI 已覆盖但当前 skill 缺失的网站：

1. `weixin`：公众号搜索、文章下载、草稿箱读取或创建草稿。价值高，但需要明确公众号后台写操作边界。
2. `weread`：书架、笔记、高亮、AI 大纲。适合知识归档。
3. `quark`：网盘列表、保存、移动、删除等。需要严格区分只读、保存和删除。
4. `jd` / `taobao` / `xianyu`：搜索、详情、评论、购物车状态。购物车和发布类操作必须默认禁用。
5. `eastmoney` / `xueqiu`：行情、公告、讨论和自选股只读。金融数据需标注非投资建议。
6. `deepseek` / `kimi` / `qwen` / `yuanbao`：聊天历史、发送、读取。需先统一 AI 聊天类 skill 输出和隐私边界。

### P3：建立差异同步机制

1. 写一个只读检查脚本：读取 OpenCLI `cli-manifest.json`，输出中国站点清单、当前 skill 覆盖清单和差异。
2. 将差异报告作为维护文档，而不是手动复制长列表。
3. 每次新增站点或命令后跑 `python3 -m py_compile scripts/<site>_workflow.py`、`--help`，并用一个低风险只读样例验证。

## 当前建议

先做 P0，然后选择 P1 中 2-3 个低风险只读缺口实现。推荐顺序：

1. 知乎 `answer-comments`：和现有知乎脚本最接近，范围小。
2. 小红书 `comments`：和现有 note/profile 下载强相关，实际价值高。
3. Bilibili `feed-detail`：补齐现有动态流的详情读取。

这三个都不引入账号写操作，验证成本相对可控。
