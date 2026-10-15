# 接入真实 Claude 决策

先确认 `python3 -m phage_lab demo` 能在离线模式跑通。
真实模式调用 Anthropic Messages API，使用你自己的 API 额度。
需要 API key 和你的账号当前可用、支持工具调用的模型 ID；聊天订阅不能替代 API 配置。

本程序读取终端环境变量，**不会自动加载 `.env` 文件**，不要把密钥写进仓库或聊天。

## 已完成 Claude 联调：启动面板

在之前成功运行真实 Claude、且 API 环境变量仍然有效的终端中进入新版项目目录。
Windows 命令提示符运行：

```bat
py -3 -m phage_lab dashboard
```

WSL / Ubuntu 使用 `python3 -m phage_lab dashboard`。然后在页面选择 Claude，点击启动演示。
若 Claude 选项显示“未配置 API”，说明启动面板的进程没有读取到两个环境变量；
这与是否下载 ZIP 无关。双击 BAT 启动的新进程不一定继承另一个终端中的临时设置。

## WSL / Ubuntu

在已经进入仓库的终端里，依次执行。第一步会等待你输入密钥；输入时不显示字符。

```bash
read -rsp "Anthropic API key: " ANTHROPIC_API_KEY
```

输入密钥并回车后，再执行：

```bash
export ANTHROPIC_API_KEY
```

把下一条中的占位文字替换成账号可用的模型 ID：

```bash
export ANTHROPIC_MODEL="your-available-model-id"
```

最后运行：

```bash
python3 -m phage_lab demo --agent anthropic --seed 42
```

同一个终端里不必重复配置。关闭终端后环境变量会失效。

## 模型做什么

- 接收基因组摘要、模拟候选评分、设备能力和固定工作流。
- 通过结构化工具输出选择 2–3 个候选 ID，并给每一步分配设备。
- 设备卡死后接收观察到的状态，提出取消后重试、取消后换机或停止。
- 调度器校验每个选择，并确认原任务已取消，才执行后续动作。

默认卡死场景通常调用模型两次：一次规划、一次恢复。网络请求不会自动重试，
错误会记录在失败报告中；没有静默的规则模式后备。报告也记录模型 ID。

模型接收的是长度、contig 数、SHA-256 摘要等元数据，不含 FASTA 标题或原始序列。
所有候选 ID、评分、实验结果和设备依然是模拟的。

## 如何验收真实模式

1. 终端显示 `Claude API（真实模型调用）`，报告 `agent` 为 `anthropic`。
2. 日志中出现通过本地校验的 `plan_accepted` 和 `recovery_decided`。
3. 若模型选择恢复，确认 `cancellation_acknowledged` 早于第二次 `job_submitted`。
4. 检查最终报告为 `succeeded`，并保留失败运行用于分析。

单元测试使用伪造的 HTTP 响应验证客户端契约，不会使用你的密钥。
没有真实成功运行记录时，不应宣称已完成端到端模型联调。

参考：[Anthropic Messages API](https://platform.claude.com/docs/en/api/messages/create)。
