# GitHub ActionBook 操作说明

当前只启用两个只读能力：当前登录账号 `whoami`，以及公开 Trending 仓库 `trending`。`github-trending` 是 OpenCLI 的参考别名，归入 canonical `github` adapter。

## 常用命令

```bash
python3 scripts/adapters/github_workflow.py trending --since daily --count 10
python3 scripts/adapters/github_workflow.py trending --language python --since weekly --count 10
python3 scripts/adapters/github_workflow.py whoami \
  --task-id github-read --session <session> --tab <owned-tab>
```

Trending 使用公开页面读取，不需要登录。`whoami` 复用当前 Chrome 的 owned tab；未登录、MFA、验证码或风控会停止为 `needs_user_action` / `blocked`，不自动输入凭据。

## 输出

每次运行输出一个 Result Envelope，并在目标目录写入 `artifacts/<resource>.json`、`contract/summary.json` 和 `summary.md`。不提供 GitHub Issue、PR、仓库写入或代码修改能力。
