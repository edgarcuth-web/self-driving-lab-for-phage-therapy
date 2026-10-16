# Self-driving lab for phage therapy

一套可审计的实验编排系统：**让 AI 操控设备完成"这组噬菌体对这株细菌有没有效"的湿实验，而人不必接触有毒试剂。**

设计成可以按自己的硬件改。你有什么设备就接什么设备，没有的部分用软件 device twin 顶着，整条控制链照样跑得通、测得到。

Apache License 2.0。

## 这个项目在赌什么

判断噬菌体是否有效，本来是一件重复、枯燥、而且要反复接触试剂的工作。它值得交给机器——但要交得出去，前提不是"能自动跑完"，而是**跑完之后你知道到底发生了什么**。

所以这个仓库里几乎所有的设计力气都花在三件事上：

**模拟硬件可以，模拟证据不行。** 没有机械臂的时候，设备动作可以由软件 twin 执行；但虚拟读数会被标成 `evidence: "none"`，不能当实验或疗效证据，报告标题直接变成"虚拟硬件运行报告"。编排成功永远不会被自动解释成生物学有效。

**软件停下来 ≠ 台面是安全的。** 一次运行中途停下，可能留下枪头里吸着有毒液体、夹爪夹着打开的平板、加热块还开着。所以每个真实设备 driver 必须声明失败时它的硬件会怎么做，控制器在每条中止路径上都会请求进入安全状态，报不出来就写"状态未知、需要人工处理"。这是这个仓库最想留给后来者的一条东西。

**超时只代表不知道，不代表失败。** 不知道的时候不能重复不可逆动作。控制器先去问设备权威状态，拿不到取消确认就不重试、不换机。

## 现在能用什么、还缺什么

| | 状态 |
|---|---|
| 实验编排、调度、故障 reconciliation / failover | 可用，有测试覆盖 |
| safe-state 契约与物理状态报告 | 可用，有测试覆盖 |
| virtual hardware（软件 device twin） | 可用，可端到端跑完 |
| 候选检索（INPHARED 快照 + provenance） | 可用；列名 alias 未对真实 export 核过 |
| host-range 排序（PHIST） | 可用，对真实 PHIST 1.2.1 验证过 |
| append-only 事件流、运行报告、代码 provenance | 可用 |
| **真实设备 adapter** | **只有范例，没有任何实际设备的实现** |
| **排序的评测** | **没有。接了工具，但没有东西证明它在你的场景下够用** |
| 自制的组合感染预测模型 | 没有，只留了接口位置 |
| 状态持久化（崩溃后续跑、多样本并行） | 没有 |

最后几行是实话：**这个系统现在还没有驱动过任何一台真实的机器。** 控制层、安全契约、证据边界都做好了并且测过，但"接上你的机械臂"这一步需要你写那个 adapter。[docs/hardware.md](docs/hardware.md) 是为此写的，[examples/adapters/http_instrument.py](examples/adapters/http_instrument.py) 是一个能跑的范例。

## 五分钟跑一遍

不需要任何硬件，也不需要 API key。

```bash
python -m phage_lab run --candidates candidates.json \
  --sample-id sample-001 --execution-mode virtual_hardware
```

`execution_mode` 没有默认值。调用方没说清楚期望哪种硬件就什么都拿不到，而且系统不会从 `real_hardware` 悄悄退回 twin。

完整链路（候选来源 → 排序 → 运行）：

```bash
# 1. 取一份候选库快照（只做一次；下载和运行是分开的，编排过程中不联网）
python -m phage_lab fetch-snapshot \
  --snapshot data/snapshots/inphared-1Oct2026 \
  --source inphared --version 1Oct2026 \
  --url https://millardlab-inphared.s3.climb.ac.uk/1Oct2026_data.tsv

# 2. 按宿主检索候选，每条自动带上可追溯的来源
python -m phage_lab candidates --snapshot data/snapshots/inphared-1Oct2026 \
  --host "Escherichia coli" --out candidates.json

# 3. 用已发表的工具排序（需要再取一份序列快照）
python -m phage_lab rank --candidates candidates.json \
  --sequences data/snapshots/inphared-genomes-1Oct2026 \
  --host-genome my_isolate.fasta --phist /path/to/PHIST/phist.py \
  --out ranked.json

# 4. 跑，并要求每条候选都必须来自快照
python -m phage_lab run --candidates ranked.json --sample-id sample-001 \
  --execution-mode virtual_hardware --require-snapshot
```

网络到不了上游时，先手工下载再用 `--from-file` 登记，`--source-uri` 仍记录真实上游地址。快照在加载时会重新算哈希，和 manifest 对不上就拒绝使用。

## 接你自己的硬件

完整说明见 **[docs/hardware.md](docs/hardware.md)**。要点是整个系统对你的设备只有五个问题：

| 方法 | 含义 |
|---|---|
| `write(command)` | 开始执行，返回设备自己的 job id；对同一 `command_id` 必须幂等 |
| `read(job_id)` | 去问设备现在什么状态，不许查缓存；拿不到就抛 `DeviceUnavailable` |
| `wait(job_id)` | 阻塞到结束，超时不许取消 |
| `cancel(job_id)` | 只有设备确认了才返回 `True` |
| `enter_safe_state(reason)` | 进入安全状态，并报告是否确认到位 |

