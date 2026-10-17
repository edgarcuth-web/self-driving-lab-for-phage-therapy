"use strict";
const { CASES, NODES, createState, advance, statusOf, isolatesOf, detectionOf, outputOf, reportOf, tourFrame, timelineOf, reviewOf } = window.ClinicalWorkflow;
const $ = id => document.getElementById(id);
const text = (id, value) => { $(id).textContent = value; };
const labels = { waiting: "待开始", running: "进行中", succeeded: "已完成", review: "待复核", blocked: "已阻断" };
let state = createState("mixed"), selected = "sample", playing = false, started = false, lastTick = 0, timer = null, events = [];
let runId = crypto.randomUUID();
let tourSeconds = null, tourCue = '', terminalNotified = false;
const nodeElements = new Map();
const openFragmentPanels = new Set();
const openInspectorPanels = new Set();
const make = (tag, className, value) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined) element.textContent = value;
  return element;
};
function notify(message) {
  text("notice", message);
  $("notice").hidden = false;
  clearTimeout(timer);
  timer = setTimeout(() => { $("notice").hidden = true; }, 3500);
}
function effectiveStatus(id) {
  return !started && id === "sample" ? "waiting" : statusOf(state, id);
}
function record(message, kind = "SIMULATED", day = state.day) {
  events.push({ day, message, kind });
}
function syncFields() {
  $("sample-id").value = state.sample.sample_id;
  $("sample-type").value = state.sample.sample_type;
  $("collected-at").value = state.sample.collected_at;
}
function reset(caseId = state.caseId, metadata) {
  tourSeconds = null; tourCue = ''; terminalNotified = false;
  playing = false;
  started = false;
  lastTick = 0;
  state = createState(caseId, metadata);
  runId = crypto.randomUUID();
  events = [];
  openFragmentPanels.clear();
  openInspectorPanels.clear();
  selected = "sample";
  syncFields();
  window.ClinicalReports.reset();
  render();
}
function buildNodes() {
  for (const n of NODES) {
    const card = make("button", "stage");
    card.type = "button";
    card.dataset.id = n.id;
    const top = make("div", "stage-top"), status = make("span", "stage-state");
    status.append(make("i", "status-dot"), make("span", "status-label", "待开始"));
    top.append(make("span", "stage-index", n.number), status);
    const title = make("h3");
    const icon = make("span", "node-icon", n.icon);
    icon.setAttribute("aria-hidden", "true");
    title.append(icon, make("span", "", n.title));
    if (n.id === "prepare") title.append(make("span", "duration-badge", "~7D"));
    card.append(top, title, make("p", "node-summary", n.en));
    if (n.deps.length) card.append(make("i", "node-port"));
    if (n.id !== "learn" && n.id !== "antibiotic") card.append(make("i", "node-port out"));
    card.addEventListener("click", () => {
      if (tourSeconds !== null) {tourSeconds=null; tourCue=''; playing=false; lastTick=0;}
      selected = n.id; render();
      if (document.body.classList.contains('presentation-mode')) $('detail-title').scrollIntoView({block:'start'});
    });
    $("nodes").append(card);
    nodeElements.set(n.id, card);
  }
  for (const [id, fixture] of Object.entries(CASES)) {
    const button = make("button", "case-button");
    button.type = "button";
    button.dataset.case = id;
    button.append(make("span", "case-icon", "▧"), make("span", "case-title", fixture.title), make("span", "case-id", fixture.sample_id));
    button.addEventListener("click", () => { reset(id); notify(`已切换至${fixture.title}，流程已重置。`); });
    $("case-list").append(button);
  }
}
function nodeSummary(id) {
  const status = effectiveStatus(id);
  if (status === "blocked") return "上游未匹配 · 等待人工复核";
  if (status === "review") return "未找到候选 · 保留未匹配项";
  if (id === "sample") return state.sample.sample_id;
  if (id === "isolate") return status === "succeeded" ? `${detectionOf(state).identified.length} 候选物种 · ${detectionOf(state).unclassified.length} 未分类信号` : "模拟片段比对 → 候选鉴定";
  if (id === "antibiotic") return status === "succeeded" ? "候选已返回 · 不代表药敏结果" : "并行匹配 · 无需等待制备";
  if (id === "phage") return status === "succeeded" ? "按细菌逐项返回模拟候选" : "细菌 → 模拟噬菌体候选";
  if (id === "prepare") return status === "running" ? `制备中 ${(state.day - 3).toFixed(1)} / 7 天 · 场景时间` : status === "succeeded" ? "7 天场景时间已结束" : "预计约 7 天 · 场景设定";
  if (id === "design") return "CandidateSet → ExperimentSpec";
  if (id === "test") return "虚拟流程展示 · evidence: none";
  return "结果复核 → 下一轮筛选";
}
function renderNodes() {
  for (const n of NODES) {
    const card = nodeElements.get(n.id), status = effectiveStatus(n.id);
    card.className = `stage ${status}`;
    card.setAttribute("aria-pressed", String(selected === n.id));
    card.setAttribute("aria-label", `${n.number} ${n.title} · ${labels[status]}`);
    card.querySelector(".status-label").textContent = labels[status];
    card.querySelector(".node-summary").textContent = nodeSummary(n.id);
  }
  for (const button of $("case-list").children) button.setAttribute("aria-pressed", String(button.dataset.case === state.caseId));
  const detection = detectionOf(state), unknowns = detection?.unclassified.length;
  $("discovery-stage").className = `stage discovery-stage ${!detection ? 'waiting' : unknowns ? 'review' : 'succeeded'}`;
  text('discovery-status', !detection ? '待检测' : unknowns ? '待复核' : '无未分类信号');
  text('discovery-summary', !detection ? '等待片段比对完成' : unknowns ? `${unknowns} 项信号 · 物种尚未确定` : '本次模拟未保留未分类信号');
}
function drawEdges() {
  const container = $("workflow-graph").getBoundingClientRect();
  const edges = [];
  for (const n of NODES) for (const dep of n.deps) {
    const from = nodeElements.get(dep).getBoundingClientRect(), to = nodeElements.get(n.id).getBoundingClientRect();
    let d;
    if (n.id === "test" || n.id === "learn") {
      const x = from.left + from.width / 2 - container.left;
      d = `M ${x} ${from.bottom - container.top} V ${to.top - container.top - 5}`;
    } else {
      const x1 = from.right - container.left, y1 = from.top + from.height / 2 - container.top;
      const x2 = to.left - container.left - 5, y2 = to.top + to.height / 2 - container.top;
      const middle = x1 + (x2 - x1) / 2;
      d = `M ${x1} ${y1} H ${middle} V ${y2} H ${x2}`;
    }
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    const status = effectiveStatus(n.id);
    path.setAttribute("class", `edge ${status === "running" ? "active" : status === "succeeded" ? "done" : ""}`);
    edges.push(path);
  }
  const from = nodeElements.get('isolate').getBoundingClientRect(), to = $('discovery-stage').getBoundingClientRect();
  const branch = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  const x = from.left + from.width / 2 - container.left;
  branch.setAttribute('d', `M ${x} ${from.bottom-container.top} V ${to.top-container.top-5}`);
  branch.setAttribute('class', `edge ${detectionOf(state) ? 'done' : ''}`);
  edges.push(branch);
  $("edges").replaceChildren(...edges);
}
function confidenceBadge(record) {
  const badge = make('span', `detection-confidence ${record.confidence.level}`, `${record.confidence.score.toFixed(1)} / 100`);
  badge.title = record.classification === 'unclassified_bacterial_signal' ? '未分类片段支持度；物种尚未确定，不是确诊概率' : '模拟检测置信度：未校准支持分，不是确诊概率';
  return badge;
}
function fragmentDetails(record) {
  const details = make('details', 'fragment-details');
  details.open = openFragmentPanels.has(record.id);
  details.addEventListener('toggle', () => {if (details.open) openFragmentPanels.add(record.id); else openFragmentPanels.delete(record.id);});
  details.append(make('summary', '', `${record.fragments.length} 个代表性模拟片段 · 查看比对`));
  details.append(make('p', 'fragment-notice', '仅展示60 nt代表性人工片段及人工参考窗；读段计数和覆盖率为合成场景指标，不对应真实基因、引物或可用检测靶标。'));
  for (const fragment of record.fragments) {
    const item = make('div', 'fragment-item');
    item.append(make('div', 'fragment-meta', `${fragment.id} · ${fragment.length_bp} nt · 一致性 ${fragment.identity_percent.toFixed(1)}%`));
    for (const [label, sequence] of [['片段',fragment.sequence],['参考',fragment.reference_sequence]]) {
      const line = make('div', 'sequence-line');
      line.append(make('span', '', label), make('code', '', sequence.match(/.{1,30}/g).join('\n'))); item.append(line);
    }
    details.append(item);
  }
  return details;
}
function evidenceMetrics(record) {
  const m = record.metrics, details = make('div', 'detection-metrics');
  for (const [label, value] of [['唯一读段',m.unique_reads],['参考覆盖',`${m.coverage_percent.toFixed(1)}%`],['比对一致',`${m.identity_percent.toFixed(1)}%`],['样本/对照',`${m.sample_control_ratio.toFixed(1)}×`]]) {
    const stat = make('div'); stat.append(make('span', '', label), make('strong', '', String(value))); details.append(stat);
  }
  return details;
}
function renderUnknown(detection) {
  const output = $('unknown-output');
  text('unknown-count', !detection ? '待检测' : `${detection.unclassified.length} 项待复核`);
  if (!detection) {output.replaceChildren(make('p', 'unknown-empty', '等待基因片段检测完成，尚无可判读结果。')); return;}
  if (!detection.unclassified.length) {output.replaceChildren(make('p', 'unknown-empty', '本次模拟未保留未分类信号；不代表真实样本已排除未知菌。')); return;}
  output.replaceChildren(...detection.unclassified.map(record => {
    const card = make('div', 'unknown-card'), header = make('div', 'detection-item-heading');
    header.append(make('strong', '', `未命名细菌样信号 · ${record.id}`), confidenceBadge(record));
    card.append(header, make('p', 'unknown-interpretation', '物种未确定 · 非新菌种确证 · 不自动匹配噬菌体或抗生素'), evidenceMetrics(record), fragmentDetails(record), make('p', 'detection-caveat', record.interpretation));
    return card;
  }));
}
function renderIsolates() {
  const output = $("isolate-output");
  const detection = detectionOf(state);
  renderUnknown(detection);
  if (!outputOf(state, "isolate")) {
    const empty = make("div", "empty-state"), body = make("div", "", "等待样本进入细菌分离库");
    body.append(make("small", "", "分离完成后，两条匹配分支将同时启动。"));
    empty.append(make("span", "empty-icon", "⠿"), body);
    output.replaceChildren(empty);
    text("isolate-count", "等待检测");
    return;
  }
  const isolates = isolatesOf(state), list = make("div", "isolate-list detection-list");
  list.append(make('p', 'detection-score-label', '模拟检测置信度 / 100 · 未校准'));
  for (const record of detection.identified) {
    const isolate = isolates.find(item => item.id === record.isolate_id);
    const item = make('div', 'detection-item');
    const row = make("div", "isolate-row"), name = make("div");
    name.append(make("strong", "", isolate.name), make("small", "", isolate.species));
    row.append(make("span", "mono", isolate.id), name, confidenceBadge(record));
    item.append(row, evidenceMetrics(record), fragmentDetails(record));
    if (record.confidence.score < 85) item.append(make('p', 'detection-caveat', '模拟支持较弱，候选物种需独立复核，不能据此确诊。'));
    list.append(item);
  }
  if (!detection.identified.length) list.append(make('p', 'unknown-empty', '没有得到可命名的候选物种，请查看下方未分类信号。'));
  const formula = make('details', 'confidence-method'); formula.append(make('summary', '', '模拟评分如何计算？'), make('p', '', detection.score_definition), make('p', '', '唯一读段支持以500封顶；样本/对照比以20封顶；一致性支持映射85–100%。权重及高/中/低分档均为演示设定，不是临床验证阈值。'));
  list.append(formula);
  output.replaceChildren(list);
  text("isolate-count", `${detection.identified.length} 候选 · ${detection.unclassified.length} 未分类`);
}
function io(label, content, pre = false) {
  const section = make("div", "io-section");
  section.append(make("div", "io-label", label));
  if (pre) {
    const details = make('details','inspector-data'), key = `${selected}:${label}`;
    details.open = openInspectorPanels.has(key);
    details.addEventListener('toggle',()=>{if(details.open) openInspectorPanels.add(key); else openInspectorPanels.delete(key);});
    details.append(make('summary','','查看结构化数据'),make('pre','',content)); section.append(details);
  } else section.append(make('p','',content));
  return section;
}
function renderDetail() {
  const n = NODES.find(item => item.id === selected), status = effectiveStatus(selected);
  text("detail-eyebrow", `NODE INSPECTOR / ${n.number}`);
  text("detail-title", n.title);
  text("detail-status", labels[status]);
  const body = make("div", "inspector-body");
  body.append(make("p", "node-description", n.description));
  let input;
  if (n.id === "sample") input = `${state.sample.sample_id} · ${state.sample.sample_type} · ${state.sample.collected_at.replace("T", " ")}`;
  else if (n.id === "isolate") input = outputOf(state, "sample") ? JSON.stringify(state.sample, null, 2) : "等待取样记录；完成后接收样本 metadata。";
  else if (["phage", "antibiotic"].includes(n.id)) input = outputOf(state, "isolate") ? isolatesOf(state).map(item => `${item.id} ${item.name}`).join(" · ") : "等待细菌分离库输出完整细菌清单。";
  else input = `依赖：${n.deps.map(id => NODES.find(item => item.id === id).title).join(" / ")}；${n.phase === "lab" ? "以下仅展示 main 领域概念，不创建真实领域对象。" : "读取模拟候选，不发起真实制备订单。"}`;
  body.append(io("↳ INPUT / 输入", input, n.id === "isolate" && Boolean(outputOf(state, "sample"))));
  const output = outputOf(state, n.id);
  if (output?.matches) {
    const section = make("div", "io-section");
    section.append(make("div", "io-label", "↗ OUTPUT / 模拟候选"));
    for (const match of output.matches) {
      const line = make("div", `match-line ${!match.candidates.length ? "unresolved" : ""}`);
      line.append(make("span", "", match.name), make("span", "", match.candidates.join(" / ") || "未匹配 · 待复核"));
      section.append(line);
    }
    body.append(section);
    body.append(make("p", "boundary-note", n.id === "antibiotic" ? "ABX-DEMO 为虚构抗生素编号；未进行药敏检测，未生成处方或临床建议。" : "PHG-DEMO 为虚构噬菌体编号；不是数据库 accession，无感染概率或疗效证据。"));
  } else {
    body.append(io("↗ OUTPUT / 输出", output ? JSON.stringify(output, null, 2) : status === "blocked" ? "上游候选缺失。后续模拟阶段已阻断，等待人工复核。" : "节点完成后显示输出；尚无结果。", Boolean(output)));
  }
  body.append(make("p", "boundary-note", "SIMULATED · physical_execution=false · evidence_class=none"));
  $("detail-content").replaceChildren(body);
}
function renderEvents() {
  text("event-count", String(events.length).padStart(2, "0"));
  if (!events.length) {
    $("events").replaceChildren(make("p", "event-empty", "等待开始演示。这里将记录节点交接与两条匹配分支的状态。"));
    return;
  }
  $("events").replaceChildren(...events.slice(-18).reverse().map(event => {
    const row = make("div", "event");
    row.append(make("span", "mono", `D+${event.day.toFixed(1).padStart(4, "0")}`), make("i", "status-dot green"), make("span", "", event.message), make("span", "event-kind", event.kind));
    return row;
  }));
}
function isTerminal() {
  return state.day >= 13 || statusOf(state, "phage") === "review" || statusOf(state, "antibiotic") === "review";
}
const formatTime = seconds => `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(Math.floor(seconds%60)).padStart(2,'0')}`;
function setPresentation(enabled) {
  document.body.classList.toggle('presentation-mode',enabled);
  $('presentation-toggle').setAttribute('aria-pressed',String(enabled));
  text('presentation-toggle',enabled?'↙ 退出演示模式':'⛶ 演示模式');
  if (enabled) $('report-settings').open = false;
  else if (tourSeconds !== null) {tourSeconds=null; tourCue=''; playing=false;}
  render();
  requestAnimationFrame(drawEdges);
}
function renderPresentation() {
  const active = tourSeconds !== null, frame = tourFrame(tourSeconds || 0,state.caseId);
  document.body.classList.toggle('tour-active',active);
  $('tour-case').value = state.caseId;
  $('tour-controls').hidden = !active;
  $('tour-start').hidden = active && !frame.finished;
  text('tour-start',frame.finished && active?'↻ 重新导览此病例':'▶ 一键导览此病例');
  $('story-progress').max = frame.duration; $('story-progress').value = frame.elapsed;
  text('story-clock',`${formatTime(frame.elapsed)} / ${formatTime(frame.duration)}`);
  text('story-chapter',active?`病例导览 / ${String(frame.index+1).padStart(2,'0')} OF ${String(frame.total).padStart(2,'0')} · ${frame.finished?'已结束':playing?'播放中':'已暂停'}`:`GUIDED DEMO / ${CASES[state.caseId].title}`);
  text('story-title',active?frame.title:'一份样本，两条并行路径，一个实验闭环。');
  text('story-description',active?frame.body:'选择虚构病例，一键播放完整故事。自动聚焦关键节点，并保留每一个需要人工复核的信号。');
  text('tour-pause',playing?'Ⅱ 暂停导览':frame.finished?'导览已结束':'▶ 继续导览');
  $('tour-pause').disabled = frame.finished;
  $('tour-next').disabled = frame.finished;
  for (const [id,card] of nodeElements) card.classList.toggle('tour-focus',active && (frame.node===id || frame.key==='match' && id==='antibiotic'));
  $('discovery-stage').classList.toggle('tour-focus',active && frame.key==='review' && state.caseId!=='single');
  const timeline = timelineOf(state), prep = timeline.prepare;
  $('timeline-clock').value = state.day;
  $('preparation-progress').value = prep.progress;
  text('antibiotic-timing',timeline.antibiotic.status==='succeeded'?'D+3 候选已返回 · 不等待制备':timeline.antibiotic.status==='review'?'库内未匹配 · 待复核':timeline.antibiotic.status==='running'?'两路正在并行匹配':'等待细菌清单');
  text('phage-timing',prep.status==='blocked'?'候选缺失 · 制备已阻断':prep.status==='succeeded'?'D+10 制备场景结束':prep.status==='running'?`场景制备 ${(prep.progress*7).toFixed(1)} / 7 天`:'等待候选交接');
  const tracks = document.querySelectorAll('.lane-track');
  for (const track of tracks) {track.classList.toggle('matching',state.day>=2); track.classList.toggle('ready',state.day>=3 && timeline.antibiotic.status==='succeeded'); track.classList.toggle('blocked',prep.status==='blocked');}
  text('timeline-note',prep.status==='blocked'?'本例未找到候选，制备与实验保持阻断；时间轴没有执行这些阶段。':'D+2 双路匹配 → D+3 抗生素候选返回 / 噬菌体开始制备 → D+10 制备结束。均为模拟节点。');
}
function updateTour(seconds) {
  tourSeconds = seconds;
  const frame = tourFrame(seconds,state.caseId), cueChanged = frame.key !== tourCue;
  if (cueChanged) {tourCue=frame.key; selected=frame.node;}
  const days = frame.day-state.day;
  if (days>0) progress(days); else render();
  if (frame.finished) {playing=false; render();}
  if (cueChanged) {
    const currentCue = tourCue;
    requestAnimationFrame(() => {if (tourSeconds!==null && tourCue===currentCue) $(frame.target).scrollIntoView({block:'start',behavior:'instant'});});
  }
}
function render() {
  const completed = NODES.filter(n => effectiveStatus(n.id) === "succeeded").length;
  const review = NODES.some(n => effectiveStatus(n.id) === "review");
  const reviewCount = reviewOf(state).length;
  const caption = review ? "候选缺失 · 待人工复核" : state.day >= 13 ? `主流程完成${reviewCount?` · ${reviewCount}项待复核`:''}` : playing ? "模拟进行中" : started ? "已暂停" : "等待开始";
  text("run-state", caption);
  $("run-state").className = `state-badge ${review || state.day>=13 && reviewCount ? "review" : playing ? "running" : state.day >= 13 ? "succeeded" : ""}`;
  $("run-dot").className = `status-dot ${review || state.day>=13 && reviewCount ? "amber" : playing ? "cyan" : state.day >= 13 ? "green" : ""}`;
  text("play", isTerminal() ? "↻ 重新演示" : playing ? "Ⅱ 暂停演示" : started ? "▶ 继续演示" : "▶ 开始演示");
  $("step").disabled = tourSeconds!==null || playing || isTerminal();
  if (tourSeconds!==null) text('play',playing?'Ⅱ 暂停导览':tourFrame(tourSeconds,state.caseId).finished?'↻ 重新演示':'▶ 继续导览');
  text("scenario-day", `D+${state.day.toFixed(1)}`);
  text("flow-caption", `${completed} / ${NODES.length} 主流程节点完成`);
  text("active-sample", state.sample.sample_id);
  renderNodes(); renderIsolates(); renderDetail(); renderEvents(); renderPresentation(); drawEdges();
  if (started && isTerminal() && !terminalNotified) {terminalNotified=true; window.ClinicalReports.onTerminal();}
}
function progress(days) {
  const before = new Map(NODES.map(n => [n.id, statusOf(state, n.id)]));
  const previousDay = state.day;
  advance(state, days);
  // Preserve chronological transitions even when a tick crosses multiple boundaries.
  const transitions = [];
  for (const n of NODES) {
    const status = statusOf(state, n.id);
    if (before.get(n.id) !== status) {
      const day = n.end > previousDay && n.end <= state.day ? n.end : n.start > previousDay && n.start <= state.day ? n.start : state.day;
      transitions.push({ n, status, day });
    }
  }
  transitions.sort((a, b) => a.day - b.day);
  for (const { n, status, day } of transitions) {
    record(`${n.title} · ${labels[status]}`, status === "review" ? "REVIEW" : "SIMULATED", day);
    if (n.id === "isolate" && status === "succeeded") {
      record(`输出 ${isolatesOf(state).length} 株模拟细菌；同时释放噬菌体 / 抗生素匹配`, "PARALLEL", day);
    }
  }
  if (isTerminal()) {
    if (tourSeconds===null) playing = false;
    if (!terminalNotified) record(state.day >= 13 ? "模拟展示完成；未生成物理证据或临床结论" : "候选缺失，后续流程阻断；等待人工复核", "SUMMARY");
  }
  render();
}
function tick(now) {
  if (playing) {
    if (lastTick && now - lastTick >= 150) {
      // One scenario day = 6 seconds at 1x. Cap background-tab catch-up.
      const elapsed = Math.min(now-lastTick,1000)*Number($('speed').value);
      if (tourSeconds!==null) updateTour(tourSeconds+elapsed/1000);
      else progress(elapsed/6000);
      lastTick = now;
    }
    if (!lastTick) lastTick = now;
  } else lastTick = 0;
  requestAnimationFrame(tick);
}
$("play").addEventListener("click", () => {
  if (tourSeconds!==null && !tourFrame(tourSeconds,state.caseId).finished) {playing=!playing; lastTick=0; render(); return;}
  if (isTerminal()) reset(state.caseId, state.sample);
  playing = !playing;
  if (!started) { started = true; record("模拟病人取样 · 开始登记样本 metadata"); }
  else record(playing ? "继续演示" : "已暂停；场景时间停止", "CONTROL");
  lastTick = 0;
  render();
});
$('presentation-toggle').addEventListener('click',()=>setPresentation(!document.body.classList.contains('presentation-mode')));
$('tour-case').addEventListener('change',()=>{reset($('tour-case').value); notify('已切换病例，点击一键导览开始。');});
$('tour-start').addEventListener('click',()=>{
  reset(state.caseId,state.sample); setPresentation(true);
  $('speed').value='1'; started=true; playing=true; lastTick=0;
  record('病例导览开始 · 播放时间与场景时间独立','CONTROL'); updateTour(0);
});
$('tour-pause').addEventListener('click',()=>{playing=!playing; lastTick=0; render();});
$('tour-next').addEventListener('click',()=>{playing=false; lastTick=0; updateTour(tourFrame(tourSeconds,state.caseId).end);});
$('tour-stop').addEventListener('click',()=>{tourSeconds=null; tourCue=''; playing=false; lastTick=0; render();});
document.addEventListener('keydown',event=>{if(event.key==='Escape' && document.body.classList.contains('presentation-mode')) setPresentation(false);});
$("reset").addEventListener("click", () => { reset(state.caseId, state.sample); notify("流程已重置，保留当前样本 metadata。"); });
$("discovery-stage").addEventListener('click', () => $('unknown-detection').scrollIntoView({block:'center'}));
$("step").addEventListener("click", () => {
  if (playing || isTerminal()) return;
  if (!started) { started = true; record("模拟病人取样 · 开始登记样本 metadata"); }
  const next = Math.min(...NODES.flatMap(n => [n.start, n.end]).filter(day => day > state.day));
  progress(next - state.day);
});
$("metadata-form").addEventListener("submit", event => {
  event.preventDefault();
  const sample_id = $("sample-id").value.trim(), sample_type = $("sample-type").value.trim(), collected_at = $("collected-at").value;
  if (!sample_id || !sample_type || !collected_at) { notify("请完整填写样本 metadata。"); return; }
  reset(state.caseId, { sample_id, sample_type, collected_at });
  notify("样本 metadata 已更新，流程已重置。");
});
$("speed").addEventListener("change", () => { if (started) record(`播放速度调整为 ${$("speed").value}×`, "CONTROL"); render(); });
function currentSnapshot() {
  const report = reportOf(state);
  report.run_id = runId;
  if (!started) report.nodes.find(n => n.id === "sample").status = "waiting";
  report.playback = playing ? "playing" : started ? "paused_or_finished" : "not_started";
  report.presentation_events = events;
  return report;
}
$("download").addEventListener("click", () => {
  const report = currentSnapshot();
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob), link = make("a");
  link.href = url; link.download = `clinical-workflow-${state.caseId}.json`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  notify("已导出当前模拟快照；未完成节点的输出为 null。");
});
buildNodes(); syncFields(); render();
window.ClinicalReports.init({ getSnapshot:currentSnapshot });
new ResizeObserver(drawEdges).observe($("workflow-graph"));
requestAnimationFrame(tick);
