# 面向真实研究流程的 closed-loop phage R&D platform

这个项目把科学决策与实验执行连成可追溯的 Design–Build/Acquire–Test–Learn 闭环。从目标细菌表征出发，选择或组合天然噬菌体，在必要时升级到宿主范围工程，并把真实实验结果反馈到下一轮设计。

```text
Host genome / isolate
        ↓
HostProfile
        ↓
HostState H(t)
        ↓
PhageProfile + InteractionEvidence
        ↓
InteractionPrediction v1
        ↓
[next: CandidateSet / natural-phage recommender]
        ↓
CocktailDesign / scientific intent
        ↓
ExperimentSpec v2 + ExperimentArm(s)
        ↓
Lab orchestration
        ↓
arm-scoped Measurement
        ↓
Phenotype → PhenotypeComparison
        ↓
FailureAttribution / model update
        └────────────────────→ next cycle
```

## 当前范围

已实现：

- HostProfile v1；
- HostState v1：content-addressed H(t)、explicit evidence、previous-state lineage、no implicit inheritance；
- PhageProfile v1（retrieved / natural / engineered provenance）；
- InteractionEvidence v1；
- InteractionPrediction v1：exact HostState/PhageProfile/evidence/model lineage，P(adsorption) / P(productive infection) / P(resistance emergence) + uncertainty；
- CocktailDesign v1 与 conservative PHIST screening baseline；
- ExperimentSpec v2 / ExperimentArm：control / treatment、0/1/N phage、conditions、expected readouts；
- MaterialBatch v1 与 test-ready batch binding；
- Measurement v2：spec-bound 结果按 ExperimentArm 摄取并保留 arm-specific material lineage；
- Phenotype v2 + PhenotypeComparison v1：单 arm interpretation 与显式 arm-vs-arm comparison；
- 固定参考快照、候选检索、序列索引；
- PHIST 排序及结构化 interaction evidence；
- 调度、恢复、事件日志；
- real/virtual device boundary 与 safe-state；
- HTTP instrument adapter 示例。

待实现：

- host characterization analyzers；
- failure attribution / active learning；
- host-range engineering；
- 仪器专用驱动与真实物理运行。

## 关键边界

- Scientific decision layer 决定“测什么、为什么”；orchestrator 只负责执行已验证的 ExperimentSpec。
- HostProfile 是稳定 identity/characterization anchor；HostState H(t) 是时间标记的动态状态快照，不能把旧状态默认为当前状态。
- HostState 未出现的 component 代表 unknown，不代表 assessed negative；每个出现的 component 必须引用 admitted evidence。
- 默认先评估天然 phage，再做 cocktail；工程化由明确的 coverage / resistance gap 触发。
- virtual hardware 只模拟设备行为，不产生 biological evidence。
- PHIST 是 interaction evidence 的一个来源，不等于 host-range probability。
- 只有 InteractionPrediction 层可以输出 probability-shaped biological predictions；每个 estimated probability 必须同时给 uncertainty interval 与 uncertainty method。
- 当前仓库没有把 PHIST 硬映射为概率的“假模型”；evidence-only baseline 会显式输出 not_estimated。
- database candidate / accession 不是 MaterialBatch；物理实验要引用明确的 batch identity 与 QC 状态。
- workflow success 不会自动把 Measurement 标成 QC-valid；virtual Measurement 永远不能支持 Phenotype。

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

### HostState H(t)

`HostProfile` 不承担“当前状态”的职责。动态状态单独写入不可变 `HostState`：

```bash
python -m phage_lab host-state \
  --host-profile host-profile.json \
  --host-state-id isolate-001-state \
  --as-of 2026-10-16T12:00:00+00:00 \
  --state-input host-state-input.json \
  --out host-state.json
```

`host-state-input.json` 只含 `components`、`evidence`、`limitations`。component domain 当前包括 receptor/surface/defense state、physiology、antimicrobial state、phage exposure、phenotype history 与 environment；每个 component 必须引用同一 snapshot 内的 evidence ID。Measurement / Phenotype 可以通过代码适配器转换为 HostState evidence reference，适配器只复制 artifact ID/hash/timestamp，不解释生物学结果。

