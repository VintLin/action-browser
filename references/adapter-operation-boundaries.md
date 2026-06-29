# 适配脚本运行边界

本文定义 `scripts/adapters/*.py` 的通用运行边界。它约束的是所有站点适配脚本共享的浏览器运行方式、session/tab 生命周期、等待策略、失败处理与停止策略。站点范围、命令目录、字段语义和站点特有禁区，仍以对应的 `references/adapters/<site>.md` 为准。

## 能做什么

- 复用调用方给定的 `--session` / `--tab`，或在非 scheduler 场景下通过 `scripts/actionbook_session.py` 获取可用 tab 后继续。
- 在当前任务 tab 内做读取、滚动、抽取、导出、验证等站点文档已声明的业务动作。
- 在确有必要的站点流程里临时打开详情 tab、预览 tab 或下载辅助 tab，但必须把它们视为当前任务的临时资源，而不是新的长期运行上下文。
- 遇到登录、验证码、MFA、风险控制或账号校验时暂停，把当前 Chrome 窗口留给用户手动处理。
- 长时间抓取、批量导出、可能需要中断/恢复的任务，通过 `scripts/actionbook_run.py` 启动。

## 不能做什么

- 不能在业务 workflow 里直接 open-code 原生 `actionbook browser start/new-tab/list-tabs/close-tab` 作为常规生命周期控制；这些边界统一走 `scripts/actionbook_session.py`。
- 不能用页面 JS 直接关闭 tab，例如 `window.close()`；关闭 tab 必须走 helper，并在关闭后确认目标 tab 已消失。
- 不能隐式切走到别的 tab、不能 silent adopt 其他 session、不能把一个失败的 tab 悄悄替换成新 tab 继续跑。
- 不能把固定 `sleep` 当成主要等待策略；应优先等待 URL、标题、关键容器、列表项数量、详情区块或其他显式页面状态。
- 不能在检测到登录页、验证码页、MFA 页、风险控制页后继续盲点或盲重试。
- 不能在未获站点文档明确授权时执行写操作。默认适配脚本应视为只读；若未来某站点支持写操作，必须在对应站点文档中单独声明，并提供显式执行开关。

## 生命周期约束

- `session` 是浏览器容器；`tab` 是任务页上下文。一个适配脚本运行只拥有它当前工作的主 tab，以及它自己临时打开的附属 tab。
- 主 tab 承担任务主流程；临时 tab 只用于局部读取、详情补全、预览确认或站点文档明确允许的辅助动作，不得长期保留。
- 每次打开临时 tab 后，必须：
  1. 记录返回的真实 `tab_id`
  2. 在该 tab 内完成局部动作
  3. 通过 helper 关闭该 tab
  4. 复查 tab 已消失后再处理下一项
- 如果 workflow 作为共享 session 的一个子任务运行，只能关闭自己打开的临时 tab，不能顺手关闭整个 session。
- 如果 workflow 通过 `actionbook_run.py` 以独占任务方式启动，任务结束后是否关闭 session 由调用方决定；业务流程默认不要擅自关闭用户可能还要复用的主 session。
- 如果适配脚本面向 scheduler 合约运行，应严格绑定调用方给定的 `--session` / `--tab`，不得在运行中偷偷 rebuild session、adopt 别的 session、或迁移到未租赁的新 tab。

## 等待与校验约束

- 页面 ready 不能只看“页面里出现了某类通用节点”；必须结合当前 URL、标题、关键容器或站点上下文判断是否真的到了目标页面。
- 每次关键交互后都要验证结果，例如：导航是否完成、目标详情是否真的打开、展开动作是否真正影响了目标对象、列表是否回到预期状态。
- 固定 sleep 只适合极短的动画缓冲。超过 1 秒的等待如果没有显式状态校验，通常都应视为脆弱实现。

## 失败与停止约束

- 同一对象的局部补全失败时，应记录可恢复的 warning 或 failure 证据，不要在 workflow 内递归重开新 tab 自愈。
- 若当前 tab 丢失、session 不可达、或页面跳回登录/风控，应直接把控制权交还给上层，而不是在 workflow 内私自重建运行态。
- scheduler 场景下，等待用户处理登录、验证码、MFA 或风险控制时，应落明确的 `waiting_user` 进度状态，而不是只抛异常退出。
- 用户要求停止时，优先停止 `actionbook_run.py` 跟踪的 run；不要假设中断 agent turn 会自动结束底层进程。
