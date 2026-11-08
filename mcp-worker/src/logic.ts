// Pure planner logic; ported from planner.py / v_conflicts. No I/O.
export interface Session {
  id: string; day: string; start: string; end: string; stage: string | null; track: string | null;
  title: string; description: string | null; speakers: string | null; starts_utc: string; ends_utc: string;
  kind: 'official' | 'side'; url?: string | null; organizer?: string | null; price?: string | null; currency?: string | null;
  is_free?: number | null; online?: number | null; end_known?: number | null;
}
export interface PlanEntry { id: string; status: 'maybe' | 'must' | 'skip' | 'removed' }

const lc = (s: string | null | undefined) => (s ?? '').toLowerCase();

export function search(all: Session[], o: { query?: string; day?: string; track?: string; stage?: string; limit?: number; kind?: 'official' | 'side' | 'all' }) {
  const limit = Math.min(Math.max(o.limit ?? 30, 1), 100);
  const q = lc(o.query);
  return all
    .filter((s) => (o.kind === 'all' || s.kind === (o.kind ?? 'official')) && (!q || lc(s.title).includes(q) || lc(s.description).includes(q) || lc(s.speakers).includes(q)) &&
      (!o.day || s.day === o.day) && (!o.track || s.track === o.track) && (!o.stage || s.stage === o.stage))
    .slice(0, limit)
    .map(({ id, day, start, end, stage, track, title, kind }) => ({ id, day, start, end, stage, track, title, kind }));
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
  const row = (s: Session) => ({ id: s.id, title: s.title, day: s.day, start: s.start, end: s.end, stage: s.stage });
  for (let i = 0; i < active.length; i++) for (let j = i + 1; j < active.length; j++) {
    let a = active[i], b = active[j];
    if (a.id > b.id) [a, b] = [b, a];
    const overlap = a.starts_utc < b.ends_utc && b.starts_utc < a.ends_utc;
    const tight = bufferMin > 0 && (a.stage ?? '') !== (b.stage ?? '') &&
      a.starts_utc < addMin(b.ends_utc, bufferMin) && b.starts_utc < addMin(a.ends_utc, bufferMin);
    if (overlap || tight) conflicts.push({ kind: overlap ? 'overlap' : 'tight-gap', a: row(a), b: row(b), _k: a.starts_utc + b.starts_utc });
  }
  conflicts.sort((x: any, y: any) => x._k.localeCompare(y._k));
  for (const c of conflicts as any[]) delete c._k;
  return { plan: active.map((s) => ({ ...row(s), status: latest.get(s.id)!.status })), conflicts, unknown };
}

const CODE: Record<PlanEntry['status'], string> = { maybe: 'a', must: 'u', skip: 's', removed: 'r' };
const FROM = Object.fromEntries(Object.entries(CODE).map(([k, v]) => [v, k])) as Record<string, PlanEntry['status']>;
export const MAX_PLAN = 200;
const toB64 = (text: string) => {
  let bin = '';
  for (const b of new TextEncoder().encode(text)) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};
const fromB64 = (code: string) => {
  const bin = atob(code.replace(/-/g, '+').replace(/_/g, '/'));
  return new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
};

export function encodePlan(plan: PlanEntry[]) {
  if (plan.length > MAX_PLAN) throw new Error('plan too long');
  return toB64(JSON.stringify(plan.map((p) => [p.id, CODE[p.status]])));
}
export function decodePlan(code: string): PlanEntry[] {
  try {
    const raw = JSON.parse(fromB64(code));
    if (!Array.isArray(raw) || raw.length > MAX_PLAN) throw new Error();
    return raw.map((e: unknown) => {
      if (!Array.isArray(e) || typeof e[0] !== 'string' || !FROM[e[1]]) throw new Error();
      return { id: e[0], status: FROM[e[1]] };
    });
  } catch {
    throw new Error('bad plan code');
  }
}
