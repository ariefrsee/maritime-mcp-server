"""Capture every response this server gives a real MCP client, for diffing.

Drives the server over stdio the way a client does, keeping stdin open so the
server does not shut down before answering. A naive pipe closes it and the last
request is silently dropped, which looked like a failure twice during S01.

    python tools/compare_wire.py --out before.json
    # change something
    python tools/compare_wire.py --out after.json
    diff before.json after.json
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUESTS = [
    ("tools_list", {"method": "tools/list", "params": {}}),
    ("resources_list", {"method": "resources/list", "params": {}}),
    ("call_details", {"method": "tools/call", "params": {
        "name": "vessel_details", "arguments": {"query": "Kowloon Express"}}}),
    ("call_search", {"method": "tools/call", "params": {
        "name": "search_vessels", "arguments": {"vessel_type": "Tanker"}}}),
    ("call_search_padded", {"method": "tools/call", "params": {
        "name": "search_vessels", "arguments": {"flag": " malaysia "}}}),
    ("call_near", {"method": "tools/call", "params": {
        "name": "vessels_near_port", "arguments": {"port": "Port Klang", "radius_nm": 30}}}),
    ("call_near_bad_port", {"method": "tools/call", "params": {
        "name": "vessels_near_port", "arguments": {"port": "Nowhere"}}}),
    ("call_near_bad_radius", {"method": "tools/call", "params": {
        "name": "vessels_near_port", "arguments": {"port": "Port Klang", "radius_nm": -5}}}),
    ("call_blank_query", {"method": "tools/call", "params": {
        "name": "vessel_details", "arguments": {"query": ""}}}),
    ("read_resource", {"method": "resources/read", "params": {"uri": "vessels://all"}}),
]


def capture(python: str) -> dict:
    """Run the server and collect one response per request above."""
    env = {**os.environ, "AISSTREAM_API_KEY": ""}   # snapshot mode, so output is stable
    proc = subprocess.Popen(
        [python, "-m", "maritime_mcp_server.server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        cwd=str(ROOT), text=True, bufsize=1, env=env)
    inbox: queue.Queue = queue.Queue()
    threading.Thread(
        target=lambda: [inbox.put(json.loads(line)) for line in proc.stdout if line.strip()],
        daemon=True).start()

    def send(payload, expect_reply=True):
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()
        return inbox.get(timeout=30) if expect_reply else None

    out = {}
    out["initialize"] = send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "compare_wire", "version": "1"}}})["result"]
    send({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)

    for index, (label, request) in enumerate(REQUESTS, start=2):
        reply = send({"jsonrpc": "2.0", "id": index, **request})
        out[label] = reply.get("result", reply.get("error"))

    proc.stdin.close()
    proc.wait(timeout=15)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="where to write the capture")
    parser.add_argument("--python", default=sys.executable,
                        help="interpreter to run the server with")
    args = parser.parse_args()
    captured = capture(args.python)
    Path(args.out).write_text(json.dumps(captured, indent=2, sort_keys=True))
    print(f"captured {len(captured)} responses to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
