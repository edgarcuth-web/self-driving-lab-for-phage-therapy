# Self-driving lab for phage therapy

从目标细菌基因组出发，整合 **Bioinformatics 设计、Synbio 制备、真实硬件测试和结果反馈**，建设自主噬菌体研发系统。

## 系统目标

```text
人类输入细菌基因组与研究目标
                ↓
Bioinformatics：候选噬菌体与鸡尾酒设计
                ↓
Synbio：材料获取、核酸合成与实体制备
                ↓
自动化测试：真实设备执行与实验数据采集
                ↓
分析与学习：评价结果，反馈下一轮设计
```

设计支持多条路径：筛选已有噬菌体、安排鸡尾酒组合、寻找或提出互补候选，以及提出新的或改造后的基因组候选。不同路径可以组合使用，并共享设计版本、材料身份和实验记录。

Synbio 根据候选情况安排库存调用、外部获取或合成与制备任务，将通过质量确认的实体材料交付测试系统。实验结果与制备结果分别反馈，驱动下一轮研究。

## 当前进度

| 能力 | 当前状态 |
| --- | --- |
| 参考快照、候选检索、序列索引 | 已实现 |
| PHIST 排序、结构化规划、调度与恢复 | 已实现 |
| 设备契约、事件日志与运行报告 | 已实现，提供 HTTP adapter 范例 |
| 仪器专用驱动与真实实验运行 | 待接入与验证 |
| 多路径设计、Synbio 材料与制备管理 | 待实现 |
| 实测结果反馈、模型评测与闭环学习 | 待实现 |

现有代码提供数据与控制基础。软件 twin 用于开发测试；项目交付目标是真实设备上的设计—制备—测试—学习闭环。

## 快速开始：现有候选与编排链路

环境要求：Python 3.11+。以下命令演示已实现的数据检索与开发测试流程。

```bash
# 1. 下载固定参考快照
python -m phage_lab fetch-snapshot \
  --snapshot data/snapshots/inphared-1Oct2026 \
  --source inphared --version 1Oct2026 \
  --url https://millardlab-inphared.s3.climb.ac.uk/1Oct2026_data.tsv

# 2. 按数据库宿主注释检索候选
python -m phage_lab candidates \
  --snapshot data/snapshots/inphared-1Oct2026 \
  --host "Escherichia coli" --limit 20 --out candidates.json

# 3. 用开发用设备 twin 验证编排链路
python -m phage_lab run --candidates candidates.json \
  --sample-id sample-001 --execution-mode virtual_hardware --require-snapshot
```

快照加载时验证校验和，候选保留来源与版本。用 `--select-min` / `--select-max` 设置选择数量，默认 1–3 个。

### PHIST 排序（可选）

安装 PHIST 后，下载序列快照并排序：

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

运行时将 `--candidates` 改为 `ranked.json`。PHIST 路径也可通过 `PHIST_PATH` 或 `PATH` 配置。排序记录工具版本、参数和输入哈希；共享 k-mer 是工具统计量。未排序时记录为 `source_order`，工具缺失或失败会报错。

## 真实设备接入

`real_hardware` 要求通过 Python API 提供声明 `simulated=False` 的设备 adapter；`virtual_hardware` 使用声明 `simulated=True` 的开发用 twin。每次运行必须显式指定模式，两者不会自动切换。

设备可通过 SDK、REST、serial 或 OPC-UA 等方式连接，契约覆盖执行、状态查询、取消和安全状态确认。详见 [硬件接入文档](docs/hardware.md) 与 [HTTP adapter 范例](examples/adapters/http_instrument.py)。

## 记录与开发

当前每次运行生成 `runs/<run-id>/`，包含 `report.md`、`report.json` 和追加式 `events.jsonl`，记录候选来源、执行模式、设备结果、恢复过程和代码身份。

```bash
python -m unittest discover -s tests -v
python -m phage_lab version
```

完整系统分层、Synbio 职责、数据交接与实施里程碑见 [架构文档](docs/architecture.md)；开发规则见 [AGENTS.md](AGENTS.md)。

## 许可

[Apache License 2.0](LICENSE)
