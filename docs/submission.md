# 提交信息与当前验证范围

| 字段 | 内容 |
|---|---|
| 题号 | 1 |
| 项目 | 素材审核与发布排期 Agent |
| GitHub URL | https://github.com/lichungood/xiaoying-material-scheduler-agent |
| 可见性 | 公开 |
| 当前验证 | 43 项测试、13 组离线场景通过 |
| 真实模型决策 | 已选择 DeepSeek，待本机配置 API Key 后运行；当前没有真实模型 Trace |
| AI 与个人贡献 | 见 [04-ai-usage.md](04-ai-usage.md)，按实际协作归属记录 |

提交 SHA 应从实际交付版本获取：

```console
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

只有两者一致，才能确认该本地提交已成为远程 main 的当前版本。不要将源码 ZIP 的 SHA-256 当作 Git commit SHA。最终 SHA 在仓库外的提交消息中给出，避免把包含本文件的提交哈希写回自身而造成循环变更。

当前版本可复现离线工程行为，尚不能据此宣称满足真实模型 ReAct 要求。配置本机私有 `.env` 后运行：

```console
python -m src.scheduler demo --provider live --env-file .env --out examples/live
```

保留实际成功与失败 Trace，核对两条以上不同工具结果下的模型路径、硬性时间确认边界和真实保存结果，更新评估文档，再提交并推送新的 SHA 作为完整交付版本。
