#!/usr/bin/env python3
"""Download the Web Summit Lisbon 2026 schedule and write JSON + Markdown.

Usage: fetch_schedule.py [--delay 1.0] [--dates 2026-11-09 ...] [--out out] [--force]

Raw pages are cached in <out>/raw/, so an interrupted run resumes without
re-requesting (cached pages cost no delay). Standard library only.
"""
import argparse, json, sys, time, urllib.error, urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = ("https://websummit.com/api/list-items/?slug=schedule"
        "&typename=DefaultTemplate_Custompage_FlexibleContent_ScheduleList"
        "&timezone=Europe%2FLisbon")
DEFAULT_DATES = ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]
UA = "Mozilla/5.0 (schedule-fetcher; personal use)"
TZ = ZoneInfo("Europe/Lisbon")


def fmt(sec):
    sec = max(0, int(sec))
    return f"{sec // 60:d}:{sec % 60:02d}"


class Progress:
    def __init__(self):
        self.total = 0
        self.done = 0
        self.t0 = time.time()
        self.net_done = 0  # pages actually fetched (cached ones don't count for ETA)

    def draw(self, label):
        frac = self.done / self.total if self.total else 0
        w = 30
        bar = "#" * int(w * frac) + "-" * (w - int(w * frac))
        el = time.time() - self.t0
        eta = (el / self.net_done) * (self.total - self.done) if self.net_done else 0
        msg = (f"\r[{bar}] {self.done}/{self.total} {frac:4.0%}  "
               f"elapsed {fmt(el)}  ETA {fmt(eta)}  {label:<14}")
        sys.stderr.write(msg)
        sys.stderr.flush()


def get_json(url, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))  # 2,4,8s backoff
    raise RuntimeError("unreachable")


def page_url(date, page):
    return f"{BASE}&page={page}&date={date}"


def load_page(date, page, raw, delay, prog, force):
    """Return (data, fetched_from_network). Sleeps `delay` before network calls."""
    f = raw / f"{date}_p{page:03d}.json"
    if f.exists() and not force:
        return json.loads(f.read_text(encoding='utf-8'))["data"], False
    if prog.net_done:  # no delay before the very first request
        time.sleep(delay)
    d = get_json(page_url(date, page))
    if "data" not in d:
        raise RuntimeError(f"unexpected response for {date} page {page}: {str(d)[:200]}")
    f.write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')
    return d["data"], True


def local(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)


def to_markdown(items, fetched_at):
    by_day = defaultdict(list)
    for it in items:
        by_day[local(it["starts_at"]).date()].append(it)
    out = [
        "# Web Summit Lisbon 2026 — Schedule",
        "",
        f"Fetched {fetched_at} from websummit.com. {len(items)} sessions. "
        "All times Europe/Lisbon. Format: `HH:MM–HH:MM | Stage | Track` then title, "
        "speakers, description.",
        "",
    ]
    for day in sorted(by_day):
        out += [f"## {day:%A %d %B %Y}", ""]
        for it in sorted(by_day[day], key=lambda i: (i["starts_at"], i["location"]["name"])):
            s, e = local(it["starts_at"]), local(it["ends_at"])
            track = (it.get("schedule_track") or {}).get("name") or "-"
            out.append(f"### {it['title']}")
            out.append(f"{s:%H:%M}–{e:%H:%M} | {it['location']['name'] or '-'} | {track}")
            people = [
                f"{p['name']} ({', '.join(x for x in (p.get('job_title'), p.get('company_name')) if x)})"
                for p in it.get("timeslot_participations") or []
            ]
            if people:
                out.append("Speakers: " + "; ".join(people))
            if it.get("description"):
                out += ["", it["description"].strip()]
            out.append(f"\nid: {it['id']}  slug: {it['slug']}\n")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    ap.add_argument("--dates", nargs="+", default=DEFAULT_DATES)
    ap.add_argument("--out", default="out")
    ap.add_argument("--force", action="store_true", help="ignore cached raw pages")
    a = ap.parse_args()

    out = Path(a.out)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    prog = Progress()
    items = {}

    def take(data):
        for it in data["listItems"]:
            items[it["id"]] = it

    # Pass 1: first page of each date reveals nbPages.
    first, pages = {}, {}
    prog.total = len(a.dates)
    for d in a.dates:
        prog.draw(f"{d} p1")
        data, net = load_page(d, 1, raw, a.delay, prog, a.force)
        prog.net_done += net
        prog.done += 1
        first[d], pages[d] = data, data["nbPages"]
        take(data)
        prog.total = prog.done + sum(pages[x] - 1 for x in pages) + (len(a.dates) - len(first))

    # Pass 2: remaining pages.
    for d in a.dates:
        for p in range(2, pages[d] + 1):
            prog.draw(f"{d} p{p}")
            data, net = load_page(d, p, raw, a.delay, prog, a.force)
            prog.net_done += net
            prog.done += 1
            take(data)
            if not data["listItems"]:
                break
    prog.draw("done")
    sys.stderr.write("\n")

    ordered = sorted(items.values(), key=lambda i: (i["starts_at"], i["location"]["name"], i["title"]))
    fetched_at = datetime.now(TZ).strftime("%Y-%m-%d %H:%M %Z")
    (out / "schedule.json").write_text(json.dumps(ordered, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / "schedule.md").write_text(to_markdown(ordered, fetched_at), encoding='utf-8')
    print(f"{len(ordered)} unique sessions -> {out}/schedule.json, {out}/schedule.md")


if __name__ == "__main__":
    main()
