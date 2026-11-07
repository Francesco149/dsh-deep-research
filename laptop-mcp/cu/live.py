"""bin/cu live: the laptop's screen in a web page, for the owner to watch a run or take over.

Watching needs nothing. "Take control" takes deskd's lease from whoever holds it (an agent's next
action then fails with "leased to owner" until the owner lets go), and clicks, wheel, keys and
text on the page become real input on the laptop. It is how the owner clears the checks agents
escalate (bin/cu escalations): from your desktop or a phone on the LAN, without walking to the laptop.

Serves on the LAN behind a random token printed at start (CU_LIVE_TOKEN keeps one across a restart); nothing is
stored. The laptop's mouse cursor is drawn over the screenshot, which leaves it out.
"""
import http.server
import json
import os
import secrets
import socket
import sys
import threading
import urllib.parse

from .laptop import DeskdError, Laptop

PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>laptop live</title>
<style>
:root{--bg:#111;--fg:#eee;--mut:#999;--acc:#7aa2f7;--warn:#e0af68}
@media (prefers-color-scheme:light){:root:not([data-theme=dark]){--bg:#f6f6f4;--fg:#1b1b1b;--mut:#666;--acc:#2f5bd3;--warn:#a05a00}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif}
header{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:8px 16px}
#st{color:var(--mut);flex:1;min-width:200px}button{font:inherit;padding:6px 10px;border-radius:6px;border:1px solid var(--mut);background:transparent;color:var(--fg)}
button.on{border-color:var(--warn);color:var(--warn)}#wrap{position:relative;max-width:1600px;margin:0 auto}#screen{display:block;width:100%;touch-action:manipulation;cursor:crosshair}
#ptr{position:absolute;width:16px;height:24px;pointer-events:none;display:none;filter:drop-shadow(0 0 1px #000)}
#keys{display:flex;flex-wrap:wrap;gap:6px;padding:8px 16px}#keys input{flex:1;min-width:160px;font:inherit;padding:6px;border-radius:6px;border:1px solid var(--mut);background:transparent;color:var(--fg)}
.off #keys{display:none}
</style>
<body class=off>
<header><b>laptop</b><span id=st>watching</span><button id=ctl>Take control</button></header>
<div id=wrap><img id=screen alt="laptop screen"><svg id=ptr viewBox="0 0 12 18"><path d="M1 1v14l3.5-3.5 2.8 5.6 2-1-2.8-5.6H11z" fill="#fff" stroke="#000" stroke-width="1" stroke-linejoin="round"/></svg></div>
<div id=keys><input id=txt placeholder="text to type, Enter sends"><button data-k=enter>Enter</button><button data-k=tab>Tab</button>
<button data-k=esc>Esc</button><button data-k=backspace>Bksp</button><button data-k=pagedown>PgDn</button><button data-k=pageup>PgUp</button><button data-k=f5>F5</button></div>
<script>
const base = location.pathname.replace(/\\/$/, ""), img = document.getElementById("screen"), st = document.getElementById("st"), ptr = document.getElementById("ptr");
let control = false, busy = false;
async function post(path, body) {
  const r = await fetch(base + path, {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body || {})});
  const j = await r.json(); if (!r.ok) st.textContent = j.error || r.status; return j;
}
function pointer(c) {  // the laptop's mouse cursor: screenshots leave it out, deskd reports where it is
  const [fx, fy] = (c || "").split(",").map(Number);
  if (!c || !(fx >= 0 && fx <= 1 && fy >= 0 && fy <= 1)) { ptr.style.display = "none"; return; }
  ptr.style.left = fx * 100 + "%"; ptr.style.top = fy * 100 + "%"; ptr.style.display = "block";
}
async function tick() {
  if (!busy) { busy = true;
    try { const r = await fetch(base + "/shot.jpg?" + Date.now()); if (r.ok) { const b = await r.blob(); const u = URL.createObjectURL(b); const old = img.src; img.src = u; if (old) URL.revokeObjectURL(old); pointer(r.headers.get("x-cursor")); st.textContent = (control ? "in control" : "watching") + " · " + (r.headers.get("x-lease") || "no lease"); } }
    catch (e) { st.textContent = "laptop unreachable"; }
    busy = false; }
  setTimeout(tick, control ? 400 : 1500);
}
function rel(e) { const r = img.getBoundingClientRect(); return {x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height}; }
img.addEventListener("click", e => { if (control) post("/input", {action: "click", ...rel(e)}); });
img.addEventListener("contextmenu", e => { if (control) { e.preventDefault(); post("/input", {action: "click", button: "right", ...rel(e)}); } });
img.addEventListener("wheel", e => { if (control) { e.preventDefault(); post("/input", {action: "scroll", dy: Math.sign(e.deltaY) * 3, ...rel(e)}); } }, {passive: false});
document.getElementById("ctl").onclick = async e => {
  const j = await post(control ? "/release" : "/take");
  control = !!j.control; e.target.textContent = control ? "Let go" : "Take control"; e.target.classList.toggle("on", control);
  document.body.classList.toggle("off", !control);
};
document.querySelectorAll("[data-k]").forEach(b => b.onclick = () => post("/input", {action: "key", combo: b.dataset.k}));
const txt = document.getElementById("txt");
txt.addEventListener("keydown", e => { if (e.key === "Enter") { post("/input", {action: "type", text: txt.value}); txt.value = ""; } });
tick();
</script>
"""


class Live:
    def __init__(self):
        self.lap = Laptop()
        self.lock = threading.Lock()
        self.control = False

    def shot(self):
        with self.lock:
            data, meta = self.lap.screenshot(1280, "jpeg", 70)
            health = self.lap.health()
        lease = health.get("lease")
        (w, h), (x, y) = health["screen"], meta["cursor"]
        return data, (f"leased to {lease['owner']}" if lease else ""), f"{x / w:.4f},{y / h:.4f}"

    def take(self):
        with self.lock:
            self.lap.take_lease("owner (live view)", "the owner is driving", ttl=900, force=True)
            self.control = True

    def release(self):
        with self.lock:
            self.lap.release_lease()
            self.control = False

    def input(self, a):
        if not self.control:
            raise DeskdError("take control first")
        step = dict(a)
        if step.get("action") == "type":
            step["cps"] = 20
        with self.lock:
            if "x" in step:
                w, h = self.lap.health()["screen"]
                step["x"], step["y"] = round(step["x"] * w), round(step["y"] * h)
            return self.lap.input(step)


def serve(port=8790):
    live = Live()
    token = os.environ.get("CU_LIVE_TOKEN") or secrets.token_urlsafe(9)  # a restart can keep the owner's link

    class H(http.server.BaseHTTPRequestHandler):
        def send(self, code, body, ctype="application/json", extra=None):
            body = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def route(self):
            parts = urllib.parse.urlparse(self.path).path.strip("/").split("/", 1)
            if not parts or parts[0] != token:
                self.send(404, {"error": "not found"})
                return None
            return parts[1] if len(parts) > 1 else ""

        def do_GET(self):
            path = self.route()
            if path is None:
                return
            try:
                if path == "":
                    self.send(200, PAGE.encode(), "text/html; charset=utf-8")
                elif path == "shot.jpg":
                    data, lease, cursor = live.shot()
                    self.send(200, data, "image/jpeg", {"X-Lease": lease, "X-Cursor": cursor})
                else:
                    self.send(404, {"error": "not found"})
            except DeskdError as e:
                self.send(502, {"error": str(e)})

        def do_POST(self):
            path = self.route()
            if path is None:
                return
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            try:
                if path == "take":
                    live.take()
                elif path == "release":
                    live.release()
                elif path == "input":
                    live.input(body)
                else:
                    return self.send(404, {"error": "not found"})
                self.send(200, {"control": live.control})
            except DeskdError as e:
                self.send(409, {"error": str(e), "control": live.control})

        def log_message(self, *a):
            pass

    host = socket.gethostname()
    print(f"live view: http://{host}:{port}/{token}/  (LAN; Ctrl+C ends it and lets go of the laptop)", flush=True)
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), H)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if live.control:
            live.release()
        live.lap.close()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8790)
