"""deskd: the desktop daemon that runs inside the agent account's interactive session.

sshd sessions live in session 0 and cannot see or drive the desktop, so this process runs in
the agent account's console session (scheduled task `computer-use-deskd`, laptop/install.ps1) and offers the
primitives over HTTP on 127.0.0.1 only. Callers reach it through an ssh tunnel and send the
token from state/token. Everything smart (tools, logs, leases, CDP, page text) lives on the
caller's side; this file stays small and dumb so the laptop rarely needs a deploy.

Coordinates are physical pixels of the primary monitor (the process is per-monitor DPI aware).
"""
import ctypes
import ctypes.wintypes as wt
import datetime
import http.client
import http.server
import io
import json
import math
import os
import pathlib
import random
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse

import mss
from PIL import Image

VERSION = "0.4.0"
HOME = pathlib.Path(__file__).resolve().parent
STATE = HOME / "state"
PORT = int(os.environ.get("DESKD_PORT", "8770"))
CDP_PORT = int(os.environ.get("DESKD_CDP_PORT", "9222"))

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2

# --- SendInput -------------------------------------------------------------------------------

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x0001, 0x8000, 0x4000
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
BUTTONS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0001, 0x0002, 0x0004
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    if user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT)) != len(inputs):
        raise OSError(f"SendInput blocked (error {ctypes.get_last_error()}): locked screen or an elevated window?")


def mouse(flags, dx=0, dy=0, data=0):
    i = INPUT(type=INPUT_MOUSE)
    i.u.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
    return i


def key(vk=0, scan=0, flags=0):
    i = INPUT(type=INPUT_KEYBOARD)
    i.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


# Names callers use for keys; single characters are looked up with VkKeyScanW.
VK = {"backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "shift": 0x10, "ctrl": 0x11,
      "control": 0x11, "alt": 0x12, "pause": 0x13, "capslock": 0x14, "esc": 0x1B, "escape": 0x1B,
      "space": 0x20, "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24, "left": 0x25,
      "up": 0x26, "right": 0x27, "down": 0x28, "printscreen": 0x2C, "insert": 0x2D, "delete": 0x2E,
      "win": 0x5B, "super": 0x5B, "cmd": 0x5B, "meta": 0x5B, "menu": 0x5D, "apps": 0x5D,
      **{f"f{n}": 0x6F + n for n in range(1, 25)}, "numlock": 0x90, "scrolllock": 0x91,
      "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF}
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5D}


def vk_of(name):
    n = name.lower()
    if n in VK:
        return VK[n], False
    if len(name) == 1:
        res = user32.VkKeyScanW(ord(name))
        if res == -1:
            raise ValueError(f"no key for {name!r}")
        return res & 0xFF, bool(res & 0x100)
    raise ValueError(f"unknown key {name!r}")


def press_combo(combo, repeat=1):
    """'ctrl+shift+t', 'enter', 'alt+f4'. Modifiers go down in order and up in reverse."""
    names = [p for p in combo.replace(" ", "").split("+") if p]
    for _ in range(repeat):
        codes = []
        for n in names:
            vk, shift = vk_of(n)
            if shift and "shift" not in [x.lower() for x in names]:
                codes.append(0x10)
            codes.append(vk)
        down = [key(vk, flags=KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0) for vk in codes]
        up = [key(vk, flags=KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0))
              for vk in reversed(codes)]
        send(*down)
        time.sleep(0.03)
        send(*up)
        time.sleep(0.15)  # let focus land: Ctrl+L then typing at once loses the first letter


def type_text(text, cps=None):
    """Unicode typing (KEYEVENTF_UNICODE): layout-independent, any script. Newlines press Enter."""
    delay = 1.0 / cps if cps else 0
    for ch in text:
        if ch == "\n":
            press_combo("enter")
            continue
        if ch == "\r":
            continue
        units = ch.encode("utf-16-le")
        for k in range(0, len(units), 2):
            code = int.from_bytes(units[k:k + 2], "little")
            send(key(0, code, KEYEVENTF_UNICODE), key(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        if delay:
            time.sleep(delay * random.uniform(0.6, 1.4))


# --- screen & mouse --------------------------------------------------------------------------

def screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def cursor_pos():
    p = wt.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def _abs(x, y):
    w, h = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)  # virtual screen
    left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    return (round((x - left) * 65535 / max(w - 1, 1)), round((y - top) * 65535 / max(h - 1, 1)))


def move_to(x, y, duration=None):
    """Glide along a slight curve, the way a hand moves a mouse, ending exactly on (x, y)."""
    x0, y0 = cursor_pos()
    dist = math.hypot(x - x0, y - y0)
    if duration is None:
        duration = min(0.6, 0.08 + dist / 3000)
    steps = max(1, int(duration * 90))
    bend = random.uniform(-0.15, 0.15) * dist
    nx, ny = (-(y - y0) / dist, (x - x0) / dist) if dist else (0, 0)
    cx, cy = (x0 + x) / 2 + nx * bend, (y0 + y) / 2 + ny * bend
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)  # ease in/out
        px = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x
        py = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y
        ax, ay = _abs(px, py)
        send(mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, ax, ay))
        time.sleep(duration / steps)


