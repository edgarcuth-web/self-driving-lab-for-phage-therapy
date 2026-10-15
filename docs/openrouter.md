# OpenRouter API

需要 OpenRouter API Key 和支持工具调用的模型。

## 面板配置

1. 启动 `start-dashboard.bat` 或运行 `python3 -m phage_lab dashboard`。
2. 展开左侧 RUN CONFIGURATION，填写 API Key 和模型代号并保存。
3. 在流程栏第一格（00 · 上传）选择 FASTA 文件，点击 **开始**。

模型代号原样提交给 OpenRouter，不查询模型列表或补前缀。支持填写简称或完整 ID；是否可用由 OpenRouter 返回结果决定。

密钥只保存在服务进程内存中，关闭服务后清除。再次保存时留空可保留原密钥；**清除本次配置** 会清除密钥和模型。运行中不能修改配置。
保存不调用 API；点击开始时才验证。API 失败会生成失败报告，不切换到离线模式。

## 命令行配置

程序读取环境变量，不读取 `.env`。WSL / Ubuntu：

```bash
read -rsp "OpenRouter API key: " OPENROUTER_API_KEY && export OPENROUTER_API_KEY
export OPENROUTER_MODEL="你的模型代号"
python3 -m phage_lab demo --agent openrouter --seed 42
```

面板启动时也会读取这些变量；之后的面板设置只覆盖进程内配置。

调用遵循 [OpenRouter 工具调用接口](https://openrouter.ai/docs/guides/features/tool-calling)。发送基因组摘要、模拟候选和设备信息，不发送原始序列或标题。