传输方式随意：vendor SDK、REST、串口、OPC-UA，或者受控的 GUI 操作。

范例可以直接跑起来看（对着一个本地替身服务，包含超时、取消、safe state 三条路径）：

```bash
python examples/adapters/http_instrument.py
```

### safe state 是强制的

`simulated=False` 的 driver 必须声明失败时它的硬件会怎么做，否则 `real_hardware` 模式拒绝运行：

```python
"safe_state": {
    "policy": "park_and_release",   # 或 contained_hold / operator_required
    "retains_hazard": False,
    "description": "Parks axes clear of the deck and ejects the tip to waste.",
}
```

`contained_hold`（原地冻结）和 `operator_required`（必须人工介入）不允许声明 `retains_hazard: False`——原地停住的设备还握着它原来握着的东西。

设备没确认安全状态时，报告写 `status: "unknown"`、`operator_action_required: true`，而不是暗示台面已经清空。`status` 取所有设备里最差的那个，因为人走到台子前面面对的是全部设备，不是它们的平均值。

**这个仓库提供编排和可审计性，不提供任何安全认证。** `enter_safe_state` 不是急停。它让"失败时物理上会发生什么"变成一个必须回答并记录的问题，但它不替代围封、通风、真实的物理急停，以及你所在机构的审批。接真设备前请看 docs/hardware.md 末尾的检查清单。

## 诚实地说排序能做到什么

候选顺序由具名的外部工具决定，**或者干脆没有顺序**：工具找不到或跑失败就直接报错，绝不退回启发式／字母序／数据库行序然后管它叫"排序"。`report["candidate_ranking"]` 一定说明这次是哪种。

但要讲清楚边界：

- PHIST 的统计量是 phage 与 host 基因组之间的**共享 k-mer**。这和 host range 相关，但不是对它的测量。代码里不存在把 p 值转成感染成功概率的路径，往 `ranking` 块里加名字像 probability / likelihood / efficacy 的字段会被校验拒掉。
- 工具没报告某个候选，只代表没有这一信号，**不代表它不能感染**。
- PHIST 是 species 级方法，而 phage therapy 真正需要的是 strain 级 host range。这个差距换个工具补不上，得靠湿实验数据回流。
- INPHARED 的 host 字段是提交者登记的注释，不是实验测定的 host range，记录里用 `recorded_host` 和 `host_annotation_source: depositor_metadata` 标明。
- **还没有评测。** 下一步要定 benchmark 数据集和指标，在那之前这套排序只是"有工具支持的顺序"，不是"经过验证的顺序"。

## 运行记录

每次运行生成独立的 `runs/<run-id>/`：

- `report.md` — 人类可读总结、执行模式声明、设备物理状态
- `report.json` — 候选及其来源、排序出处、计划、设备结果、恢复记录、源码身份
- `events.jsonl` — append-only 顺序事件流

编排层永远不会把 workflow 成功自动解释成 biological efficacy。

## 代码结构

- `biology.py` — FASTA 校验与输入摘要，只保留哈希和统计，不保留序列或 header
- `devices.py` — 设备契约，含 safe-state 声明
- `workflow.py` — 候选校验、执行模式校验、planner、调度、reconciliation、物理状态账本
- `snapshots.py` — 外部参考数据的固定本地副本，带 checksum manifest
- `candidates.py` — 从快照检索候选并盖 provenance 的 provider
- `sequences.py` — 按 accession 索引序列快照
- `ranking.py` — 调用外部工具做 host-range 排序，自身不含排序逻辑
- `virtual_hardware.py` — 软件 device twin
- `agents.py` — 只在给定候选／设备集合内做结构化决策，没有直接的硬件权限
- `records.py` — append-only 事件、运行报告、执行 provenance

故障注入在 `tests/support.py`，不在生产代码里：调度器的恢复逻辑需要测试覆盖，但程序本身不需要会弄坏自己的能力。

```bash
python -m unittest discover -s tests -v
```

架构说明见 [docs/architecture.md](docs/architecture.md)，开发约定见 [AGENTS.md](AGENTS.md)。

## 想帮忙的话，最缺这些

1. **一个真实设备的 adapter。** 任何移液工作站、读板机、机械臂都算。第一个真实 adapter 会暴露一堆契约层面的问题，这比再加一个功能有价值得多。
2. **排序的评测。** benchmark 数据集（RefSeq-VHDB / MetaHiC-VHDB）、指标（hit@k、按宿主属分层、temporal split 防泄漏）。
3. **第二个 ranker**（iPHoP 或 CHERRY）做对照，顺便验证 ranker 抽象站不站得住。
4. **状态持久化**，这样崩溃后能续跑、能多样本并行。SQLite 够用。
5. 第二个候选 provider（PhageScope 或 RefSeq viral）。

如果你接了自己的硬件、而 `safe_state` 这套契约在你的设备上说不通，那是最值得提的 issue——那说明契约设计得不对，而不是你的设备不对。
