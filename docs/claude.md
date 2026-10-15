# 接入真实 Claude 决策

先确认 `python3 -m phage_lab demo` 能在离线模式跑通。
真实模式调用 Anthropic Messages API，使用你自己的 API 额度。
需要 API key 和你的账号当前可用、支持工具调用的模型 ID；聊天订阅不能替代 API 配置。

面板可以直接填写 API 配置；命令行模式使用终端环境变量。
**不会自动加载 `.env` 文件**，不要把密钥写进仓库或聊天。

## 推荐：直接在面板配置

1. 双击 `start-dashboard.bat` 打开面板。
2. 在左侧 **Claude API 配置** 中填写 API Key 和之前已跑通的模型 ID。
3. 点击 **保存并使用 Claude**，再点击 **启动演示**。

配置仅保存在本次面板服务的内存中。刷新网页不会丢失，关闭服务后需要重新填写。
密钥不写入文件、报告、日志或浏览器存储，服务也不把密钥返回给网页。
保存后密钥输入框清空；修改模型时可将密钥留空以保留，也可填写新密钥替换。
**清除本次配置** 会清除当前服务使用的密钥和模型。运行中不能修改或清除配置。

“已配置”表示已接收配置，尚未验证账号权限；保存时不会产生 API 调用或费用。
启动演示才会请求 Claude。若密钥、权限或模型不正确，运行会明确失败，不切换到离线规则。

原来的环境变量方式仍可使用：启动时读取 `ANTHROPIC_API_KEY` 和 `ANTHROPIC_MODEL`，
面板设置会覆盖本次进程中的配置，但不会修改环境变量。清除后本次服务不会再自动载入旧值；
重新启动服务时，如果环境变量仍在，会再次读取。

WSL / Ubuntu 使用 `python3 -m phage_lab dashboard` 打开同一面板。

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
