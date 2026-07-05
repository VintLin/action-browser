# Actionbook 状态检查

本文用于每次使用 Actionbook 前做最小状态检查，避免在浏览器、daemon、插件或 session 状态异常时直接开始任务。

如果任务使用 Chrome 插件模式，优先直接跑通用 bootstrap：

```bash
python3 scripts/actionbook_session.py ensure \
  --session task-check \
  --url "https://example.com" \
  --json
```

这个脚本会优先复用同名健康 session，并返回最终可用的 `session_id` / `tab_id`。显式传入的 `--session` 不会再偷偷 adopt 到别的 session。只有在需要手工排错时，再按下面的细分检查逐步执行。

默认规则：

- 任务流程里的 session/tab 生命周期统一走 `scripts/actionbook_session.py`
- 原生 `actionbook browser start/new-tab/list-tabs/close-tab` 只用于诊断、对照实验、或 helper 自己的底层实现排查

如果怀疑 extension / session 状态存在抖动，先跑一轮诊断脚本，把 `start -> status -> list-tabs` 的真实输出落盘：

```bash
python3 scripts/diagnostics/actionbook_diagnose.py --session-prefix diag --url "https://example.com" --delays 0,1,3
```

如果怀疑是低概率抖动，直接做批量 smoke：

```bash
python3 scripts/diagnostics/actionbook_diagnose.py --session-prefix diag --url "https://example.com" --delays 0,1,3 --runs 5
```

优先看报告里的 `summary`：

- `extension_connected_after_start`
- `session_visible_direct`
- `session_visible_in_fresh_shell`
- `tabs_visible_direct`

批量模式再看：

- `start_ok_runs`
- `session_visible_direct_runs`
- `session_visible_in_fresh_shell_runs`

## 目录

