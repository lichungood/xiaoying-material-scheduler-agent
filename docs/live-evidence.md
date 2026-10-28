# 千问真实模型运行与迭代证据

## 实际接入

2026-10-28 使用阿里云百炼中国内地 OpenAI 兼容接口，模型 `qwen-plus`，`enable_thinking=false`。本轮调用真实模型选择工具动作，业务工具使用本地合成资料和 SQLite 草稿，不接真实发布。

正式矩阵包含 13 个场景、15 份实际输出，共 **79 次模型响应、7 种动作序列**。服务返回的 token 用量合计为 prompt 120555、completion 3851、total 124406；该统计只含改进后的正式矩阵，不含首轮与连通性检查，也不是费用计算。凭据见 [provenance.json](../examples/live/provenance.json)。

每个步骤都记录工具参数、原始结构化结果、结果摘要、简短依据、下一动作，以及服务端 response_id、tool_call_id、返回模型名、token 用量和延迟。没有提交密钥、Authorization 头或内部思维过程。

## 真实动态路径

| 场景 | 实际动作与结果 | 证据 |
|---|---|---|
| 正常 | 读取 -> 审核 -> 查询 -> 保存 19:00 -> 结束；completed | [输出](../examples/live/normal/output.json)、[Trace](../examples/live/normal/trace.jsonl) |
| 信息不足 | 读取 -> 审核缺版权 -> 补查 -> 再审核仍缺 -> 结束；needs_information，未保存 | [输出](../examples/live/missing/output.json)、[Trace](../examples/live/missing/trace.jsonl) |
| 规则风险 | 读取 -> 审核命中 R-CLAIM -> 直接结束；blocked | [输出](../examples/live/risk/output.json)、[Trace](../examples/live/risk/trace.jsonl) |
| 时间冲突 | 查询观察到 18:00 占用，模型选择保存 19:00 建议；pending，不改原要求 | [输出](../examples/live/conflict/output.json)、[Trace](../examples/live/conflict/trace.jsonl) |
| 查询失败 | 观察暂时错误后补查素材、重新审核和查询，再保存；8 步完成 | [输出](../examples/live/query_failure/output.json)、[Trace](../examples/live/query_failure/trace.jsonl) |
| 保存失败 | save_draft 返回 storage_error 后结束；failed、draft=null，无伪造保存成功 | [输出](../examples/live/save_failure/output.json)、[Trace](../examples/live/save_failure/trace.jsonl) |
| 重复请求 | 第二次返回 duplicate、同一 draft_id，数据库仍 1 份 | [第二次输出](../examples/live/duplicate/output-2.json)、[最终草稿](../examples/live/duplicate/drafts.json) |
| 用户确认 | 第二次请求带用户 confirmed_slots，pending 更新为 confirmed，未新增草稿 | [确认输入](../examples/live/confirmation/input-2.json)、[第二次输出](../examples/live/confirmation/output-2.json) |
| 更换占用 | 将占用改为 19:00 后，同样要求的 18:00 可用，模型保存 18:00 | [场景快照](../examples/live/changed_schedule/scenario.json)、[输出](../examples/live/changed_schedule/output.json) |

完整 13 项断言见 [evaluation.json](../examples/live/evaluation.json)，包括补查成功、无时段、批量素材与步数上限。`step_limit` 的预期结果就是 incomplete，`save_failure` 的预期结果就是 failed；“场景通过”不表示把所有任务都标为成功。

## 首轮失败与改进

首轮真实矩阵 **11/13** 通过，完整记录保存在 [01-initial](../examples/live-attempts/01-initial/evaluation.json)，其原系统提示也一并保留，没有删除失败用例。

1. **missing**：模型补查后直接 finish，没有重新 check_rules。读取会使旧审核失效，执行器正确返回 incomplete，未保存。
2. **query_failure**：模型遇到一次只读查询故障就结束，返回 failed，没有完成预期的暂时错误恢复。

据此明确工具与提示契约：读取结果增加 review_required；每次读取后要求重新审核；暂时只读错误增加 retryable，并明确最多补查一次；保存 storage_error 则保留为本次失败，由用户重新提交触发重试。执行器没有增加自动选动作或自动重试分支，后续动作仍由真实模型在观察结果后选择。

改动后重新运行**完整同一矩阵**，结果 13/13。两轮对照见 [iteration.json](../examples/live/iteration.json)，最终系统提示见 [system-prompt.txt](../examples/live/system-prompt.txt)。首条连通性运行也保存在 [00-connectivity](../examples/live-attempts/00-connectivity/output.json)。

## 结果的实际边界

- 本次是固定合成矩阵的一轮前后对照，不是统计意义的稳定成功率，也不保证后续模型版本或新资料同样通过。
- 模型有时会多读一次元数据或提前选择补充读取；工具调用序列并不总与 Mock 一致。
- 简短理由偶有确认用语不准确：例如原时段可用时，保存前的理由仍写“待确认”；确认场景也有类似措辞。原始记录保留。最终 confirmation_status、save_status 和 task_status 来自工具与数据库，不采用这些自由文本作为事实。
- 业务风险检查依赖合成元数据，工具故障通过明确标注的注入产生；这验证真实模型对工具结果的反应，不代表真实视频审核或线上系统已经验证。
