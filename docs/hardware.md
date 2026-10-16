# 接入你自己的硬件

这份文档写给要把自己的设备接进来的人。架构说明见 [architecture.md](architecture.md)，这里只讲一件事：怎么写一个 adapter，以及为什么每条要求长这样。

可运行的范例在 [`examples/adapters/http_instrument.py`](../examples/adapters/http_instrument.py)。它对着一个本地替身服务跑，包含超时、取消和 safe state 三条路径：

```bash
python examples/adapters/http_instrument.py
```

复制那个文件，把四个 `_request` 调用换成你设备的接口，就是一个 adapter。

## 整个系统对你的设备只有五个问题

传输方式可以是 vendor SDK、REST、串口、OPC-UA，甚至受控的 GUI 操作。这些差别很大，但要回答的问题是同一组：

| 方法 | 你要实现的意思 |
|---|---|
| `write(command)` | 开始执行这条指令，返回设备自己的 job id |
| `read(job_id)` | 这个 job 现在到底什么状态（去问设备，不要查缓存） |
| `wait(job_id)` | 阻塞到结束，**超时不许取消** |
| `cancel(job_id)` | 请求停止，只有设备确认了才返回 `True` |
| `enter_safe_state(reason)` | 让机器进入安全状态，并报告是否确认到位 |

`describe()` 另外要报告身份和能力，`close()` 只释放本地资源。

## 四条容易写错、而且写错会动到液体的地方

### timeout 不是失败，是"不知道"

控制器有自己的步骤超时。超时只说明没按时拿到结果，**不说明物理动作失败了**。

所以 `wait()` 里不要自己设截止时间然后取消。一个在超时时顺手取消的 driver，会把"还不知道"变成"真的中止了"——而中止是一个物理动作。超时之后，控制器会调 `read(job_id)` 去问权威状态，再决定重试还是换机。

### `read()` 必须去问设备

控制器调 `read()` 的时机，恰恰是它已经搞不清这个 job 怎么样了的时候。这时候返回本地缓存比不返回更糟。

拿不到就抛 `DeviceUnavailable`，不要猜"大概做完了"。编造出来的"大概"正是让控制器重复一次移液的原因。注意区分两种情况：

- 设备返回了 4xx/5xx：设备是通的，它拒绝了 → `DeviceError`
- 完全没回应：job 可能在跑、可能做完了、可能没开始 → `DeviceUnavailable`

### `write()` 必须对 `command_id` 幂等

控制器超时后会用**同一个 `command_id`** 重投。如果你这时候又起一个 job，就是第二次物理动作。

同一个 `command_id` 再来，返回已经存在的 job id。范例里用的是内存字典，**真实 adapter 应该持久化这个映射**——进程重启的时候恰恰是你最需要它的时候。

### `cancel()` 只有确认了才返回 True

乐观地返回 `True`，会让控制器在第一次还在动的时候就开始第二次尝试。

控制器的不变量是：没拿到取消确认，就不重试、不换机。你返回 `True` 就是在替它做这个保证。

## safe state：软件停下来 ≠ 台面是安全的

这是这个项目和一般编排框架最不一样的地方，也是整个设计里最该被 fork 的人注意的地方。

一次运行中途停下，可能留下的是：枪头里还吸着有毒液体、夹爪还夹着打开的平板、加热块还开着。**编排层停止是软件行为，物理危害不会因此消失。**

所以每个 `simulated=False` 的 driver 必须在 `describe()` 里声明一个 `safe_state` 块，否则 `real_hardware` 模式直接拒绝运行。这不是可选的礼节——这个答案决定了一个人能不能走到台子前面。

```python
"safe_state": {
    "policy": "park_and_release",
    "retains_hazard": False,
    "description": "Parks axes clear of the deck and ejects the tip to waste.",
}
```

### 三种 policy

这是**硬件的属性，不是偏好**。选哪个取决于你的设备实际能做什么。

`park_and_release` — 设备能自己到达一个明确的安全状态：液体排掉或回到密封容器、枪头弹到废液、各轴停到不挡人的位置。不需要人介入。`retains_hazard` 可以是 `False`。

