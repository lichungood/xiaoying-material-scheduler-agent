# 提交信息与当前验证范围

| 字段 | 内容 |
|---|---|
| 题号 | 1 |
| 项目 | 素材审核与发布排期 Agent |
| GitHub URL | https://github.com/lichungood/xiaoying-material-scheduler-agent |
| 可见性 | 公开 |
| 当前验证 | 45 项测试、13 组离线场景、13 组真实模型场景通过 |
| 真实模型决策 | 阿里云百炼 qwen-plus，79 次正式矩阵响应、7 种动作序列，完整 Trace 与响应 ID 已提交 |
| AI 与个人贡献 | 见 [04-ai-usage.md](04-ai-usage.md)，按实际协作归属记录 |

提交 SHA 应从实际交付版本获取：

```console
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

只有两者一致，才能确认该本地提交已成为远程 main 的当前版本。不要将源码 ZIP 的 SHA-256 当作 Git commit SHA。最终 SHA 在仓库外的提交消息中给出，避免把包含本文件的提交哈希写回自身而造成循环变更。

真实模型、离线流程、首轮失败与改进均已归档。复现时配置本机私有 `.env`，输出到新目录：

```console
python -m src.scheduler demo --provider live --env-file .env --out work/live-reproduction
```

评审可直接查看 [真实运行说明](live-evidence.md) 与 [实际评估](03-evaluation.md)。后续复跑不保证相同结果；新的成功和失败均应保留，不替换原始失败来制造稳定成功率。
