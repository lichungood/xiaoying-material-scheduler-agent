# 素材审核与发布排期 Agent

小影科技 2027 校招 AI Agent 笔试，第 1 题。帮助内容团队审核合成素材、查询发布时段并保存无冲突草稿。

公开仓库：[lichungood/xiaoying-material-scheduler-agent](https://github.com/lichungood/xiaoying-material-scheduler-agent)。交付说明见 [submission.md](docs/submission.md)。

**当前已验证：42 项测试通过，13 组离线验收场景通过。真实模型入口已实现，后续真实验证请求尚待配置密钥与模型。Mock 的条件决策仅验证流程，不能作为满足真实模型 ReAct 要求的证据。**

所有结果都是草稿；`completed` 表示草稿已保存且无需进一步时间确认，始终 `published=false`。

## 评审入口

- [需求与验收边界](docs/01-requirements.md)
- [决策循环与技术取舍](docs/02-solution.md)
- [实际评估、证据路径与限制](docs/03-evaluation.md)
- [AI 使用与贡献记录](docs/04-ai-usage.md)
- [工程复盘与下一步](docs/05-retrospective.md)
- [离线运行结果总表](examples/mock/summary.md)、[机器可读评估](examples/mock/evaluation.json)
- [可执行测试结果](examples/verification/tests.json)、[完整测试日志](examples/verification/unittest.txt)

## 环境与安装

Python **3.11+**，实际验证版本为 **3.13.9 / Windows**。运行及测试只使用标准库，无需安装依赖；见 [requirements.txt](requirements.txt)。不使用 Agent 框架。

以下命令在本项目根目录执行，Windows PowerShell 与常见终端均可使用。Windows 若终端中文乱码，可先运行 `$env:PYTHONUTF8="1"`。所有输入输出文件均为 UTF-8。

```console
python -m src.scheduler --help
python -m src.scheduler demo --provider mock
python scripts/check.py
```

`demo` 为每个场景建立独立临时数据库，实际执行后把输入、输出、Trace、最终草稿及评估写入 `examples/mock/`，可重复运行，不依赖历史数据。重复提交和用户确认场景在各自场景内复用数据库。

## 单个请求

```console
python -m src.scheduler run --provider mock --input examples/inputs/conflict.json --db work/demo.sqlite3 --out work/conflict
```

输出文件为 `input.json`、`output.json`、`trace.jsonl`。相同命令再次执行会复用草稿，不会新增一份。`work/` 为运行产物，不进入版本控制。

请求示例：

```json
{
  "request_id": "campaign-001",
  "material_ids": ["M01"],
  "channel": "douyin",
  "requested_at": "2026-11-01T18:00+08:00",
  "search_window": {
    "start": "2026-11-01T18:00+08:00",
    "end": "2026-11-01T21:00+08:00"
  },
  "hard_time": true
}
```

合成排期中 18:00 已占用。系统建议 19:00，保存 `confirmation_status=pending` 的草稿并返回 `needs_confirmation`；原始 `requested_at` 保留 18:00。

用户明确同意后，可在**同一份请求**中添加以下字段并重新运行；模型工具参数没有确认权限：

```json
"confirmed_slots": {"M01": "2026-11-01T19:00+08:00"}
```

这会将同一草稿更新为 `confirmed`。独立的用户确认输入与执行记录见 [confirmation 场景](examples/mock/confirmation/input-2.json)。本地 CLI 调用人被视为用户；接入 HTTP 服务时必须另行实现身份与确认权限校验。

`hard_time` 默认 `true`。只有用户显式设为 `false` 才允许直接在搜索窗口内调整。未提供 `search_window` 时，仅查询原请求时段；不擅自扩大范围。更改原始需求或更换已保存的建议时段须使用新 `request_id`。相同 ID 的不同原始请求返回 `idempotency_conflict`。

## 故障与执行上限

```console
python -m src.scheduler run --provider mock --input examples/inputs/normal.json --db work/failure.sqlite3 --out work/failure --fault save_draft:1
python -m src.scheduler run --provider mock --input examples/inputs/normal.json --db work/limit.sqlite3 --out work/limit --max-steps 2
```

第一个命令预期退出码 3，结果为 `failed`，无新增草稿；第二个预期退出码 2，结果为 `incomplete`，`termination=max_steps`。故障通过 CLI 注入，不允许素材数据或模型参数修改故障设置。

默认整个请求最多 30 次动作选择（含 `finish`），上限可设为 1..100，批量素材共用预算。模型 HTTP 调用超时为 30 秒，无隐式无限重试。

| 退出码 | 含义 |
|---|---|
| 0 | 草稿已完成或已保存为待确认建议；`demo` 中表示所有场景断言通过 |
| 2 | 信息不足、风险阻断、无可行时段、批量部分完成或执行未完成 |
| 3 | 工具执行或保存失败 |
| 4 | 输入或配置错误 |
| 1 | `demo` 中存在未通过的验收断言 |

## 真实模型入口（尚未实测）

适配器采用 Chat Completions 原生函数调用。服务需支持 `tools`、严格 JSON Schema、`tool_choice=required`、关闭并行工具调用。模型每轮看到真实工具返回，重新选择一个动作；不会根据场景名称选择预设日志。

[.env.example](.env.example) 仅为模板，程序**不自动加载 `.env`**。在 PowerShell 当前进程配置：

```powershell
$env:LLM_BASE_URL="https://api.openai.com/v1"
$env:LLM_MODEL="填写你有权限使用且支持工具调用的模型名"
$env:LLM_API_KEY=Read-Host "API key" -MaskInput
python -m src.scheduler run --provider live --input examples/inputs/normal.json --db work/live.sqlite3 --out examples/live/normal
```

`Read-Host -MaskInput` 需要 PowerShell 7.1+；其他终端请通过本机环境变量安全配置。未指定模型或密钥会报错；live 失败不会自动切到 Mock。运行会产生模型服务费用，请按服务商配置和实际返回评估。

也可在本机将 `.env.example` 复制为 `.env` 并填写，然后**显式**读取：

```console
python -m src.scheduler demo --provider live --env-file .env --out examples/live
```

私有配置只接受 LLM_API_KEY、LLM_MODEL、LLM_BASE_URL 三个字段，以 `名称=值` 每行一个填写，可使用成对单引号或双引号。不会执行文件内容，错误不会回显值；显式文件优先于当前进程环境变量，且不修改进程环境。`.env` 已被 Git 忽略，打包脚本也不会包含它。

需要补交真实模型证据时，运行以下命令生成独立目录的实际记录，并人工复核决策依据、硬性时间边界与保存状态：

```console
python -m src.scheduler demo --provider live --out examples/live
```

此命令未在本轮执行。真实模型不保证通过所有场景；应保留失败记录、修订后再次评估。至少保留两条不同工具结果下的真实决策路径，覆盖正常、信息不足、工具失败。HTTP 替身测试只验证协议构造，不证明服务商兼容性或模型质量。

## 目录

```text
src/scheduler/    输入、Agent 循环、模型接入、业务工具、SQLite 存储、CLI
tests/           行为、异常、并发及模型越权边界测试
data/            合成素材、补充登记表、规则、已有排期
examples/inputs/ 可修改输入
examples/mock/   本轮离线实际输出与 Trace
examples/verification/ 测试与交付检查记录
docs/            五份要求文档及实际工作记录
scripts/         测试记录与打包脚本
```

## 提交前待完成

1. 候选人复核 AI 使用与贡献记录；个人修改、复跑和投入时间均只按实际发生的事实记录，不将 AI 生成归为个人独立编码。
2. 接入真实模型，保存两条以上真实决策路径，更新评估文档；当前 Mock 记录不能替代此项。
3. 仓库已创建为公开；提交时填写题号 **1**、上述 GitHub URL 和实际交付版本的 `git rev-parse HEAD`。当前版本的真实模型证据仍待配置后补充，不能将离线结果作为完整 ReAct 验收结论。
