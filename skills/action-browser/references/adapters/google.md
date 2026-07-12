# Google ActionBook 操作说明

当前只启用 OpenCLI Reference Baseline 中的四个公开只读能力：`news`、`search`、`suggest`、`trends`。Google Scholar、Gemini 和 NotebookLM 不属于本 adapter。

## 常用命令

```bash
python3 scripts/adapters/google_workflow.py search --query "OpenAI" --count 10
# Google HTTP 出现 SG_REL retry interstitial 时，显式提供已领取的 owned tab 做 DOM fallback
python3 scripts/adapters/google_workflow.py search --query "OpenAI" --count 10 \
  --task-id google-search --session <session> --tab <owned-tab>
python3 scripts/adapters/google_workflow.py news --count 10
python3 scripts/adapters/google_workflow.py suggest --query "OpenAI" --count 10
python3 scripts/adapters/google_workflow.py trends --count 10
```

这些能力优先使用公开 HTTP/RSS，默认不获取浏览器 tab。Google Search 出现 SG_REL retry interstitial 时，只有显式提供已领取的 owned tab 才进入模拟操作 fallback：打开 Google 首页、填写搜索框并按 Enter，再读取结果页；验证码、访问限制或无法解释的页面仍立即失败，不绕过风控。

## 输出

每次运行输出一个 Result Envelope，并在目标目录写入 `artifacts/<resource>.json`、`contract/summary.json` 和 `summary.md`。不提供 OpenCLI 的表格、YAML 或 CSV 输出模式。
