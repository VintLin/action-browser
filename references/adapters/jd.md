# JD ActionBook 操作说明

本文记录京东网页在 ActionBook extension 模式下的站点专属经验。通用会话、等待、错误处理规则见 `../SKILL.md`。

## 支持范围

当前参考 OpenCLI JD 适配器，只启用只读入口：

- `search`: 搜索商品。
- `item`: 读取商品增强详情，包括价格、店铺、规格、主图和详情图。
- `detail`: 读取商品紧凑详情字段。
- `reviews`: 读取商品评价。
- `cart`: 读取当前登录账号购物车。此命令涉及个人登录态数据，仅在用户明确要求查看购物车时运行。
- `whoami`: 读取当前京东登录态可见账号信息。

暂不启用写操作：

- 加入购物车。
- 结算、购买、提交订单。
- 删除购物车商品、修改数量。
- 登录凭据、Cookie、Token、密码读取或导出。

## 常用命令

```bash
python3 scripts/adapters/jd_workflow.py search view \
  --query "机械键盘" \
  --count 10

python3 scripts/adapters/jd_workflow.py item view \
  --sku 100291143898 \
  --images 50

python3 scripts/adapters/jd_workflow.py detail view \
  --sku 100291143898

python3 scripts/adapters/jd_workflow.py reviews view \
  --sku 100291143898 \
  --count 10

python3 scripts/adapters/jd_workflow.py cart view --count 20

python3 scripts/adapters/jd_workflow.py whoami view
```

所有命令都支持：

- `--session`: ActionBook session id，默认 `jd-task`。
- `--tab`: 已确认存在的 ActionBook tab id。
- `--output`: 自定义输出目录。
- `--count`: 输出数量，按命令上限裁剪。

## 输出位置

默认输出在 `assets/jd/` 下：

- `view`: `assets/jd/views/<channel>/<timestamp>/`

每次运行写入：

- `summary.json`: 结构化结果数组。
- `summary.md`: 人类可读摘要。
- `failures.json`: 当前实现中为空数组。

## 登录和风控

脚本通过 `ActionBookSession` 使用 Chrome extension 模式，复用用户当前 Chrome 登录态。浏览器操作节奏参考 OpenCLI：目标页打开后保留 5 秒级等待，滚动延迟保持 1.5 秒级，避免快速连续操作。

检测到以下状态时脚本停止并返回 `LOGIN_REQUIRED`：

- 京东登录页。
- 安全验证、身份验证或风险控制提示。
- 购物车或账号页要求登录。

遇到这些状态时，应在同一 Chrome 窗口完成登录或验证，然后重新运行命令。

## 数据边界

- 不调用 OpenCLI CLI，OpenCLI 仅作为行为参考。
- 不读取 `document.cookie`、`localStorage`、`sessionStorage`、Token 或密码。
- 京东购物车读取沿用 OpenCLI 的同页只读 `fetch(..., credentials: "include")` 和 DOM 兜底方式，但不修改购物车。
- malformed payload、登录页和风控页不会静默转换为空结果。

## 修改后验证

修改京东脚本或流程说明后，优先运行：

```bash
python3 -m py_compile scripts/adapters/jd_workflow.py
python3 scripts/adapters/jd_workflow.py --help
python3 scripts/adapters/jd_workflow.py search view --query "机械键盘" --count 3
python3 scripts/adapters/jd_workflow.py detail view --sku 100291143898
```

购物车 smoke 会读取个人登录态数据，只有用户明确批准时再运行：

```bash
python3 scripts/adapters/jd_workflow.py cart view --count 5
```