def click(x=None, y=None, button="left", count=1):
    if x is not None:
        move_to(x, y)
        time.sleep(random.uniform(0.04, 0.09))
    down, up = BUTTONS[button]
    for n in range(count):
        send(mouse(down))
        time.sleep(random.uniform(0.04, 0.08))
        send(mouse(up))
        if n + 1 < count:
            time.sleep(random.uniform(0.06, 0.1))


def drag(x0, y0, x1, y1, button="left"):
    down, up = BUTTONS[button]
    move_to(x0, y0)
    send(mouse(down))
    time.sleep(0.1)
    move_to(x1, y1, duration=0.5)
    time.sleep(0.1)
    send(mouse(up))


def scroll(x=None, y=None, dy=0, dx=0):
    """dy/dx in wheel notches: dy > 0 scrolls down, dx > 0 scrolls right."""
    if x is not None:
        move_to(x, y)
    for _ in range(abs(int(dy))):
        send(mouse(MOUSEEVENTF_WHEEL, data=-120 if dy > 0 else 120))
        time.sleep(0.05)
    for _ in range(abs(int(dx))):
        send(mouse(MOUSEEVENTF_HWHEEL, data=120 if dx > 0 else -120))
        time.sleep(0.05)


def screenshot(max_w=None, fmt="png", quality=80, region=None):
    with mss.mss() as s:
        mon = s.monitors[1]
        box = mon if not region else {"left": region[0], "top": region[1], "width": region[2], "height": region[3]}
        shot = s.grab(box)
    img = Image.frombytes("RGB", shot.size, shot.rgb)
    scale = 1.0
    if max_w and img.width > max_w:
        scale = img.width / max_w
        img = img.resize((max_w, round(img.height / scale)), Image.LANCZOS)
    buf = io.BytesIO()
    if fmt == "jpeg":
        img.save(buf, "JPEG", quality=quality)
    else:
        img.save(buf, "PNG", optimize=False, compress_level=3)
    return buf.getvalue(), img.size, scale


# --- windows & session -----------------------------------------------------------------------

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def window_text(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def process_name(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return pathlib.PureWindowsPath(buf.value).name
    finally:
        kernel32.CloseHandle(h)


def list_windows():
    fg = user32.GetForegroundWindow()
    out = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):  # skip owned popups
            return True
        title = window_text(hwnd)
        if not title:
            return True
        r = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        out.append({"hwnd": hwnd, "title": title, "pid": pid.value, "exe": process_name(pid.value),
                    "rect": [r.left, r.top, r.right - r.left, r.bottom - r.top],
                    "minimized": bool(user32.IsIconic(hwnd)), "foreground": hwnd == fg})
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def focus_window(hwnd):
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # Windows only lets the process that made the last input take the foreground: tap Alt first.
    send(key(0x12), key(0x12, flags=KEYEVENTF_KEYUP))
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    return user32.GetForegroundWindow() == hwnd


def window_action(hwnd, action):
    if action == "focus":
        return focus_window(hwnd)
    show = {"maximize": 3, "minimize": 6, "restore": 9}
    if action in show:
        return bool(user32.ShowWindow(hwnd, show[action]))
    if action == "close":
        return bool(user32.PostMessageW(hwnd, 0x0010, 0, 0))  # WM_CLOSE
    raise ValueError(f"unknown window action {action!r}")


def input_desktop():
    """'Default' when the session is unlocked; 'Winlogon' (or None) when locked or at UAC."""
    h = user32.OpenInputDesktop(0, False, 0x0001)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetUserObjectInformationW(h, 2, buf, ctypes.sizeof(buf), None)  # UOI_NAME
        return buf.value
    finally:
        user32.CloseDesktop(h)


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


def idle_ms():
    li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO))
    user32.GetLastInputInfo(ctypes.byref(li))
    return kernel32.GetTickCount() - li.dwTime


