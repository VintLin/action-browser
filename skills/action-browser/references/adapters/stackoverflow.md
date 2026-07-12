# Stack Overflow ActionBook 操作说明

当前只启用 OpenCLI Reference Baseline 中的八个公开只读能力：`bounties`、`hot`、`read`、`related`、`search`、`tag`、`unanswered`、`user`。

## 常用命令

```bash
python3 scripts/adapters/stackoverflow_workflow.py search --query "python asyncio" --count 10
python3 scripts/adapters/stackoverflow_workflow.py read --question-id 231767
python3 scripts/adapters/stackoverflow_workflow.py tag --tag python --count 10
python3 scripts/adapters/stackoverflow_workflow.py user --user "Jon Skeet" --count 10
```

脚本使用 Stack Exchange 公共 API，遵守其 `backoff` 字段并限制单次最多 50 条。配额、限流或 API 结构变化按 typed failure 处理。

## 输出

每次运行输出一个 Result Envelope，并在目标目录写入 `artifacts/<resource>.json`、`contract/summary.json` 和 `summary.md`。
