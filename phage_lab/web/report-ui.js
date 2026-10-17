/* Optional local-server Kimi report client. Credentials never enter browser storage. */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const make = (tag, cls, content) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (content !== undefined) node.textContent = content;
    return node;
  };
  let config = null, getSnapshot, epoch = 0, pollTimer = null;
  let phase = "idle", report = null, failure = "", attemptedRun = null, configBusy = false;
  function terminal(snapshot) {
    return snapshot.nodes.some(n => n.id === 'learn' && n.status === 'succeeded') ||
      snapshot.nodes.some(n => ['phage', 'antibiotic'].includes(n.id) && n.status === 'review');
  }
  async function request(path, options = {}) {
    const response = await fetch(path, { cache: 'no-store', ...options });
    let data;
    try { data = await response.json(); } catch { throw new Error("本机报告服务不可用，请重启服务并刷新页面。"); }
    if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）。`);
    return data;
  }
  function post(path, body) {
    return request(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lab-Token': config.token }, body: JSON.stringify(body) });
  }
  function placeholder(title, detail, kind = "") {
    const box = make('div', `report-placeholder ${kind}`), body = make('div');
    body.append(make('strong', '', title), make('p', '', detail));
    box.append(make('span', 'report-symbol', kind === 'generating' ? '◴' : '▤'), body);
    return box;
  }
  function sectionKind(heading) {
    if (/未命名|未分类/.test(heading)) return 'unclassified';
    if (/分离菌|细菌分离/.test(heading)) return 'isolates';
    if (/噬菌体.*(候选|匹配)|(候选|匹配).*噬菌体/.test(heading)) return 'phage';
    if (/抗生素.*(候选|匹配)|(候选|匹配).*抗生素/.test(heading)) return 'antibiotic';
    return null;
  }
  function tableModules(draft) {
    const isolates = draft.source.isolates;
    const detection = draft.source.detection;
    const detected = new Map((detection?.identified || []).map(item=>[item.isolate_id,item]));
    const modules = [{kind:'isolates', title:'模拟分离菌', headers:['菌株编号', '细菌名称', '物种（学名）', '来源'],
      rows:isolates.map(item => [item.id, item.name, item.species, '模拟分离库'])}];
    if (detection) {
      modules[0].headers = ['菌株编号', '候选细菌', '物种（学名）', '模拟置信分'];
      modules[0].rows = isolates.map(item=>[item.id,item.name,item.species,
        detected.has(item.id)?`${detected.get(item.id).confidence.score.toFixed(1)} / 100`:'物种未确定']);
      modules[0].description = '片段检测支持评分，未经临床校准；不是确诊概率或统计置信区间。';
    }
    for (const [kind, title, column] of [['phage','噬菌体候选','噬菌体候选编号'], ['antibiotic','抗生素候选','抗生素候选编号']]) {
      const matches = new Map(draft.source.matches[kind].map(item => [item.isolate_id, item]));
      const rows = isolates.flatMap(isolate => {
        const candidates = matches.get(isolate.id)?.candidates || [];
        return candidates.length
          ? candidates.map(candidate => [isolate.id, isolate.name, candidate, '模拟候选'])
          : [[isolate.id, isolate.name, '—', '未匹配 · 待复核']];
      });
      modules.push({kind, title, headers:['菌株编号', '细菌名称', column, '匹配状态'], rows});
    }
    if (detection?.unclassified.length) modules.push({kind:'unclassified',title:'发现未命名细菌',
      headers:['信号编号','片段支持分','物种鉴定','处理'],
      rows:detection.unclassified.map(item=>[item.id,`${item.confidence.score.toFixed(1)} / 100`,'未确定','待复核 · 不自动匹配']),
      description:'仅为未分类细菌样信号，不是已确认的新菌种；需要排除低特异比对、参考库缺口和污染。'});
    for (const module of modules) module.notes = draft.sections.filter(section => sectionKind(section.heading) === module.kind).map(section => section.content);
    return modules;
  }
  function copyButton(label, getText) {
    const button = make('button', 'report-copy-button', '⧉ 一键复制');
    button.type = 'button';
    button.setAttribute('aria-label', label);
    button.setAttribute('aria-live', 'polite');
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        await navigator.clipboard.writeText(getText());
        button.textContent = '✓ 已复制';
        button.title = '内容已复制到剪贴板';
      } catch {
        button.textContent = '复制失败';
        button.title = '请允许浏览器访问剪贴板后重试';
      } finally {
        button.disabled = false;
        setTimeout(() => {button.textContent = '⧉ 一键复制';}, 2200);
      }
    });
    return button;
  }
  const plainCell = value => String(value).replace(/[\t\r\n]+/g, ' ');
  function moduleText(module) {
    return [module.title, '模拟数据 · 需医师复核', module.headers.join('\t'),
      ...module.rows.map(row => row.map(plainCell).join('\t')), ...(module.description?[module.description]:[]), ...module.notes].join('\n');
  }
  function renderTableModule(module) {
    const block = make('section', `report-table-module report-module-${module.kind}`);
    const header = make('div', 'report-table-heading'), title = make('div', 'report-table-title');
    title.append(make('h4', '', module.title), make('span', 'tiny-label', `${module.rows.length} 条记录`));
    header.append(title, copyButton(`复制${module.title}`, () => moduleText(module)));
    const scroll = make('div', 'report-table-scroll'), table = make('table', 'report-table');
    table.setAttribute('aria-label', module.title);
    const head = make('thead'), headings = make('tr');
    for (const label of module.headers) {
      const cell = make('th', '', label); cell.setAttribute('scope', 'col'); headings.append(cell);
    }
    head.append(headings);
    const body = make('tbody');
    for (const row of module.rows) {
      const tr = make('tr');
      row.forEach((value, index) => {
        const cell = make('td', index === 0 || index === 2 && module.kind !== 'isolates' ? 'report-cell-id' : '', index === 3 ? undefined : value);
        if (index === 3) cell.append(make('span', /未匹配|未确定|待复核/.test(value) ? 'report-cell-status unresolved' : 'report-cell-status', value));
        tr.append(cell);
      });
      body.append(tr);
    }
    table.append(head, body); scroll.append(table); block.append(header, scroll);
    if (module.description) block.append(make('p', 'report-table-description', module.description));
    if (module.notes.length) {
      const note = make('div', 'report-table-note');
      note.append(make('span', 'eyebrow', 'AI 整理说明'));
      module.notes.forEach(content => note.append(make('p', '', content)));
      block.append(note);
    }
    return block;
  }
  function render() {
    if (!getSnapshot) return;
    const ready = terminal(getSnapshot());
    $('generate-report').disabled = !ready || !config?.configured || phase === 'generating' || configBusy;
    $('generate-report').textContent = phase === 'failed' ? '手动重试' : phase === 'complete' ? '已生成本次报告' : '生成报告';
    if (phase === 'complete') $('generate-report').disabled = true;
    $('download-clinical-report').disabled = !report;
    $('save-report-config').disabled = phase === 'generating' || configBusy;
    $('clear-report-config').disabled = !config?.configured || phase === 'generating' || configBusy;
    $('report-config-state').textContent = config?.configured ? '已配置 · k3' : '未配置';
    $('report-state').textContent = phase === 'generating' ? 'K3 生成中' : phase === 'complete' ? '草稿已生成' : phase === 'failed' ? '生成失败' : !config?.configured ? '待配置 API' : ready ? '待生成' : '等待流程结束';
    const output = $('clinical-report-output');
    if (phase === 'generating') output.replaceChildren(placeholder('Kimi K3 正在整理报告', '已发送本次结构化摘要。可继续查看节点；生成完成前不会重复请求。', 'generating'));
    else if (phase === 'failed') output.replaceChildren(placeholder('报告尚未生成', failure + ' 未使用本地模板替代。', 'report-error'));
    else if (report) {
      const document = make('article', 'report-document');
      const head = make('div', 'report-document-head');
      const titlebar = make('div', 'report-titlebar'), title = make('div');
      title.append(make('p', 'eyebrow', 'CLINICAL MICROBIOLOGY / DRAFT'), make('h3', '', report.title));
      titlebar.append(title, copyButton('复制完整报告', () => reportMarkdown(false)));
      head.append(titlebar);
      head.append(make('p', 'report-provenance', `${report.provider} · ${report.model} · ${new Date(report.generated_at).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai'})}（上海时间） · 输入 ${report.input_sha256.slice(0,12)}`));
      document.append(head);
      const facts = make('dl', 'report-facts');
      for (const [label, value] of [['样本编号', report.source.sample.sample_id], ['样本类型', report.source.sample.sample_type], ['采集时间', report.source.sample.collected_at.replace('T', ' ')], ['流程状态', report.source.workflow_status === 'completed' ? '模拟流程完成' : '候选缺失 · 待复核']]) {
        const pair = make('div'); pair.append(make('dt', '', label), make('dd', '', value)); facts.append(pair);
      }
      document.append(facts, make('p', 'report-summary', report.summary));
      tableModules(report).forEach(module => document.append(renderTableModule(module)));
      for (const section of report.sections) {
        if (sectionKind(section.heading)) continue;
        const block = make('section', 'report-section');
        block.append(make('h4', '', section.heading), make('p', '', section.content));
        document.append(block);
      }
      const limits = make('div', 'report-limitations');
      for (const line of report.limitations) limits.append(make('p', '', line));
      document.append(limits); output.replaceChildren(document);
    } else output.replaceChildren(placeholder(ready ? '流程已结束，等待报告生成' : '等待流程结束', config?.configured ? '启用自动生成后，流程结束时会调用 Kimi K3。' : '请展开 API 配置并保存密钥；未配置时不会调用外部服务。'));
  }
  function accept(job) {
    if (job.status === 'succeeded') { report = job.report; phase = 'complete'; }
    else if (job.status === 'failed') { phase = 'failed'; failure = job.error; }
    else phase = 'generating';
    render();
  }
  async function poll(jobId, generation) {
    try {
      const job = await request(`/api/reports/${jobId}`);
      if (generation !== epoch) return;
      accept(job);
      if (phase === 'generating') pollTimer = setTimeout(() => poll(jobId, generation), 1200);
    } catch (error) {
      if (generation !== epoch) return;
      // Polling is read-only. Do not send another paid request after uncertainty.
      phase = 'failed'; failure = error.message + ' 请求结果未知，未自动重新提交。'; render();
    }
  }
  async function generate(retry = false) {
    const snapshot = getSnapshot();
    if (!terminal(snapshot) || !config?.configured || phase === 'generating' || phase === 'complete') return;
    const generation = epoch;
    attemptedRun = snapshot.run_id;
    phase = 'generating'; failure = ''; report = null; render();
    try {
      const job = await post('/api/reports', {snapshot, retry});
      if (generation !== epoch) return;
      accept(job);
      if (phase === 'generating') pollTimer = setTimeout(() => poll(job.id, generation), 600);
    } catch (error) {
      if (generation !== epoch) return;
      phase = 'failed'; failure = error.message; render();
    }
  }
  function maybeGenerate() {
    if (!getSnapshot) return;
    const snapshot = getSnapshot();
    render();
    if (config?.configured && !configBusy && $('report-auto').checked && terminal(snapshot) && attemptedRun !== snapshot.run_id) generate();
  }
  function reset() {
    epoch++; clearTimeout(pollTimer); pollTimer = null;
    phase = 'idle'; report = null; failure = ''; attemptedRun = null;
    render();
  }
  async function loadConfiguration() {
    try { config = await request('/api/report-config'); maybeGenerate(); }
    catch (error) { $('report-config-message').hidden = false; $('report-config-message').textContent = error.message; render(); }
  }
  async function saveConfiguration(clear = false) {
    if (!config || configBusy) return;
    configBusy = true; render();
    try {
      const options = clear ? {clear:true} : {api_key:$('kimi-api-key').value.trim()};
      const updated = await post('/api/report-config', options);
      config = {...config, ...updated};
      $('kimi-api-key').value = '';
      reset();
      $('report-config-message').textContent = clear ? '本次密钥已清除。' : '配置已保存在本机服务内存，模型固定为 k3。';
    } catch (error) { $('report-config-message').textContent = error.message; }
    finally { configBusy = false; $('report-config-message').hidden = false; maybeGenerate(); }
  }
  const escape = text => String(text).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  function reportMarkdown(includeSource = true) {
    const sample = report.source.sample;
    const lines = [`# ${report.title}`, '', ...report.limitations.map(line => `> ${line}`), '',
      `- 样本编号：${escape(sample.sample_id)}`, `- 样本类型：${escape(sample.sample_type)}`, `- 采集时间：${escape(sample.collected_at)}`,
      `- 模型：${report.provider} / ${report.model}`, `- 生成时间：${report.generated_at}`, `- 输入 SHA-256：${report.input_sha256}`, '', '## 摘要', '', escape(report.summary)];
    const tableCell = value => escape(plainCell(value)).replaceAll('|', '\\|');
    for (const module of tableModules(report)) {
      lines.push('', `## ${module.title}`, '', `| ${module.headers.map(tableCell).join(' | ')} |`,
        `| ${module.headers.map(() => '---').join(' | ')} |`,
        ...module.rows.map(row => `| ${row.map(tableCell).join(' | ')} |`), '', ...(module.description?[escape(module.description)]:[]), ...module.notes.map(escape));
    }
    for (const section of report.sections) if (!sectionKind(section.heading)) lines.push('', `## ${escape(section.heading).replaceAll('\n', ' ')}`, '', escape(section.content));
    if (includeSource) lines.push('', '## 结构化来源摘要', '', '```json', JSON.stringify(report.source, null, 2), '```');
    return lines.join('\n');
  }
  function download() {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([reportMarkdown()], {type:'text/markdown;charset=utf-8'}));
    const link = make('a'); link.href = url; link.download = `clinical-report-${report.source.run_id}.md`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function init(options) {
    getSnapshot = options.getSnapshot;
    $('report-config-form').addEventListener('submit', event => {event.preventDefault(); saveConfiguration();});
    $('clear-report-config').addEventListener('click', () => saveConfiguration(true));
    $('generate-report').addEventListener('click', () => generate(phase === 'failed'));
    $('download-clinical-report').addEventListener('click', download);
    $('report-auto').addEventListener('change', maybeGenerate);
    loadConfiguration();
  }
  window.ClinicalReports = {init, reset, onTerminal:maybeGenerate};
})();
