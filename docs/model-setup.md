# DeepSeek 本机配置

当前服务商为候选人选择的 DeepSeek。根据 2026-10-28 实际读取的[官方入口](https://api-docs.deepseek.com/)，本项目采用普通 Chat Completions 地址 `https://api.deepseek.com`，模型名使用 `deepseek-flash`。

## 操作步骤

1. 登录 [DeepSeek API Keys 后台](https://platform.deepseek.com/api_keys)，创建并复制 API Key。
2. 打开项目根目录的本机 `.env` 文件。接口地址和模型名已预填，只在 `LLM_API_KEY=` 后填写自己的密钥并保存。
3. 不要把密钥发到聊天、截图或 GitHub。该文件已被 Git 忽略，也不会进入项目压缩包。
4. 在项目根目录运行：

```console
python -m src.scheduler demo --provider live --env-file .env --out examples/live
```

本机配置结构如下，其中密钥占位文字必须替换：

```dotenv
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash
LLM_API_KEY=填写你自己的APIKey
```

配置后即可由执行代理运行真实验证。API Key 未提供之前不会伪造或标记任何真实模型 Trace。

## 接口取舍

[DeepSeek Chat Completion 文档](https://api-docs.deepseek.com/api/create-chat-completion)注明 `required` 工具选择不支持思考模式，故适配器明确发送 `thinking.type=disabled`。请求与日志不需要模型内部思维过程。

[Tool Calls 文档](https://api-docs.deepseek.com/guides/tool_calls)注明 strict 属于 Beta 功能，需要专用 Beta 地址。项目使用普通地址时不发送 strict，也不发送该接口未列出的 parallel_tool_calls 参数；每轮一个工具的要求由系统提示、响应解析和执行器上限约束。工具自身继续校验参数、权限和保存条件。

以上差异已有 HTTP 替身契约测试；替身测试不能替代真实模型运行。真实请求失败时必须保留失败记录，不能切为 Mock 后声称成功。
