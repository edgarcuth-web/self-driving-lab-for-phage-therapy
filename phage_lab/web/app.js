"use strict";

const $ = (id) => document.getElementById(id);
const steps = ["synthesize", "prepare", "transfer", "infect", "measure"];
const names = {
  synthesize: "合成",
  prepare: "制备",
  transfer: "转运",
  infect: "感染",
  measure: "读数",
};
const statusNames = {
  waiting: "等待",
  running: "执行中",
  recovering: "恢复中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "已中断",
};
const recoveryActions = {
  cancel_and_failover: "取消并换机",
  cancel_and_retry: "取消后重试",
  abort: "停止运行",
};
const state = {
  meta: null,
  runId: null,
  events: [],
  report: null,
  history: [],
  pending: false,
  submitting: false,
  cursor: 0,
  polls: 0,
  connected: false,
  previousRunId: null,
  followActive: true,
  configuring: false,
  apiInitialized: false,
  configRevision: 0,
};

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function text(id, value) {
  $(id).textContent = value;
}
function showError(message) {
  text("error", message || "");
  $("error").hidden = !message;
}
function deviceName(id) {
  if (!id) return "设备";
  const parts = id.split("-");
  return `${names[parts[0]] || parts[0]}${parts[1] === "backup" ? "备用机" : "主机"}`;
}
async function api(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}
function selectRun(id) {
  state.runId = id;
  state.events = [];
  state.report = null;
  state.cursor = 0;
  render();
  renderHistory();
}
function setConnection(connected) {
  state.connected = connected;
  $("connection").className = `connection ${connected ? "online" : "offline"}`;
  text("connection-text", connected ? "本地调度器已连接" : "连接中断 · 正在重连");
  updateControls();
}
function updateControls() {
  const busy = state.submitting || state.pending || Boolean(state.meta?.busy);
  const needsConfig = $("agent").value === "openrouter" && !state.meta?.openrouter_ready;
  $("start").disabled = !state.connected || busy || state.configuring || needsConfig;
  $("configuration").disabled = busy || state.configuring;
  $("genome").disabled = $("reset-genome").disabled = busy;
  $("input-stage").classList.toggle("locked", busy);
  $("api-fields").disabled = !state.connected || busy || state.configuring;
  $("api-clear").disabled = !state.meta?.api_key_configured && !state.meta?.model;
  text("api-save", state.configuring ? "正在保存…" : "保存并使用 OpenRouter");
  text(
    "start-label",
    state.submitting || state.pending
      ? "正在启动…"
      : busy
        ? "实验运行中…"
        : needsConfig
          ? "请先配置 API"
          : "开始",
  );
}
function updateAgent() {
  const available = Boolean(state.meta?.openrouter_ready);
  $("openrouter-option").disabled = !available;
  $("openrouter-option").textContent = available
    ? `OpenRouter · ${state.meta.model}`
    : "OpenRouter · 未配置 API";
  text("api-state", available ? "已配置" : "未配置");
  $("api-key").required = !state.meta?.api_key_configured;
  $("api-key").placeholder = state.meta?.api_key_configured
    ? "留空保留当前密钥"
    : "粘贴你的 OpenRouter API Key";
  text(
    "api-key-note",
    state.meta?.api_key_configured
      ? "已有密钥；留空保留，填写则替换。"
      : "密钥仅保存在本次服务中，不写入文件。",
  );
  if (state.meta && !state.apiInitialized) {
    $("api-model").value = state.meta.model || "";
    $("api-settings").open = !available;
    state.apiInitialized = true;
  }
  text(
    "agent-note",
    $("agent").value === "openrouter"
      ? "使用已配置的 OpenRouter API；只发送摘要，不发送原始序列。"
      : "固定规则模式，不调用 AI。",
  );
  updateControls();
}
async function saveApiConfig(clear = false) {
  if (
    !state.connected ||
    state.configuring ||
    state.submitting ||
    state.pending ||
    state.meta?.busy
  )
    return;
  state.configuring = true;
  updateControls();
  $("api-message").hidden = true;
  try {
    const options = clear
      ? { clear: true }
      : { api_key: $("api-key").value.trim(), model: $("api-model").value.trim() };
    state.meta = await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Lab-Token": state.meta.token },
      body: JSON.stringify(options),
    });
    state.configRevision++;
    $("api-key").value = "";
    $("api-model").value = state.meta.model || "";
    // Switch provider only on an explicit save; polling never changes the user's choice.
    if (!clear) $("agent").value = "openrouter";
    updateAgent();
    showError("");
    $("api-message").className = "field-note api-success";
    text(
      "api-message",
      clear
        ? "本次配置已清除。可重新填写，或选择离线规则。"
        : "已保存并选择 OpenRouter。上传 FASTA 后点击开始。",
    );
  } catch (error) {
    $("api-message").className = "error-message";
    text("api-message", error.message);
  } finally {
    $("api-message").hidden = false;
    state.configuring = false;
    updateControls();
  }
}
function derive() {
  const stepStates = Object.fromEntries(steps.map((step) => [step, "waiting"]));
  const deviceStates = Object.fromEntries(
    steps.flatMap((step) => ["primary", "backup"].map((suffix) => [`${step}-${suffix}`, "待命"])),
  );
  let status = state.pending ? "starting" : "waiting",
    mode = null,
    started = null,
    finished = null,
    readout = null;
  const faults = new Set(),
    completed = new Set();
  let recoveryContext = null;
  for (const event of state.events) {
    const d = event.details || {};
    switch (event.event) {
      case "run_started":
        started = event.at;
        status = "planning";
        mode = d.agent;
        break;
      case "planning_requested":
        status = "planning";
        break;
      case "plan_accepted":
        status = "running";
        break;
      case "job_submitted":
        stepStates[d.step] = "running";
        deviceStates[d.device] = "执行中";
        break;
      case "fault_injected":
        faults.add(d.step);
        deviceStates[d.device] = "故障注入";
        break;
      case "job_timeout":
        stepStates[d.step] = "recovering";
        deviceStates[d.device] = "待核对";
        status = "recovering";
        break;
      case "job_reconciled":
        deviceStates[d.device] = d.state === "succeeded" ? "已完成" : "等待恢复";
        break;
      case "recovery_requested":
        recoveryContext = d;
        break;
      case "cancellation_acknowledged":
        deviceStates[d.device] = "已取消";
        break;
      case "recovery_executing":
        if (d.action === "cancel_and_failover" && recoveryContext)
          deviceStates[recoveryContext.current_device] = "已隔离";
        break;
      case "reconciliation_failed":
        deviceStates[d.device] = "失联";
        stepStates[d.step] = "failed";
        break;
      case "device_job_completed":
        deviceStates[d.device] = "已完成";
        break;
      case "step_completed":
        stepStates[d.step] = "succeeded";
        completed.add(d.step);
        status = "running";
        if (d.step === "measure") readout = d.result;
        break;
      case "run_finished":
        status = d.status;
        finished = event.at;
        break;
    }
  }
  if (state.report) {
    status = state.report.status;
    mode = state.report.agent;
    started = state.report.started_at;
    finished = state.report.finished_at;
    readout = state.report.results?.measure || readout;
  } else if (
    state.runId &&
    !state.meta?.busy &&
    state.history.find((item) => item.run_id === state.runId)?.status === "interrupted"
  ) {
    status = "interrupted";
    finished = state.events.at(-1)?.at;
  }
  if (["failed", "cancelled", "interrupted"].includes(status)) {
    for (const step of steps)
      if (["running", "recovering"].includes(stepStates[step])) stepStates[step] = "failed";
  }
  return {
    stepStates,
    deviceStates,
    status,
    mode,
    started,
    finished,
    readout,
    completed,
    faults,
    recovered: [...faults].filter((step) => completed.has(step)).length,
  };
}
function renderPipeline(view) {
  $("pipeline").replaceChildren(
    ...steps.map((step, index) => {
      const status = view.stepStates[step],
        card = node("div", `stage ${status}`),
        top = node("div", "stage-top");
      top.append(node("span", "stage-index", `0${index + 1}`));
      const label = node("span", "stage-status");
      label.append(node("span", "dot"), document.createTextNode(statusNames[status]));
      top.append(label);
      card.append(
        top,
        node("h3", "", names[step]),
        node("div", "stage-operation", step.toUpperCase()),
      );
      return card;
    }),
  );
  text("flow-caption", `${view.completed.size} / 5 步骤完成`);
}
function renderDevices(view) {
  $("devices").replaceChildren(
    ...steps.map((step) => {
      const group = node("div", "device-group");
      group.append(node("span", "device-kind", names[step]));
      for (const suffix of ["primary", "backup"]) {
        const status = view.deviceStates[`${step}-${suffix}`];
        const color =
          status === "已完成"
            ? "succeeded"
            : status === "执行中"
              ? "running"
              : ["失联", "已隔离", "故障注入"].includes(status)
                ? "failed"
                : ["待核对", "等待恢复", "已取消"].includes(status)
                  ? "recovering"
                  : "";
        const device = node("div", `device-node ${color}`);
        device.append(
          node("span", "", suffix === "primary" ? "主机" : "备用机"),
          node("span", "device-state", status),
        );
        group.append(device);
      }
      return group;
    }),
  );
}
function renderResults(view) {
  const values = view.readout?.readings;
  if (Array.isArray(values)) {
    $("readings").replaceChildren(
      ...values.map((value, index) => {
        const item = node("div", "reading"),
          meter = node("meter");
        meter.min = 0;
        meter.max = 1;
        meter.value = value;
        meter.setAttribute("aria-label", `模拟读数 ${index + 1}：${value}`);
        item.append(
          node("span", "reading-label", `READOUT 0${index + 1}`),
          node("strong", "", Number(value).toFixed(4)),
          meter,
        );
        return item;
      }),
    );
    text("quality", "模拟读数完整");
  } else {
    $("readings").replaceChildren(node("p", "empty-small", "完成测量后显示模拟读数。"));
    text(
      "quality",
      ["failed", "cancelled", "interrupted"].includes(view.status) ? "结果不完整" : "等待读数",
    );
  }
  text(
    "result-message",
    state.report?.error ||
      (values
        ? "单位：任意模拟单位。生物学结论：未评估。"
        : "报告将在运行结束后生成。"),
  );
  for (const [id, file] of [
    ["download-md", "report.md"],
    ["download-json", "report.json"],
    ["download-events", "events.jsonl"],
  ]) {
    const ready =
      state.runId && (file === "events.jsonl" ? state.events.length : Boolean(state.report));
    $(id).classList.toggle("disabled", !ready);
    $(id).setAttribute("aria-disabled", String(!ready));
    if (ready) $(id).href = `/api/runs/${encodeURIComponent(state.runId)}/download/${file}`;
    else $(id).removeAttribute("href");
  }
  renderSource();
}
function sourceText(source) {
  return `v${source.version} · source ${source.source_sha256.slice(0, 16)}${source.git_commit ? ` · git ${source.git_commit.slice(0, 7)}` : " · ZIP / 无 Git 记录"}`;
}
function renderSource() {
  const current = state.meta?.source,
    run =
      state.report?.source ||
      state.events.find((event) => event.event === "source_identified")?.details;
  let label = current ? `Phage Lab · ${sourceText(current)}` : "Phage Lab";
  if (run && run.source_sha256 !== current?.source_sha256) label += ` · 该运行：${sourceText(run)}`;
  else if (!run && state.report) label += " · 该运行未记录源码版本";
  text("source-label", label);
}
function eventDescription(event) {
  const d = event.details || {},
    step = names[d.step] || d.step || "";
  const mapping = {
    run_started: [
      "实验启动",
      d.agent === "openrouter" ? "使用 OpenRouter API 决策" : "使用离线规则决策",
    ],
    source_identified: ["记录运行版本", `源码指纹 ${(d.source_sha256 || "").slice(0, 12)}`],
    input_validated: ["输入校验通过", `${d.bases} bp · ${d.contigs} contig`],
    devices_discovered: ["设备就绪", `发现 ${d.count} 台模拟设备`],
    planning_requested: ["请求规划", "等待候选选择与设备分配"],
    plan_accepted: ["规划与候选选择", ""],
    job_submitted: [`${step}任务已提交`, `${deviceName(d.device)} · 第 ${d.attempt} 次尝试`],
    fault_injected: [
      "故障已注入",
      `${deviceName(d.device)} · ${{ hang: "卡死", "response-lost": "回执丢失", unreachable: "失联" }[d.fault] || d.fault}`,
    ],
    job_timeout: ["任务等待超时", "查询原任务状态，尚未重复执行"],
    job_reconciled: [
      "已核对任务状态",
      d.state === "succeeded"
        ? "设备已完成，将取回已有结果，不重复提交"
        : `原任务${statusNames[d.state] || d.state}`,
    ],
    recovery_requested: ["请求恢复决策", "仅允许取消确认后的重试或换机"],
    recovery_decided: [
      `恢复决策 · ${recoveryActions[d.action] || d.action}`,
      d.action === "cancel_and_failover"
        ? `${step} · 取消后切换${deviceName(d.replacement_device_id)}`
        : d.action === "abort"
          ? `${step} · 停止后续任务`
          : `${step} · 取消原任务后在原设备重试`,
    ],
    cancellation_acknowledged: ["原任务确认取消", deviceName(d.device)],
    recovery_executing: ["执行恢复方案", `下一次任务使用${deviceName(d.device)}`],
    reconciliation_failed: ["无法确认设备状态", "停止后续任务，避免重复执行"],
    device_job_completed: ["设备返回结果", deviceName(d.device)],
    step_completed: [`${step}步骤完成`, "结果已记录"],
    run_finished: [
      "流程结束",
      `${statusNames[d.status] || d.status}${d.error ? ` · ${d.error}` : ""}`,
    ],
  };
  return mapping[event.event] || [event.event, ""];
}
function appendDecision(content, event) {
  const d = event.details || {};
  const provider = d.agent === "openrouter" ? "OpenRouter API" : d.agent === "rule" ? "离线规则" : "";
  content.append(node("div", "decision-meta", provider ? `${provider} · 已校验` : "已校验"));
  if (event.event === "plan_accepted") {
    const candidates = node("div", "candidate-list");
    candidates.append(...(d.candidate_ids || []).map((id) => node("span", "candidate-chip", id)));
    content.append(candidates);
  }
  if (d.reason) {
    const label = event.event === "plan_accepted" ? "选择原因" : "恢复原因";
    content.append(node("p", "decision-reason", `${label}：${d.reason}`));
  }
}
function appendRecoveryProof(content, event) {
  const d = event.details || {};
  if (event.event !== "job_submitted" || !(d.attempt > 1)) return;
  const previous = state.events.findLast(
    (item) => item.event === "job_submitted" && item.details?.step === d.step &&
      item.details.attempt === d.attempt - 1 && item.seq < event.seq,
  );
  if (!previous?.details.job_id) return;
  const cancellation = state.events.find(
    (item) => item.event === "cancellation_acknowledged" &&
      item.details?.job_id === previous.details.job_id &&
      item.seq > previous.seq && item.seq < event.seq,
  );
  if (cancellation)
    content.append(node("p", "recovery-proof",
      `✓ #${cancellation.seq} 已确认取消 → #${event.seq} 提交第 ${d.attempt} 次任务`,
    ));
}
function appendEvents(events) {
  if (!events.length) return;
  const timeline = $("timeline"),
    follow = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 70;
  if (!state.events.length) timeline.replaceChildren();
  for (const event of events) {
    if (event.seq <= state.cursor) continue;
    state.events.push(event);
    state.cursor = event.seq;
    const [title, description] = eventDescription(event);
    const decision = ["plan_accepted", "recovery_decided"].includes(event.event);
    const severity = [
      "fault_injected",
      "job_timeout",
      "recovery_requested",
      "recovery_decided",
    ].includes(event.event)
      ? "warning"
      : event.event === "reconciliation_failed" ||
          (event.event === "run_finished" && event.details.status !== "succeeded")
        ? "error"
        : ["step_completed", "cancellation_acknowledged", "run_finished"].includes(event.event)
          ? "success"
          : "";
    const item = node("div", `timeline-item ${severity}${decision ? " decision-event" : ""}`),
      content = node("div", "event-content"),
      head = node("div", "event-head");
    const seconds = (Date.parse(event.at) - Date.parse(state.events[0].at)) / 1000;
    head.append(
      node("span", "event-title", title),
      node("span", "event-time", `#${String(event.seq).padStart(2, "0")} · +${seconds.toFixed(1)}s`),
    );
    content.append(head);
    if (description) content.append(node("p", "event-description", description));
    if (decision) appendDecision(content, event);
    appendRecoveryProof(content, event);
    item.append(node("span", "event-dot"), content);
    timeline.append(item);
  }
  if (follow) timeline.scrollTop = timeline.scrollHeight;
}
function render() {
  const view = derive();
  const title = { ...statusNames, waiting: "等待启动", starting: "正在启动", planning: "规划中" };
  text("run-status", title[view.status] || view.status);
  $("run-status").className = `state-text ${view.status}`;
  text("run-id", state.runId || "");
  $("run-id").title = state.runId || "";
  $("run-id").hidden = !state.runId;
  text("fault-count", `${view.faults.size} / ${view.recovered}`);
  text(
    "mode-label",
    view.mode === "openrouter"
      ? "OpenRouter API · 模拟设备"
      : view.mode === "rule"
        ? "离线规则 · 模拟设备"
        : "模拟设备",
  );
  const elapsed = view.started
    ? ((view.finished ? Date.parse(view.finished) : Date.now()) - Date.parse(view.started)) / 1000
    : null;
  text("elapsed", elapsed === null ? "— s" : `${Math.max(0, elapsed).toFixed(1)} s`);
  text("event-count", `${state.events.length} 条事件`);
  renderPipeline(view);
  renderDevices(view);
  renderResults(view);
  if (!state.events.length) {
    const empty = node("div", "timeline-empty");
    empty.append(
      node(
        "h3",
        "",
        state.pending ? "正在启动实验" : state.runId ? "正在读取日志" : "等待实验启动",
      ),
      node("p", "", "事件与决策将在这里实时更新。"),
    );
    $("timeline").replaceChildren(empty);
  }
}
function renderHistory() {
  if (!state.history.length) {
    $("history").replaceChildren(node("p", "empty-small", "尚无运行记录"));
    return;
  }
  $("history").replaceChildren(
    ...state.history.slice(0, 6).map((run) => {
      const button = node("button", `history-item ${run.run_id === state.runId ? "selected" : ""}`);
      button.type = "button";
      button.title = run.run_id;
      button.setAttribute("aria-pressed", String(run.run_id === state.runId));
      button.append(
        node("span", `legend-dot ${run.status}`),
        node("span", "", run.run_id.slice(0, 15)),
        node("span", "history-status", statusNames[run.status] || run.status),
      );
      button.addEventListener("click", () => {
        state.followActive = false;
        selectRun(run.run_id);
      });
      return button;
    }),
  );
}
async function refreshHistory() {
  const data = await api("/api/runs");
  state.history = data.runs;
  renderHistory();
}
async function poll() {
  try {
    const revision = state.configRevision,
      meta = await api("/api/status");
    if (revision === state.configRevision) state.meta = meta;
    setConnection(true);
    updateAgent();
    if (state.polls++ % 6 === 0 || state.pending) await refreshHistory();
    if (state.pending && state.meta.active_run && state.meta.active_run !== state.previousRunId) {
      state.pending = false;
      selectRun(state.meta.active_run);
    }
    if (
      !state.pending &&
      state.followActive &&
      state.meta.busy &&
      state.meta.active_run &&
      state.runId !== state.meta.active_run
    ) {
      selectRun(state.meta.active_run);
    }
    if (!state.runId && !state.pending) {
      const next = state.meta.active_run || state.history[0]?.run_id;
      if (next) selectRun(next);
    }
    if (state.meta.last_error) {
      state.pending = false;
      showError(state.meta.last_error);
    }
    if (state.runId) {
      const id = state.runId,
        snapshot = await api(`/api/runs/${encodeURIComponent(id)}?after=${state.cursor}`);
      if (id === state.runId) {
        appendEvents(snapshot.events);
        state.report = snapshot.report;
      }
    }
    updateControls();
    render();
  } catch (error) {
    setConnection(false);
  } finally {
    window.setTimeout(poll, 500);
  }
}
$("run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (
    state.submitting ||
    state.pending ||
    state.configuring ||
    state.meta?.busy ||
    !state.connected
  )
    return;
  state.submitting = true;
  updateControls();
  showError("");
  try {
    const seed = Number($("seed").value);
    if (!Number.isInteger(seed)) throw new Error("随机种子必须为整数。");
    const options = {
      seed,
      agent: $("agent").value,
      fault: $("fault").value,
      fault_step: $("fault-step").value || null,
    };
    const file = $("genome").files[0];
    if (!file) throw new Error("请先上传细菌 FASTA 文件。");
    if (file.size > 1000000) throw new Error("FASTA 文件不能超过 1 MB。");
    options.genome_text = await file.text();
    state.previousRunId = state.meta.active_run;
    await api("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Lab-Token": state.meta.token },
      body: JSON.stringify(options),
    });
    state.pending = true;
    state.followActive = true;
    selectRun(null);
    state.polls = 0;
  } catch (error) {
    showError(error.message);
  } finally {
    state.submitting = false;
    updateControls();
  }
});
$("agent").addEventListener("change", updateAgent);
$("api-form").addEventListener("submit", (event) => {
  event.preventDefault();
  saveApiConfig();
});
$("api-clear").addEventListener("click", () => saveApiConfig(true));
$("genome").addEventListener("change", () => {
  const file = $("genome").files[0];
  text("file-label", file?.name || "");
  $("file-label").title = file?.name || "";
  text("input-description", file ? `${(file.size / 1024).toFixed(1)} KB · 仅上传至本机服务` : "");
  $("upload-zone").hidden = Boolean(file);
  $("input-selected").hidden = !file;
  $("input-stage").classList.toggle("succeeded", Boolean(file));
  $("input-status").lastChild.textContent = file ? "已选择" : "待上传";
  if (file?.size > 1000000) showError("FASTA 文件不能超过 1 MB，请选择更小的文件。");
  else showError("");
});
$("reset-genome").addEventListener("click", () => {
  $("genome").value = "";
  $("genome").dispatchEvent(new Event("change"));
  $("genome").focus();
});
$("refresh-history").addEventListener("click", () =>
  refreshHistory().catch((error) => showError(error.message)),
);
// localStorage can throw (private mode, blocked storage); layout prefs are best-effort.
const prefs = {
  get(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {}
  },
};
const sidebarLimits = { min: 200, max: 480, collapseBelow: 140, step: 16 };
function storedSidebar() {
  try {
    return JSON.parse(prefs.get("phage-lab-sidebar")) || {};
  } catch {
    return {};
  }
}
function setSidebar(width, collapsed, persist = true) {
  const layout = $("layout");
  if (width) layout.style.setProperty("--sidebar-width", `${width}px`);
  layout.classList.toggle("sidebar-collapsed", collapsed);
  $("sidebar-expand").hidden = !collapsed;
  $("sidebar-resizer").setAttribute("aria-valuenow", collapsed ? 0 : Math.round(width || sidebarWidth()));
  if (!persist) return;
  const saved = storedSidebar();
  prefs.set("phage-lab-sidebar", JSON.stringify({ width: width || saved.width || null, collapsed }));
}
function sidebarWidth() {
  return $("sidebar").getBoundingClientRect().width;
}
function clampSidebar(width) {
  return Math.min(sidebarLimits.max, Math.max(sidebarLimits.min, width));
}
$("sidebar-resizer").addEventListener("pointerdown", (event) => {
  if (event.button !== 0) return;
  event.preventDefault();
  const handle = $("sidebar-resizer");
  const startX = event.clientX;
  const startWidth = sidebarWidth();
  let width = startWidth;
  let collapsed = false;
  handle.setPointerCapture(event.pointerId);
  $("layout").classList.add("resizing");
  const move = (moveEvent) => {
    const raw = startWidth + moveEvent.clientX - startX;
    collapsed = raw < sidebarLimits.collapseBelow;
    width = collapsed ? startWidth : clampSidebar(raw);
    setSidebar(width, collapsed, false);
  };
  const end = () => {
    handle.removeEventListener("pointermove", move);
    handle.removeEventListener("pointerup", end);
    handle.removeEventListener("pointercancel", end);
    $("layout").classList.remove("resizing");
    setSidebar(width, collapsed);
    if (collapsed) $("sidebar-expand").focus();
  };
  handle.addEventListener("pointermove", move);
  handle.addEventListener("pointerup", end);
  handle.addEventListener("pointercancel", end);
});
$("sidebar-resizer").addEventListener("keydown", (event) => {
  const width = sidebarWidth();
  if (event.key === "ArrowLeft" && width - sidebarLimits.step < sidebarLimits.min) {
    setSidebar(width, true);
    $("sidebar-expand").focus();
  } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    const delta = event.key === "ArrowLeft" ? -sidebarLimits.step : sidebarLimits.step;
    setSidebar(clampSidebar(width + delta), false);
  } else return;
  event.preventDefault();
});
$("sidebar-expand").addEventListener("click", () => {
  setSidebar(storedSidebar().width, false);
  $("sidebar-resizer").focus();
});
{
  const saved = storedSidebar();
  const width = Number(saved.width) ? clampSidebar(Number(saved.width)) : null;
  setSidebar(width, Boolean(saved.collapsed), false);
}
$("sidebar-resizer").setAttribute("aria-valuemin", sidebarLimits.min);
$("sidebar-resizer").setAttribute("aria-valuemax", sidebarLimits.max);
function setTimelineCollapsed(collapsed, persist = true) {
  $("timeline-panel").classList.toggle("collapsed", collapsed);
  $("timeline-toggle").setAttribute("aria-expanded", String(!collapsed));
  if (persist) prefs.set("phage-lab-timeline-collapsed", collapsed ? "1" : "0");
}
$("timeline-toggle").addEventListener("click", () => {
  const collapsed = !$("timeline-panel").classList.contains("collapsed");
  setTimelineCollapsed(collapsed);
  if (!collapsed) {
    const timeline = $("timeline");
    timeline.scrollTop = timeline.scrollHeight;
  }
});
setTimelineCollapsed(prefs.get("phage-lab-timeline-collapsed") === "1", false);
render();
poll();
