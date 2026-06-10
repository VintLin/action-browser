# 知乎 ActionBook 操作说明

本文记录知乎网页在 ActionBook extension 模式下的站点专属经验。通用会话、等待、错误处理规则见 `../SKILL.md`。

## 支持范围

当前对齐 OpenCLI 知乎只读能力：

- `hot`: 知乎热榜。
- `recommend`: 知乎首页推荐，需要登录态更稳定。
- `search`: 搜索回答、文章、问题或全部类型。
- `question`: 读取问题下的回答。
- `answer-detail`: 读取单个回答完整内容。
- `collections`: 读取当前账号收藏夹列表，需要登录态。
- `collection`: 读取指定收藏夹内容，需要权限。
- `download`: 导出知乎专栏文章为 Markdown，可选下载图片。

暂不启用账号写操作：

- `follow`
- `like`
- `favorite`
- `comment`
- `answer`

这些操作会关注、点赞、收藏、评论或发布回答。若后续需要，应单独设计 `dry-run` / `--execute` 和显式确认边界。

## 常用命令

```bash
python3 scripts/zhihu_workflow.py hot view --count 10

python3 scripts/zhihu_workflow.py recommend view --count 10

python3 scripts/zhihu_workflow.py search view \
  --query "agent" \
  --type all \
  --count 10

python3 scripts/zhihu_workflow.py question view \
  --id 123456789 \
  --count 5

python3 scripts/zhihu_workflow.py answer-detail view \
  --id "https://www.zhihu.com/question/123456789/answer/987654321"

python3 scripts/zhihu_workflow.py collections view --count 20

python3 scripts/zhihu_workflow.py collection view \
  --id 83283292 \
  --count 20

python3 scripts/zhihu_workflow.py download \
  --url "https://zhuanlan.zhihu.com/p/998877" \
  --download-images
```

所有 `view` 命令都支持：

- `--session`: ActionBook session id，默认 `zhihu-task`。
- `--tab`: 已确认存在的 ActionBook tab id。
- `--output`: 自定义输出目录。
- `--count`: 输出数量。

## 输出位置

默认输出在 `assets/zhihu/` 下：

- `view`: `assets/zhihu/views/<channel>/<timestamp>/`
- `download`: `assets/zhihu/downloads/download/<timestamp>/`

每次运行写入：

- `summary.json`: 结构化结果。
- `summary.md`: 人类可读摘要。
- `failures.json`: 当前实现中为空数组。

文章下载会额外写入：

- `article.md`: 固定文件名 Markdown。
- `<文章标题>.md`: 便于直接查看的标题文件。
- `article.json`: 文章元数据、HTML 和图片下载状态。
- `media/`: 使用 `--download-images` 时写入图片。

## 登录和风控

知乎热榜通常可读，但推荐流、搜索、问题回答、回答详情、收藏夹和专栏文章更依赖浏览器登录态和 Cookie。脚本检测到以下状态会停止：

- URL 或正文包含登录页。
- 页面提示安全验证、验证码、异常流量或反爬验证。

遇到这些状态时，应在同一 Chrome 窗口完成登录或验证，然后重新运行命令。

## 数据边界

- `hot` 使用 `api/v3/feed/topstory/hot-lists/total`。
- `recommend` 使用 `api/v3/feed/topstory/recommend` 分页。
- `search` 使用 `api/v4/search_v3`，支持 `all`、`answer`、`article`、`question`。
- `question` 使用 `api/v4/questions/<id>/answers`，默认每个回答正文截断到 200 字；`--max-content 0` 返回完整文本。
- `answer-detail` 使用 `api/v4/answers/<id>`，默认返回完整文本。
- `collections` 会先读取 `api/v4/me?include=url_token`，因此需要当前账号登录。
- `download` 只处理 `zhuanlan.zhihu.com/p/<id>` 或 `article:<id>`。

## 修改后验证

修改知乎脚本或流程说明后，优先运行：

```bash
python3 -m py_compile scripts/zhihu_workflow.py
python3 scripts/zhihu_workflow.py --help
python3 scripts/zhihu_workflow.py hot view --count 3
python3 scripts/zhihu_workflow.py search view --query "agent" --type all --count 3
python3 scripts/zhihu_workflow.py collections view --count 1
```
