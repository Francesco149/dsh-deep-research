#!/usr/bin/env python3
"""Serve the Windows bootstrap to the laptop and collect what it reports.

Run on the machine that will drive the laptop: python3 bootstrap/serve.py [port]
(CU_BOOTSTRAP_LAN, default 192.168.0.0/16: which addresses may fetch the scripts; CU_AGENT_USER: the agent account)
On the laptop, signed in as the agent account, Win+R:  powershell irm http://<this machine>:<port>|iex

GET  /           stage 1 (boot.ps1, runs as the agent account, then asks UAC for stage 2)
GET  /admin.ps1  stage 2 (elevated)
POST /report/<stage>  JSON the scripts send back, appended to reports.jsonl
Only LAN clients are served. Placeholders in the scripts: {{SERVER}}, {{PUBKEYS}}, {{LAN}}.
"""
import datetime
import http.server
import ipaddress
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
LAN = ipaddress.ip_network(os.environ.get("CU_BOOTSTRAP_LAN", "192.168.0.0/16"))
AGENT_USER = os.environ.get("CU_AGENT_USER", "agent")
REPORTS = HERE / "reports.jsonl"
PUBKEYS = (pathlib.Path.home() / ".ssh" / "id_ed25519.pub").read_text().strip()
SCRIPTS = {"/": "boot.ps1", "/boot.ps1": "boot.ps1", "/admin.ps1": "admin.ps1"}


class Handler(http.server.BaseHTTPRequestHandler):
    def allowed(self):
        ip = ipaddress.ip_address(self.client_address[0])
        if ip in LAN or ip.is_loopback:
            return True
        self.send_error(403)
        return False

    def do_GET(self):
        if not self.allowed():
            return
        name = SCRIPTS.get(self.path.split("?")[0])
        if not name:
            self.send_error(404)
            return
        text = (HERE / name).read_text()
        for key, value in {
            "{{SERVER}}": f"http://{self.headers.get('Host')}",
            "{{PUBKEYS}}": PUBKEYS,
            "{{LAN}}": str(LAN),
            "{{AGENT_USER}}": AGENT_USER,
        }.items():
            text = text.replace(key, value)
        body = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.allowed():
            return
        if not self.path.startswith("/report/"):
            self.send_error(404)
            return
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except ValueError:
            data = {"unparsed": raw.decode("utf-8", "replace")}
        stage = self.path.removeprefix("/report/")
        entry = {
            "t": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "from": self.client_address[0],
            "stage": stage,
            "data": data,
        }
        with REPORTS.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        print(f"report {stage} from {self.client_address[0]}", flush=True)
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} {fmt % args}", flush=True)


if __name__ == "__main__":
    print(f"serving {HERE} on :{PORT}, reports -> {REPORTS}", flush=True)
    http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
