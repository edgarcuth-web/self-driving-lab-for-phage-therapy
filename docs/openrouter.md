# OpenRouter API

需要 OpenRouter API Key 和支持工具调用的模型。

## 命令行配置

程序读取环境变量，不读取 `.env`。WSL / Ubuntu：

```bash
read -rsp "OpenRouter API key: " OPENROUTER_API_KEY && export OPENROUTER_API_KEY
export OPENROUTER_MODEL="你的模型代号"
python3 -m phage_lab run --candidates candidates.json --sample-id sample-001 \
  --execution-mode virtual_hardware --agent openrouter
```

模型代号原样提交给 OpenRouter，不查询模型列表也不补前缀；是否可用由 OpenRouter 返回结果决定。API 失败会生成失败报告，不切换到离线模式。

调用遵循 [OpenRouter 工具调用接口](https://openrouter.ai/docs/guides/features/tool-calling)。发送基因组摘要、候选记录和设备信息，不发送原始序列或 FASTA 标题。
