# Taobao ActionBook 操作说明

本文记录淘宝网页在 ActionBook extension 模式下的站点专属经验。通用会话、等待、错误处理规则见 `../SKILL.md`。

## 支持范围

当前参考 OpenCLI Taobao 适配器，只启用只读入口：

- `search`: 搜索商品，支持默认、销量和价格排序。
- `detail`: 读取商品详情字段。
- `reviews`: 读取商品评价。
- `cart`: 读取当前登录账号购物车。此命令涉及个人登录态数据，仅在用户明确要求查看购物车时运行。
- `whoami`: 读取当前淘宝登录态可见账号信息。

暂不启用写操作：

- 加入购物车。
- 结算、购买、提交订单。
- 删除购物车商品、修改数量。
- 登录凭据、Cookie、Token、密码读取或导出。

## 常用命令

```bash
python3 scripts/adapters/taobao_workflow.py search view \
  --query "机械键盘" \
  --sort default \
  --count 10

python3 scripts/adapters/taobao_workflow.py detail view \
  --id 827563850178

python3 scripts/adapters/taobao_workflow.py reviews view \
  --id 827563850178 \
  --count 10

python3 scripts/adapters/taobao_workflow.py cart view --count 20

python3 scripts/adapters/taobao_workflow.py whoami view
```

所有命令都支持：

- `--session`: ActionBook session id，默认 `taobao-task`。
- `--tab`: 已确认存在的 ActionBook tab id。
- `--output`: 自定义输出目录。
- `--count`: 输出数量，按命令上限裁剪。

`search view` 额外支持：

- `--sort default|sale|price`

## 输出位置

默认输出在 `assets/taobao/` 下：

- `view`: `assets/taobao/views/<channel>/<timestamp>/`

每次运行写入：

- `summary.json`: 结构化结果数组。
- `summary.md`: 人类可读摘要。
- `failures.json`: 当前实现中为空数组。

## 登录和风控

脚本通过 `ActionBookSession` 使用 Chrome extension 模式，复用用户当前 Chrome 登录态。浏览器操作节奏参考 OpenCLI：

- 先打开淘宝首页并预热至少 2 秒。
- 搜索页跳转后等待至少 8 秒。
- 商品详情、评价、购物车页跳转后等待至少 6 秒。
- 搜索滚动延迟保持 2 秒级，购物车滚动延迟保持 1.5 秒级。

检测到以下状态时脚本停止并返回 `LOGIN_REQUIRED`：

- 淘宝登录页或扫码登录页。
- 安全验证、验证码、滑块、访问频繁或风险控制提示。
- 购物车或账号页要求登录。

遇到这些状态时，应在同一 Chrome 窗口完成登录或验证，然后重新运行命令。

## 数据边界

- 不调用 OpenCLI CLI，OpenCLI 仅作为行为参考。
- 不读取 `document.cookie`、`localStorage`、`sessionStorage`、Token 或密码。
- 搜索、详情和购物车以 DOM 抽取为主。
- 评价读取使用 OpenCLI 同类的页面内 JSONP 方式访问 `rate.tmall.com/list_detail_rate.htm`。
- malformed payload、登录页和风控页不会静默转换为空结果。

## 修改后验证

修改淘宝脚本或流程说明后，优先运行：

```bash
python3 -m unittest tests.test_jd_taobao_workflows
python3 -m py_compile scripts/adapters/taobao_workflow.py
python3 scripts/adapters/taobao_workflow.py --help
python3 scripts/adapters/taobao_workflow.py search view --query "机械键盘" --count 3
python3 scripts/adapters/taobao_workflow.py detail view --id 827563850178
```

淘宝商品可能被下架或地区不可用。若示例 ID 返回 `item unavailable or removed`，换一个当前可访问商品 ID 验证详情流程。

购物车 smoke 会读取个人登录态数据，只有用户明确批准时再运行：

```bash
python3 scripts/adapters/taobao_workflow.py cart view --count 5
```
