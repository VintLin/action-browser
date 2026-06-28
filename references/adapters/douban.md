# 豆瓣 ActionBook 操作说明

本文记录豆瓣网页在 ActionBook extension 模式下的站点专属经验。通用会话、等待、错误处理规则见 `../SKILL.md`。

## 支持范围

当前对齐 OpenCLI 豆瓣只读能力：

- `search`: 搜索电影、图书或音乐。
- `top250`: 豆瓣电影 Top250。
- `movie-hot`: 豆瓣电影热门榜单。
- `book-hot`: 豆瓣图书热门榜单。
- `subject`: 读取电影或图书条目详情。
- `photos`: 获取电影海报/剧照图片列表。
- `download`: 下载电影海报/剧照图片，等价于 `photos download`。
- `marks`: 导出个人观影标记，需要登录态。
- `reviews`: 导出个人影评，需要登录态。

## 常用命令

```bash
python3 scripts/adapters/douban_workflow.py search view \
  --type movie \
  --keyword "流浪地球" \
  --count 10

python3 scripts/adapters/douban_workflow.py top250 view --count 25

python3 scripts/adapters/douban_workflow.py movie-hot view --count 20

python3 scripts/adapters/douban_workflow.py book-hot view --count 20

python3 scripts/adapters/douban_workflow.py subject view \
  --id 30382501 \
  --type movie

python3 scripts/adapters/douban_workflow.py subject view \
  --id 1007305 \
  --type book

python3 scripts/adapters/douban_workflow.py photos view \
  --id 30382501 \
  --type Rb \
  --count 20

python3 scripts/adapters/douban_workflow.py photos download \
  --id 30382501 \
  --type Rb \
  --count 5

python3 scripts/adapters/douban_workflow.py download \
  --id 30382501 \
  --type Rb \
  --count 5

python3 scripts/adapters/douban_workflow.py marks view \
  --status collect \
  --count 20

python3 scripts/adapters/douban_workflow.py reviews view \
  --count 20
```

所有命令都支持：

- `--session`: ActionBook session id，默认 `douban-task`。
- `--tab`: 已确认存在的 ActionBook tab id。
- `--output`: 自定义输出目录。
- `--count`: 输出数量。

## 输出位置

默认输出在 `assets/douban/` 下：

- `view`: `assets/douban/views/<channel>/<timestamp>/`
- `download`: `assets/douban/downloads/<channel>/<timestamp>/`

每次运行写入：

- `summary.json`: 结构化结果。
- `summary.md`: 人类可读摘要。
- `failures.json`: 当前实现中为空数组；下载失败会记录在对应图片行的 `status` / `error` 字段。

图片下载会额外写入：

- `<subject_id>/media/`: 图片文件。
- `<subject_id>/metadata.json`: 下载图片元数据和状态。

## 登录和风控

多数榜单、搜索、条目、图片列表可在未登录状态读取，但豆瓣可能将浏览器跳转到登录或安全验证页面。脚本检测到以下状态会停止：

- URL 包含 `sec.douban.com`。
- URL 包含 `accounts.douban.com`。
- 页面标题包含 `登录跳转`。
- 页面正文包含 `异常请求`。

`marks` 和 `reviews` 默认从 `https://movie.douban.com/mine` 自动识别当前账号 uid，因此需要 Chrome 中已经登录豆瓣。若未登录，应在同一 Chrome 窗口完成登录或验证，然后重新运行命令。

## 数据边界

- `subject --type movie` 读取电影详情页的标题、年份、评分、类型、导演、主演、地区、片长、简介、封面和 URL。
- `subject --type book` 读取图书详情页的标题、作者、译者、出版社、出版年、页数、装帧、定价、丛书、ISBN、评分、简介、封面和 URL。
- `photos` 和 `download` 仅面向 `movie.douban.com` 电影条目图片页。
- `marks` 和 `reviews` 当前面向 `movie.douban.com/people/<uid>/...`，不处理图书或音乐标记。

## 修改后验证

修改豆瓣脚本或流程说明后，优先运行：

```bash
python3 -m py_compile scripts/adapters/douban_workflow.py
python3 scripts/adapters/douban_workflow.py --help
python3 scripts/adapters/douban_workflow.py search view --type movie --keyword "流浪地球" --count 3
python3 scripts/adapters/douban_workflow.py subject view --id 30382501 --type movie
python3 scripts/adapters/douban_workflow.py photos download --id 30382501 --type Rb --count 2
```
