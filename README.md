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

## 候选从哪来

候选由 provider 从**固定快照**里检索。快照是下载一次、算好哈希、旁边配一份 manifest 的文件；之后每次运行都查这份固定文件，而不是上游今天恰好返回什么。两次同样的运行看到同样的候选，报告里的 provenance 指向一个能再取回来的版本。

下载和运行是分开的两步：编排过程中永远不联网。

```bash
# 1. 取一份 INPHARED 快照（只做一次）
python -m phage_lab fetch-snapshot \
  --snapshot data/snapshots/inphared-1Oct2026 \
  --source inphared --version 1Oct2026 \
  --url https://millardlab-inphared.s3.climb.ac.uk/1Oct2026_data.tsv

# 网络到不了上游时，先手工下好，再登记（--source-uri 仍记录真实上游地址）
python -m phage_lab fetch-snapshot \
  --snapshot data/snapshots/inphared-1Oct2026 \
  --source inphared --version 1Oct2026 \
  --from-file ~/Downloads/1Oct2026_data.tsv \
  --source-uri https://millardlab-inphared.s3.climb.ac.uk/1Oct2026_data.tsv

# 2. 按宿主检索候选
python -m phage_lab candidates \
  --snapshot data/snapshots/inphared-1Oct2026 \
  --host "Escherichia coli" --limit 20 --out candidates.json

# 3. 跑，并且要求每条候选都必须来自快照
python -m phage_lab run --candidates candidates.json \
  --sample-id sample-001 --execution-mode virtual_hardware --require-snapshot

# 或者一步到位，直接从快照取候选再跑
python -m phage_lab run --snapshot data/snapshots/inphared-1Oct2026 \
  --host "Escherichia coli" --sample-id sample-001 \
  --execution-mode virtual_hardware --require-snapshot
```

快照在加载时会重新算一遍哈希，和 manifest 对不上就拒绝使用——本地文件被改过、下错了、传输截断了都会在这里拦住。

## 候选记录必须带来源

实验路径只接受带可追溯来源的候选。每条记录都要有 `source_db`、`accession`、`retrieved_at`（ISO 8601）和 `source_uri`，缺一项就拒绝。来自快照的记录再加 `snapshot_version` 和 `snapshot_sha256`：

```json
{
  "id": "NC_000866.4",
  "accession": "NC_000866.4",
  "description": "Escherichia phage T4",
  "recorded_host": "Escherichia coli",
  "host_annotation_source": "depositor_metadata",
  "source_db": "inphared",
  "retrieved_at": "2026-10-15T00:00:00+00:00",
  "source_uri": "https://millardlab-inphared.s3.climb.ac.uk/1Oct2026_data.tsv",
  "snapshot_version": "1Oct2026",
  "snapshot_sha256": "…"
}
```

这是白名单，不是黑名单。按命名规范去拒（`SIM-` 前缀之类）只能拦住那些老老实实给自己贴标签的假数据，所以不用那种做法。

两个 snapshot 字段要么都有要么都没有——只写一半是追不回去的。`--require-snapshot` 让它们成为该次运行的硬性要求。默认不强制，是因为实验室自己分离的株也有正当来源，但没有快照。

## provider 报告什么、不报告什么

provider 只转述源数据库的记录。它不打分、不排序、不预测感染。

特别是 INPHARED 的 `Host` 字段是**提交者登记的宿主注释**，不是实验测定的 host range；记录里用 `recorded_host` 和 `host_annotation_source: depositor_metadata` 标明这一点。把它当成"这些噬菌体能感染这株菌"是错的。真正的排序要等接入 PHIST / iPHoP 这类经过独立验证的工具。

`--candidates` 读的是别人取好的记录，所以不走 provider 时，文件里的 provenance 只和写文件的人一样可靠；加 `--require-snapshot` 至少能挡住凭空手写的那一类。

## 候选数量

一个噬菌体和六个噬菌体的 cocktail 都是正当实验，所以 plan 选几个候选由 `--select-min` / `--select-max`（库内是 `selection_size`）决定，默认 1 到 3。

## 当前边界

- `biology.py`：FASTA 校验和输入摘要，只保留哈希与统计，不保留序列或 header。
- `snapshots.py`：外部参考数据的固定本地副本，带 checksum manifest。
- `candidates.py`：从快照检索候选并盖 provenance 的 provider。
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

## 许可

[Apache License 2.0](LICENSE)。可以自由使用、修改、分发，包括商业用途，含明确的专利授权。按自己的硬件改、拿去做别的东西，都没问题。

分发时保留版权与许可声明，并标注你做过的修改即可。

### 没有担保

许可证第 7、8 条写明：软件按现状提供，不附带任何形式的担保，贡献者不承担任何损害赔偿责任。

这一点在这里比通常更重要。**本项目编排的是实验室设备。**其中没有任何部分经过安全性验证、临床验证或针对危险物料的验证，它产出的任何运行记录都不构成生物学有效性证据。把它接到物理仪器上的人，需要自行负责风险评估、联锁保护和机构审批。

## 下一步

1. 接已发表的 host-range 排序工具（PHIST / iPHoP / CHERRY）当 baseline，并定下评测数据集和指标。在那之前，候选的顺序不代表任何生物学判断。
2. 再加一个 provider（PhageScope 或 RefSeq viral），顺便验证 provider 抽象是否站得住。
3. 持久化 experiment / command / device-job / result 状态（SQLite 够用）。
4. 如果能通过 Computer Use 控制现有软件或云端实验服务，新增独立 adapter。
5. 真正拿到实验设备后，再把同一 DeviceDriver contract 接到物理硬件。
