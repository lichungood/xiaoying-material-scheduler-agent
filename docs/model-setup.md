# 千问本机配置与复现

当前真实评估使用阿里云百炼的 `qwen-plus`，中国内地 OpenAI 兼容地址为 `https://dashscope.aliyuncs.com/compatible-mode/v1`。该配置已经实际完成模型调用。

## 本机配置

将 `.env.example` 复制为项目根目录的 `.env`，只在本机填写密钥：

```dotenv
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
LLM_API_KEY=填写自己的APIKey
```

API Key 从阿里云百炼控制台获取，并与接入地域匹配。本项目不会提交 `.env`，不会把 Authorization 头或密钥写入 Trace。

## 复现命令

```console
python -m src.scheduler demo --provider live --env-file .env --out work/live-reproduction
```

先输出到新的目录，避免覆盖已经提交的证据。需要归档时保留完整输入、输出、Trace 和 evaluation.json，再更新评估结论。

## 协议依据

- [阿里云 OpenAI 兼容接口](https://help.aliyun.com/zh/model-studio/developer-reference/compatibility-of-openai-with-dashscope)
- [千问 Function Calling](https://help.aliyun.com/zh/model-studio/qwen-function-calling)

适配器发送原生 tools，明确关闭思考模式 `enable_thinking=false`，设置 `parallel_tool_calls=false`，并要求返回工具动作。工具参数与权限由执行器再次校验；不依赖服务端 strict 字段。

真实响应的 response_id、tool_call_id、返回模型名、token 用量和调用延迟随每一步保存。模型内部思维过程和真实密钥不进入交付文件。

此前保留的 DeepSeek 适配采用其非思考工具调用协议，但本次没有使用 DeepSeek 密钥或服务作为评估来源。
