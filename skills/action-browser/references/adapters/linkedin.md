# LinkedIn ActionBook 操作说明

当前只开放 OpenCLI Reference Baseline 中的 21 个只读入口：公司页、连接、消息收件箱、职位详情、职位偏好、人员搜索、动态/文章、个人资料、分析、Sales Navigator 读取、服务页、线程快照、时间线和当前账号。

## 常用命令

```bash
python3 scripts/adapters/linkedin_workflow.py profile-read \
  --profile-url "https://www.linkedin.com/in/<profile>" \
  --task-id linkedin-read --session <session> --tab <owned-tab>

python3 scripts/adapters/linkedin_workflow.py search \
  --query "Python engineer" --limit 10 \
  --task-id linkedin-read --session <session> --tab <owned-tab>

python3 scripts/adapters/linkedin_workflow.py whoami \
  --task-id linkedin-read --session <session> --tab <owned-tab>
```

所有能力都复用现有 owned-tab 生命周期，不代填凭据、不绕过登录、MFA、验证码或风控。遇到用户门禁时只暂停 LinkedIn 对应 capability。

当前第一版保留页面可见文本、标题、链接和文章卡片作为统一 Site Artifact；具体 capability 的 OpenCLI 语义字段仍必须通过 assisted smoke 和独立 verifier 逐项确认，未确认项不得标记为 `verified`。