- [0. 缺失时的处理原则](#0-缺失时的处理原则)
- [1. 基础检查](#1-基础检查)
- [2. 检查 daemon 和 session](#2-检查-daemon-和-session)
- [3. 本地模式检查](#3-本地模式检查)
- [4. 插件模式检查](#4-插件模式检查)
- [5. 打开目标站点前检查](#5-打开目标站点前检查)
- [6. 常见异常判断](#6-常见异常判断)
- [7. 最小检查脚本](#7-最小检查脚本)
- [8. 开始任务标准](#8-开始任务标准)

## 0. 缺失时的处理原则

如果检查发现以下任一项缺失，应先执行 `initialization.md`，不要继续当前任务：

- `node` 不存在
- `npm` 不存在
- `actionbook` 不存在
- `~/.actionbook/config.toml` 不存在
- 本地模式无法打开 `https://example.com`
- 插件模式下 Chrome 未安装或未启用 Actionbook 插件

状态检查只负责确认环境是否可用，不负责跳过缺失依赖。

## 1. 基础检查

检查 CLI 是否可用：

```bash
node --version
npm --version
which actionbook
actionbook --version
```

检查配置文件：

```bash
test -f ~/.actionbook/config.toml && sed -n '1,120p' ~/.actionbook/config.toml
```

重点看：

- `[browser] mode = "local"`：独立浏览器模式
- `[browser] mode = "extension"`：Chrome 插件模式
- `headless = false`：需要人工登录或查看页面时建议关闭 headless

## 2. 检查 daemon 和 session

列出当前 session：

```bash
actionbook browser list-sessions --json
```

检查指定 session：

```bash
actionbook browser status --session task-check --json
```

如果返回 `SESSION_NOT_FOUND`，说明该 session 不存在或 daemon 已重启。需要重新启动：

```bash
actionbook browser start --session task-check --open-url "about:blank" --json
```

不要假设之前的 tab id 仍有效。session 重建后应重新 `snapshot`。

如果 `list-sessions` 里能看到 session，但 `tabs_count` 为 `0`，或 `list-tabs` 返回空数组，这也是失效状态。不要继续复用这个空 session；直接关闭并重建。

另外，不要把一次 `browser start` 的成功直接当成“session 已可复用”。至少再跑一条独立命令确认同一个 session 仍然存在，例如：

```bash
actionbook browser start --session local-check --open-url "https://example.com" --json
actionbook browser status --session local-check --json
actionbook browser list-tabs --session local-check --json
```

如果第二条或第三条命令已经报 `SESSION_NOT_FOUND`，说明当前 ActionBook 运行态还不具备“shared session + leased tabs”的调度前提，先修复 extension / daemon 持久性，不要继续往调度器里塞任务。

## 3. 本地模式检查

如果使用本地模式，执行：

```bash
actionbook browser start --session local-check --open-url "https://example.com" --json
actionbook browser list-tabs --session local-check --json
actionbook browser title --session local-check --tab "<real-tab-id>" --json
actionbook browser url --session local-check --tab "<real-tab-id>" --json
actionbook browser snapshot --session local-check --tab "<real-tab-id>" --json
```

正常标准：

- `browser start` 返回 `ok: true`
- `mode` 为 `local`
- `url` 能读取到目标页面
- `snapshot` 能返回页面结构

检查完成后可以关闭测试会话：

```bash
actionbook browser close --session local-check --json
```

## 4. 插件模式检查

如果使用 Chrome 插件模式，先检查插件状态：

```bash
test -d "/Applications/Google Chrome.app" && echo "Chrome installed"
actionbook extension status --json
actionbook extension ping --json
```

正常标准：

```json
{
  "bridge": "listening",
  "extension_connected": true
}
```

如果显示 `bridge: not_listening`，先启动一个浏览器命令触发 daemon 和 bridge：

```bash
actionbook browser start --session extension-check --open-url "https://example.com" --json
```

然后再次检查：

```bash
actionbook extension status --json
```

如果仍未连接，检查 Chrome 扩展页：

```text
chrome://extensions/
```

确认：

- Actionbook 插件已安装
- Actionbook 插件已启用
- 插件 ID 是 `bebchpafpemheedhcdabookaifcijmfo`
- Chrome 顶部没有阻止调试或扩展运行的提示

如果插件不存在，不要先跳到浏览器商店版本，也不要先假设 CLI 当前捆绑扩展可用。先按 skill 自带固定 zip 修复：

```bash
cd "<skill-dir>"
unzip -o actionbook-extension-v0.5.0.zip
```

然后在 `chrome://extensions/`：

1. 开启开发者模式
2. 点击“加载未打包的扩展程序”
3. 选择 `<skill-dir>/actionbook-extension-v0.5.0`

当前应确认该目录里的扩展版本是 `0.5.0`，再重试 `actionbook extension status --json`。

这里也要明确：agent 不能直接把扩展安装进 Chrome。若当前线程里的 agent 无法操作用户的 Chrome 扩展页，必须明确提示用户自己完成这 3 个点击步骤，再继续后续检查。

## 5. 打开目标站点前检查

建议先通过 helper 获取固定 session 和真实 tab id：

```bash
export ACTIONBOOK_SESSION_ID="task-1"

python3 scripts/actionbook_session.py ensure \
  --session "$ACTIONBOOK_SESSION_ID" \
  --url "https://example.com" \
  --json
python3 scripts/actionbook_session.py list-tabs --session "$ACTIONBOOK_SESSION_ID" --json
```

这里不要先写死 `ACTIONBOOK_TAB_ID=t1`。先从 `ensure` 返回值或 `list-tabs` 结果里确认真实 tab id，再继续后面的命令。

如果任务需要并发页面，不要默认新建多个 extension session。先验证单个 session 是否健康，再在该 session 内分配多个 tab。

如果需要手工复查目标站点状态：

```bash
actionbook browser wait network-idle --session "$ACTIONBOOK_SESSION_ID" --tab "<real-tab-id>" --timeout 15000 --json
actionbook browser snapshot --session "$ACTIONBOOK_SESSION_ID" --tab "<real-tab-id>" --json
```

如果页面结构变化、跳转到登录页、出现验证码或风控页，先暂停自动化，不要继续点击或抓取。

## 6. 常见异常判断

`SESSION_NOT_FOUND`：

- session 不存在
- daemon 重启后丢失状态
- 上一次命令启动的会话没有保留下来

处理：

```bash
actionbook browser list-sessions --json
actionbook browser start --session task-check --open-url "about:blank" --json
```

如果 session 存在但 `list-tabs` 为空，也按同一类问题处理：先关闭，再重建。

`browser start` / `actionbook_session.py ensure` 返回成功，但下一条命令立刻 `SESSION_NOT_FOUND`、`list-tabs: []`、`EXTENSION_NOT_CONNECTED`、`bridge: not_listening`，或 `extension_connected: false`：

- 不要把第一次成功当成可用 session；先停止真实业务发送或下载。
- 先停本任务的 tracked run，不要直接关 Chrome 登录态：

```bash
python3 scripts/actionbook_run.py list --active
python3 scripts/actionbook_run.py stop --id <run-id>
ps aux | grep -E 'actionbook_run.py|_workflow.py' | grep -v grep
```

- 如果没有活跃 workflow，重启 ActionBook daemon，再重新 bootstrap：

```bash
pkill -f 'actionbook __daemon' || true
python3 scripts/actionbook_session.py ensure --session task-check --url "https://example.com" --json
actionbook extension status --json
python3 scripts/actionbook_session.py list-tabs --session task-check --json
```

- 如果仍然抖动，先落盘诊断，不要继续调度任务到这个 session：

```bash
python3 scripts/diagnostics/actionbook_diagnose.py --session-prefix diag --url "https://example.com" --delays 0,1,3
```

只有报告里 `extension_connected_after_start`、`session_visible_in_fresh_shell`、`tabs_visible_direct` 都为 `true`，才继续站点 workflow。长任务继续用 `scripts/actionbook_run.py run --id <run-id> --cwd "$PWD" --replace -- ...` 启动，让 workflow 自己创建新 session，并保留后续可中断记录。

如果新建命名 session 稳定失败，但 `list-sessions` 里已有健康的 extension session，先显式复用，不要直接改回原生命令：

```bash
python3 scripts/actionbook_session.py ensure \
  --session task-check \
  --url "https://example.com" \
  --adopt-running-session \
  --json
```

这个开关只在当前命名 session 无法创建或恢复时，允许 helper 复用别的 running extension session；默认仍保持“显式 session 不跨 session adopt”。

如果 `status` 能读到旧 session，但 `list-tabs` 或 `close` 长时间无返回，不要把这个 session 当作可恢复容器。中断卡住的 CLI 命令后，按上面的 daemon 重启和重新 bootstrap 流程处理。

`CDP_NODE_NOT_FOUND`：

- 页面结构已变化
- 旧 snapshot ref 失效

处理：

```bash
actionbook browser snapshot --session task-check --tab t1 --json
```

`CDP_NOT_INTERACTABLE`：

- 元素不可见
- 被弹窗遮挡
- 需要滚动到视口

处理：

```bash
actionbook browser scroll down 500 --session task-check --tab t1 --json
actionbook browser snapshot --session task-check --tab t1 --json
```

`CDP_NAV_TIMEOUT`：

- 页面加载慢
- 网络不稳定
- 目标站点阻塞

处理：

```bash
actionbook browser wait network-idle --session task-check --tab t1 --timeout 30000 --json
actionbook browser url --session task-check --tab t1 --json
actionbook browser title --session task-check --tab t1 --json
```

`bridge: not_listening`：

- Actionbook daemon 没有启动 bridge
- 还没有执行 browser 命令
- 插件模式配置不完整

处理：

```bash
actionbook browser start --session extension-check --open-url "https://example.com" --json
actionbook extension status --json
```

`extension_connected: false`：

- Chrome 插件未启用
- 插件未连接到 bridge
- Chrome 当前 profile 没有安装 Actionbook 插件
- daemon 刚重启，Chrome 端还没有重新连上 bridge

处理：

- 打开 `chrome://extensions/`
- 确认 Actionbook 插件已启用
- 确认当前 Chrome profile 里安装的是 skill 自带 `actionbook-extension-v0.5.0/`
- 重新执行 `actionbook browser start`
- 再执行 `actionbook extension status --json`，确认 `bridge: listening` 且 `extension_connected: true`

## 7. 最小检查脚本

可以在任务开始前执行：

```bash
set -e

SESSION_ID="${ACTIONBOOK_SESSION_ID:-task-check}"
TARGET_URL="${1:-https://example.com}"

actionbook --version
actionbook browser start --session "$SESSION_ID" --open-url "$TARGET_URL" --json
actionbook browser list-sessions --json
actionbook browser list-tabs --session "$SESSION_ID" --json
actionbook browser url --session "$SESSION_ID" --tab "<real-tab-id>" --json
actionbook browser title --session "$SESSION_ID" --tab "<real-tab-id>" --json
actionbook browser snapshot --session "$SESSION_ID" --tab "<real-tab-id>" --json >/tmp/actionbook-snapshot.json
```

如果使用插件模式，再追加：

```bash
actionbook extension status --json
actionbook extension ping --json
```

## 8. 开始任务标准

只有满足以下条件后再开始自动化：

- CLI 可用，版本号正常
- 配置模式符合任务需要
- session 已启动
- 目标 tab 可读取 `url` 和 `title`
- `snapshot` 成功
- 插件模式下 bridge 已监听且插件已连接
- 没有登录、验证码、风控或错误页阻塞

未满足时先修复状态，不要继续执行抓取或批处理。
