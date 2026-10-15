# Self-driving lab for phage therapy

这个项目采用 **hybrid self-driving lab** 路线：数据、候选来源、分析和决策尽量做成真实可追溯的；在没有机械臂、移液工作站、读板机等设备时，硬件执行层使用软件 device twin。

关键原则是：**可以模拟硬件，不模拟证据。**

## 两种执行模式

执行模式必须显式声明，没有默认值。系统不会从 `real_hardware` 退回 `virtual_hardware`。

### `virtual_hardware` — 当前主要开发模式

真实、可追溯的候选记录进入真实 workflow 和 planner，设备动作由软件 twin 执行。

```bash
python -m phage_lab run \
  --genome examples/toy_genome.fasta \
  --candidates my_candidates.json \
  --sample-id sample-001 \
  --execution-mode virtual_hardware
```

所有设备结果都标记为 simulated，报告同时记录 `execution_mode`、`physical_execution = false`，并写明没有发生真实湿实验、虚拟测量不能作为实验或疗效证据。

### `real_hardware` — 未来设备接入模式

调用方式相同，但必须显式提供 `simulated=False` 的真实设备 adapter：

```python
from phage_lab.workflow import run_experiment

report, directory = await run_experiment(
    genome_path, output_root,
    sample_id="sample-001",
    candidates=candidate_records,
    devices=real_device_adapters,
    workflow={"prepare": (), "infect": ("prepare",), "measure": ("infect",)},
    agent=planner,
    execution_mode="real_hardware",
)
```

具体设备可以通过 vendor SDK、REST、serial、OPC-UA，未来也可以通过受控的 Computer Use / GUI adapter 接入。没有提供真实 adapter 时，`real_hardware` 直接拒绝运行，不会悄悄换成 twin。

## 候选记录必须带来源

实验路径只接受带可追溯来源的候选。每条记录都要有 `source_db`、`accession`、`retrieved_at`（ISO 8601）和 `source_uri`，缺一项就拒绝：

```json
[
  {
    "id": "NC_000866.4",
    "source_db": "RefSeq",
    "accession": "NC_000866.4",
    "retrieved_at": "2026-10-15T00:00:00+00:00",
    "source_uri": "https://www.ncbi.nlm.nih.gov/nuccore/NC_000866.4"
  }
]
```

这是白名单，不是黑名单。按命名规范去拒（`SIM-` 前缀之类）只能拦住那些老老实实给自己贴标签的假数据，所以不用那种做法。

`--candidates` 目前只是读取别人已经取好的记录，不自己去查库，所以文件里的 provenance 只和写文件的人一样可靠。下一步是做一个自己查库、自己盖 provenance 的 CandidateProvider。

## 候选数量

一个噬菌体和六个噬菌体的 cocktail 都是正当实验，所以 plan 选几个候选由 `--select-min` / `--select-max`（库内是 `selection_size`）决定，默认 1 到 3。

## 当前边界

- `biology.py`：FASTA 校验和输入摘要，只保留哈希与统计，不保留序列或 header。
- `workflow.py`：候选 provenance 校验、执行模式校验、planner、调度、reconciliation。
- `devices.py`：统一设备契约。
- `virtual_hardware.py`：软件 device twin。
- `agents.py`：只在提供的候选/设备集合中做结构化决策。
- `records.py`：append-only events、运行报告和代码 provenance。

故障注入在 `tests/support.py`，不在生产代码里：调度器的 reconciliation 和 failover 需要测试覆盖，但程序本身不需要会弄坏自己。

## 可靠性原则

timeout 只代表没有及时收到结果，不代表物理动作失败。控制器先 reconciliation，再决定是否 retry/failover；状态未知时停止，避免重复不可逆动作。

这些规则在 virtual hardware 里用于开发和测试，将来接真实设备时保持同样的控制语义。

## 运行记录

每次运行生成独立的 `runs/<run-id>/`：

- `report.md` — 人类可读总结和执行模式声明
- `report.json` — 候选及其来源、计划、设备结果、恢复记录、源码身份
- `events.jsonl` — append-only 顺序事件流

编排层永远不会把 workflow 成功自动解释成 biological efficacy。`evaluate()` 判断读数是否为虚拟的依据是设备自己报告的 `simulated` 标志，不是识别某个单位字符串。

## 开发

```bash
python -m unittest discover -s tests -v
python -m phage_lab version
```

架构见 [docs/architecture.md](docs/architecture.md)，开发约定见 [AGENTS.md](AGENTS.md)。

## 下一步

1. 做 `CandidateProvider`：从真实噬菌体基因组库检索候选，自己盖 provenance 戳。
2. 接已发表的 host-range 排序工具（PHIST / iPHoP / CHERRY）当 baseline。
3. 持久化 experiment / command / device-job / result 状态（SQLite 够用）。
4. 如果能通过 Computer Use 控制现有软件或云端实验服务，新增独立 adapter。
5. 真正拿到实验设备后，再把同一 DeviceDriver contract 接到物理硬件。
