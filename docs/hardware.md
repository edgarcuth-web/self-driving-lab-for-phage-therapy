# 硬件接入

示例 adapter：[`examples/adapters/http_instrument.py`](../examples/adapters/http_instrument.py)

```bash
python examples/adapters/http_instrument.py
```

设备可以通过 SDK、REST、serial、OPC-UA 或受控 GUI 接入。driver 需要实现以下语义。

## DeviceDriver

| 方法 | 语义 |
| --- | --- |
| `describe()` | 返回设备身份、能力、`simulated` 和 safe-state 声明 |
| `write(command)` | 提交指令，返回设备 job id |
| `read(job_id)` | 向设备查询权威 job 状态 |
| `wait(job_id)` | 等待 job；超时不得自动取消 |
| `cancel(job_id)` | 只有设备确认取消后才返回 `True` |
| `enter_safe_state(reason)` | 请求设备进入声明的安全状态并返回确认 |
| `close()` | 释放本地资源；不是 safe-state 操作 |

## Required execution semantics

### Timeout

timeout 表示 **outcome unknown**，不是 failure。

超时后 controller 会调用 `read(job_id)` reconciliation。driver 不得因为本地等待超时而自行取消物理 job。

### Authoritative read

`read()` 必须查询设备，不得用本地缓存代替权威状态。

- 设备可达但拒绝请求：`DeviceError`
- 设备无法确认状态：`DeviceUnavailable`

不要猜测 job 已完成或失败。

### Execution payload

controller 在所有 driver 前统一验证 payload。

legacy run 的必需字段：

```json
{
  "sample_id": "sample-001",
  "candidate_ids": ["..."]
}
```

ExperimentSpec-bound run 会额外携带完整 arm lineage：

```json
{
  "experiment_spec_id": "experiment-001:v1",
  "experiment_spec_sha256": "...",
  "phage_profile_ids": ["..."],
  "experiment_arms": [
    {
      "arm_id": "host-control",
      "role": "control",
      "target_host": {"profile_id": "isolate-001:v1", "genome_sha256": "..."},
      "phage_profile_ids": [],
      "conditions": {},
      "expected_readouts": ["biological_phenotype"]
    }
  ],
  "material_batch_ids": ["host-batch:v1", "phage-batch:v1"]
}
```

若 spec 来自 CocktailDesign，payload 还可包含 `cocktail_design_id`。ExperimentSpec lineage 必须完整，且所有 `experiment_arms[*].phage_profile_ids` 的并集必须等于顶层 `phage_profile_ids`；driver 不得自行改变 arm membership、conditions 或 expected readouts。

对于会产生可摄取 Measurement 的 spec-bound step，device result 必须保留按 arm 分隔的结果，例如：

```json
{
  "arms": {
    "host-control": {"signal": [1.0, 1.1], "unit": "instrument_units"},
    "cocktail-treatment": {"signal": [0.2, 0.3], "unit": "instrument_units"}
  }
}
```

Measurement ingestion 会按 `arm_id` 选择对应结果；它不会把一个全局读数事后复制到多个 arms。formal real-hardware spec-run 仍会在 dispatch 前验证 host 与所有 phage 都有唯一 test-ready MaterialBatch。

### Idempotent write

同一个 `command_id` 重投必须返回原 job，而不是启动第二次物理动作。

真实 adapter 应持久化 `command_id → job_id` 映射，使进程重启后仍能 reconciliation。

### Confirmed cancellation

`cancel()` 只有在设备确认取消后才能返回 `True`。

未确认取消时，controller 不得重试或 fail over。

## Safe state

所有 `simulated=False` driver 必须在 `describe()` 中声明：

```python
"safe_state": {
    "policy": "park_and_release",
    "retains_hazard": False,
    "description": "Parks axes and releases hazardous contents to the defined safe destination.",
}
```

支持三种 policy：

| policy | 含义 | `retains_hazard` |
| --- | --- | --- |
| `park_and_release` | 设备可自行进入定义好的无残留危险状态 | 可为 `False` |
| `contained_hold` | 设备保持当前位置，危险物仍留在受控围封内 | 必须为 `True` |
| `operator_required` | 需要人工介入才能安全处理 | 必须为 `True` |

`enter_safe_state()` 至少返回：

```json
{
  "entered": true,
  "policy": "park_and_release",
  "retains_hazard": false,
  "detail": "..."
}
```

无法确认时返回 `entered: false` 或抛出错误；controller 会记录 physical state 为 `unknown`。

非成功运行会对已执行物理工作的设备请求 safe state。设备失联、safe-state 调用失败或确认无效时，都不得假设台面安全。

`enter_safe_state` 不是物理 emergency stop。

## Virtual hardware

virtual hardware 使用相同的 job/recovery/safe-state 接口，用于测试：

- timeout / reconciliation；
- cancellation；
- retry / failover；
- safe-state；
- artifact handoff。

它不执行物理动作，也不产生 biological evidence。

故障测试 seam 在 `tests/support.py`。

## Pre-flight checklist

软件侧：

- [ ] `simulated=False`
- [ ] safe-state 声明与真实硬件一致
- [ ] `command_id` 幂等且映射持久化
- [ ] `wait()` 超时不取消
- [ ] `read()` 查询设备权威状态
- [ ] `cancel()` 只在确认后返回 `True`
- [ ] 失联使用 `DeviceUnavailable`

实验设施侧：

- [ ] 围封、通风、废液处置符合场地要求
- [ ] 独立于本软件的物理急停
- [ ] 人工处置流程和 PPE 已定义
- [ ] 所需的机构生物安全/伦理审批已完成

本项目提供 orchestration 和 auditability，不提供安全认证。
