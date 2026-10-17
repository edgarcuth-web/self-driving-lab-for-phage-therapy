// Exercise asynchronous report delivery without a browser, network or API key.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../phage_lab/web/report-ui.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

function harness(reportResponse, {clipboardError = false} = {}) {
  class Element {
    constructor(tagName = '') { this.tagName = tagName; this.children = []; this.events = {}; this.attributes = {}; this.textContent = ''; this.value = ''; }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.children = nodes; }
    addEventListener(event, action) { this.events[event] = action; }
    setAttribute(name, value) { this.attributes[name] = value; }
    get text() { return this.textContent + this.children.map(n => n.text).join(''); }
    all(predicate) { return [...(predicate(this) ? [this] : []), ...this.children.flatMap(n => n.all(predicate))]; }
  }
  const elements = new Map(), calls = [], clipboard = [], window = {};
  const document = {
    createElement: tag => new Element(tag),
    getElementById: id => {
      if (!elements.has(id)) elements.set(id, new Element());
      return elements.get(id);
    },
  };
  document.getElementById('report-auto').checked = true;
  vm.runInNewContext(source, {
    window, document, clearTimeout: () => {}, setTimeout: () => 1,
    navigator: {clipboard: {writeText: async value => {
      if (clipboardError) throw new Error('clipboard denied');
      clipboard.push(value);
    }}},
    fetch: async (path, options) => {
      calls.push({path, body: options.body ? JSON.parse(options.body) : null});
      const data = path === '/api/report-config'
        ? {configured:true, model:'k3', token:'test-session-token'}
        : await reportResponse();
      return {ok:true, json:async () => data};
    },
  });
  return {api: window.ClinicalReports, elements, calls, clipboard};
}

test('reset detaches an in-flight model result from a new run', async () => {
  let resolve;
  const pending = new Promise(done => {resolve = done;});
  const h = harness(() => pending);
  let snapshot = {run_id:'old-run', nodes:[{id:'learn', status:'succeeded'}]};
  h.api.init({getSnapshot: () => snapshot});
  await settle();
  assert.equal(h.calls.filter(c => c.path === '/api/reports').length, 1);
  snapshot = {run_id:'new-run', nodes:[{id:'learn', status:'waiting'}]};
  h.api.reset();
  resolve({status:'succeeded', report:{summary:'OLD-REPORT'}});
  await settle();
  assert.equal(h.elements.get('report-state').textContent, '等待流程结束');
  assert.equal(h.elements.get('clinical-report-output').text.includes('OLD-REPORT'), false);
  assert.equal(h.elements.get('download-clinical-report').disabled, true);
});

test('one auto-attempt per run; a failed request retries only on explicit click', async () => {
  const h = harness(async () => ({status:'failed', error:'TEST UPSTREAM ERROR'}));
  const snapshot = {run_id:'same-run', nodes:[{id:'learn', status:'succeeded'}]};
  h.api.init({getSnapshot: () => snapshot});
  await settle();
  h.api.onTerminal(); h.api.onTerminal();
  await settle();
  assert.equal(h.calls.filter(c => c.path === '/api/reports').length, 1);
  assert.equal(h.elements.get('report-state').textContent, '生成失败');
  assert.equal(h.elements.get('clinical-report-output').text.includes('TEST UPSTREAM ERROR'), true);
  h.elements.get('generate-report').events.click();
  await settle();
  const requests = h.calls.filter(c => c.path === '/api/reports');
  assert.equal(requests.length, 2);
  assert.equal(requests[1].body.retry, true);
});

function draft() {
  return {title:'临床报告（模拟草稿）', provider:'Kimi Code', model:'k3', generated_at:'2026-10-17T06:00:00Z', input_sha256:'a'.repeat(64),
    summary:'SUMMARY', limitations:['模拟数据，需医师复核。'],
    source:{run_id:'test-run', sample:{sample_id:'DEMO-001',sample_type:'模拟样本',collected_at:'2026-10-17T09:00'}, workflow_status:'needs_review',
      isolates:[{id:'ISO-A',name:'示例菌A',species:'Demo A'},{id:'ISO-B',name:'未收录菌株',species:'Demo B'}],
      matches:{phage:[{isolate_id:'ISO-A',candidates:['PHG-DEMO-A01','PHG-DEMO-A02']},{isolate_id:'ISO-B',candidates:[]}],
        antibiotic:[{isolate_id:'ISO-A',candidates:['ABX-DEMO-01']},{isolate_id:'ISO-B',candidates:[]}] }},
    sections:[{heading:'样本概况',content:'SAMPLE NARRATIVE'},{heading:'模拟分离菌',content:'ISOLATE NARRATIVE'},
      {heading:'噬菌体候选（虚构编号）',content:'PHAGE NARRATIVE'},{heading:'抗生素候选（虚构编号）',content:'ANTIBIOTIC NARRATIVE'}]};
}

