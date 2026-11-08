// Parity: the Worker's checkPlan must match `planner.py conflicts` on fixture plans.
import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { checkPlan, encodePlan, decodePlan } from '../src/logic.ts';

const py = (db, ...a) => JSON.parse(execFileSync('python3', ['../skills/websummit-planner/scripts/planner.py', '--db', db, ...a], { encoding: 'utf8' }));
execFileSync('python3', ['../skills/websummit-planner/scripts/export_text.py', '--out', '../out/text']);
const all = JSON.parse(readFileSync('../out/text/schedule.json', 'utf8')).sessions;

// Fixture plans: pairs chosen from real overlapping / adjacent sessions on one day.
const day = all.filter((s) => s.day === '2026-11-10');
const fixtures = [
  { buffer: 0, ids: day.slice(0, 6).map((s) => s.id) },
  { buffer: 15, ids: day.slice(100, 112).map((s) => s.id) },
  { buffer: 30, ids: day.filter((_, i) => i % 40 === 0).map((s) => s.id) },
];

for (const [n, f] of fixtures.entries()) {
  test(`parity fixture ${n}`, () => {
    const db = join(mkdtempSync(join(tmpdir(), 'par-')), 'p.db');
    for (const id of f.ids) py(db, 'mark', id, 'maybe');
    py(db, 'buffer', String(f.buffer));
    const expected = py(db, 'conflicts').map((c) => [c.kind, c.a_id, c.b_id]);
    const got = checkPlan(all, f.ids.map((id) => ({ id, status: 'maybe' })), f.buffer).conflicts.map((c) => [c.kind, c.a.id, c.b.id]);
    const key = (r) => r.join('|');
    assert.deepEqual(got.map(key).sort(), expected.map(key).sort());
  });
}

test('plan code round trip', () => {
  const p = [{ id: 'a', status: 'must' }, { id: 'b', status: 'maybe' }, { id: 'c', status: 'removed' }];
  assert.deepEqual(decodePlan(encodePlan(p)), p);
  assert.throws(() => decodePlan('@@'));
});

test('unknown ids reported, skip excluded', () => {
  const r = checkPlan(all, [{ id: 'zzz', status: 'must' }, { id: day[0].id, status: 'skip' }]);
  assert.deepEqual(r.unknown, ['zzz']);
  assert.equal(r.plan.length, 0);
});
