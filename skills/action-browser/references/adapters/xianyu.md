# 闲鱼 ActionBook 操作说明

闲鱼站点域名为 `www.goofish.com`。本适配参考 OpenCLI 当前主分支的闲鱼实现，按本项目的 owned-tab、只读默认和文件化结果契约重新实现；没有复制 OpenCLI CLI 或运行时。

## OpenCLI 当前支持范围

截至 2026-07-17，OpenCLI 的闲鱼浏览器适配器支持：

- `search`：商品搜索，支持价格区间、省份和城市服务端筛选。
- `item`：商品详情。
- `inbox`：私信会话列表，可筛未读。
- `messages`：读取当前可见/最近消息，可用会话 ID 或收件箱序号定位。
- `chat` / `reply`：打开会话并发送消息。
- `publish`：发布闲鱼商品。

本项目暂只启用前四个只读入口。`chat`、`reply`、`publish` 以及登录/账号身份入口属于写入或账号状态能力，未在本脚本中启用。

参考资料：

- [OpenCLI 闲鱼适配文档](https://opencli.info/docs/adapters/browser/xianyu.html)
- [OpenCLI 闲鱼源码（参考基线 b0f84c99）](https://github.com/jackwener/opencli/tree/b0f84c99c93037add29e1c1b361f5f7094f52f74/clis/xianyu)

## 前置条件

1. Chrome 已运行，并在 `www.goofish.com` 完成登录。
2. ActionBook extension/daemon/session/tab 已按 `../../SKILL.md` 初始化。
3. 先由调用方领取 owned tab；脚本不会自动创建、替换或接管其它 tab。

```bash
python3 scripts/actionbook_session.py acquire-tab \
  --task xianyu-search \
  --session shared \
  --url "https://www.goofish.com/search" \
  --adopt-running-session --json
```

## 命令

所有命令都需要 `--task-id`、`--session`、`--tab`，并支持 `--output`。未传 `--output` 时写入 `assets/xianyu/views/<intent>/<timestamp>/`。

### 搜索商品

```bash
python3 scripts/adapters/xianyu_workflow.py search view \
  --query "机械键盘" --count 10 \
  --min-price 100 --max-price 800 --city 深圳 \
  --task-id xianyu-search --session <session-id> --tab <tab-id>
```

字段包括 `item_id`、`title`、`price`、`condition`、`brand`、`location`、`badge`、`want` 和 `url`。价格、地区筛选直接传给闲鱼的 MTop 搜索接口，不在本地二次过滤。

### 查看商品详情

```bash
python3 scripts/adapters/xianyu_workflow.py item view \
  --id 1040754408976 \
  --task-id xianyu-item --session <session-id> --tab <tab-id>
```

`--id` 也接受包含 `?id=`、`?itemId=` 或 `?item_id=` 的闲鱼链接。结果包含标题、描述、价格、成色、品牌、卖家、统计数字、商品链接和图片 URL。

### 查看私信收件箱

```bash
python3 scripts/adapters/xianyu_workflow.py inbox view \
  --count 20 --unread-only \
  --task-id xianyu-inbox --session <session-id> --tab <tab-id>
```

虚拟列表未暴露商品/用户 ID 时，`item_id`、`peer_user_id` 和 `url` 可能为空；这是页面当前可见 DOM 的真实缺口，不转换成伪 ID。

### 查看私信消息

优先使用明确的商品 ID 和对方用户 ID：

```bash
python3 scripts/adapters/xianyu_workflow.py messages view \
  --item-id 1038951278192 --user-id 3650092411 --count 50 \
  --task-id xianyu-messages --session <session-id> --tab <tab-id>
```

也可以按收件箱可见顺序定位：

```bash
python3 scripts/adapters/xianyu_workflow.py messages view \
  --rank 1 --count 50 \
  --task-id xianyu-messages-rank --session <session-id> --tab <tab-id>
```

消息结果只代表当前会话已加载且可见的最近消息；历史消息是否能继续加载由闲鱼页面决定，脚本不盲目滚动或伪造完整历史。

## 登录、验证码和风控

脚本检测到登录页、扫码登录、验证码、安全验证、异常访问、访问频繁或风险控制时返回 `LOGIN_REQUIRED`（退出码 3），保留当前 tab，等待用户在同一 Chrome 窗口人工处理后重试。不会读取 Cookie、Token、密码，也不会绕过风控。

## 输出契约

每次成功运行写入：

```text
<output>/summary.json
<output>/summary.md
<output>/failures.json
<output>/contract/summary.json
<output>/contract/progress.json
<output>/contract/artifacts/results.json
```

## 修改后验证

```bash
python3 -m py_compile scripts/adapters/xianyu_workflow.py
python3 scripts/adapters/xianyu_workflow.py --help
python3 scripts/adapters/xianyu_workflow.py search view --help
```

真实 smoke 需要用户当前 Chrome 登录态，建议先运行低风险搜索，再运行一个公开商品详情；私信读取只在用户明确要求时运行。
