const { test } = require('node:test');
const assert = require('node:assert/strict');
const { CASES, NODES, createState, advance, statusOf, isolatesOf, outputOf, reportOf, detectionOf } =
  require('../phage_lab/web/workflow-model.js');

test('isolation preserves the entire fixture and releases both match branches', () => {
  const state = createState('mixed');
  assert.equal(statusOf(state, 'sample'), 'running');
  advance(state, 2);
  assert.equal(statusOf(state, 'isolate'), 'succeeded');
  assert.equal(statusOf(state, 'phage'), 'running');
  assert.equal(statusOf(state, 'antibiotic'), 'running');
  assert.deepEqual(outputOf(state, 'isolate').isolates, CASES.mixed.isolates);
});

test('fragment evidence is deterministic, synthetic, locally scoped and not a clinical probability', () => {
  const a = createState('mixed'), b = createState('mixed');
  assert.equal(detectionOf(a), null);
  advance(a, 2); advance(b, 2);
  const detection = detectionOf(a);
  assert.deepEqual(detection, detectionOf(b));
  assert.equal(detection.method, 'synthetic-mngs-v1');
  assert.equal(detection.identified.length, 3);
  assert.ok(detection.identified[0].confidence.score > detection.identified[2].confidence.score);
  for (const item of [...detection.identified, ...detection.unclassified]) {
    assert.equal(item.confidence.calibrated, false);
    assert.equal(item.confidence.clinical_probability, null);
    assert.ok(item.confidence.score >= 0 && item.confidence.score <= 100);
    assert.ok(item.fragments.length >= 2);
    for (const fragment of item.fragments) {
      assert.match(fragment.sequence, /^[ACGT]+$/);
      assert.equal(fragment.sequence.length, fragment.length_bp);
      assert.equal(fragment.synthetic, true);
    }
  }
  assert.equal(detection.unclassified.length, 1);
  assert.equal(detection.unclassified[0].species_assignment, null);
  assert.equal(detection.unclassified[0].confirmed_new_species, false);
  assert.equal(outputOf(a, 'phage'), null);
  advance(a, 1);
  assert.equal(outputOf(a, 'phage').matches.some(m=>m.isolate_id===detection.unclassified[0].id), false);
  assert.equal(reportOf(a).probabilities, 'not_estimated');
  detection.identified[0].fragments[0].sequence = 'TAMPERED';
  assert.notEqual(detectionOf(a).identified[0].fragments[0].sequence, 'TAMPERED');
});

test('single sample has no unnamed signal; unmatched sample does not invent a species', () => {
  const single = createState('single'), unmatched = createState('unmatched');
  advance(single, 3); advance(unmatched, 3);
  assert.equal(detectionOf(single).unclassified.length, 0);
  assert.equal(detectionOf(unmatched).identified.length, 0);
  assert.equal(detectionOf(unmatched).unclassified[0].species_assignment, null);
  assert.equal(statusOf(unmatched, 'phage'), 'review');
});
test('antibiotic output completes independently while preparation is pending', () => {
  const state = createState('mixed');
  advance(state, 3);
  assert.equal(statusOf(state, 'antibiotic'), 'succeeded');
  assert.equal(statusOf(state, 'prepare'), 'running');
  assert.equal(statusOf(state, 'design'), 'waiting');
  advance(state, 6.9);
  assert.equal(statusOf(state, 'prepare'), 'running');
  advance(state, 0.1);
  assert.equal(statusOf(state, 'prepare'), 'succeeded');
});
test('unmatched isolate stays unresolved; no preparation or downstream dispatch', () => {
  const state = createState('unmatched');
  advance(state, 50);
  assert.equal(statusOf(state, 'phage'), 'review');
  assert.equal(statusOf(state, 'antibiotic'), 'review');
  assert.equal(statusOf(state, 'prepare'), 'blocked');
  assert.equal(statusOf(state, 'design'), 'blocked');
  assert.equal(outputOf(state, 'phage').matches[0].candidates.length, 0);
});
test('reports distinguish simulated presentation from physical evidence', () => {
  const state = createState('mixed', { sample_id: '<img src=x>', sample_type: '模拟样本', collected_at: '2026-10-17T09:00' });
  const pending = reportOf(state);
  assert.equal(pending.nodes.find(n => n.id === 'isolate').output, null);
  advance(state, 50);
  const report = reportOf(state);
  assert.equal(report.sample.sample_id, '<img src=x>');
  assert.equal(report.simulated, true);
  assert.equal(report.evidence_class, 'none');
  assert.equal(report.physical_execution, false);
  assert.equal(report.execution_mode, 'presentation_only');
  assert.equal(report.probabilities, 'not_estimated');
  assert.equal(reportOf(createState('mixed')).scenario_day, 0);
  assert.equal(statusOf(state, 'learn'), 'succeeded');
});
test('fixtures and independent runs cannot mutate each other', () => {
  const a = createState('mixed');
  isolatesOf(a)[0].name = 'tampered';
  assert.notEqual(isolatesOf(createState('mixed'))[0].name, 'tampered');
  assert.throws(() => createState('absent'));
  assert.throws(() => advance(a, -1));
  assert.equal(new Set(NODES.map(n => n.id)).size, NODES.length);
});
