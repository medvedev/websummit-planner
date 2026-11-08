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
  { buffer: 10, ids: all.filter((s) => s.day === '2026-11-11' && (s.kind === 'side' || s.start < '10:30')).slice(0, 60).map((s) => s.id) },
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

test('plan code handles unicode ids and rejects malformed input', () => {
  const p = [{ id: 'сесія-1', status: 'maybe' }];
  assert.deepEqual(decodePlan(encodePlan(p)), p);
  const enc = (v) => Buffer.from(JSON.stringify(v)).toString('base64url');
  assert.throws(() => decodePlan(enc([null])), /bad plan code/);
  assert.throws(() => decodePlan(enc([['x', 'q']])), /bad plan code/);
  assert.throws(() => decodePlan(enc(Array.from({ length: 201 }, () => ['x', 'a']))), /bad plan code/);
  assert.throws(() => encodePlan(Array.from({ length: 201 }, () => ({ id: 'x', status: 'must' }))));
});

test('conflicts are chronological across days and carry the day', () => {
  const mk = (id, day, start, end) => ({ id, day, start: start.slice(11, 16), end: end.slice(11, 16), stage: 'S' + id, track: null,
    title: id, description: null, speakers: null, starts_utc: start, ends_utc: end, kind: 'official' });
  const sessions = [
    mk('a', '2026-11-11', '2026-11-11T09:00:00Z', '2026-11-11T10:00:00Z'), mk('b', '2026-11-11', '2026-11-11T09:30:00Z', '2026-11-11T10:30:00Z'),
    mk('c', '2026-11-10', '2026-11-10T15:00:00Z', '2026-11-10T16:00:00Z'), mk('d', '2026-11-10', '2026-11-10T15:30:00Z', '2026-11-10T16:30:00Z'),
  ];
  const r = checkPlan(sessions, ['a', 'b', 'c', 'd'].map((id) => ({ id, status: 'must' })));
  assert.deepEqual(r.conflicts.map((c) => c.a.day), ['2026-11-10', '2026-11-11']);
});

test('search defaults to official sessions; kind=side finds side events', async () => {
  const { search } = await import('../src/logic.ts');
  assert.ok(search(all, { limit: 100 }).every((r) => r.kind === 'official'));
  const side = search(all, { kind: 'side', limit: 100 });
  assert.ok(side.length > 0 && side.every((r) => r.id.startsWith('side:')));
  const mixed = search(all, { kind: 'all', limit: 100 });
  assert.ok(mixed.some((r) => r.kind === 'side') && mixed.some((r) => r.kind === 'official'));
});
