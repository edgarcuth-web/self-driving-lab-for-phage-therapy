# 接入真实 Claude 决策

先确认离线模式 `python3 -m phage_lab demo` 能跑通。真实模式调用 Anthropic Messages API，
需要 API Key 和账号可用的模型 ID，费用计入你的 API 额度（聊天订阅不能替代）。

## 面板配置（推荐）

1. 启动面板（`start-dashboard.bat` 或 `python3 -m phage_lab dashboard`）。
2. 在左侧 **Claude API 配置** 填写 API Key 和模型 ID，点击 **保存并使用 Claude**。
3. 点击 **启动演示**。

配置规则：

- 只保存在服务进程内存中：刷新网页保留，关闭服务后清除；不写入文件、日志、报告或浏览器存储，也不返回给网页。
- 保存时不调用 API，所以“已配置”不代表密钥有效；启动演示时才会验证。
- 再次保存时密钥留空即保留原密钥，只修改模型 ID。**清除本次配置** 同时清除密钥和模型。
- 运行中不能修改配置。
- 服务启动时会读取 `ANTHROPIC_API_KEY` 和 `ANTHROPIC_MODEL` 环境变量作为初始值；面板设置覆盖它们，但不修改环境变量。

## 命令行配置

不会读取 `.env` 文件。在 WSL / Ubuntu 终端执行（输入密钥时不显示字符）：

```bash
read -rsp "Anthropic API key: " ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY
export ANTHROPIC_MODEL="your-model-id"
python3 -m phage_lab demo --agent anthropic --seed 42
```

环境变量在关闭终端后失效。

## 模型做什么

- **规划**：根据基因组摘要、模拟候选评分和设备能力，选择 2–3 个候选并给每步分配设备。
- **恢复**：设备卡死后，根据观察到的状态选择取消后重试、取消后换机或停止。

调度器校验每个决定，并确认原任务已取消后才执行。默认卡死场景调用模型两次。
请求失败不重试，也不切换到规则模式，错误写入失败报告。

## 验收

1. 报告中 `agent` 为 `anthropic`，并记录模型 ID。
2. 事件日志出现 `plan_accepted` 和 `recovery_decided`。
3. `cancellation_acknowledged` 早于第二次 `job_submitted`。
4. 最终状态为 `succeeded`。

单元测试使用伪造的 HTTP 响应，没有真实成功的运行记录前，不应宣称已完成端到端联调。
