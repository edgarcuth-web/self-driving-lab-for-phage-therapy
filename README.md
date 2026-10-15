# Self-driving lab for phage therapy

这个仓库已经从黑客松模拟演示转向真实实验编排系统。

目标不是生成看起来像实验的数据，而是把真实候选记录、真实设备状态、真实测量结果和可审计的决策连接成一个可靠的实验闭环。

## 当前原则

- `phage_lab.workflow.run_experiment()` 是真实运行入口。候选记录和设备驱动必须由调用方显式提供。
- 真实运行拒绝任何 `SIM-*`、`source=synthetic_fixture` 或 `simulated=True` 的候选 / 设备；不存在自动回退到模拟器。
- `phage_lab/devices.py` 只定义通用设备契约。具体仪器通过 adapter 实现该契约。
- 原黑客松模拟器保留在 `phage_lab/simulation.py`，只用于回归测试、故障恢复测试和旧 dashboard 演示。
- Agent 输出始终是不可信提案：候选 ID、设备能力和恢复动作在执行前由确定性代码校验。
- timeout 不等于失败。控制器必须先查询真实 job 状态；无法确认状态时停止，不能盲目重复物理操作。
- 编排层不把任何测量自动解释成疗效结论。

## Real Lab v0 状态

第一阶段重构已经建立 production / simulation 边界，但仓库目前还没有绑定某一台具体实验仪器或某一个真实候选数据库。因此：

```bash
python -m phage_lab run
```

会明确拒绝启动，而不是偷偷使用模拟设备。

真实集成应通过 Python API 注入：

```python
from phage_lab.workflow import run_experiment

report, directory = await run_experiment(
    genome_path,
    output_root,
    sample_id="sample-001",
    candidates=real_candidate_records,
    devices=real_device_drivers,
    workflow=validated_workflow,
    agent=planner,
)
```

每个真实 driver 的 `describe()` 必须显式返回 `"simulated": False`。

## Simulation test harness

旧演示仍可显式运行，用于测试编排、幂等、timeout reconciliation 和 failover：

```bash
python -m phage_lab demo
```

浏览器 dashboard 当前也仍然连接这个 simulation harness：

```bash
python -m phage_lab dashboard
```

它不是 production 实验入口。

## 运行记录

每次运行都会写入独立的 `runs/<run-id>/`：

| 文件 | 内容 |
|---|---|
| `report.md` | 人类可读总结 |
| `report.json` | 输入摘要、计划、步骤结果、恢复记录、源码身份 |
| `events.jsonl` | append-only 顺序事件流 |

真实运行不会把 orchestration 成功等同于 biological efficacy；报告中的 biological conclusion 默认为 `not_assessed`。

## 开发

```bash
python -m unittest discover -s tests -v
```

架构见 [docs/architecture.md](docs/architecture.md)，开发约定见 [AGENTS.md](AGENTS.md)。

## 下一步

Real Lab v0 接下来优先做三件事：

1. 接入第一台真实仪器 adapter，并把设备 job ID / state / result 持久化。
2. 把候选来源改成有 provenance 的真实 registry / 数据库接口，而不是由 workflow 内部生成。
3. 把固定 demo 流程升级为版本化 protocol，并为不可逆步骤增加明确的 approval / reconciliation 语义。

## 参考

设备抽象最初受 Anthropic Model Hardware Standard 研究预览中的 discovery / capability / read-write 思路启发；本仓库接口是自己的契约，不声称兼容任何未公开规范。