def my_session():
    sid = wt.DWORD()
    kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
    return sid.value


# Display-off on this Modern Standby laptop can suppress input, so while the agent account's session owns the
# console the system and display stay on. When the owner switches to their own account the hold
# lapses. POST /awake {"on": false} turns the hold off until {"on": true}.
_awake = {"wanted": True, "held": False}


def _awake_thread():
    ES_CONTINUOUS, ES_SYSTEM, ES_DISPLAY = 0x80000000, 0x1, 0x2
    me = my_session()
    while True:
        hold = _awake["wanted"] and kernel32.WTSGetActiveConsoleSessionId() == me
        kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM | ES_DISPLAY if hold else 0))
        _awake["held"] = hold
        time.sleep(10)


# --- clipboard -------------------------------------------------------------------------------

CF_UNICODETEXT = 13
kernel32.GlobalAlloc.restype = wt.HGLOBAL
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
user32.GetClipboardData.restype = wt.HANDLE
user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]


def _open_clipboard():
    for _ in range(20):
        if user32.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise OSError("clipboard busy")


def clipboard_get():
    _open_clipboard()
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def clipboard_set(text):
    data = text.encode("utf-16-le") + b"\0\0"
    _open_clipboard()
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(h)
        user32.SetClipboardData(CF_UNICODETEXT, h)
    finally:
        user32.CloseClipboard()


# --- browser ---------------------------------------------------------------------------------

