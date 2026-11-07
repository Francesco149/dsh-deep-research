"""bin/cu: operate the computer-use laptop from the machine that drives it. `bin/cu help` lists the commands."""
import json
import pathlib
import subprocess
import sys

from .laptop import HOST, REMOTE_HOME, Laptop, ssh

REPO = pathlib.Path(__file__).resolve().parent.parent
LAPTOP_FILES = ["deskd.py", "pyproject.toml", "install.ps1"]

HELP = """bin/cu <command>
  deploy                 copy laptop/ to the laptop, uv sync, (re)start deskd in the agent account's session
  start | stop           start or stop deskd's scheduled task
  health                 deskd's view: session, screen, lock state, foreground window
  shot [file] [max_w]    screenshot to a PNG (default shot.png)
  windows                visible top-level windows
  click X Y | type TEXT | key COMBO | scroll X Y DY   input, in physical pixels
  browser [chrome|edge] [url]   start the agent browser on its own profile
  log [n]                last n lines of deskd's log (default 20)
  lease [break]          who holds the desktop; `break` takes it from them
  queue                  the laptop queue (cu/queue.py): which agent has the laptop, until when, who waits
  add-client NAME        a token for one PC's Claude sessions to reach the MCP service over HTTP (printed once; only its
                         hash is kept, in $CU_CLIENTS); drop-client NAME removes it
  runs [n]               the newest MCP sessions (state/runs/)
  report RUN             one run as an HTML timeline with screenshots (state/runs/RUN/index.html)
  escalations [--urls]   what needs the owner, grouped by site (--urls: just the parked URLs)
  live [port]            the laptop's screen in a web page on the LAN: watch, or take control to clear checks
  tabs [close]           the agent Chrome's open tabs; `close` closes all but one and blanks it (sessions do it at exit)
  ssh CMD                run a PowerShell command on the laptop
Input commands take a short lease named "bin/cu" and fail while a session holds the desktop.
"""
ACTIONS = {"click", "type", "key", "scroll", "browser", "tabs"}


def main(argv=sys.argv[1:]):
    cmd, args = (argv[0], argv[1:]) if argv else ("help", [])
    lap = Laptop()
    try:
        if cmd in ACTIONS:
            lap.take_lease("bin/cu", "manual command", ttl=120)
        if cmd in ("runs", "report", "escalations"):
            from . import report
            {"runs": lambda: report.runs(int(args[0]) if args else 20),
             "report": lambda: report.report(args[0].rstrip("/").split("/")[-1]),
             "escalations": lambda: report.escalations("--urls" in args)}[cmd]()
        elif cmd in ("add-client", "drop-client"):
            import hashlib
            import os
            import secrets
            path = pathlib.Path(os.environ.get("CU_CLIENTS") or REPO / "state" / "clients.json")
            doc = json.loads(path.read_text()) if path.exists() else {"clients": []}
            doc["clients"] = [c for c in doc["clients"] if c["name"] != args[0]]
            if cmd == "add-client":
                tok = secrets.token_urlsafe(32)
                doc["clients"].append({"name": args[0], "sha256": hashlib.sha256(tok.encode()).hexdigest()})
                print(tok)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=1) + "\n")
            print(f"{len(doc['clients'])} clients in {path}", file=sys.stderr)
        elif cmd == "queue":
            from . import queue as line
            st = line.status()
            h = st["holder"]
            print(f"laptop: {h['owner']} ({h['purpose']}), {h['left_min']} of {h['minutes']:g} min left" if h else "laptop: free")
            for w in st["waiting"]:
                print(f"  waiting {w['waited_min']} min: {w['owner']} ({w['purpose']}), {w['minutes']:g} min asked")
        elif cmd == "live":
            from . import live
            live.serve(int(args[0]) if args else 8790)
        elif cmd == "lease":
            if args and args[0] == "break":
                lap.take_lease("bin/cu", "lease break", ttl=60, force=True)
                print("taken; released again at exit")
            else:
                print(json.dumps(lap.health().get("lease"), indent=2))
        elif cmd == "deploy":
            ssh(f"New-Item -ItemType Directory -Force {REMOTE_HOME} | Out-Null")
            src = [str(REPO / "laptop" / f) for f in LAPTOP_FILES]
            subprocess.run(["scp", "-q", *src, f"{HOST}:{REMOTE_HOME}/"], check=True)
            print(ssh(f"powershell -NoProfile -ExecutionPolicy Bypass -File {REMOTE_HOME}/install.ps1",
                      timeout=600).strip())
        elif cmd == "start":
            ssh("Start-ScheduledTask -TaskName computer-use-deskd")
        elif cmd == "stop":
            ssh("Stop-ScheduledTask -TaskName computer-use-deskd")
        elif cmd == "health":
            print(json.dumps(lap.health(), indent=2))
        elif cmd == "shot":
            out = args[0] if args else "shot.png"
            data, meta = lap.screenshot(int(args[1]) if len(args) > 1 else None)
            pathlib.Path(out).write_bytes(data)
            print(out, meta)
        elif cmd == "windows":
            for w in lap.windows():
                print(("* " if w["foreground"] else "  ") + f"{w['hwnd']:>9} {w['exe'] or '?':<22} {w['rect']} {w['title'][:70]}")
        elif cmd == "click":
            print(lap.input({"action": "click", "x": int(args[0]), "y": int(args[1])}))
        elif cmd == "type":
            print(lap.input({"action": "type", "text": " ".join(args)}))
        elif cmd == "key":
            print(lap.input({"action": "key", "combo": args[0]}))
        elif cmd == "scroll":
            print(lap.input({"action": "scroll", "x": int(args[0]), "y": int(args[1]), "dy": int(args[2])}))
        elif cmd == "browser":
            print(json.dumps(lap.browser_start(args[0] if args else "chrome", args[1] if len(args) > 1 else None), indent=2))
        elif cmd == "log":
            print(ssh(f"Get-Content {REMOTE_HOME}/state/deskd.log -Tail {int(args[0]) if args else 20}"))
        elif cmd == "tabs":
            import asyncio
            from .browser import Browser
            lap.open()
            b = Browser(lap.cdp_port)
            if args and args[0] == "close":
                async def tidy():
                    try:
                        return await b.tidy()
                    finally:
                        await b.close()
                print(f"closed {asyncio.run(tidy())} tab(s); one blank tab left")
            for t in b.tabs():
                print(f"{t['title'][:70]:70s} {t['url'][:90]}")
        elif cmd == "ssh":
            print(ssh(" ".join(args), check=False))
        else:
            print(HELP)
    finally:
        lap.release_lease()
        lap.close()


if __name__ == "__main__":
    main()
