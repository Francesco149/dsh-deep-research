"""The laptop as seen from the machine running the MCP server: an ssh tunnel to deskd (and the browser's CDP port) plus a
thin client for deskd's HTTP API. Nothing listens on the laptop's LAN address except sshd."""
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request

HOST = os.environ.get("CU_HOST", "laptop")
# Extra ssh options, e.g. where the server runs as a system service: its own key and the laptop's pinned host key
SSH_OPTS = os.environ.get("CU_SSH_OPTS", "").split()
AGENT_USER = os.environ.get("CU_AGENT_USER", "agent")  # the Windows account the agents drive
REMOTE_HOME = os.environ.get("CU_REMOTE_HOME", f"C:/Users/{AGENT_USER}/computer-use")
DESKD_PORT, CDP_PORT = 8770, 9222


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ssh(command, check=True, timeout=120, input=None):
    """Runs a PowerShell command on the laptop (sshd's default shell there is PowerShell)."""
    r = subprocess.run(["ssh", *SSH_OPTS, "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", HOST, command],
                       capture_output=True, text=True, timeout=timeout, input=input)
    if check and r.returncode:
        raise RuntimeError(f"ssh {HOST} failed ({r.returncode}): {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


class DeskdError(RuntimeError):
    pass


class Laptop:
    """One tunnel per process, opened lazily, reopened if ssh dies."""

    def __init__(self, host=HOST):
        self.host = host
        self.proc = None
        self.token = None
        self.deskd_port = self.cdp_port = None
        self.lease = None

    def open(self):
        if self.proc and self.proc.poll() is None:
            return
        self.deskd_port, self.cdp_port = free_port(), free_port()
        self.proc = subprocess.Popen(
            ["ssh", *SSH_OPTS, "-N", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
             "-o", "ServerAliveInterval=15", "-o", "ConnectTimeout=8",
             "-L", f"127.0.0.1:{self.deskd_port}:127.0.0.1:{DESKD_PORT}",
             "-L", f"127.0.0.1:{self.cdp_port}:127.0.0.1:{CDP_PORT}", self.host],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.time() + 15
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise DeskdError(f"ssh tunnel to {self.host} exited: {self.proc.stderr.read().decode().strip()}")
            try:
                socket.create_connection(("127.0.0.1", self.deskd_port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.2)
        if self.token is None:
            self.token = ssh(f"Get-Content {REMOTE_HOME}/state/token").strip()

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(5)
        self.proc = None

    def request(self, method, path, body=None, timeout=60, raw=False):
        self.open()
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.deskd_port}{path}", data=data, method=method,
                                     headers={"Authorization": f"Bearer {self.token}",
                                              "Content-Type": "application/json",
                                              "X-Lease": (self.lease or {}).get("id", "")})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payload = r.read()
                return (payload, dict(r.headers)) if raw else json.loads(payload)
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read())
                msg = err.get("error")
                if err.get("held"):
                    h = err["held"]
                    msg = f"the desktop is leased to {h['owner']} ({h['purpose']}) until {time.strftime('%H:%M:%S', time.localtime(h['expires']))}"
            except ValueError:
                msg = str(e)
            raise DeskdError(f"{method} {path}: {msg}") from None
        except (urllib.error.URLError, ConnectionError, socket.timeout) as e:
            raise DeskdError(f"{method} {path}: deskd unreachable ({e}). deskd runs only while {AGENT_USER} is signed in "
                             f"on the laptop: after a reboot sign in as {AGENT_USER}; if it is, bin/cu start") from None

    # deskd API
    def take_lease(self, owner, purpose="", ttl=600, force=False):
        """Takes the desktop for this session, or raises DeskdError naming who holds it."""
        self.lease = self.request("POST", "/lease", {"owner": owner, "purpose": purpose, "ttl": ttl,
                                                     "force": force})["lease"]
        return self.lease

    def release_lease(self):
        if self.lease:
            try:
                self.request("POST", "/lease/release", {"lease": self.lease["id"]}, timeout=10)
            finally:
                self.lease = None

    def health(self):
        return self.request("GET", "/health")

    def screenshot(self, max_w=None, fmt="png", quality=80, region=None):
        q = [f"fmt={fmt}", f"q={quality}"] + ([f"max_w={max_w}"] if max_w else [])
        if region:
            q.append("region=" + ",".join(str(int(v)) for v in region))
        data, headers = self.request("GET", "/screenshot?" + "&".join(q), raw=True)
        return data, {"width": int(headers["X-Width"]), "height": int(headers["X-Height"]),
                      "scale": float(headers["X-Scale"]),
                      "cursor": [int(v) for v in headers["X-Cursor"].split(",")]}

    def input(self, *steps, timeout=120):
        return self.request("POST", "/input", {"steps": list(steps)}, timeout=timeout)

    def windows(self):
        return self.request("GET", "/windows")

    def window(self, hwnd, action):
        return self.request("POST", "/window", {"hwnd": hwnd, "action": action})

    def clipboard(self, text=None):
        if text is None:
            return self.request("GET", "/clipboard")["text"]
        return self.request("POST", "/clipboard", {"text": text})

    def awake(self, on=True):
        return self.request("POST", "/awake", {"on": on})

    def browser_start(self, browser="chrome", url=None, extra=(), timeout=90):
        """Starts the agent browser on its profile; deskd does nothing when Chrome already answers on its port (see
        deskd's browser_start), so this is safe to call whenever the port seems down."""
        return self.request("POST", "/browser/start", {"browser": browser, "url": url, "extra": list(extra)},
                            timeout=timeout)
