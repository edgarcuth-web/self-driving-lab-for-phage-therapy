# Self-driving lab for phage therapy

一个能在设备故障后继续完成流程的实验编排原型，用于黑客松演示：

**输入 FASTA → 选择噬菌体组合 → 虚拟合成 → 制备 / 转运 / 感染 / 读数 → 评估 → 报告。**

默认演示会在随机一个步骤注入一次设备卡死，确认旧任务取消后切换到备用设备。

> 候选、合成订单、设备和读数全部是模拟数据。候选评分不代表感染概率，
> 运行成功只代表控制流程完成。设备接口为 **MHS-inspired**，不是官方协议实现。

## 快速开始

需要 Python 3.11+，无需安装依赖。

**浏览器面板（Windows）**：下载 ZIP 并解压，双击 `start-dashboard.bat`，
在打开的页面点击 **启动演示**。浏览器没有自动打开时，访问 `http://127.0.0.1:8765`。
运行期间保留终端窗口。

WSL / Ubuntu 使用 `python3 -m phage_lab dashboard`；端口被占用时加 `--port 8766`。

**命令行**：

```bash
python3 -m phage_lab demo
```

默认离线规则决策，不调用 AI，也不联网。Windows 终端可把 `python3` 换成 `py`。

## 使用 OpenRouter API

在面板左侧展开 **OpenRouter API 配置**，填写 API Key 和模型 ID，保存后启动演示。
密钥只保存在本次服务进程的内存中。命令行模式改用环境变量。详见 [OpenRouter 接入说明](docs/openrouter.md)。

| 模式 | 规划与故障决策 | 需要 API |
|---|---|---|
| `--agent rule`（默认） | 固定规则，便于离线演示和测试 | 否 |
| `--agent openrouter` | 经 OpenRouter 调用模型，选择候选、分配设备和恢复动作，本地校验后执行 | 是 |

API 出错时会生成失败报告，不会自动切回规则模式。

## 运行结果

每次运行生成 `runs/<运行编号>/`：

| 文件 | 内容 |
|---|---|
| `report.md` | 可读总结、恢复记录、未完成原因 |
| `report.json` | 输入指纹、计划、各步骤结果、源码版本 |
| `events.jsonl` | 带序号和时间的完整事件记录 |

返回码 `0` 表示流程完成，`2` 表示失败或中断（仍会保存报告）。
报告记录源码 SHA-256 指纹，ZIP 下载没有 Git 也能比对代码版本；`python3 -m phage_lab version` 可查看当前版本。

## 演示参数

| 参数 | 含义 |
|---|---|
| `--seed 42` | 决定故障步骤、延迟和模拟读数；同一种子可复现 |
| `--fault hang` | 默认：设备卡死，取消后换机恢复 |
| `--fault response-lost` | 设备已完成但回执丢失；查询后取回结果，不重复执行 |
| `--fault unreachable` | 设备失联，无法确认状态；停止并输出失败报告 |
| `--fault none` / `random` | 无故障 / 随机选择以上一种 |
| `--fault-step measure` | 固定故障步骤：`synthesize/prepare/transfer/infect/measure` |
| `--time-scale 0.1` | 加快模拟延迟，范围 0.01–10 |
| `--genome path.fasta` | 指定输入，仅做格式校验和摘要 |
| `--output-dir path` | 报告保存位置 |

## 当前边界

- 单样本、五个顺序步骤，每类设备一台主机一台备用机。
- 超时先查状态；仍在运行则确认取消后再重试或换机，每步最多两次。
- AI 输出视为不可信数据，候选、设备和恢复动作都先校验再执行。
- 只向 OpenRouter 及所选模型提供商发送序列长度、contig 数和指纹，不发送序列或标题。
- 没有崩溃后续跑、持久化去重或多样本并行。

## 开发

```bash
python3 -m unittest discover -s tests -v
```

OpenRouter 适配器测试使用模拟 HTTP 响应，不等于真实 API 联调。
代码结构见 [架构说明](docs/architecture.md)，开发约定见 [AGENTS.md](AGENTS.md)。

## 后续计划

1. 真实模型多场景联调，记录规划和恢复成功率。
2. Windows 浏览器视觉验收和现场彩排。
3. 接入经过独立验证的候选预测服务。

## MHS 参考

接口设计参考了 Anthropic 的 [MHS 研究预览公告](https://www.anthropic.com/news/model-hardware-standard-research-preview)
中公开的设备发现、能力描述和读写原语思路。本仓库的 Python 接口是自定义的演示契约，不声称兼容或通过认证。