test('report tables preserve all isolates and unmatched rows; each module copies its own data', async () => {
  const h = harness(async () => ({status:'succeeded', report:draft()}));
  h.api.init({getSnapshot: () => ({run_id:'test-run',nodes:[{id:'learn',status:'succeeded'}]})});
  await settle();
  const output = h.elements.get('clinical-report-output');
  const tables = output.all(n => n.tagName === 'table');
  assert.equal(tables.length, 3);
  assert.ok(tables[0].text.includes('ISO-A') && tables[0].text.includes('ISO-B'));
  assert.ok(tables[1].text.includes('PHG-DEMO-A02') && tables[1].text.includes('未匹配'));
  assert.ok(tables[2].text.includes('ABX-DEMO-01') && tables[2].text.includes('未匹配'));
  const buttons = output.all(n => n.tagName === 'button');
  assert.equal(buttons.length, 4);
  await buttons.find(n => n.attributes['aria-label'] === '复制噬菌体候选').events.click();
  assert.ok(h.clipboard[0].includes('\t') && h.clipboard[0].includes('PHG-DEMO-A02'));
  assert.ok(h.clipboard[0].includes('未匹配') && !h.clipboard[0].includes('ABX-DEMO-01'));
  await buttons.find(n => n.attributes['aria-label'] === '复制完整报告').events.click();
  assert.ok(h.clipboard[1].includes('ABX-DEMO-01') && h.clipboard[1].includes('模拟分离菌'));
  assert.ok(h.clipboard[1].includes('SAMPLE NARRATIVE') && h.clipboard[1].includes('需医师复核'));
});

test('denied clipboard access gives visible failure feedback without removing the report', async () => {
  const h = harness(async () => ({status:'succeeded',report:draft()}), {clipboardError:true});
  h.api.init({getSnapshot: () => ({run_id:'test-run',nodes:[{id:'learn',status:'succeeded'}]})});
  await settle();
  const output = h.elements.get('clinical-report-output');
  const button = output.all(n => n.attributes['aria-label'] === '复制完整报告')[0];
  assert.ok(button);
  await button.events.click();
  assert.ok(button.textContent.includes('复制失败'));
  assert.ok(output.text.includes('SUMMARY'));
});

test('fragment support and unnamed signals remain separate from species confidence and candidate matching', async () => {
  const report = draft();
  report.source.detection = {identified:[{isolate_id:'ISO-A',confidence:{score:97.1}}],
    unclassified:[{id:'UNCL-001',species_assignment:null,confidence:{score:63.7}}]};
  report.sections.push({heading:'发现未命名细菌',content:'物种未确定，不是新菌种确证。'});
  const h = harness(async () => ({status:'succeeded',report}));
  h.api.init({getSnapshot:()=>({run_id:'test-run',nodes:[{id:'learn',status:'succeeded'}]})});
  await settle();
  const output = h.elements.get('clinical-report-output');
  const tables = output.all(n=>n.tagName==='table');
  assert.equal(tables.length,4);
  assert.ok(tables[0].text.includes('97.1 / 100'));
  assert.ok(tables[3].text.includes('UNCL-001') && tables[3].text.includes('未确定'));
  assert.ok(!tables[1].text.includes('UNCL-001') && !tables[2].text.includes('UNCL-001'));
  await output.all(n=>n.attributes['aria-label']==='复制完整报告')[0].events.click();
  assert.ok(h.clipboard[0].includes('97.1 / 100') && h.clipboard[0].includes('发现未命名细菌'));
  assert.ok(h.clipboard[0].includes('未经临床校准'));
});
