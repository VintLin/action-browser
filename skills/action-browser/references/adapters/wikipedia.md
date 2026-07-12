# Wikipedia ActionBook 操作说明

当前只启用 OpenCLI Reference Baseline 中的五个公开只读能力：`page`、`random`、`search`、`summary`、`trending`。

## 常用命令

```bash
python3 scripts/adapters/wikipedia_workflow.py search --query "Python" --count 10
python3 scripts/adapters/wikipedia_workflow.py page --title "Python (programming language)"
python3 scripts/adapters/wikipedia_workflow.py summary --title Python
python3 scripts/adapters/wikipedia_workflow.py random --count 10
python3 scripts/adapters/wikipedia_workflow.py trending --count 10
```

脚本使用 MediaWiki API、REST summary API 和 Wikimedia pageview API。页面不存在、API 限流或返回结构异常时停止，不把空结果当作成功详情。

## 输出

每次运行输出一个 Result Envelope，并在目标目录写入 `artifacts/<resource>.json`、`contract/summary.json` 和 `summary.md`。
