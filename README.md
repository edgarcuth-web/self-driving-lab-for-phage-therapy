# 面向真实研究流程的 closed-loop phage R&D platform

这个项目把科学决策与实验执行连成可追溯的 Design–Build/Acquire–Test–Learn 闭环。从目标细菌表征出发，选择或组合天然噬菌体，在必要时升级到宿主范围工程，并把真实实验结果反馈到下一轮设计。

```text
Host genome / isolate
        ↓
HostProfile
        ↓
PhageProfile + InteractionEvidence
        ↓
CocktailDesign
        ↓
ExperimentSpec
        ↓
Lab orchestration
        ↓
Measurement / Phenotype
        ↓
FailureAttribution / model update
        └────────────────────→ next cycle
```

## 当前范围

已实现：

- HostProfile v1；
- PhageProfile v1（retrieved / natural / engineered provenance）；
- InteractionEvidence v1；
- CocktailDesign v1 与 conservative PHIST screening baseline；
- 固定参考快照、候选检索、序列索引；
- PHIST 排序及结构化 interaction evidence；
- 调度、恢复、事件日志；
- real/virtual device boundary 与 safe-state；
- HTTP instrument adapter 示例。

待实现：

- host characterization analyzers；
- ExperimentSpec integration；
- 实测 phenotype ingestion；
- failure attribution / active learning；
- host-range engineering；
- 仪器专用驱动与真实物理运行。

## 关键边界

- Scientific decision layer 决定“测什么、为什么”；orchestrator 只负责执行已验证的 ExperimentSpec。
- 默认先评估天然 phage，再做 cocktail；工程化由明确的 coverage / resistance gap 触发。
- virtual hardware 只模拟设备行为，不产生 biological evidence。
- PHIST 是 interaction evidence 的一个来源，不等于 host-range probability。

## 快速开始

环境：Python 3.11+。

### 1. 建立 HostProfile

```bash
python -m phage_lab host-profile \
  --genome my_isolate.fasta \
  --sample-id isolate-001 \
  --out host-profile.json
```

没有 analyzer 运行时，receptors、surface structures、defense systems、AMR、virulence 保持 `unknown`。raw FASTA 不写入 profile。

### 2. 获取参考快照并检索候选

```bash
python -m phage_lab fetch-snapshot \
  --snapshot data/snapshots/inphared-1Oct2026 \
  --source inphared --version 1Oct2026 \
  --url https://millardlab-inphared.s3.climb.ac.uk/1Oct2026_data.tsv

python -m phage_lab candidates \
  --snapshot data/snapshots/inphared-1Oct2026 \
  --host "Escherichia coli" \
  --limit 20 \
  --out candidates.json
```

INPHARED 的 host 字段是数据库注释，不是目标 isolate 的实测 host range。

### 3. 转换为 PhageProfile

```bash
python -m phage_lab phage-profiles \
  --candidates candidates.json \
  --out phage-profiles.json
```

PhageProfile v1 区分三类 provenance：

- `retrieved`：来自外部数据库/参考记录；只说明记录来源，不自动断言 biological origin；
- `natural`：本地明确记录的天然 isolate，使用 collection/isolate identity；
- `engineered`：设计/工程化 phage，必须保留 parent PhageProfile lineage。

candidate 的 host query 和 PHIST ranking 不会复制进 PhageProfile；它们属于后续 `InteractionEvidence`。

### 4. 可选：PHIST 排序

```bash
python -m phage_lab fetch-snapshot \
  --snapshot data/snapshots/inphared-genomes-1Oct2026 \
  --source inphared --version 1Oct2026 \
  --url https://millardlab-inphared.s3.climb.ac.uk/1Oct2026_genomes.fa

python -m phage_lab rank \
  --candidates candidates.json \
  --sequences data/snapshots/inphared-genomes-1Oct2026 \
  --host-genome my_isolate.fasta \
  --host-profile host-profile.json \
  --phist /path/to/PHIST/phist.py \
  --out ranked.json
```

PHIST 的 shared k-mer statistic 不是感染成功概率；no-match 也不是 negative phenotype。

`ranked.json` 继续保留 legacy `ranking` block 以兼容现有 workflow，同时每个候选新增 `interaction_evidence`。提供 `--host-profile` 时，CLI 会先确认 profile 与 host FASTA 的规范化 genome identity 一致，再把 HostProfile ID 写入 evidence。PHIST evidence 记录 pairwise signal、tool/version/parameters、sequence snapshot provenance 与原始统计量；候选池中的相对 `rank` 只保留在 legacy ranking，不进入 pairwise evidence。未来 scientific decision layer 应优先消费 `InteractionEvidence`。

### 5. 生成 CocktailDesign v1

```bash
python -m phage_lab cocktail-design \
  --host-profile host-profile.json \
  --phage-profiles phage-profiles.json \
  --candidates ranked.json \
  --cocktail-id cocktail-001 \
  --cocktail-min 2 \
  --cocktail-max 3 \
  --out cocktail-design.json
```

当前 baseline 只从非 engineered PhageProfile 中选择 PHIST-reported candidates，并把 cohort rank 记录为 design context。它明确保留 physical phenotype、receptor/RBP、defense/counter-defense、cross-resistance 和 phage-phage compatibility 等未解决 gap，因此不是疗效优化器，也不会用 `no_signal` 候选硬凑组合。

现有 `run` 尚未直接消费 CocktailDesign；把 design 变成受约束的 ExperimentSpec 是下一阶段。

### 6. 验证 orchestration

```bash
python -m phage_lab run \
  --candidates ranked.json \
  --sample-id sample-001 \
  --execution-mode virtual_hardware \
  --require-snapshot
```

virtual hardware 只验证控制链路。

## 真实设备

`real_hardware` 只接受 `simulated=False` 的 adapter；`virtual_hardware` 只接受 `simulated=True`。两种模式不会自动切换或混用。

设备接口见 [docs/hardware.md](docs/hardware.md)，示例见 [examples/adapters/http_instrument.py](examples/adapters/http_instrument.py)。

## 记录

每次运行写入 `runs/<run-id>/`：

- `report.json`
- `report.md`
- `events.jsonl`

目标 lineage：

```text
HostProfile
  → Design
  → MaterialBatch
  → ExperimentSpec
  → Measurement / Phenotype
  → Feedback
  → next Design
```

架构见 [docs/architecture.md](docs/architecture.md)，开发约束见 [AGENTS.md](AGENTS.md)。

## 开发

```bash
python -m unittest discover -s tests -v
python -m phage_lab version
```

## License

[Apache License 2.0](LICENSE)
