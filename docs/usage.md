# CLI 操作指南

从仓库根目录运行，Python 3.11+。先用 [README 的本地检查](../README.md#本地检查)
确认环境。`python -m phage_lab <command> --help` 列出该命令的参数。

下面是接口示例，需要调用方提供相应文件；不是可直接执行的端到端实验。
证据语义、校验规则与选择策略统一见 [architecture](architecture.md)。

## 1. 建立 host identity 和状态

```bash
python -m phage_lab host-profile \
  --genome my_isolate.fasta --sample-id isolate-001 --out host-profile.json

python -m phage_lab host-state \
  --host-profile host-profile.json --host-state-id isolate-001-state \
  --as-of 2026-10-16T12:00:00+00:00 \
  --state-input host-state-input.json --out host-state.json
```

`host-state-input.json` 包含 `components`、`evidence`、`limitations` 三个数组。
component 必须引用同一快照中的 evidence ID。可省略该输入生成空状态。
新状态可用 `--previous-host-state` 引用旧状态，但需要重新声明当前 components。

## 2. 固定参考数据并获取 PhageProfiles

```bash
python -m phage_lab fetch-snapshot \
  --snapshot data/snapshots/inphared-1Oct2026 --source inphared --version 1Oct2026 \
  --url https://millardlab-inphared.s3.climb.ac.uk/1Oct2026_data.tsv

python -m phage_lab candidates \
  --snapshot data/snapshots/inphared-1Oct2026 --host "Escherichia coli" \
  --limit 20 --out candidates.json

python -m phage_lab phage-profiles \
  --candidates candidates.json --out phage-profiles.json
```

也可以用 `fetch-snapshot --from-file <file> --source-uri <upstream-reference>` 固定本地数据。
数据库 host 注释不代表目标 isolate 的实测 host range；转换得到的 provenance 是 retrieved。

需要 PHIST evidence 时，额外准备 genome snapshot 和本地 PHIST：

```bash
python -m phage_lab fetch-snapshot \
  --snapshot data/snapshots/inphared-genomes-1Oct2026 --source inphared --version 1Oct2026 \
  --url https://millardlab-inphared.s3.climb.ac.uk/1Oct2026_genomes.fa

python -m phage_lab rank --candidates candidates.json \
  --sequences data/snapshots/inphared-genomes-1Oct2026 \
  --host-genome my_isolate.fasta --host-profile host-profile.json \
  --phist /path/to/PHIST/phist.py --out ranked.json
```

ranked 输出保留兼容的 `ranking` block，并在每个候选中附上 `interaction_evidence`。
需要将单条 evidence/profile 交给下一步时，从该输出/数组中保存对应完整对象。

## 3. 记录 prediction 并选择筛选候选

没有校准模型时，每个 pair 显式生成 unresolved prediction：

```bash
python -m phage_lab interaction-prediction \
  --host-state host-state.json --phage-profile phage-profile.json \
  --interaction-evidence interaction-evidence.json --prediction-id prediction-a \
  --evidence-only-unresolved --out prediction-a.json
```

`--interaction-evidence` 可重复，也可省略。已有模型输出时，用
`--prediction-input model-output.json` 替换 `--evidence-only-unresolved`。
输入必须包含 `probabilities`（adsorption / productive_infection / resistance_emergence）、
`mechanistic_explanation`、`limitations`、`producer`。每个 estimated target 必须带 uncertainty。

```bash
python -m phage_lab recommend-phages \
  --host-state host-state.json --phage-profiles phage-profiles.json \
  --interaction-prediction prediction-a.json --interaction-prediction prediction-b.json \
  --candidate-set-id screen-001 --max-candidates 3 --exploration-slots 1 \
  --out candidate-set.json

python -m phage_lab experiment-spec \
  --candidate-set candidate-set.json --experiment-id screen-experiment-001 \
  --objective "Compare each selected single-phage arm with the host control." \
  --expected-readout biological_phenotype --out experiment-spec.json
```

每个 profile 只提供一个选定 prediction。`--expected-readout` 可重复；
`--conditions conditions.json` 可提供共同条件，缺省为空。入选项生成独立 single-phage arms 和 host control。

其他 spec 来源：

| 来源 | 命令参数 | 说明 |
| --- | --- | --- |
| 通用 arms | `--arms arms.json --objective "..."` | 输入完整 ExperimentArm 数组 |
| CocktailDesign | `--cocktail-design cocktail-design.json` | 生成 host-control / cocktail-treatment |
| 后续反馈决策 | `--active-learning-decision next-decision.json` | 复制初始实验上下文，见最后一节 |

来源四选一，都需要 `--experiment-id` 和 `--out`。旧 v1 spec 需要重新生成成 v2。
兼容 PHIST cocktail baseline 的创建命令：

```bash
python -m phage_lab cocktail-design \
  --host-profile host-profile.json --phage-profiles phage-profiles.json \
  --candidates ranked.json --cocktail-id cocktail-001 --cocktail-min 2 --cocktail-max 3 \
  --out cocktail-design.json
```

## 4. 登记材料并执行冻结设计

以下只登记批次 metadata。host 和每个 phage 都需要自己的 batch；由上游系统汇总为数组。

```bash
python -m phage_lab material-batch \
  --batch-id phage-batch-001 --material-type phage --profile-id NC_000866.4:v1 \
  --material-source-kind acquired --material-source-reference "LIMS:phage-batch-001" \
  --quality-status released --quality-evidence "LIMS:qc-001" --out phage-batch-001.json

python -m phage_lab run --experiment-spec experiment-spec.json \
  --candidates ranked.json --material-batches material-batches.json \
  --genome my_isolate.fasta --sample-id sample-001 \
  --execution-mode virtual_hardware --require-snapshot
```

virtual 模式仅检查控制流程与 lineage，不产生实验结果或消耗批次。
真实驱动需通过 Python API 配置，见 [hardware](hardware.md)；CLI 当前没有驱动加载配置。
`real_hardware` 的 spec-run 必须绑定唯一、released 且 available/reserved 的匹配批次。
旧的无 spec candidate-based run 仍兼容；新集成使用 spec。

## 5. 摄取结果与显式判读

对 run 中每个 arm 分别摄取 Measurement，设备输出也必须按 arm 分开：

```bash
python -m phage_lab measurement \
  --run-report runs/<run-id>/report.json --measurement-id measurement-control-001 \
  --arm-id host-control --step measure --qc-status valid \
  --qc-evidence "LIMS:measurement-qc-control-001" --out measurement-control.json
```

treatment arm 同样独立摄取。下列命令要求已 admission 的 physical/QC-valid Measurements；
virtual run 的 Measurement 会保留 `evidence_class=none`，不能进入 Phenotype。

```bash
python -m phage_lab phenotype \
  --experiment-spec experiment-spec.json --measurements measurement-treatment.json \
  --arm-id single-phage-1 --phenotype-id phenotype-treatment-001 \
  --phenotype-type growth_response --phenotype-outcome graded --phenotype-value 0.42 \
  --interpretation "Assessor-defined treatment-arm interpretation." \
  --assessor manual-review --assessor-version 1 --out phenotype-treatment.json

python -m phage_lab phenotype-comparison \
  --experiment-spec experiment-spec.json --baseline-phenotype phenotype-control.json \
  --comparator-phenotype phenotype-treatment.json --comparison-id comparison-001 \
  --comparison-type treatment_vs_host_control --comparison-outcome reduced_signal \
  --comparison-value -0.35 --interpretation "Assessor-stated comparison." \
  --assessor manual-review --out comparison.json
```

control Phenotype 也需要单独创建。这里的值与说明仅展示 CLI 格式，不是实验数据或自动阈值。
使用 spec 中的实际 arm ID；cocktail source 默认 treatment ID 为 `cocktail-treatment`。

判读输入 `review-input.json`（人工声明，非实验数据）：

```json
{
  "outcome": "inconclusive",
  "criterion": "Describe the objective and decision criterion used for this review.",
  "interpretation": "The reviewed results do not resolve this criterion.",
  "limitations": ["Failure mechanism remains unknown."],
  "hypotheses": []
}
```

```bash
python -m phage_lab failure-attribution \
  --experiment-spec experiment-spec.json --arm-id single-phage-1 \
  --measurements admitted-measurements.json --phenotypes phenotype-control.json \
  --phenotypes phenotype-treatment.json --phenotype-comparison comparison.json \
  --attribution-id review-001 --attribution-input review-input.json \
  --assessor manual-review --assessor-version 1 --out failure-attribution.json
```

`--phenotypes` / `--phenotype-comparison` 可重复。Measurement 输入可为单对象或数组；
单 arm 判读可省略 comparison 和其他 arm 的 Phenotype。必须提供所有引用的 Measurement。
支持的 outcome 与 hypotheses 契约见 architecture。

## 6. 记录 prediction-vs-outcome 并评估 calibration

LearningObservation 要求 single-phage treatment Phenotype，并由 assessor 明确声明某个
prediction target 的 binary observed label。Phenotype 的 positive/negative/graded 不会自动
映射成标签。

```bash
python -m phage_lab learning-observation \
  --interaction-prediction prediction-a.json \
  --experiment-spec experiment-spec.json \
  --phenotype phenotype-treatment.json \
  --observation-id learning-001 --target productive_infection --observed true \
  --interpretation "Assessor-declared target label from the admitted phenotype." \
  --assessor manual-review --assessor-version 1 \
  --limitation "Assay-specific label; external generalization not established." \
  --out learning-001.json
```

如果原 prediction 对该 target 是 `not_estimated`，记录仍会保存为 `label_only`，
可作为后续训练证据，但不能进入 CalibrationReport。

对相同 target、相同 PredictionProducer 配置和相同 uncertainty method 的 scorable
observations 做描述性评估：

```bash
python -m phage_lab calibration-report \
  --learning-observation learning-001.json \
  --learning-observation learning-002.json \
  --report-id calibration-001 --target productive_infection \
  --out calibration-report.json
```

输出包含 sample count、mean predicted probability、observed rate、calibration gap、
Brier score 和 log loss。该命令不拟合、不重校准、不替换模型，也不更新 H(t)。

## 7. 用反馈选择下一轮

```bash
python -m phage_lab active-learn \
  --candidate-set candidate-set.json --experiment-spec initial-screening-spec.json \
  --failure-attribution failure-attribution.json \
  --screening-criterion "Describe the objective and decision criterion used for this review." \
  --decision-id screening-round-2 --out next-decision.json

python -m phage_lab experiment-spec --active-learning-decision next-decision.json \
  --experiment-id screening-round-2 --out next-experiment-spec.json
```

`initial-screening-spec.json` 必须是该 CandidateSet 初次生成的 single-phage screening spec；
criterion 要与反馈中的声明逐字匹配。`--failure-attribution` 可重复。无反馈时保存 no-feedback 决策。

继续第三轮时，仍传原始 CandidateSet 和初始 spec，增加 `--previous-decision next-decision.json`、
新的 attribution 和 decision ID。旧反馈会带入；冲突或竞争 revision 需先复核。
候选耗尽会 abstain，不能生成实验。后续 spec 不接受 objective / conditions / readout / workflow 覆盖。
改变 H(t)、上下文或候选池时要创建新的科学意图，不能自动迁移旧反馈。
