# Hacker News ActionBook 操作说明

当前只启用 OpenCLI Reference Baseline 中的九个公开只读能力：`ask`、`best`、`jobs`、`new`、`read`、`search`、`show`、`top`、`user`。

## 常用命令

```bash
python3 scripts/adapters/hackernews_workflow.py top --count 10
python3 scripts/adapters/hackernews_workflow.py search --query "browser automation" --count 10
python3 scripts/adapters/hackernews_workflow.py read --item-id 1
python3 scripts/adapters/hackernews_workflow.py user --user pg
```

列表和详情使用 Hacker News Firebase API；搜索使用 Algolia 公共 API。评论读取限制为单条故事前 20 个可见评论，不递归抓取完整评论树。

## 输出

每次运行输出一个 Result Envelope，并在目标目录写入 `artifacts/<resource>.json`、`contract/summary.json` 和 `summary.md`。
