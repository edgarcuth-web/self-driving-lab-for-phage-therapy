# Autonomous phage R&D platform

这个项目正在从黑客松时期的 self-driving-lab demo，演进为一个面向真实研究流程的 **closed-loop phage R&D platform**：从目标细菌的表征出发，选择或组合天然噬菌体，在必要时升级到宿主范围工程，并把真实实验结果反馈到下一轮设计。

核心目标不是“让 LLM 控制机器人”，而是把科学决策与实验执行连成可追溯的 Design–Build/Acquire–Test–Learn 闭环。

```text
Host genome / isolate
        ↓
Host characterization
        ↓
HostProfile
        ↓
PhageProfile + interaction evidence
        ↓
CocktailDesign
        ↓
ExperimentSpec
        ↓
Lab orchestration
        ↓
Measurement / Phenotype
        ↓
Failure attribution
        ↓
model update / engineering escalation
        └────────────────────→ next cycle
```

## 架构原则

**Scientific intelligence 和 lab orchestration 分离。**

科学决策层回答“为什么选这些噬菌体、覆盖缺口在哪里、下一项实验最值得做什么”；控制层只负责把已经验证的 ExperimentSpec 安全、可恢复、可审计地执行到设备上。

**天然候选优先，工程化是升级路径。**

默认顺序是：天然噬菌体筛选 → cocktail 优化 → 识别剩余覆盖/耐受缺口 → 宿主范围工程 → 更深入的 defense/counter-defense 或 genome-level design。工程化不是与天然筛选平行的默认入口。

**软件 twin 模拟设备行为，不模拟生物学证据。**

virtual hardware 可以测试 job 生命周期、超时、取消、恢复和 safe-state；它的输出不构成湿实验或疗效证据。未来优先使用历史真实数据 replay 或明确测试 fixture，而不是生成看起来像实验结果的随机信号。

**PHIST 是证据源之一，不是完整 host-range 模型。**

当前 PHIST 集成保留为一个可追溯的外部分析组件。后续 interaction model 可以组合 genome、RBP/receptor、surface structure、defense/counter-defense 和实测 phenotype 等证据。

## 当前实现

| 能力 | 当前状态 |
| --- | --- |
| 固定参考快照、候选检索、序列索引 | 已实现 |
| PHIST 排序及其 provenance | 已实现 |
| 结构化规划、调度、恢复、事件日志 | 已实现 |
| 设备契约、real/virtual execution mode、safe-state | 已实现 |
| HTTP instrument adapter 范例 | 已实现 |
| HostProfile 领域模型 | 建设中 |
| PhageProfile / interaction evidence | 待实现 |
| CocktailDesign | 待实现 |
| 实测 phenotype ingestion | 待实现 |
| failure attribution / active learning | 待实现 |
| host-range engineering escalation | 待实现 |
| 仪器专用驱动与真实物理运行 | 待接入与验证 |

现有 control-plane 代码会继续保留并复用；接下来主要建设 scientific decision layer，而不是继续扩张机器人模拟器。

## 当前可运行链路

环境要求：Python 3.11+。

### 1. 获取固定参考快照

```bash
python -m phage_lab fetch-snapshot \
  --snapshot data/snapshots/inphared-1Oct2026 \
  --source inphared --version 1Oct2026 \
  --url https://millardlab-inphared.s3.climb.ac.uk/1Oct2026_data.tsv
```

### 2. 按数据库宿主注释检索候选

```bash
python -m phage_lab candidates \
  --snapshot data/snapshots/inphared-1Oct2026 \
  --host "Escherichia coli" --limit 20 --out candidates.json
```

INPHARED 的 host 字段是来源数据库记录的宿主注释，不是对目标 isolate 的实测 host range。

### 3. 可选：PHIST 排序

```bash
python -m phage_lab fetch-snapshot \
  --snapshot data/snapshots/inphared-genomes-1Oct2026 \
  --source inphared --version 1Oct2026 \
  --url https://millardlab-inphared.s3.climb.ac.uk/1Oct2026_genomes.fa

python -m phage_lab rank --candidates candidates.json \
  --sequences data/snapshots/inphared-genomes-1Oct2026 \
  --host-genome my_isolate.fasta --phist /path/to/PHIST/phist.py \
  --out ranked.json
```

PHIST 的共享 k-mer 统计量不等于感染成功概率；未被工具报告也不等于不能感染。

### 4. 验证 orchestration

```bash
python -m phage_lab run --candidates ranked.json \
  --sample-id sample-001 \
  --execution-mode virtual_hardware \
  --require-snapshot
```

virtual hardware 只验证控制链路。它不会产生可用于 biological conclusion 的证据。

## 真实设备接入

`real_hardware` 要求调用方提供声明 `simulated=False` 的设备 adapter；`virtual_hardware` 只接受 `simulated=True` 的开发 twin。两种模式必须显式选择，不会自动 fallback 或混用。

设备可通过 SDK、REST、serial、OPC-UA 或受控 GUI 接口连接。契约覆盖执行、状态查询、取消、reconciliation 与 safe-state。详见 [硬件接入文档](docs/hardware.md) 和 [HTTP adapter 范例](examples/adapters/http_instrument.py)。

## 追溯与记录

每次运行当前写入 `runs/<run-id>/`：

- `report.json`
- `report.md`
- `events.jsonl`

候选来源、分析工具、执行模式、设备结果、恢复过程和代码身份均保留 provenance。随着新领域对象落地，追溯链将扩展为：

```text
HostProfile
  → Design version
  → material batch
  → ExperimentSpec
  → measurement / phenotype
  → feedback decision
  → next design version
```

完整目标架构见 [docs/architecture.md](docs/architecture.md)，开发约束见 [AGENTS.md](AGENTS.md)。

## 开发

```bash
python -m unittest discover -s tests -v
python -m phage_lab version
```

## 许可

[Apache License 2.0](LICENSE)
