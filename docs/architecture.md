# Architecture

## 1. 目标

系统以目标细菌 isolate/genome 与研究目标为输入，把科学决策、材料获取/制备、自动化实验与结果学习连接成可追溯的闭环。

目标不是单独构建“会控制设备的 agent”，而是构建一个 **autonomous phage R&D platform**：

```text
Host genome / isolate
        ↓
Host characterization
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
FailureAttribution
        ↓
model update / engineering escalation
        └────────────────────→ next cycle
```

当前代码已经具备较成熟的 control-plane 基础：参考数据、候选检索、PHIST、调度恢复、设备契约、执行记录和 provenance。接下来优先建设 scientific decision layer，而不是继续扩张虚拟机器人能力。

## 2. 两层智能必须分离

### Scientific decision layer

回答：

- 目标 host 是什么；
- 哪些 phage-host 相互作用证据存在；
- 哪些天然候选最值得测试；
- cocktail 为什么这样组合；
- 哪些覆盖缺口或抗性路径仍未解决；
- 下一轮最有信息价值的实验是什么；
- 是否有充分依据升级到工程化路径。

其输出必须是结构化、可版本化、可追溯的科学对象，而不是直接设备命令。

### Lab orchestration layer

回答：

- 哪些操作组成 ExperimentSpec；
- 哪台设备执行；
- 任务依赖是什么；
- job 是否真正完成；
- timeout 后如何 reconciliation；
- 是否可以重试/切换设备；
- 中止时设备处于什么 safe state；
- 哪些 artifact 与本次运行关联。

它不能自行发明 biological efficacy，也不能把 workflow success 解释成 biological success。

```text
Scientific decision
      ↓
validated ExperimentSpec
      ↓
Orchestrator
      ↓
DeviceDriver(s)
```

## 3. 核心领域对象

以下对象逐步替代跨模块传递的匿名 dict。

| 对象 | 作用 |
| --- | --- |
| `HostProfile` | 目标 host 的版本化表征 |
| `PhageProfile` | 天然或设计 phage 的版本化表征 |
| `InteractionEvidence` | phage-host 关系的一条可追溯证据或模型输出 |
| `CocktailDesign` | cocktail 成员、目标、依据、版本 |
| `ExperimentSpec` | 要验证什么，以及允许的实验边界 |
| `MaterialBatch` | 实体 phage/host/material 的批次与质量状态 |
| `Measurement` | 与具体实验/设备/原始 artifact 绑定的测量 |
| `Phenotype` | 对有效测量进行的生物学解释 |
| `FailureAttribution` | 对失败机制的显式假设及证据 |
| model/analysis record | 工具、模型、参数、输入和评测版本 |

完整 lineage 最终应能表达：

```text
HostProfile
    ↓
Design version
    ↓
MaterialBatch
    ↓
ExperimentSpec
    ↓
Measurement
    ↓
Phenotype / FailureAttribution
    ↓
Feedback decision
    ↓
next Design version
```

已用于 build/test 的设计版本不可覆盖修改。

## 4. Host characterization

Host genome 是科学闭环的入口，但 raw FASTA 本身不是 HostProfile。

Host characterization pipeline 将本地序列分析结果组织为版本化 profile。目标 profile 可以逐步容纳：

- taxonomy / strain identity；
- receptor candidates；
- capsule、LPS 或其他 surface structures；
- anti-phage defense systems；
- AMR；
- virulence context；
- historical susceptibility / phenotype references。

关键语义：

**unknown != assessed negative。**

如果某一 feature class 从未分析，应明确为 `unknown`。只有一个有身份和版本的分析过程实际评估过该 feature class，才允许表达“已评估但未发现”。

原始 FASTA 默认不发送给外部 LLM。需要序列的本地 bioinformatics tool 可以读取它；外部 reasoning component 默认接收结构化 profile 与必要 provenance。

第一阶段只建立 `HostProfile v1` 的 schema、版本、序列摘要、feature 状态和 analysis provenance，不假装已经存在 receptor/defense predictor。

## 5. Phage characterization 与 InteractionEvidence

天然 phage、实验室 collection 和 engineered/generated phage 必须区分 provenance。

`PhageProfile` 后续可以容纳：

- sequence/design identity；
- natural/retrieved/generated/engineered provenance；
- RBP/tail annotations；
- receptor evidence；
- counter-defense annotations；
- known host-range phenotype references；
- production/material references。

`InteractionEvidence` 用于把“证据”与“最终设计决策”分离。可以来自：

- database annotation；
- PHIST 或其他 genome-based tool；
- sequence/embedding model；
- RBP-receptor model；
- defense/counter-defense model；
- physical experiment。

PHIST 当前保留为其中一个 evidence producer。共享 k-mer statistics 不是 infection probability；未报告不是 negative phenotype。

## 6. CocktailDesign

Cocktail design 不应由 orchestration agent 简单“取排名前 N 个”。

未来 `CocktailDesign` 至少需要保留：

- design version；
- target HostProfile；
- member PhageProfile versions；
- supporting InteractionEvidence；
- objective/rationale；
- coverage assumptions；
- uncertainty / unresolved gaps；
- model/optimizer identity。

设计目标可以逐步扩展为多目标问题，例如 coverage、mechanistic complementarity、cross-resistance risk 与实验信息价值；具体数值模型必须有独立评测与 provenance。

LLM 可以解释或协调 bounded decisions，但不能凭文本推理把数据库 annotation 变成感染概率。

## 7. Engineering escalation

工程化不是默认入口。

推荐 escalation：

