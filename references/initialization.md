# Actionbook 初始化

本文用于在本地没有 Actionbook，或 Actionbook 环境不完整时，从零安装并完成基础配置。

## 目录

- [0. 适用范围和边界](#0-适用范围和边界)
- [1. 前置检查](#1-前置检查)
- [2. 安装 CLI](#2-安装-cli)
- [3. 运行初始化配置](#3-运行初始化配置)
- [4. 本地浏览器模式](#4-本地浏览器模式)
- [5. Chrome 插件模式](#5-chrome-插件模式)
- [6. 插件模式验证](#6-插件模式验证)
- [7. API Key](#7-api-key)
- [8. 初始化完成标准](#8-初始化完成标准)
- [9. Agent 执行顺序](#9-agent-执行顺序)
- [10. 干净电脑完成标准](#10-干净电脑完成标准)

## 0. 适用范围和边界

本文面向完全没有 Actionbook 配置的电脑。Agent 应按顺序检查并安装：

1. Node.js 和 npm
2. Chrome 或 Chromium 系浏览器
3. Actionbook CLI
4. Actionbook 基础配置
5. 可选的 Chrome 插件模式

有些步骤需要用户手动完成：

- 安装 Chrome Web Store 插件
- 在 Chrome 中确认扩展权限
- 登录目标网站、处理验证码或安全验证
- 输入 API Key、账号、密码等敏感信息

Agent 不应自动读取、保存或提交用户的账号密码、Cookie、Token、API Key。

## 1. 前置检查

先检查本机是否已经有 Actionbook：

```bash
which actionbook
actionbook --version
```

如果 `which actionbook` 没有输出，或 `actionbook --version` 报错，按后续步骤安装。

检查 Node.js：

```bash
node --version
npm --version
```

Actionbook 官方 npm 安装方式要求 Node.js `>= 18`。

如果 `node` 或 `npm` 不存在，先安装 Node.js。

macOS 推荐方式：

```bash
brew install node
```

如果没有 Homebrew，先让用户安装 Homebrew，或使用 Node.js 官方安装包：

```text
https://nodejs.org/
```

安装后重新检查：

```bash
node --version
npm --version
```

检查 Chrome：

```bash
test -d "/Applications/Google Chrome.app" && echo "Chrome installed"
```

如果 Chrome 不存在，需要先安装 Google Chrome：

```text
https://www.google.com/chrome/
```

本地模式通常需要可用的 Chromium 系浏览器。插件模式必须使用安装了 Actionbook 插件的 Chrome profile。

## 2. 安装 CLI

推荐使用官方 npm 包安装：

```bash
npm install -g @actionbookdev/cli
```

升级到最新版本：

```bash
npm install -g @actionbookdev/cli@latest
```

验证安装：

```bash
actionbook --version
```

如果安装后找不到 `actionbook`，检查 npm 全局 bin 是否在 `PATH` 中：

```bash
npm config get prefix
echo "$PATH"
```

临时修复示例：

```bash
export PATH="$(npm config get prefix)/bin:$PATH"
```

长期修复应写入当前 shell 的配置文件，例如 `~/.zshrc` 或 `~/.bashrc`。

如果本机使用 Homebrew 管理 Actionbook，也可以检查：

```bash
brew list --versions actionbook
brew upgrade actionbook
```

不要同时混用多个来源的 `actionbook`。如果 `which actionbook` 指向 Homebrew，则优先用 Homebrew 维护；如果指向 npm 全局目录，则优先用 npm 维护。

干净电脑推荐只使用 npm 方式，除非该机器已经明确使用 Homebrew 维护 Actionbook。

## 3. 运行初始化配置

首次安装后运行：

```bash
actionbook setup
```

如果需要非交互式配置为本地浏览器模式：

```bash
actionbook setup --browser local --non-interactive
```

如果需要使用当前 Chrome 登录态和插件模式：

```bash
actionbook setup --browser extension --non-interactive
```

配置文件位置：

```bash
~/.actionbook/config.toml
```

常见配置示例：

```toml
version = 1

[api]
base_url = "https://api.actionbook.dev"

[browser]
mode = "local"
headless = false
profile_name = "actionbook"
```

## 4. 本地浏览器模式

本地模式适合普通自动化任务。它会启动独立 Chrome 会话，不依赖用户当前 Chrome 登录态。

配置为本地模式：

```bash
actionbook setup --browser local --non-interactive
```

启动测试：

```bash
actionbook browser start --session init-check --open-url "https://example.com" --json
actionbook browser snapshot --session init-check --tab t1 --json
```

清理测试会话：

```bash
actionbook browser close --session init-check --json
```

## 5. Chrome 插件模式

插件模式适合需要使用用户当前 Chrome 登录态、Cookie、已登录账号的任务。

如果任务不需要用户当前登录态，优先使用本地模式。插件模式依赖 Chrome 扩展和用户 profile，排查成本更高。

先配置为插件模式：

```bash
actionbook setup --browser extension --non-interactive
```

安装 Chrome 插件的推荐方式是 Chrome Web Store：

```text
https://chromewebstore.google.com/detail/actionbook/bebchpafpemheedhcdabookaifcijmfo
```

Agent 可以打开该链接，但添加扩展通常需要用户在 Chrome 中确认。

安装后确认 Chrome 扩展管理页中 Actionbook 已启用：

```text
chrome://extensions/
```

如果 Web Store 安装不可用，可以使用本地 fallback 包：

```bash
actionbook extension install --force --json
actionbook extension path --json
```

然后在 Chrome 中执行：

1. 打开 `chrome://extensions/`
2. 开启开发者模式
3. 点击“加载未打包的扩展程序”
4. 选择 `actionbook extension path` 输出的目录

本地 fallback 包只负责把扩展文件放到本机目录，不会自动把扩展安装进 Chrome。必须在 Chrome 扩展页手动加载。

## 6. 插件模式验证

启动一个测试会话：

```bash
actionbook browser start --session extension-check --open-url "https://example.com" --json
```

检查插件连接：

```bash
actionbook extension status --json
actionbook extension ping --json
```

正常状态应包含：

```json
{
  "bridge": "listening",
  "extension_connected": true
}
```

如果状态是 `bridge: not_listening`，先执行任意 browser 命令触发 daemon 启动：

```bash
actionbook browser start --session extension-check --open-url "https://example.com" --json
```

如果仍未连接，检查：

- Chrome 是否正在运行
- Chrome 扩展页中 Actionbook 是否启用
- 是否安装了正确扩展 ID：`bebchpafpemheedhcdabookaifcijmfo`
- `~/.actionbook/config.toml` 中 `browser.mode` 是否为 `extension`

## 7. API Key

Actionbook 可在没有 API Key 的情况下运行，但可能受到公共限额限制。

如果有 API Key，可以写入环境变量：

```bash
export ACTIONBOOK_API_KEY="your_api_key"
```

不要把 API Key 写入项目文档、脚本或仓库。

## 8. 初始化完成标准

初始化完成应满足：

- `actionbook --version` 正常输出版本号
- `actionbook setup` 已执行完成
- `~/.actionbook/config.toml` 存在
- 本地模式下可以打开 `https://example.com`
- 插件模式下 `actionbook extension status --json` 显示 `bridge=listening` 且 `extension_connected=true`

完成后再执行具体网页自动化任务。

## 9. Agent 执行顺序

给 Agent 的推荐执行顺序：

```bash
# 1. 检查基础命令
which node || true
which npm || true
which actionbook || true

# 2. 如缺少 Node.js，先安装 Node.js
# macOS 可用 Homebrew；没有 Homebrew 时让用户安装 Node.js 官方包

# 3. 安装 Actionbook CLI
npm install -g @actionbookdev/cli@latest

# 4. 验证 CLI
actionbook --version

# 5. 默认配置为本地模式
actionbook setup --browser local --non-interactive

# 6. 测试本地模式
actionbook browser start --session init-check --open-url "https://example.com" --json
actionbook browser snapshot --session init-check --tab t1 --json
```

如果任务明确需要 Chrome 当前登录态，再追加插件模式配置：

```bash
actionbook setup --browser extension --non-interactive
actionbook extension install --force --json
actionbook extension path --json
```

然后让用户在 Chrome 中安装或启用 Actionbook 插件，再执行：

```bash
actionbook browser start --session extension-check --open-url "https://example.com" --json
actionbook extension status --json
```

## 10. 干净电脑完成标准

完全没有配置的电脑，完成初始化后应满足：

- `node --version` 正常输出，版本不低于 `18`
- `npm --version` 正常输出
- `which actionbook` 能找到 CLI
- `actionbook --version` 正常输出
- `~/.actionbook/config.toml` 存在
- 本地模式可以打开并读取 `https://example.com`
- 需要插件模式时，Chrome 已安装 Actionbook 插件并启用
- 插件模式下 `bridge=listening` 且 `extension_connected=true`

若任一项不满足，应先修复初始化，不要进入正式网页自动化。
