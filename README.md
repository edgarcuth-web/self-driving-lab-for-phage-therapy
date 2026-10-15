# Self-driving lab for phage therapy

这个项目现在采用 **hybrid self-driving lab** 路线：尽量把数据、候选来源、分析和决策做成真实可追溯的；在没有机械臂、移液工作站、读板机等设备时，硬件执行层继续使用软件 device twin。

关键原则是：**可以模拟硬件，不模拟证据。**

## 三种执行模式

### `virtual_hardware` — 当前主要开发模式

真实/可追溯的候选记录进入真实 workflow 和 planner，但设备动作由软件 twin 执行。

```python
from phage_lab.workflow import run_experiment

report, directory = await run_experiment(
    genome_path,
    output_root,
    sample_id="sample-001",
    candidates=real_candidate_records,
    devices=None,
    workflow=validated_workflow,
    agent=planner,
    execution_mode="virtual_hardware",
)
```

当 `devices=None` 且明确选择 `virtual_hardware` 时，系统会为 workflow 创建虚拟设备。所有设备结果都标记为 simulated，报告同时记录：

- `execution_mode = "virtual_hardware"`
- `physical_execution = false`
- 没有发生真实湿实验
- 虚拟测量不能作为实验或疗效证据

系统不会从 `real_hardware` 自动退回该模式。

### `real_hardware` — 未来设备接入模式

调用方式相同，但必须显式提供 `simulated=False` 的真实设备 adapter。具体设备可以通过 vendor SDK、REST、serial、OPC-UA，未来也可以通过受控的 Computer Use / GUI adapter 接入。

### `legacy_demo` — 原黑客松演示

```bash
python -m phage_lab demo
python -m phage_lab dashboard
```

这一模式连候选和读数都是 synthetic fixture，只用于回归测试和展示，不属于实验路径。

## 当前边界

- `biology.py`：FASTA 校验和输入摘要。
- `workflow.py`：真实候选驱动的 planner、调度、reconciliation。
- `devices.py`：统一设备契约。
- `simulation.py`：软件 device twin，以及独立保留的 legacy demo。
- `agents.py`：只在提供的候选/设备集合中做结构化决策。
- `records.py`：append-only events、运行报告和代码 provenance。

实验路径仍拒绝旧的 `SIM-PHAGE-*` / `synthetic_fixture` 候选。换句话说，允许暂时“没有机器人”，但不允许用随机候选假装已经做了生物学发现。

## 可靠性原则

timeout 只代表没有及时收到结果，不代表物理动作失败。控制器先 reconciliation，再决定是否 retry/failover；状态未知时停止，避免重复不可逆动作。

这些规则在 virtual hardware 里用于开发和测试，将来接真实设备时保持同样的控制语义。

## 运行记录

每次运行生成独立的 `runs/<run-id>/`：

| 文件 | 内容 |
|---|---|
| `report.md` | 人类可读总结和执行模式声明 |
| `report.json` | 候选、计划、设备结果、恢复记录、源码身份 |
| `events.jsonl` | append-only 顺序事件流 |

编排层永远不会把 workflow 成功自动解释成 biological efficacy。

## 开发

```bash
python -m unittest discover -s tests -v
python -m phage_lab demo --seed 42 --time-scale 0.1
```

架构见 [docs/architecture.md](docs/architecture.md)，开发约定见 [AGENTS.md](AGENTS.md)。

## 下一步

当前优先级变成：

1. 建立真实 candidate/evidence registry 和 provenance。
2. 让 `virtual_hardware` 成为正式开发 backend，而不只是黑客松 demo。
3. 持久化 experiment / command / device-job / result 状态。
4. 如果能通过 Computer Use 控制现有软件或云端实验服务，新增独立 adapter。
5. 真正拿到实验设备后，再把同一 DeviceDriver contract 接到物理硬件。
