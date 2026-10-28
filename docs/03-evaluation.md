# 03 实际评估、失败与限制

## 执行方式与范围

项目先完成离线 Mock 验证，随后按候选人要求接入阿里云千问 qwen-plus 完成真实模型评估。全部业务输入仍为合成资料，业务工具为本地实现；真实模型服务被实际调用，没有接真实发布。

实际执行命令：

```console
python -m src.scheduler demo --provider mock
python -m src.scheduler demo --provider live --env-file .env --out examples/live
python scripts/check.py
```

当前实际结果：**离线 13/13、真实模型 13/13、可执行测试 45/45 通过**。测试 0 失败、0 错误、0 跳过，记录见 [tests.json](../examples/verification/tests.json) 与 [unittest.txt](../examples/verification/unittest.txt)。真实评估首轮为 11/13，修正工具契约与提示后复跑同一完整矩阵达 13/13，首轮记录保留。测试结果与真实模型结果分别统计，不互相替代。

真实模型逐项输出见 [live/summary.md](../examples/live/summary.md) 与 [live/evaluation.json](../examples/live/evaluation.json)，动态路径、原始失败和迭代说明见 [live-evidence.md](live-evidence.md)。正式真实矩阵共 15 份输出、79 次模型响应、7 种动作序列；实际 response_id 和 token 汇总见 [provenance.json](../examples/live/provenance.json)。

## 验收证据矩阵

每个场景目录含实际 `input.json`、`output.json`、`trace.jsonl`、最终数据库导出的 `drafts.json`，以及故障与排期快照 `scenario.json`。两次执行场景另有 `input-2.json`、`output-2.json`、`trace-2.jsonl`。

| 场景 | 预期与实际 | 实际输出 | Trace |
|---|---|---|---|
| 正常排期 | completed；保存 1 份原时段草稿 | [normal](../examples/mock/normal/output.json) | [Trace](../examples/mock/normal/trace.jsonl) |
| 信息缺失 | needs_information；补查后版权字段仍缺，草稿 0 | [missing](../examples/mock/missing/output.json) | [Trace](../examples/mock/missing/trace.jsonl) |
| 规则风险 | blocked；R-CLAIM 风险，草稿 0 | [risk](../examples/mock/risk/output.json) | [Trace](../examples/mock/risk/trace.jsonl) |
| 时段冲突 | needs_confirmation；18:00 -> 19:00，保留原要求 | [conflict](../examples/mock/conflict/output.json) | [Trace](../examples/mock/conflict/trace.jsonl) |
| 重复提交 | completed；第二次 duplicate，只有同一份草稿 | [第二次输出](../examples/mock/duplicate/output-2.json) | [第二次 Trace](../examples/mock/duplicate/trace-2.jsonl) |
| 保存失败 | failed；storage_error，草稿 0，仍报告建议时段 | [save_failure](../examples/mock/save_failure/output.json) | [Trace](../examples/mock/save_failure/trace.jsonl) |
| 补查成功 | completed；missing -> 补查 -> passed -> 保存 | [supplement](../examples/mock/supplement/output.json) | [Trace](../examples/mock/supplement/trace.jsonl) |
| 查询失败恢复 | completed；观察一次 tool_unavailable 后再次查询 | [query_failure](../examples/mock/query_failure/output.json) | [Trace](../examples/mock/query_failure/trace.jsonl) |
| 无时段 | no_feasible_slot；窗口中全部占用，草稿 0 | [no_slots](../examples/mock/no_slots/output.json) | [Trace](../examples/mock/no_slots/trace.jsonl) |
| 用户明确确认 | completed；pending -> confirmed，原草稿更新 | [第二次输出](../examples/mock/confirmation/output-2.json) | [第二次 Trace](../examples/mock/confirmation/trace-2.jsonl) |
| 批量素材 | partial；M01 完成、M04 待确认，2 份不同时段草稿 | [batch](../examples/mock/batch/output.json) | [Trace](../examples/mock/batch/trace.jsonl) |
| 执行上限 | incomplete；2 步后停止，草稿 0 | [step_limit](../examples/mock/step_limit/output.json) | [Trace](../examples/mock/step_limit/trace.jsonl) |
| 更换占用时段 | completed；占用改为 19:00 后直接保存要求的 18:00 | [changed_schedule](../examples/mock/changed_schedule/output.json) | [Trace](../examples/mock/changed_schedule/trace.jsonl) |

