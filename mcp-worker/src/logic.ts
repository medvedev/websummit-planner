// Pure planner logic; ported from planner.py / v_conflicts. No I/O.
export interface Session {
  id: string; day: string; start: string; end: string; stage: string | null; track: string | null;
  title: string; description: string | null; speakers: string | null; starts_utc: string; ends_utc: string;
}
export interface PlanEntry { id: string; status: 'maybe' | 'must' | 'skip' | 'removed' }

const lc = (s: string | null | undefined) => (s ?? '').toLowerCase();

export function search(all: Session[], o: { query?: string; day?: string; track?: string; stage?: string; limit?: number }) {
  const limit = Math.min(Math.max(o.limit ?? 30, 1), 100);
  const q = lc(o.query);
  return all
    .filter((s) => (!q || lc(s.title).includes(q) || lc(s.description).includes(q) || lc(s.speakers).includes(q)) &&
      (!o.day || s.day === o.day) && (!o.track || s.track === o.track) && (!o.stage || s.stage === o.stage))
    .slice(0, limit)
    .map(({ id, day, start, end, stage, track, title }) => ({ id, day, start, end, stage, track, title }));
}

export function details(all: Session[], ids: string[]) {
  const set = new Set(ids.slice(0, 20));
  return all.filter((s) => set.has(s.id));
}

const addMin = (iso: string, min: number) => new Date(Date.parse(iso) + min * 60000).toISOString().replace('.000Z', 'Z');

// Mirrors v_conflicts: overlap, or (different stage, buffer>0) gap smaller than the buffer.
export function checkPlan(all: Session[], plan: PlanEntry[], bufferMin = 0) {
  const byId = new Map(all.map((s) => [s.id, s]));
  const unknown = plan.filter((p) => !byId.has(p.id)).map((p) => p.id);
  const latest = new Map<string, PlanEntry>();
  for (const p of plan) if (byId.has(p.id)) latest.set(p.id, p);
  const active = [...latest.values()].filter((p) => p.status === 'maybe' || p.status === 'must')
    .map((p) => byId.get(p.id)!).sort((a, b) => a.starts_utc.localeCompare(b.starts_utc) || a.id.localeCompare(b.id));
  const conflicts: unknown[] = [];
  const row = (s: Session) => ({ id: s.id, title: s.title, start: s.start, end: s.end, stage: s.stage });
  for (let i = 0; i < active.length; i++) for (let j = i + 1; j < active.length; j++) {
    let a = active[i], b = active[j];
    if (a.id > b.id) [a, b] = [b, a];
    const overlap = a.starts_utc < b.ends_utc && b.starts_utc < a.ends_utc;
    const tight = bufferMin > 0 && (a.stage ?? '') !== (b.stage ?? '') &&
      a.starts_utc < addMin(b.ends_utc, bufferMin) && b.starts_utc < addMin(a.ends_utc, bufferMin);
    if (overlap || tight) conflicts.push({ kind: overlap ? 'overlap' : 'tight-gap', a: row(a), b: row(b) });
  }
  conflicts.sort((x: any, y: any) => (x.a.start + x.b.start).localeCompare(y.a.start + y.b.start));
  return { plan: active.map((s) => ({ ...row(s), day: s.day, status: latest.get(s.id)!.status })), conflicts, unknown };
}

const CODE: Record<PlanEntry['status'], string> = { maybe: 'a', must: 'u', skip: 's', removed: 'r' };
const FROM = Object.fromEntries(Object.entries(CODE).map(([k, v]) => [v, k])) as Record<string, PlanEntry['status']>;
const b64 = (s: string) => btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

export function encodePlan(plan: PlanEntry[]) {
  return b64(JSON.stringify(plan.map((p) => [p.id, CODE[p.status]])));
}
export function decodePlan(code: string): PlanEntry[] {
  const raw = JSON.parse(atob(code.replace(/-/g, '+').replace(/_/g, '/')));
  if (!Array.isArray(raw) || raw.length > 500) throw new Error('bad plan code');
  return raw.map(([id, c]: [string, string]) => {
    if (typeof id !== 'string' || !FROM[c]) throw new Error('bad plan code');
    return { id, status: FROM[c] };
  });
}
