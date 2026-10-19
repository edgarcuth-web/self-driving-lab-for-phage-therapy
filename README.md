# Closed-loop phage R&D platform

把科学决策、实验执行和结果判读连接成可追溯的 Design–Build/Acquire–Test–Learn 流程。

当前实现的是**反馈驱动的筛选软件闭环**：记录输入与预测，生成冻结的实验设计，摄取经过 QC 的结果，形成显式 prediction-vs-outcome 学习记录，并选择下一轮尚未解决的筛选问题。生物学表征分析（首个真实分析器为 PADLOC）及其来源追踪也归本仓库所有；模型专属 embedding、训练、校准和推理留在独立模型仓库。可对同一预测 cohort 做描述性 calibration 评估；尚无自动模型训练、自动重校准或真实仪器运行验证。

## 当前能力

| 部分 | 已实现 | 限制 |
| --- | --- | --- |
| 输入与证据 | HostProfile、HostState、PhageProfile、参考快照、PHIST evidence | 未运行 analyzer 的特征保持 unknown；PHIST 不是感染概率 |
| 科学决策 | InteractionPrediction 输入契约、CandidateSet、PHIST cocktail baseline | unresolved prediction 不填占位概率；尚无疗效优化器 |
| 实验设计 | ExperimentSpec v2、control/treatment arms、MaterialBatch binding | 记录意图与材料来源；不替用户定义实验方法 |
| 执行 | 调度、日志、超时核对、取消恢复、虚拟设备、HTTP adapter 示例 | CLI 默认不配置真实驱动；虚拟设备不产生生物学证据 |
| 反馈与学习 | Measurement、Phenotype、Comparison、FailureAttribution、LearningObservation、CalibrationReport、下一轮选择 | label 必须显式声明；calibration 仅描述评估，不训练模型或更新 H(t) |

主路径：

```text
HostState + PhageProfile + InteractionEvidence
  → InteractionPrediction → CandidateSet
  → ExperimentSpec → execution + MaterialBatch
  → Measurement → Phenotype / Comparison → FailureAttribution
  ├→ LearningObservation → CalibrationReport
  └→ feedback-screening decision → next ExperimentSpec
```

CocktailDesign 是 ExperimentSpec 的另一种可选来源；单噬菌体筛选不需要先组成 cocktail。

## 本地检查

### 临床工作流前端（离线模拟）

```bash
python -m phage_lab dashboard
```

Windows 可双击 `start-dashboard.bat`。浏览器打开 `http://127.0.0.1:8765`；
端口占用时加 `--port 8766`，不自动打开浏览器时加 `--no-browser`。

深色工作流界面演示：**病人取样 → 样本 metadata → 模拟细菌分离库 →
全部模拟分离菌 → 并行噬菌体 / 抗生素匹配**。噬菌体分支继续模拟约 7 天制备，
随后展示 main 的筛选、实验设计、测试、反馈概念。可切换样本、编辑 metadata、
暂停/继续、查看节点输入输出和导出 JSON 快照。画布较宽时可横向滚动。

点击「一键导览此病例」进入演示模式：隐藏配置侧栏，放大工作流文字，
自动聚焦取样、检测、信号复核、双路匹配、制备、实验闭环与报告。
混合/单菌病例在 1× 下导览约 2 分 12 秒；未匹配病例约 1 分 10 秒并在复核处停止。
讲解条支持暂停/继续、下一章节和病例切换；「结束导览」保留当前结果供手动探索，
「退出演示模式」或 Esc 返回工作台并停止自动推进。速度可在工作流工具栏调整。
时间轴分别展示 D+3 返回的抗生素候选与 D+3–10 的噬菌体制备；这里的天数为
模拟场景时间，导览压缩播放。主流程完成仍显示低支持候选及未分类信号的复核数量。
导览结束与实际报告生成状态独立，报告未返回时仍显示等待/生成状态。

细菌检测按 mNGS 片段比对路径模拟：展示代表性人工 DNA 片段、唯一读段数、
人工参考窗覆盖率、比对一致性、样本/阴性对照比和未校准的 0–100 检测置信评分。
评分权重及分档仅为演示设定，不是临床确诊概率、验证阈值或置信区间。
在工作流检测节点下方及检测结果下方均有「发现未命名细菌」复核模块。
默认混合样本保留未分类细菌样信号；它不表示已发现新菌种，也不自动匹配候选药物。
单菌场景无未分类信号，未匹配场景保留低支持的待复核条目。
基因片段与参考窗均为人工序列，不是真实菌株序列或 PCR 引物。

该界面使用本地合成数据，未接入真实分离库、药敏分析、科学模块或设备，
不会创建领域实验对象。`ABX-DEMO` / `PHG-DEMO` 为虚构编号；制备约 7 天是
演示场景设定，候选不代表临床建议或疗效。

