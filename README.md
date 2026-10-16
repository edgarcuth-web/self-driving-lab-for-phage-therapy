# Self-driving lab for phage therapy

面向噬菌体研究的自动化实验编排系统，支持参考数据快照、候选检索、PHIST 排序、实验调度和全流程记录。当前通过软件设备 twin 开发和测试，也可通过 adapter 接入真实设备。

## 快速开始

环境要求：Python 3.11+。在项目根目录运行以下命令。

### 1. 下载参考数据

```bash
python -m phage_lab fetch-snapshot \
  --snapshot data/snapshots/inphared-1Oct2026 \
  --source inphared --version 1Oct2026 \
  --url https://millardlab-inphared.s3.climb.ac.uk/1Oct2026_data.tsv
```

快照保存来源、版本和校验和，加载时验证文件完整性；实验运行使用本地快照。

### 2. 检索候选

```bash
python -m phage_lab candidates \
  --snapshot data/snapshots/inphared-1Oct2026 \
  --host "Escherichia coli" --limit 20 --out candidates.json
```

候选记录包含数据库、accession、检索时间和来源地址；快照候选还包含快照版本与哈希。宿主检索依据数据库中的宿主注释。

### 3. 运行工作流

```bash
python -m phage_lab run \
  --candidates candidates.json \
  --sample-id sample-001 \
  --execution-mode virtual_hardware \
  --require-snapshot
```

使用 `--select-min` / `--select-max` 设置候选选择数量，默认 1–3 个。

## PHIST 排序（可选）

安装 PHIST 后，下载序列快照并对候选排序：

```bash
python -m phage_lab fetch-snapshot \
  --snapshot data/snapshots/inphared-genomes-1Oct2026 \
  --source inphared --version 1Oct2026 \
  --url https://millardlab-inphared.s3.climb.ac.uk/1Oct2026_genomes.fa

python -m phage_lab rank \
  --candidates candidates.json \
  --sequences data/snapshots/inphared-genomes-1Oct2026 \
  --host-genome my_isolate.fasta \
  --phist /path/to/PHIST/phist.py \
  --out ranked.json
```

将运行命令中的 `--candidates` 改为 `ranked.json` 即可使用排序结果。PHIST 路径也可通过 `PHIST_PATH` 或 `PATH` 配置。

排序记录包含工具版本、参数和输入哈希。PHIST 输出的是共享 k-mer 统计量；未运行排序时，报告标记为 `source_order`。排序工具缺失或执行失败会报错。

## 执行模式

每次运行必须显式指定模式：

| 模式 | 设备 | 用途 |
| --- | --- | --- |
| `virtual_hardware` | 软件 device twin，可自动创建 | 工作流开发、调度和接口测试，结果标记为 simulated |
| `real_hardware` | 调用方提供的真实设备 adapter | 连接实际设备执行，要求设备声明 `simulated=False` |

真实设备通过 Python API 的 `devices` 参数接入，可使用 SDK、REST、serial 或 OPC-UA 等适配方式。两种模式不会自动切换。仓库提供 adapter 范例，具体设备需要实现对应驱动。

接入说明见 [硬件文档](docs/hardware.md)，可运行范例见 [HTTP adapter](examples/adapters/http_instrument.py)。设备契约包含任务执行、状态查询、等待、取消和安全状态确认；真实设备驱动需声明 `safe_state` 策略。

## 运行记录

每次运行生成 `runs/<run-id>/`：

- `report.md`：可读总结、执行模式及设备物理状态。
- `report.json`：候选来源、计划、设备结果、恢复记录和代码身份。
- `events.jsonl`：追加式事件日志。

调度器支持任务状态核对与故障恢复；超时后先查询原任务状态，再决定是否重试。

## 开发

```bash
python -m unittest discover -s tests -v
python -m phage_lab version
```

核心模块位于 `phage_lab/`：数据处理（`biology`、`snapshots`、`candidates`、`sequences`）、排序（`ranking`）、编排（`workflow`、`agents`）、设备（`devices`、`virtual_hardware`）和记录（`records`、`provenance`）。

更多说明见 [架构文档](docs/architecture.md) 和 [开发约定](AGENTS.md)。

## 后续计划

- 建立 benchmark 数据集和评测指标。
- 接入更多排序工具及候选数据源。
- 持久化实验、命令和设备任务状态。
- 接入真实实验设备。

## 许可

[Apache License 2.0](LICENSE)