新的 H(t+1) 使用 `--previous-host-state` 指向旧 snapshot，但**不会自动继承**旧 components。调用方必须重新声明在 t+1 仍然成立的动态状态；否则它们回到 unknown。这是为了防止历史 phenotype、培养条件或 defense state 被错误当作“当前事实”。

### InteractionPrediction v1

InteractionPrediction 是 Evidence 与 recommender/optimizer 之间的预测层。每条 prediction 固定：

- exact HostState record ID + content hash；
- exact PhageProfile ID + profile-content fingerprint；
- exact supporting InteractionEvidence IDs；
- model / rule producer name、version、parameters，以及可选 model artifact SHA-256；
- prediction timestamp。

v1 有三个固定 target：

```text
P(adsorption)
P(productive infection)
P(resistance emergence)
```

每个 target 要么是 `estimated`，此时必须提供 0–1 probability、uncertainty lower/upper 和 uncertainty method；要么是 `not_estimated`，此时禁止塞入占位概率。

仓库目前没有一个经过校准的 biological predictor。只有 PHIST / source signals 时，应显式生成 unresolved prediction：

```bash
python -m phage_lab interaction-prediction \
  --host-state host-state.json \
  --phage-profile phage-profile.json \
  --interaction-evidence interaction-evidence.json \
  --prediction-id prediction-001 \
  --evidence-only-unresolved \
  --out interaction-prediction.json
```

这会保留 evidence lineage，但三个概率全部为 `not_estimated`。它不会把 shared k-mer signal 伪装成 infection probability。

真正模型的输出可以通过 `--prediction-input model-output.json` 摄取；输入必须同时给三类 target、mechanistic explanation、limitations 和 producer provenance。模型可以预测没有 pair-specific InteractionEvidence 的 unseen pair，但这种 evidence absence 必须保持显式，不能伪造 pair evidence。

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

### 6. 建立 ExperimentSpec v2 / ExperimentArm

CocktailDesign 仍可作为一个上游 source，但不再是 ExperimentSpec 的必需父对象：

```bash
python -m phage_lab experiment-spec \
  --cocktail-design cocktail-design.json \
  --experiment-id experiment-001 \
  --out experiment-spec.json
```

该路径默认生成显式 `host-control` 与 `cocktail-treatment` arms，并保留 CocktailDesign ID/hash 作为 source reference。

也可以直接从通用 arm JSON 创建 single-phage 或其他比较实验：

```bash
python -m phage_lab experiment-spec \
  --arms arms.json \
  --experiment-id experiment-single-001 \
  --objective "Compare one phage arm with its host control." \
  --out experiment-spec.json
```

每个 `ExperimentArm` 锁定 role、target HostProfile、0/1/N 个 PhageProfile、conditions 与 expected readouts。ExperimentSpec 仍不包含 device assignment；orchestrator 只能执行已经冻结的 arm intent。v1 序列化 spec 需要重新生成成 v2。

### 7. 注册 MaterialBatch v1

MaterialBatch 表示真实跟踪的物理批次，不是数据库 candidate。示例只登记 metadata：

```bash
python -m phage_lab material-batch \
  --batch-id phage-batch-001 \
  --material-type phage \
  --profile-id NC_000866.4:v1 \
  --material-source-kind acquired \
  --material-source-reference "LIMS:phage-batch-001" \
  --quality-status released \
  --quality-evidence "LIMS:qc-001" \
  --out phage-batch-001.json
```

host 与每个 phage member 都需要自己的 batch record。正式 real-hardware spec-run 只接受 `released` 且 `available/reserved` 的唯一匹配 batch；`released` 或 `rejected` 状态必须带 quality evidence reference。多个 batch 可由 LIMS/上游系统汇总为 `material-batches.json` 数组。

### 8. 执行 locked ExperimentSpec

