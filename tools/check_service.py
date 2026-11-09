#!/usr/bin/env python3
"""Integration parity against Python/SQLite; launches the built Go service locally."""
import base64
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PLANNER = ROOT / "skills/websummit-planner/scripts/planner.py"


def main():
    data = json.loads((ROOT / "service/data/schedule.json").read_text())
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "PORT": str(port), "SCHEDULE_PATH": str(ROOT / "service/data/schedule.json"),
           "COMPANIES_PATH": str(ROOT / "service/data/companies.json")}
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen([str(ROOT / "service/server")], env=env, stdout=log, stderr=log)
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 10
            while True:
                try:
                    urllib.request.urlopen(base + "/health", timeout=1).close()
                    break
                except (OSError, urllib.error.URLError):
                    if process.poll() is not None or time.monotonic() >= deadline:
                        log.seek(0)
                        raise RuntimeError("service did not start: " + log.read().decode())
                    time.sleep(.01)

            def rpc(method, params):
                req = urllib.request.Request(base + "/mcp", data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(), headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
                with urllib.request.urlopen(req, timeout=10) as response:
                    result = json.load(response)
                assert "error" not in result, result
                return result["result"]

            def call(name, args):
                result = rpc("tools/call", {"name": name, "arguments": args})
                assert not result.get("isError"), result
                return json.loads(result["content"][0]["text"])

            rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "parity", "version": "1"}})
            tools = rpc("tools/list", {})["tools"]
            assert {t["name"] for t in tools} == {"info", "search", "details", "fetch", "check_plan", "encode_plan", "decode_plan", "search_companies", "company_details"}
            assert all(t["annotations"]["readOnlyHint"] for t in tools)
            assert call("info", {})["sessions"] == data["info"]["sessions"]
            rows = data["sessions"]
            day = [s for s in rows if s["day"] == "2026-11-10"]
            fixtures = [(0, day[:8]), (15, day[100:112]), (30, day[::30][:15])]
            for buffer, sessions in fixtures:
                plan = [{"id": s["id"], "status": "must"} for s in sessions]
                with tempfile.TemporaryDirectory() as tmp:
                    db = str(Path(tmp) / "plan.db")
                    def py(*args):
                        return json.loads(subprocess.check_output([sys.executable, str(PLANNER), "--db", db, *args]))
                    for p in plan:
                        py("mark", p["id"], p["status"])
                    py("buffer", str(buffer))
                    expected = sorted((c["kind"], c["a_id"], c["b_id"]) for c in py("conflicts"))
                    result = call("check_plan", {"sessions": plan, "buffer_min": buffer})
                    actual = sorted((c["kind"], c["a"]["id"], c["b"]["id"]) for c in result["conflicts"])
                    assert actual == expected, (buffer, actual, expected)
                code = call("encode_plan", {"sessions": plan})["code"]
                decoded = json.loads(base64.urlsafe_b64decode(code + "=" * (-len(code) % 4)))
                assert decoded == [[p["id"], "u"] for p in plan]
                assert call("decode_plan", {"code": code})["sessions"] == plan
            sid = day[0]["id"]
            detail = call("details", {"session_ids": [sid]})[0]
            assert detail["id"] == sid
            assert call("fetch", {"id": sid})["id"] == sid
            assert call("search", {"kind": "side", "limit": 2})["results"]
            assert call("check_plan", {"sessions": [{"id": "missing", "status": "must"}]})["unknown"] == ["missing"]
            companies = json.loads((ROOT / "service/data/companies.json").read_text())
            assert call("info", {})["companies"] == len(companies["companies"])
            with tempfile.TemporaryDirectory() as tmp:
                cdb = str(Path(tmp) / "c.db")

                def pyc(*args):
                    return json.loads(subprocess.check_output([sys.executable, str(PLANNER), "--db", cdb, *args]))
                cases = [({"query": "drone", "limit": 40}, ["drone", "--limit", "40"]),
                         ({"facts": ["seed", "actively fundraising"], "limit": 40}, ["--fact", "seed", "--fact", "actively fundraising", "--limit", "40"]),
                         ({"tier": "Beta", "industry": "AI & machine learning", "facts": ["Series A"], "limit": 40},
                          ["--tier", "Beta", "--industry", "AI & machine learning", "--fact", "Series A", "--limit", "40"])]
                for args, cli in cases:
                    got, want = call("search_companies", args)["results"], pyc("companies", *cli)
                    assert got == want and want, (args, len(got), len(want))
                for ids in (["company:62217"], ["101575", "company:62217"]):
                    assert call("company_details", {"company_ids": ids}) == pyc("company", *ids), ids
                assert call("fetch", {"id": "company:62217"})["title"] == "MakeLocal"
                plan = call("check_plan", {"sessions": [{"id": "company:62217", "status": "must"}]})
                assert [c["id"] for c in plan["companies"]] == ["company:62217"] and plan["unknown"] == [], plan
            print("MCP HTTP + 3 Python/SQLite conflict parity fixtures + legacy plan-code compatibility + company search/details parity: PASS")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
