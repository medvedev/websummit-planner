#!/usr/bin/env python3
"""Render context-held selections without writing to the schedule or a personal DB.
agenda.py PLAN.json --format markdown|ics|pdf --out PATH [--schedule schedule.json]
PLAN.json is an array of {id,status,note?}; only must/maybe entries are exported.
PDF requires reportlab and a Unicode TrueType font (--font or DejaVu Sans).
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from xml.sax.saxutils import escape


def resolve(rows, plan):
    if not isinstance(plan, list) or len(plan) > 200:
        raise ValueError("plan must be an array of at most 200 selections")
    by_id = {s["id"]: {**s, **({"url": "https://attend.websummit.com/lis26/events/" + s["id"]}
                              if s.get("kind") == "official" else {})} for s in rows}
    latest = {}
    for p in plan:
        if not isinstance(p, dict) or p.get("status") not in {"must", "maybe", "skip", "removed"}:
            raise ValueError("each selection needs id and status: must, maybe, skip, removed")
        if not isinstance(p.get("id"), str) or p["id"] not in by_id:
            raise ValueError("unknown session ID: " + str(p.get("id")))
        if not isinstance(p.get("note", ""), str):
            raise ValueError("note must be text")
        latest[p["id"]] = p
    return sorted([{**by_id[k], "status": p["status"], "note": p.get("note", "")}
                   for k, p in latest.items() if p["status"] in {"must", "maybe"}],
                  key=lambda s: (s["starts_utc"], s["id"]))


def plain(value):
    return " ".join(str(value or "").split())


def markdown(rows):
    lines = ["# Web Summit 2026 agenda", "", "Times: Europe/Lisbon. Unofficial snapshot; verify changes and registration.", ""]
    for s in rows:
        end = s["end"] if s.get("end_known") != 0 else "end unknown"
        lines += [f"## {s['day']} {s['start']} - {end}", "",
                  plain(s["title"]), "", f"Location: {plain(s.get('address') or s.get('stage'))}",
                  f"ID: {s['id']} | Status: {s['status']}", ""]
        for field in ("speakers", "description", "url", "note"):
            if s.get(field): lines += [plain(s[field]), ""]
    if not rows: lines += ["No selected sessions.", ""]
    return "\n".join(lines)


def ical_text(value):
    return str(value or "").replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold(line):
    parts, current = [], ""
    for ch in line:
        if len((current + ch).encode("utf-8")) > 75:
            parts.append(current)
            current = " "
        current += ch
    return "\r\n".join(parts + [current])


def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def calendar(rows):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//WebSummit Planner//Agenda//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for s in rows:
        uid = hashlib.sha256(s["id"].encode()).hexdigest() + "@websummit-planner"
        description = "\n".join(str(s.get(k) or "") for k in ("description", "speakers", "note"))
        description += "\nSession ID: " + s["id"] + "\nUnofficial snapshot; verify schedule and registration."
        if s.get("end_known") == 0: description += "\nEnd time unknown; no duration inferred."
        lines += ["BEGIN:VEVENT", "UID:" + uid, "DTSTAMP:" + now,
                  "DTSTART:" + stamp(s["starts_utc"])]
        if s.get("end_known") != 0: lines += ["DTEND:" + stamp(s["ends_utc"])]
        lines += ["SUMMARY:" + ical_text(s["title"]),
                  "LOCATION:" + ical_text(s.get("address") or s.get("stage")),
                  "DESCRIPTION:" + ical_text(description),
                  "STATUS:" + ("TENTATIVE" if s["status"] == "maybe" else "CONFIRMED"),
                  "END:VEVENT"]
    return "\r\n".join(fold(line) for line in lines + ["END:VCALENDAR"]) + "\r\n"


def pdf(rows, out, font=None):
    try:
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        raise ValueError("PDF export requires reportlab: python -m pip install reportlab")
    candidates = [Path(font)] if font else [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/dejavu/DejaVuSans.ttf")]
    chosen = next((p for p in candidates if p.is_file()), None)
    if chosen is None: raise ValueError("PDF needs a Unicode TrueType font; pass --font PATH")
    pdfmetrics.registerFont(TTFont("Agenda", str(chosen)))
    styles = getSampleStyleSheet()
    for style in styles.byName.values(): style.fontName = "Agenda"
    story, block = [], []
    for line in markdown(rows).splitlines():
        if line.startswith("## "):
            if block: story.append(KeepTogether(block))
            block = []
            style, line = styles["Heading2"], line[3:]
        elif line.startswith("# "): style, line = styles["Title"], line[2:]
        else: style = styles["BodyText"]
        block.append(Paragraph(escape(line), style) if line else Spacer(1, 7))
    if block: story.append(KeepTogether(block))
    SimpleDocTemplate(str(out), title="Web Summit 2026 agenda", leftMargin=42, rightMargin=42).build(story)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--schedule", type=Path)
    source.add_argument("--db", type=Path, help="read a specific planner snapshot without modifying it")
    parser.add_argument("--format", choices=["markdown", "ics", "pdf"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--font")
    args = parser.parse_args()
    try:
        if args.schedule:
            rows = json.loads(args.schedule.read_text(encoding="utf-8"))["sessions"]
        else:
            from export_text import load, SEED
            rows, _ = load(args.db or SEED)
        selected = resolve(rows, json.loads(args.plan.read_text(encoding="utf-8")))
        if args.format == "pdf": pdf(selected, args.out, args.font)
        elif args.format == "ics": args.out.write_bytes(calendar(selected).encode("utf-8"))
        else: args.out.write_text(markdown(selected), encoding="utf-8")
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__": main()