```bash
python -m phage_lab run \
  --experiment-spec experiment-spec.json \
  --candidates ranked.json \
  --material-batches material-batches.json \
  --genome my_isolate.fasta \
  --sample-id sample-001 \
  --execution-mode virtual_hardware \
  --require-snapshot
```

spec-bound run 只解析 ExperimentSpec 锁定的成员。提供 MaterialBatch 时，report 与 device payload 会记录 exact batch IDs。virtual mode 即使绑定真实 batch metadata，也只用于 lineage 测试，不声明物理消耗；formal `real_hardware + ExperimentSpec` 没有完整 test-ready batches 时会在 dispatch 前拒绝。

未提供 `--experiment-spec` 时，旧 candidate-based `run` 仍保留作兼容路径。

### 9. 按 ExperimentArm 摄取 Measurement v2

spec-bound run 的 measurement-producing device result 必须返回按 arm 分开的结果。摄取时显式选择一个 arm：

```bash
python -m phage_lab measurement \
  --run-report runs/<run-id>/report.json \
  --measurement-id measurement-control-001 \
  --arm-id host-control \
  --step measure \
  --qc-status valid \
  --qc-evidence "LIMS:measurement-qc-control-001" \
  --out measurement-control.json
```

同一 run 的 treatment arm 需要独立摄取成另一个 Measurement。Measurement v2 记录 ExperimentSpec、ExperimentArm、host、该 arm 的 phage membership、device/QC lineage，并只引用该 arm 实际需要的 MaterialBatch：host-only control 只保留 host batch；treatment arm 保留 host + 该 arm 的 phage batches。virtual result 仍可摄取，但 `evidence_class=none`。

### 10. 建立单-arm Phenotype v2

```bash
python -m phage_lab phenotype \
  --experiment-spec experiment-spec.json \
  --measurements measurement-treatment.json \
  --arm-id cocktail-treatment \
  --phenotype-id phenotype-treatment-001 \
  --phenotype-type growth_response \
  --phenotype-outcome graded \
  --phenotype-value 0.42 \
  --interpretation "Assessor-defined treatment-arm interpretation." \
  --assessor manual-review \
  --assessor-version 1 \
  --out phenotype-treatment.json
```

Phenotype v2 只能消费同一 ExperimentSpec、同一 ExperimentArm、physical execution、`qc_status=valid` 且 material lineage 一致的 Measurement。control arm 合法拥有零个 phage；不能把 control 与 treatment Measurements 混成一个 Phenotype。

### 11. 显式比较两个 arm phenotype

```bash
python -m phage_lab phenotype-comparison \
  --experiment-spec experiment-spec.json \
  --baseline-phenotype phenotype-control.json \
  --comparator-phenotype phenotype-treatment.json \
  --comparison-id comparison-001 \
  --comparison-type treatment_vs_host_control \
  --comparison-outcome reduced_signal \
  --comparison-value -0.35 \
  --interpretation "Assessor-stated comparison of admitted arm phenotypes." \
  --assessor manual-review \
  --out comparison.json
```

`PhenotypeComparison` 不根据数值自动判断 efficacy。它只锁定两个不同 arm 的 Phenotype ID/hash、comparison type、assessor 明确声明的 outcome/value/interpretation。两个 source Phenotype 必须属于同一 ExperimentSpec 且具有相同 `phenotype_type`。

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
  → HostState H(t)
  → PhageProfile + InteractionEvidence
  → InteractionPrediction
  → source artifact(s) / scientific intent
  → ExperimentSpec v2 + ExperimentArm(s)
  → MaterialBatch
  → arm-scoped Measurement
  → Phenotype
  → PhenotypeComparison
  → Feedback
  → next decision
```

架构见 [docs/architecture.md](docs/architecture.md)，开发约束见 [AGENTS.md](AGENTS.md)。

## 开发

```bash
python -m unittest discover -s tests -v
python -m phage_lab version
```

## License

[Apache License 2.0](LICENSE)
