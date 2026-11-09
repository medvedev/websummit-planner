"""Shared company queries for planner.py, export_text.py and agenda.py. Standard library only.

Company IDs are exposed as "company:<n>" strings; the bare number only appears inside URLs.
Works with any sqlite3 connection (row factory not required).
"""
import re
from urllib.parse import quote

TIER_RANK = "CASE c.tier WHEN 'Partner' THEN 0 WHEN 'Growth' THEN 1 WHEN 'Beta' THEN 2 WHEN 'Alpha' THEN 3 WHEN 'Media Partner' THEN 4 ELSE 5 END"
_ID = re.compile(r'^(?:company:)?(\d+)$')


def event_url(event_id):
    """Universal link that opens an official event in the Web Summit mobile app."""
    return 'https://link.websummit.com/?url=' + quote('https://attend.websummit.com/dl/lis26/event?id=' + event_id + '&mobile=true', safe='')


def company_url(n):
    return 'https://attend.websummit.com/lis26/company/%d' % int(n)


def person_url(uuid):
    return 'https://attend.websummit.com/lis26/profiles/' + uuid


def parse_company_id(s):
    """'company:62217' or '62217' -> 62217; anything else -> None."""
    m = _ID.match(str(s).strip())
    if not m or int(m.group(1)) <= 0:
        return None
    return int(m.group(1))