流程结束后可自动生成 **Kimi K3 临床格式报告草稿**：展开页面中的「Kimi Code API 配置」，
输入 Kimi Code 密钥并保存。模型固定为 `k3`，调用官方 `https://api.kimi.com/coding/v1`；
也可在启动服务前设置 `KIMI_CODE_API_KEY`。密钥只保存在服务进程内存，不写入项目、
浏览器存储或导出报告；关闭服务后重新配置。未配置 API 时离线演示照常工作。

启用报告后，本机服务会发送本次样本 metadata、模拟分离菌、候选匹配及流程状态到 Kimi，
不发送原始 FASTA。生成失败会明确显示原因，不伪造模型报告；可手动重试。
检测置信评分、指标及未分类信号会进入报告摘要；人工片段碱基及参考碱基不发送给 Kimi。
报告支持 Markdown 下载，并标注来源模型、生成时间、输入指纹、模拟数据及医师复核要求。
模拟分离菌、噬菌体候选、抗生素候选分别用表格列出；各模块右上角可复制该模块，
总报告右上角可复制完整报告。模块复制使用制表符分列，便于粘贴到表格软件。
未匹配的流程会生成待复核草稿，不宣称实验完成、实测药敏、诊断或疗效。

前端验收：`python -m unittest discover -s tests -p test_dashboard.py -v`；
流程模型验收：`node --test tests/test_dashboard_model.cjs`（仅测试需要 Node 18+）。
导览与时间轴验收：`node --test tests/test_presentation.cjs`。
报告验收：`python -m unittest discover -s tests -p test_clinical_reports.py -v`（mock 接口，不消耗 API）。
`sh scripts/smoke.sh` 运行上述检查及 JS 语法检查，可用 `NODE_BIN` 指定测试用的 Node。

### 核心 CLI 检查

需要 Python 3.11+。核心编排使用标准库；序列登记与 FeatureArtifact 校验需要 `jsonschema`，真实 PADLOC 分析使用 `envs/padloc.yml` 中固定的外部工具环境。从仓库根目录运行：

```bash
python -m phage_lab version
python -m unittest discover -s tests -v
```

以下仅检查文件流转，使用仓库内的 toy FASTA，不执行设备或生成实验结果：

```bash
python -m phage_lab host-profile \
  --genome examples/toy_genome.fasta \
  --sample-id local-check --out local-data/local-check/host-profile.json

python -m phage_lab host-state \
  --host-profile local-data/local-check/host-profile.json \
  --host-state-id local-check-state \
  --as-of 2026-10-16T12:00:00+00:00 \
  --out local-data/local-check/host-state.json
```

生成的 profile 没有已评估的生物学特征；空 HostState 不表示阴性。

## 真实生物学表征分析：PADLOC

本仓库拥有序列资源登记、FeatureArtifact v1 和首个真实分析器 PADLOC v2.0.0。
它对已登记且与 HostState 基因组指纹一致的 FASTA 执行实际分析，固定
PADLOC-DB v2.0.0，保存原生输出、日志、数据库树指纹和来源记录。没有命中只表示
该数据库和这次运行范围内未检出，不证明细菌不存在防御系统；当前结果尚未自动提升为
HostProfile 的已评估阴性。安装、运行和限制见
[`docs/padloc-adapter.md`](docs/padloc-adapter.md)。

```bash
conda env create -f envs/padloc.yml
conda activate phage-padloc
python -m phage_lab annotate-host-defense-padloc --help
```

跨仓库边界的目标是由 SDL 输出冻结的 ModelInputBundle，包含获准的科学注释、
筛查状态和来源信息；模型仓库只负责模型专属表示、训练、评估、权重和推理。
当前 ModelRequest/ModelResult v1 仍是过渡接口，尚未实现 ModelInputBundle v1。

## 使用与开发

- [CLI 操作指南](docs/usage.md)：各阶段命令、输入要求与后续轮次。
- [架构与领域契约](docs/architecture.md)：对象关系、证据语义和校验边界。
- [外部模型接口](docs/model-interface.md)：独立模型仓库与实验闭环之间的版本化 JSON 契约。
- [设备接口](docs/hardware.md)：驱动、safe-state 和 HTTP adapter。
- [OpenRouter 配置](docs/openrouter.md)：可选的受限编排决策。
- [开发约束](AGENTS.md)：修改代码时必须保持的规则。

`python -m phage_lab <command> --help` 只显示该命令的参数。

正式执行以冻结的 ExperimentSpec 为入口。旧 candidate-based run 保留为兼容入口；新集成应使用 spec。真实执行需要显式配置驱动和 test-ready MaterialBatch，不会从虚拟模式自动切换。

每次运行在 `runs/<run-id>/` 写入 `report.json`、`report.md` 和 `events.jsonl`。原始 FASTA 和标题默认不发送给外部模型。

## 下一步

1. 用真实实验结果积累 LearningObservation，并建立独立训练/验证数据切分。
2. 在独立模型仓库中完成可重现的模型拟合、held-out evaluation 与 calibration；本仓库只接收通过模型接口绑定的结果。
3. 在预测器经过验证后增加 prediction-driven cocktail optimization，再评估工程化升级。

## License

[Apache License 2.0](LICENSE)