```text
natural phage retrieval
        ↓
interaction evaluation
        ↓
cocktail optimization
        ↓
remaining gap identified?
        │
        ├─ no → test / learn
        │
        └─ yes
             ↓
   mechanism-supported engineering
             ↓
   host-range / RBP-level path
             ↓ if unresolved intracellular block
   defense-counter-defense path
             ↓ only when justified
   broader genome-level design
```

是否进入某一级 engineering 由证据与明确 gap 触发，并产生新的 design provenance；不得把 engineered design 冒充 retrieved natural candidate。

## 8. Synbio 与材料

Synbio 把版本化设计转化为可测试实体材料。

需要区分：

- design；
- acquisition/order；
- synthesis product；
- build/preparation batch；
- final experimental material；
- quality status；
- inventory/reservation/consumption。

设备任务“完成”不等于材料“可用”。进入测试的 material 必须有明确身份、对应 design version、质量依据和可用量，或者返回明确 incomplete 状态。

同一 design 可以有多个 material batch；实验必须记录实际使用的 batch。

## 9. 自动化实验

自动化实验层接收：

```text
ExperimentSpec
+ identified MaterialBatch(es)
+ device capabilities
```

并产生：

```text
execution records
raw artifacts
processed Measurement(s)
```

控制层不负责判断疗效。

当前默认 `prepare → infect → measure` 只是 orchestrator 的早期 workflow 示例，不应成为最终领域模型。未来 workflow 应由 ExperimentSpec 派生，并通过明确 capability/adapter 执行。

## 10. Measurement、Phenotype 与 feedback

必须区分：

1. build/acquisition failure；
2. device execution failure；
3. invalid/incomplete measurement；
4. valid biological negative result；
5. valid biological positive/graded result。

只有有效 physical measurement 才能进入 phenotype analysis。

`FailureAttribution` 后续用于表达例如 adsorption-level、intracellular compatibility、kinetics 或 unknown 等机制类别，但必须携带支持证据和不确定性；不能由 workflow failure 自动推断。

feedback 决策引用原始设计、实验、分析和模型版本，并生成下一版本设计，而不是覆盖旧记录。

## 11. 设备与 control plane

现有设备边界继续保留。

`execution_mode` 必须显式指定：

- `real_hardware`：只接受 `simulated=False`；
- `virtual_hardware`：只接受 `simulated=True`；
- 禁止隐式 fallback 或混用。

DeviceDriver 契约包含 `describe`、`write`、`read`、`wait`、`cancel`、`enter_safe_state`、`close`。

timeout 表示 outcome unknown，不等于 failure。必须先查询原 job；只有确认取消后才能执行可能重复的物理动作。

真实 driver 必须声明 safe-state policy。中止/失败运行请求设备进入声明状态；未能确认时记录 `unknown`。

这些能力是平台基础设施，不是 biological intelligence。

## 12. Virtual hardware 的边界

virtual hardware 保留，用于：

- scheduler 开发；
- job lifecycle；
- timeout/reconciliation；
- cancellation；
- failover；
- safe-state；
- artifact handoff。

不应把随机 synthetic assay signal 当成科学闭环的数据源。

后续 measurement-shaped development data 优先来自：

1. historical physical data replay；
2. explicit deterministic fixtures；
3. unit-test-only stubs。

所有此类数据都必须明确与 physical evidence 分离。

## 13. 当前代码映射

| 当前模块 | 已实现职责 | 下一步定位 |
| --- | --- | --- |
| `biology.py` | FASTA 校验、hash、长度/contig 摘要 | HostProfile 的 genome input |
| `host_profile.py` | HostProfile v1 | scientific domain foundation |
| `snapshots.py`, `candidates.py` | 参考快照、来源候选 | natural candidate source |
| `sequences.py` | accession 序列索引 | analysis input |
| `ranking.py` | PHIST 调用、排名 provenance | InteractionEvidence producer 之一 |
| `agents.py` | bounded orchestration plan/recovery | 保持 orchestration，不承担 biological design |
| `workflow.py` | 验证、调度、恢复 | ExperimentSpec execution engine |
| `devices.py` | device contract | 保留 |
| `virtual_hardware.py` | 开发 twin | 仅模拟设备行为 |
| `records.py` | 运行 event/report | 扩展到科学 lineage |

## 14. 实施顺序

按可合并 vertical slice 推进：

1. **HostProfile v1**：schema、unknown/assessed semantics、序列摘要、serialization/provenance。
2. **PhageProfile v1**：自然/设计 provenance 分离。
3. **InteractionEvidence**：先把 PHIST 包装成明确 evidence，再接其他模型。
4. **CocktailDesign v1**：设计版本、成员、依据、目标与 uncertainty。
5. **ExperimentSpec integration**：scientific design → existing orchestrator。
6. **Measurement/Phenotype ingestion**：接真实历史数据，再接真实设备数据。
7. **FailureAttribution**。
8. **Active learning / experiment selection**。
9. **Engineering escalation**。
10. **更多真实设备和 Synbio integration**。

每个阶段都应保持 main 可运行，并有测试覆盖。避免持续多轮、不可合并的大重构。

## 15. 当前完成状态

已实现：

- reference snapshot / candidate retrieval；
- sequence indexing；
- PHIST integration；
- orchestration plan/recovery；
- real/virtual device boundary；
- safe-state；
- append-only run events 和报告；
- HTTP instrument adapter example。

尚未实现：

- 完整 host characterization analyzers；
- PhageProfile；
- 通用 InteractionEvidence；
- 真正 cocktail optimizer；
- material ledger；
- physical phenotype ingestion；
- feedback learning；
- failure attribution；
- engineering design；
- instrument-specific physical validation。

文档中必须持续区分目标架构与当前实现，不能把计划中的接口写成已经具备的能力。
