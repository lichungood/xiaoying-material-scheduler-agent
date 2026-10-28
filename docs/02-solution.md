# 02 方案、动态决策与技术取舍

## 调用流程

CLI 校验输入 -> 为当前素材构造上下文 -> provider 选择一个动作 -> 业务工具执行 -> 将结果追加为 tool 消息 -> provider 观察后重新选择 -> 调用 finish 或耗尽共享步数预算 -> 从实际证据生成结构化结果。

批量素材的遍历是预设骨架。live 模式下，骨架不硬编码工具顺序或冲突后的选择；每一步都调用模型。程序负责作用域、权限与保存约束，允许模型观察工具拒绝并调整。

MockProvider 则明确使用基于已观察结果的固定条件策略，便于无密钥复现。它不是模型，也不满足考试真实 ReAct 决策验收。两种 provider 通过同一 `decide(messages, context) -> Action` 接口使用相同工具和结果生成逻辑，live 不会静默降级。

## 工具职责

| 工具 | 模型可选参数（另带一句 reason） | 返回和约束 |
|---|---|---|
| read_material | include_supplement | 当前素材的元数据、是否补查、合成来源；素材 ID 由执行器绑定 |
| check_rules | 无 | passed/missing/blocked、缺失字段、规则 ID 与原因；依赖先读取 |
| query_slots | start_at、end_at | 窗口内时段可用性、已有草稿；包含外部合成排期和其他草稿占用 |
| save_draft | proposed_at | 实际 saved/updated/duplicate 或失败；重新检查审核与占用 |
| finish | suggested_at，可为 null | 结束当前素材，不能据此自行声明保存或发布成功 |

元数据补查后会清除旧审核，必须再次检查规则。保存前校验此前确实观察过该时段可用；保存时再次检查当前运行的排期快照和 SQLite 草稿占用。

## 决策路径举例

离线实际路径 A：读取 M01 -> 审核通过 -> 查询发现 19:00 可用 -> 保存原时段 -> 观察 saved -> finish。

离线实际路径 B：读取 M02 -> 审核缺版权字段 -> 补查登记表 -> 再审核仍缺 -> finish，返回 needs_information。

离线实际路径 C：读取 M01 -> 审核通过 -> 18:00 冲突、19:00 可用 -> 保存 19:00 的待确认建议 -> finish，返回 needs_confirmation。

离线实际路径 D：正常检查后保存返回 storage_error -> finish，返回 failed；query_slots 注入一次失败时，则根据错误重新查询后继续。

Trace 来自执行器实际记录，包含步骤、当前素材、工具名、参数、结果、摘要、简短依据和真实下一动作，不记录内部思维过程。上述是离线路径；最终另提交了千问 qwen-plus 的实际模型记录及服务端响应凭据，见 [live-evidence.md](live-evidence.md)。

## 确认与输出边界

`requested_at` 与 `proposed_at` 分开存储。硬性要求不同于建议时段时，保存工具自动标记 pending；只有输入中存在完全相同的 `confirmed_slots[material_id]` 才标记 confirmed。工具没有权限字段供模型伪造。CLI 输入人属于信任边界，生产环境应将确认关联到已认证用户和具体草稿。

最终审核状态来自 check_rules，草稿来自 SQLite，保存状态来自实际返回。即使模型直接 finish 并在理由中声称已保存，结果仍为 incomplete。没有发布工具，所有输出固定说明尚未发布。

## 幂等与并发

请求指纹为规范化 JSON 的 SHA-256，排除可后续补充的 confirmed_slots，包含其余原始需求。数据库唯一约束分别覆盖 `(request_id, material_id)` 和 `(channel, proposed_at)`。

`BEGIN IMMEDIATE` 将幂等检查和写入放在同一个事务内；重复同样请求读取原草稿，明确确认可更新 pending，改变原始请求或已保存建议则报幂等冲突。跨进程竞争同一时段时，唯一约束确保至多一个保存成功。SQLite 写入错误回滚，不虚报成功。

## 技术取舍

Python 标准库 + SQLite + CLI 使离线复现无需安装依赖，适合核心链路的短时实现。没有使用框架，依赖版本只涉及 Python；实际测试环境为 3.13.9。

实时模型适配器使用 HTTPS、Chat Completions function calling、严格工具参数与单动作调用，模型名由环境变量或显式私有配置提供。参考 [OpenAI Function calling 文档](https://developers.openai.com/api/docs/guides/function-calling)。首次文档访问失败，后续获得网络权限后已读取官方页面并核对 strict、parallel_tool_calls、tool_call_id 等协议字段；当前仍只完成 HTTP 替身契约测试，没有声称已验证实际服务商兼容性。私有配置不会执行其中的 shell 表达式，解析错误不回显密钥。

外部合成数据在每次 run 开始加载为快照；不覆盖运行中外部平台改排的实时一致性。草稿数据库的事务与唯一约束仍对本地并发写入生效。这是可运行演示的明确边界。

候选人曾选择 DeepSeek，后改用千问并提供本机模型凭据。最终真实评估通过阿里云百炼 qwen-plus 完成：明确关闭思考模式与并行工具调用，工具参数与权限由运行时代码检查；若响应并非一个工具调用，会明确返回协议失败而不执行多项副作用。每次响应的 ID、实际 token 用量及延迟被附入 Trace，便于核对真实来源。DeepSeek 的适配保留为可选接入，但没有作为本次评估服务。接口依据与配置步骤见 [model-setup.md](model-setup.md)。