总表见 [summary.md](../examples/mock/summary.md)，逐条断言见 [evaluation.json](../examples/mock/evaluation.json)。对比 conflict 与 changed_schedule 可检查输入要求相同、工具返回变化后建议是否随之变化；这些为独立新数据库，不伪称在已有草稿上无条件自动改期。

交付一致性检查覆盖离线与最终真实矩阵的 30 份输出，核对 Trace、执行上限、文档链接、真实响应凭据和密钥模式，见 [delivery.json](../examples/verification/delivery.json)。另将源码压缩包解压到新目录，重新运行离线 demo、完整测试并检查已归档的真实记录，见 [archive-smoke.json](../examples/verification/archive-smoke.json)。解压检查不调用真实模型，不重复产生模型费用。

## 额外工程验证

测试覆盖：模型提前 finish 不能声明完成、跳过审核不能保存、模型伪造 confirmed 参数失败、风险素材不能保存、补查使旧审核失效、保存前新冲突被拦截、请求同 ID 不同参数被拒绝、两个 SQLite 连接并发争用仅一份成功、持久查询失败与步数耗尽不返回成功。

`test_real_sqlite_write_failure_is_not_reported_as_saved` 对连接执行 `PRAGMA query_only = ON`，让 SQLite 真实拒绝写入，验证错误回滚并返回 failed，补足仅靠故障注入的局限。`test_save_failure_is_explicit_and_retryable` 验证保存失败后可用相同请求重跑，最终只有一份草稿。

六项 LiveContractTests 使用 HTTP 替身检查通用协议、DeepSeek 与千问适配、服务端响应凭据及 HTTP 错误脱敏。这些测试不联网；真正联网的评估证据在 examples/live/，二者分别记录。

后续增加四项 PrivateConfigTests，检查显式私有配置的优先级、进程隔离、配置错误不回显密钥、不执行文件中的表达式以及 Mock/live 不静默混用。配置功能已通过测试，但没有据此声称产生了真实模型证据。

对同一已保存请求，在下一次运行前把其草稿时段改为外部占用，重复执行会观察到新冲突；若需改为另一建议时段，保存工具要求新请求 ID，旧草稿保持不变，结果明确 failed。对应测试为 `test_occupancy_change_on_same_request_does_not_mutate_saved_draft`，不会因幂等读取就虚报本次成功。

## 开发中发现并修正的问题

首次 demo 执行曾因 CLI 项目根路径计算多上溯一级而找不到输入文件，已修正并通过端到端 CLI 测试。复核时发现缺少 allowed_channels 会被误当成渠道风险，已改为信息缺失并增加测试；保存失败的最终输出也已补充经过查询的建议时段。

## 尚未验证与已知限制

1. 真实模型已在合成矩阵中验证，但只有一次改进前后对照，不代表统计意义的稳定成功率。完整保留首轮两个失败；后续模型版本和新资料可能改变结果。
2. 审核依赖合成标签、规则与授权元数据，不具备视频语义审核能力；规则快照可能滞后于外部系统。
3. 外部已有排期是运行开始时的快照；运行中外部平台变更不被实时同步。SQLite 只能保证本地草稿之间不冲突。
4. 待确认草稿保留占位，没有取消、过期、人工审批 UI 或真实发布功能。
5. 用户确认输入信任本地 CLI 调用人，未实现多用户认证。批量素材按输入顺序处理，不求全局最优。
6. 只支持整点一小时时段；不同素材共享渠道不能重叠，尚不支持任意视频时长、跨时区或复杂日历。
7. 真实模型服务需要支持本项目原生工具协议；HTTP 替身测试不验证服务商参数兼容性。模型失败会明确停止，不自动降级。
