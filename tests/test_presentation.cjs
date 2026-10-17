const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createState, advance, tourFrame, timelineOf, reviewOf} = require('../phage_lab/web/workflow-model.js');

test('guided story maps two minutes to scenario days without changing scientific state', () => {
  assert.equal(tourFrame(0,'mixed').day,0);
  assert.equal(tourFrame(30,'mixed').key,'review');
  assert.equal(tourFrame(35,'mixed').day,2);
  assert.equal(tourFrame(58,'mixed').day,3);
  assert.equal(tourFrame(72,'mixed').day,6.5);
  assert.equal(tourFrame(86,'mixed').day,10);
  assert.equal(tourFrame(120,'mixed').key,'report');
  assert.equal(tourFrame(999,'mixed').day,13);
  assert.equal(tourFrame(999,'mixed').finished,true);
  assert.equal(tourFrame(0,'mixed').duration,132);
  for (let second=0;second<132;second++) assert.ok(tourFrame(second+1,'mixed').day>=tourFrame(second,'mixed').day);
});

test('unmatched tour stops at review, while single case does not claim an unknown discovery', () => {
  const last = tourFrame(999,'unmatched');
  assert.equal(last.day,3);
  assert.equal(last.key,'report');
  assert.match(last.body,/复核/);
  assert.doesNotMatch(tourFrame(35,'single').body,/发现了|发现一/);
  assert.equal(tourFrame(35,'single').target,'isolates-title');
});

test('parallel timeline preserves independent antibiotic completion and seven-day preparation', () => {
  const state = createState('mixed'); advance(state,6.5);
  const timeline = timelineOf(state);
  assert.equal(timeline.antibiotic.status,'succeeded');
  assert.equal(timeline.antibiotic.readyDay,3);
  assert.equal(timeline.prepare.status,'running');
  assert.equal(timeline.prepare.progress,.5);
  assert.equal(timeline.prepare.duration,7);
  const unknown = createState('unmatched'); advance(unknown,3);
  assert.equal(timelineOf(unknown).prepare.status,'blocked');
  assert.equal(timelineOf(unknown).prepare.progress,0);
});

test('review count survives successful workflow completion and includes low-support candidates', () => {
  const mixed = createState('mixed');
  assert.equal(reviewOf(mixed).length,0);
  advance(mixed,13);
  assert.deepEqual(reviewOf(mixed).map(item=>item.id),['DET-003','UNCL-001']);
  const single = createState('single'); advance(single,13);
  assert.equal(reviewOf(single).length,0);
  const unmatched = createState('unmatched'); advance(unmatched,3);
  assert.equal(reviewOf(unmatched).length,1);
});