BROWSERS = {
    "chrome": [r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
               r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"],
    "edge": [r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
             r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"],
}


def browser_exe(name):
    for p in BROWSERS[name]:
        path = os.path.expandvars(p)
        if os.path.exists(path):
            return path
    raise FileNotFoundError(f"{name} is not installed")


START_GRACE = 45  # seconds a starting Chrome gets to open its DevTools port before it counts as stuck
BROWSER_LOCK = threading.Lock()  # the start at logon and a caller's start must not both launch one


def cdp_up(timeout=2.0):
    """Chrome's DevTools endpoint answers here on the laptop (no tunnel, no proxy settings involved)."""
    c = http.client.HTTPConnection("127.0.0.1", CDP_PORT, timeout=timeout)
    try:
        c.request("GET", "/json/version")
        return c.getresponse().status == 200
    except OSError:
        return False
    finally:
        c.close()


def profile_browsers(profile):
    """The main Chrome processes on this profile in this session: [{pid, age, port_flag}]. Child processes
    (--type=...) are left out, and so is every other profile, user and session: never the owner's Chrome."""
    ps = ("ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process -Filter "
          "\"Name = 'chrome.exe' AND NOT CommandLine LIKE '%--type=%'\" | Select-Object ProcessId, SessionId, "
          "@{n='Age'; e={[int]((Get-Date) - $_.CreationDate).TotalSeconds}}, CommandLine)")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                       text=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
    me, want = my_session(), f"--user-data-dir={profile}".lower()
    out = []
    for p in json.loads(r.stdout or "[]"):
        cmd = (p.get("CommandLine") or "").lower()
        if p.get("SessionId") == me and want in cmd:
            out.append({"pid": p["ProcessId"], "age": p["Age"],
                        "port_flag": f"--remote-debugging-port={CDP_PORT}" in cmd})
    return out


def browser_ensure(profile):
    """Before a start: True if Chrome already answers on its port (or a starting one opens it within the grace).
    A Chrome that holds the profile and still does not answer (started without the flag, hung) is ended, since a
    second start would only hand its arguments to that process and the port would never open (2026-10-19)."""
    if cdp_up():
        return True
    found = profile_browsers(profile)
    young = [p["age"] for p in found if p["age"] < START_GRACE]
    if young:
        end = time.time() + START_GRACE - min(young)
        while time.time() < end:
            time.sleep(0.5)
            if cdp_up():
                log({"event": "browser-waited", "pids": [p["pid"] for p in found]})
                return True
        found = profile_browsers(profile)
    if found:
        for p in found:
            subprocess.run(["taskkill", "/PID", str(p["pid"]), "/T", "/F"], capture_output=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        log({"event": "browser-stuck", "ended": found})
        for _ in range(20):
            if not profile_browsers(profile):
                break
            time.sleep(0.5)
    return False


def browser_start(name="chrome", url=None, extra=()):
    """A normal, headful browser on its own persistent profile. The debugging port listens on
    loopback only, and Chrome 136+ refuses it on the default profile, hence the own directory.
    The agent Chrome is started once: while it answers on its port a call without a URL does nothing
    (each start used to open one more window). After a crash, a kill or a reboot Chrome would show
    "Restore pages?" over the page's top right, where it takes clicks: --hide-crash-restore-bubble (UI only)."""
    with BROWSER_LOCK:
        return _browser_start(name, url, extra)


def _browser_start(name, url, extra):
    profile = STATE / "profiles" / name
    profile.mkdir(parents=True, exist_ok=True)
    if name == "chrome" and browser_ensure(profile) and not url and not extra:
        return {"running": True, "profile": str(profile)}
    args = [browser_exe(name), f"--user-data-dir={profile}", f"--remote-debugging-port={CDP_PORT}",
            "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check",
            "--start-maximized", "--hide-crash-restore-bubble", *extra]
    if url:
        args.append(url)
    p = subprocess.Popen(args, close_fds=True)
    log({"event": "browser-launch", "browser": name, "pid": p.pid})
    return {"pid": p.pid, "profile": str(profile), "args": args[1:]}


# --- lease -----------------------------------------------------------------------------------

# One session drives the desktop at a time. Reads (health, screenshots, windows) are open to any
# token holder; every action needs the current lease in X-Lease. Each action renews it.
_lease = {}
LEASE_LOCK = threading.Lock()


def lease_take(owner, purpose="", ttl=600, force=False):
    now = time.time()
    with LEASE_LOCK:
        cur = dict(_lease)
        if cur and cur["expires"] > now and cur["owner"] != owner and not force:
            return None, cur
        if not (cur and cur["owner"] == owner and cur["expires"] > now):
            _lease.clear()
            _lease.update(id=secrets.token_urlsafe(12), owner=owner, purpose=purpose, since=now)
        _lease.update(ttl=ttl, expires=now + ttl)
        if cur and cur.get("owner") != owner:
            log({"event": "lease-broken" if cur["expires"] > now else "lease-expired", "previous": cur["owner"]})
        log({"event": "lease", "owner": owner, "purpose": purpose})
        return dict(_lease), None


def lease_check(lease_id):
    with LEASE_LOCK:
        if not _lease or _lease["expires"] < time.time():
            raise PermissionError("no active lease: take one with POST /lease")
        if lease_id != _lease["id"]:
            raise PermissionError(f"the desktop is leased to {_lease['owner']} ({_lease['purpose']})")
        _lease["expires"] = time.time() + _lease["ttl"]


def lease_release(lease_id):
    with LEASE_LOCK:
        if _lease and _lease["id"] == lease_id:
            log({"event": "release", "owner": _lease["owner"]})
            _lease.clear()
            return True
        return False


def lease_public():
    with LEASE_LOCK:
        if not _lease or _lease["expires"] < time.time():
            return None
        return {k: _lease[k] for k in ("owner", "purpose", "since", "expires")}


# --- HTTP ------------------------------------------------------------------------------------

LOCK = threading.Lock()  # one input sequence at a time
TOKEN_FILE = STATE / "token"


def redact(path, a):
    """What the log keeps of a request: clipboard text and secret typing (passwords from the
    agent's vault) only by their length."""
    if path == "/clipboard":
        return {"len": len(a.get("text", ""))}
    if path == "/input":
        steps = [{**s, "text": f"[{len(s.get('text', ''))} secret characters]"} if s.get("secret") else s
                 for s in a.get("steps", [a])]
        return {**a, "steps": steps} if "steps" in a else steps[0]
    return a


def log(entry):
    entry = {"t": datetime.datetime.now().isoformat(timespec="milliseconds"), **entry}
    with (STATE / "deskd.log").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def health():
    w, h = screen_size()
    fg = user32.GetForegroundWindow()
    return {"ok": True, "version": VERSION, "pid": os.getpid(), "session": my_session(),
            "console_session": kernel32.WTSGetActiveConsoleSessionId(),
            "screen": [w, h], "dpi": user32.GetDpiForSystem(), "cursor": cursor_pos(),
            "desktop": input_desktop(), "idle_ms": idle_ms(), "awake_held": _awake["held"],
            "browser": cdp_up(1.0),
            "lease": lease_public(),
            "foreground": {"hwnd": fg, "title": window_text(fg)}}


def do_input(a):
    kind = a.get("action")
    xy = (a["x"], a["y"]) if "x" in a else (None, None)
    if kind == "move":
        move_to(*xy, duration=a.get("duration"))
    elif kind == "click":
        click(*xy, button=a.get("button", "left"), count=a.get("count", 1))
    elif kind == "drag":
        drag(a["x"], a["y"], a["x2"], a["y2"], button=a.get("button", "left"))
    elif kind == "scroll":
        scroll(*xy, dy=a.get("dy", 0), dx=a.get("dx", 0))
    elif kind == "type":
        type_text(a["text"], cps=a.get("cps"))
    elif kind == "key":
        press_combo(a["combo"], repeat=a.get("repeat", 1))
    elif kind == "button":  # raw press/release for holds
        down, up = BUTTONS[a.get("button", "left")]
        send(mouse(down if a["state"] == "down" else up))
    elif kind == "wait":
        time.sleep(min(float(a.get("seconds", 1)), 30))
    else:
        raise ValueError(f"unknown action {kind!r}")


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def reply(self, code, body, ctype="application/json", headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(body)

    def authed(self):
        if secrets.compare_digest(self.headers.get("Authorization", ""), f"Bearer {TOKEN}"):
            return True
        self.reply(401, {"error": "unauthorized"})
        return False

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if not self.authed():
            return
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path == "/health":
                self.reply(200, health())
            elif u.path == "/screenshot":
                region = [int(v) for v in q["region"].split(",")] if "region" in q else None
                data, size, scale = screenshot(int(q["max_w"]) if "max_w" in q else None,
                                               q.get("fmt", "png"), int(q.get("q", 80)), region)
                self.reply(200, data, "image/jpeg" if q.get("fmt") == "jpeg" else "image/png",
                           {"X-Width": size[0], "X-Height": size[1], "X-Scale": f"{scale:.6f}",
                            "X-Cursor": "%d,%d" % cursor_pos()})
            elif u.path == "/windows":
                self.reply(200, list_windows())
            elif u.path == "/clipboard":
                self.reply(200, {"text": clipboard_get()})
            else:
                self.reply(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001 - every failure goes back to the caller
            self.reply(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        if not self.authed():
            return
        path = urllib.parse.urlparse(self.path).path
        try:
            a = self.body()
            if path == "/lease":
                got, held = lease_take(a["owner"], a.get("purpose", ""), int(a.get("ttl", 600)), bool(a.get("force")))
                self.reply(200 if got else 409, {"lease": got} if got else {"error": "leased", "held": held})
                return
            if path == "/lease/release":
                self.reply(200, {"released": lease_release(a.get("lease"))})
                return
            lease_check(self.headers.get("X-Lease"))
            log({"path": path, "req": redact(path, a)})
            if path == "/input":
                with LOCK:
                    for n, step in enumerate(a.get("steps", [a])):
                        if n:
                            time.sleep(0.08)
                        do_input(step)
                self.reply(200, {"ok": True, "cursor": cursor_pos()})
            elif path == "/window":
                self.reply(200, {"ok": window_action(int(a["hwnd"]), a["action"])})
            elif path == "/clipboard":
                clipboard_set(a["text"])
                self.reply(200, {"ok": True})
            elif path == "/awake":
                _awake["wanted"] = bool(a.get("on", True))
                self.reply(200, {"ok": True, "awake_wanted": _awake["wanted"]})
            elif path == "/browser/start":
                self.reply(200, browser_start(a.get("browser", "chrome"), a.get("url"), a.get("extra", ())))
            elif path == "/launch":
                p = subprocess.Popen([a["exe"], *a.get("args", [])], close_fds=True)
                self.reply(200, {"pid": p.pid})
            else:
                self.reply(404, {"error": "not found"})
        except PermissionError as e:
            self.reply(423, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            log({"path": path, "error": f"{type(e).__name__}: {e}"})
            self.reply(500, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt, *args):
        pass


def _browser_at_start():
    """The agent Chrome comes up with deskd, at the agent account's logon: after a boot and a sign-in it is ready before the first
    agent asks for it. Later starts are on demand (the service asks whenever the port does not answer)."""
    time.sleep(5)
    try:
        log({"event": "browser-at-start", **browser_start("chrome")})
    except Exception as e:  # noqa: BLE001 - the service starts it on demand anyway
        log({"event": "browser-at-start", "error": f"{type(e).__name__}: {e}"})


def main():
    global TOKEN
    STATE.mkdir(exist_ok=True)
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(32))
    TOKEN = TOKEN_FILE.read_text().strip()
    threading.Thread(target=_awake_thread, daemon=True).start()
    log({"event": "start", "version": VERSION, "pid": os.getpid(), "python": sys.version.split()[0]})
    threading.Thread(target=_browser_at_start, daemon=True).start()
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