`contained_hold` — 设备原地冻结，继续握着它手上的东西。这只在有围封的前提下算安全；**人打开围封就会直接碰到危害**。`retains_hazard` 必须是 `True`。

`operator_required` — 设备没法让自己安全，必须人来处理，穿戴对应试剂要求的防护。`retains_hazard` 必须是 `True`。

后两种声明 `retains_hazard: False` 会被校验拒绝。原地停住的设备还握着原来握着的东西，让 driver 声称相反的事情，就是在低估别人的暴露风险。

`description` 也是必填的，因为它会出现在运行报告里——给那个要走过去的人看的，不是给程序看的。

### 报不出来，就要说报不出来

`enter_safe_state()` 返回 `{"entered": False, ...}` 或者抛 `SafeStateError`，**是一个完全正当的答案，而且比谎称成功好得多**。

设备没确认时，报告会写明物理状态未知、需要人工处理，而不是暗示台面已经清空了。下面这些情况都会被记成 `unknown`：

- driver 没实现 `enter_safe_state`
- 返回值里没有 `entered` 布尔字段
- 抛了 `SafeStateError`、`DeviceUnavailable`，或者任何别的异常（driver 自己的 bug 也不会被用来掩盖危害）

### 控制器什么时候会问

只要有步骤被放弃就会问：设备失联、取消没被确认、agent 决定中止、重试次数用尽，以及任何非成功结束的运行。设备失联的情况它问不到，那就直接记成 `unknown` 并说明原因。

成功完成的运行不会发 safe-state 请求，报告里是 `not_requested`。

### 报告里长什么样

`report.json` 的 `physical_state`：

```json
{
  "status": "unknown",
  "operator_action_required": true,
  "devices": {
    "liquid-handler-1": {
      "entered": false, "policy": "park_and_release", "retains_hazard": false,
      "status": "unknown",
      "detail": "Device became unreachable during 'infect'; neither the job outcome nor the physical state could be confirmed."
    }
  },
  "note": "At least one device did not confirm its safe state. Treat the apparatus as potentially holding hazardous material and follow the reagent's handling procedure before approaching it."
}
```

`status` 取三个设备里最差的那个：一台设备没确认，整台装置就是 `unknown`。因为人走到台子前面，面对的是全部设备，不是它们的平均值。

`report.md` 里这一节会排在"未完成原因"前面，标题会变成"需要人工处理"。

## 先在 virtual hardware 上跑

twin 也声明 safe state，走的是同一条代码路径。所以在接真设备之前，你可以把调度、reconciliation、failover、safe state 全都跑一遍：

```bash
python -m phage_lab run --candidates candidates.json --sample-id test-001 \
  --execution-mode virtual_hardware
```

`tests/support.py` 里有故障注入（hang / response-lost / unreachable），可以用来验证你的 adapter 在这些情况下的行为。注意生产代码里没有故障注入——系统不需要会弄坏自己的能力。

## 接真设备之前的检查清单

这些是代码能帮你挡住的：

- [ ] `describe()["simulated"]` 是 `False`，而且不是在撒谎
- [ ] `safe_state` 三个字段都填了，policy 和硬件实际能力对得上
- [ ] 同一个 `command_id` 重投不会起第二个 job，而且这个映射**持久化**了
- [ ] `wait()` 超时不取消
- [ ] `cancel()` 只在设备确认后返回 `True`
- [ ] 失联抛 `DeviceUnavailable`，不猜状态
- [ ] `read()` 去问设备，不查缓存

这些是代码帮不了你的，但在动有毒试剂之前必须有：

- [ ] 围封、通风、废液处置符合你所在机构对这个试剂的要求
- [ ] 真实的物理急停，独立于这套软件——**软件的 `enter_safe_state` 不是急停**
- [ ] `operator_required` 情况下的人工处置流程，写下来并且操作的人知道
- [ ] 你所在机构的生物安全/伦理审批。噬菌体工作本身通常风险较低，但具体取决于你用的菌株、试剂和场地，这件事不是一个仓库能替你判断的

最后一条值得说明白：这个仓库提供的是编排和可审计性，**不提供任何安全认证**。`safe_state` 契约让"失败时物理上会发生什么"变成必须回答的问题并记录下来，它不代替围封、急停和机构审批。