def _rows(con, sql, params=()):
    cur = con.execute(sql, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _cid(n):
    return 'company:%d' % n


def search_companies(con, query='', industry=None, country=None, tier=None, tags=(), facts=(), limit=30):
    where, params = [], []
    if query:
        where.append("(instr(lower(c.name),lower(?))>0 OR instr(lower(coalesce(c.description,'')),lower(?))>0"
                     " OR instr(lower(coalesce(c.location,'')),lower(?))>0"
                     " OR EXISTS (SELECT 1 FROM company_tag t WHERE t.company_id=c.id AND instr(lower(t.tag),lower(?))>0))")
        params += [query] * 4
    for col, value in (('c.industry', industry), ('c.country', country), ('c.tier', tier)):
        if value:
            where.append(col + '=?')
            params.append(value)
    for tag in tags:
        where.append('EXISTS (SELECT 1 FROM company_tag t WHERE t.company_id=c.id AND lower(t.tag)=lower(?))')
        params.append(tag)
    for fact in facts:
        where.append('EXISTS (SELECT 1 FROM company_fact f WHERE f.company_id=c.id AND instr(lower(f.fact),lower(?))>0)')
        params.append(fact)
    sql = 'SELECT c.id,c.name,c.tier,c.industry,c.location FROM company c'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY ' + TIER_RANK + ',c.name,c.id LIMIT ?'
    out = _rows(con, sql, params + [limit])
    for r in out:
        n = r['id']
        r['id'] = _cid(n)
        r['facts'] = [x[0] for x in con.execute('SELECT fact FROM company_fact WHERE company_id=? ORDER BY position,rowid', (n,))]
        r['url'] = company_url(n)
    return [{k: r[k] for k in ('id', 'name', 'tier', 'industry', 'location', 'facts', 'url')} for r in out]


def _session_row(r):
    r = dict(r)
    r['url'] = event_url(r['id']) if r['kind'] == 'official' else None
    return r


def company_objects(con, ids=None):
    """Details objects, ordered by id. ids: iterable of ints (None = all companies)."""
    if ids is None:
        base = _rows(con, 'SELECT * FROM company ORDER BY id')
    else:
        ids = sorted(set(ids))
        base = _rows(con, 'SELECT * FROM company WHERE id IN (%s) ORDER BY id' % ','.join('?' * len(ids)), ids) if ids else []
    out = []
    for c in base:
        n = c['id']
        o = dict(c)
        o['id'] = _cid(n)
        o['url'] = company_url(n)
        o['tags'] = [x[0] for x in con.execute('SELECT tag FROM company_tag WHERE company_id=? ORDER BY tag', (n,))]
        o['facts'] = [x[0] for x in con.execute('SELECT fact FROM company_fact WHERE company_id=? ORDER BY position,rowid', (n,))]
        o['links'] = _rows(con, 'SELECT kind,url FROM company_link WHERE company_id=? ORDER BY kind,url', (n,))
        o['sessions'] = [_session_row(r) for r in _rows(
            con, 'SELECT v.id,v.day,v.start,v.end,v.stage,v.title,v.kind,e.type FROM company_event e '
                 'JOIN v_titles v ON v.id=e.session_id WHERE e.company_id=? ORDER BY v.day,v.start,v.id', (n,))]
        o['activities'] = _rows(
            con, 'SELECT title,time_text,location,type,description FROM company_event '
                 'WHERE company_id=? AND session_id IS NULL ORDER BY title,event_uuid', (n,))
        speakers = _rows(
            con, 'SELECT p.id,p.name,p.job_title,cp.role FROM company_person cp JOIN person p ON p.id=cp.person_uuid '
                 'WHERE cp.company_id=? ORDER BY p.name,p.id', (n,))
        for s in speakers:
            s['url'] = person_url(s['id'])
            s['sessions'] = [x[0] for x in con.execute(
                'SELECT id FROM (SELECT s.id,s.starts_utc FROM session_person sp JOIN session s ON s.id=sp.session_id WHERE sp.person_id=?1 '
                'UNION SELECT s.id,s.starts_utc FROM company_event_speaker es JOIN session s ON s.id=es.event_uuid '
                'WHERE es.company_id=?2 AND es.person_uuid=?1) ORDER BY starts_utc,id', (s['id'], n))]
        o['speakers'] = speakers
        o['team'] = [dict(r, url=person_url(r['person_uuid'])) for r in _rows(
            con, 'SELECT person_uuid,role,tier,industry,country FROM company_person WHERE company_id=? '
                 'AND person_uuid NOT IN (SELECT id FROM person) ORDER BY person_uuid', (n,))]
        endorses = []
        for e in _rows(con, 'SELECT e.endorsed_company_id AS eid, coalesce(c2.name,e.endorsed_name) AS name '
                            'FROM company_endorsement e LEFT JOIN company c2 ON c2.id=e.endorsed_company_id '
                            'WHERE e.company_id=? ORDER BY name,eid', (n,)):
            known = e['eid'] is not None and con.execute('SELECT 1 FROM company WHERE id=?', (e['eid'],)).fetchone()
            endorses.append({'id': _cid(e['eid']) if known else None, 'name': e['name'],
                             'url': company_url(e['eid']) if known else None})
        o['endorses'] = endorses
        out.append(o)
    return out


def session_companies(con, session_id):
    """[{id, name, relation}] host first, then speaker; ordered by relation, name, id."""
    rows = _rows(con, """
        SELECT c.id, c.name, 'host' AS relation FROM company_event e JOIN company c ON c.id=e.company_id
         WHERE e.session_id=?1
        UNION
        SELECT c.id, c.name, 'speaker' FROM session_person sp JOIN company_person cp ON cp.person_uuid=sp.person_id
         JOIN company c ON c.id=cp.company_id WHERE sp.session_id=?1
        ORDER BY 3 DESC, 2, 1""", (session_id,))
    return [{'id': _cid(r['id']), 'name': r['name'], 'relation': r['relation']} for r in rows]


def info_counts(con):
    def counts(sql):
        return {k: v for k, v in con.execute(sql)}
    return {
        'companies': con.execute('SELECT count(*) FROM company').fetchone()[0],
        'company_tiers': counts('SELECT tier,count(*) FROM company WHERE tier IS NOT NULL GROUP BY tier ORDER BY 2 DESC,1'),
        'company_industries': counts('SELECT industry,count(*) FROM company WHERE industry IS NOT NULL GROUP BY industry ORDER BY 2 DESC,1'),
        'company_facts': counts('SELECT fact,count(DISTINCT company_id) FROM company_fact GROUP BY fact ORDER BY 2 DESC,1'),
    }
