# Closed-loop phage R&D platform

把科学决策、实验执行和结果判读连接成可追溯的 Design–Build/Acquire–Test–Learn 流程。

当前实现的是**反馈驱动的筛选软件闭环**：记录输入与预测，生成冻结的实验设计，摄取经过 QC 的结果，再选择下一轮尚未解决的筛选问题。尚无经过校准的感染预测器、自动模型训练或真实仪器运行验证。

## 当前能力

| 部分 | 已实现 | 限制 |
| --- | --- | --- |
| 输入与证据 | HostProfile、HostState、PhageProfile、参考快照、PHIST evidence | 未运行 analyzer 的特征保持 unknown；PHIST 不是感染概率 |
| 科学决策 | InteractionPrediction 输入契约、CandidateSet、PHIST cocktail baseline | unresolved prediction 不填占位概率；尚无疗效优化器 |
| 实验设计 | ExperimentSpec v2、control/treatment arms、MaterialBatch binding | 记录意图与材料来源；不替用户定义实验方法 |
| 执行 | 调度、日志、超时核对、取消恢复、虚拟设备、HTTP adapter 示例 | CLI 默认不配置真实驱动；虚拟设备不产生生物学证据 |
| 反馈 | Measurement、Phenotype、Comparison、FailureAttribution、下一轮选择 | 当前是固定上下文的反馈筛选策略，不训练模型或更新 H(t) |

主路径：

```text
HostState + PhageProfile + InteractionEvidence
  → InteractionPrediction → CandidateSet
  → ExperimentSpec → execution + MaterialBatch
  → Measurement → Phenotype / Comparison → FailureAttribution
  → feedback-screening decision → next ExperimentSpec
```

CocktailDesign 是 ExperimentSpec 的另一种可选来源；单噬菌体筛选不需要先组成 cocktail。

## 本地检查

需要 Python 3.11+；核心代码只使用标准库。从仓库根目录运行：

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

## 使用与开发

- [CLI 操作指南](docs/usage.md)：各阶段命令、输入要求与后续轮次。
- [架构与领域契约](docs/architecture.md)：对象关系、证据语义和校验边界。
- [设备接口](docs/hardware.md)：驱动、safe-state 和 HTTP adapter。
- [OpenRouter 配置](docs/openrouter.md)：可选的受限编排决策。
- [开发约束](AGENTS.md)：修改代码时必须保持的规则。

`python -m phage_lab <command> --help` 只显示该命令的参数。

正式执行以冻结的 ExperimentSpec 为入口。旧 candidate-based run 保留为兼容入口；新集成应使用 spec。真实执行需要显式配置驱动和 test-ready MaterialBatch，不会从虚拟模式自动切换。

每次运行在 `runs/<run-id>/` 写入 `report.json`、`report.md` 和 `events.jsonl`。原始 FASTA 和标题默认不发送给外部模型。

## 下一步

1. 用可获得的真实实验结果验证反馈筛选流程。
2. 数据条件具备后接入经过校准和评估的预测器。
3. 在证据支持时增加 prediction-driven cocktail optimization，再评估工程化升级。

## License

[Apache License 2.0](LICENSE)
