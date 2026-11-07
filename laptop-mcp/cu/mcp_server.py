"""The computer-use MCP server: a real Chrome on a real Windows laptop, for research agents.

Run by the agent's MCP client over stdio (bin/cu-mcp). Every call is recorded under
state/runs/<run>/ (actions.jsonl + screenshots) for whoever supervises the run; bin/cu runs
lists them and bin/cu report <run> renders one as an HTML timeline.

Environment: CU_OWNER (who the lease is for, shown to other sessions), CU_PURPOSE (one line),
CU_HOST (ssh host, default laptop), CU_SHOT_WIDTH (screenshot width sent to the model),
CU_COORDS (pixels: screenshot pixels, the default; norm1000: a 0-1000 grid over the screenshot,
which Gemini models point in natively), CU_RUN (name of the run directory), CU_TYPE_CPS, CU_TOOLS (browser: the default, the
desktop tools only act on the agent's Chrome; all: the whole desktop).

The laptop queue (cu/queue.py) decides who may act. By default the agent takes the laptop with
laptop_acquire (15 minutes, at most 30), passes the lease to every laptop tool and gives it back with laptop_release;
CU_SESSION_MINUTES makes the server take it itself at the first action (one-task clients: the research harness's
browse, tests); CU_LEASE works under a lease someone else holds (the harness reading a page for the
researcher who holds it).
"""
import asyncio
import contextlib
import datetime
import argparse
import functools
import hashlib
import inspect
import json
import os
import pathlib
import re
import socket
import subprocess
import tempfile
import time
import urllib.parse

try:  # mcp 2.x (the uv venv)
    from mcp.server.mcpserver import Context, Image, MCPServer
except ImportError:  # mcp 1.x (e.g. a distro package)
    from mcp.server.fastmcp import Context, FastMCP as MCPServer, Image

from . import queue as line
from . import report, vault
from .browser import Browser, CDPError
from .laptop import DeskdError, Laptop
from .vault import VaultError

REPO = pathlib.Path(__file__).resolve().parent.parent
RUNS = report.RUNS
CHALLENGE_WAIT = 30.0  # seconds an automatic check gets to clear by itself, per attempt
SHOT_W = int(os.environ.get("CU_SHOT_WIDTH", "1280"))
COORDS = os.environ.get("CU_COORDS", "pixels")
# the agent account may be an administrator and web pages can carry instructions, so by default a session may only
# touch the agent's Chrome: no Start menu, no other app, no task switching. CU_TOOLS=all lifts it.
TOOLSET = os.environ.get("CU_TOOLS", "browser")
BLOCKED_KEYS = [{"win"}, {"super"}, {"meta"}, {"cmd"}, {"alt", "tab"}, {"ctrl", "shift", "esc"}, {"ctrl", "esc"}]
XY = {"pixels": "pixels of the latest screenshot (x from the left, y from the top)",
      "norm1000": "a 0-1000 grid over the latest screenshot (x: 0 left edge, 1000 right edge; y: 0 top, 1000 bottom)"}[COORDS]
# Keys per second when typing. Anti-bot systems now judge behaviour more than fingerprints, and
# millisecond typing or pasting is the giveaway (docs/research.md), so text goes in at a person's pace.
TYPE_CPS = float(os.environ.get("CU_TYPE_CPS", "9"))
OWNER = os.environ.get("CU_OWNER") or f"mcp@{socket.gethostname()}:{os.getpid()}"
PURPOSE = os.environ.get("CU_PURPOSE", "")
LEASE_ENV = os.environ.get("CU_LEASE", "")
SESSION_MINUTES = float(os.environ.get("CU_SESSION_MINUTES") or 0)
EXPLICIT = not LEASE_ENV and not SESSION_MINUTES  # the agent takes and gives back the laptop itself
HTTP = {"on": False, "clients": None}  # serving many clients over HTTP (main --http): a service shared by every PC on the network

QUEUE_RULES = """\
The laptop is shared by every agent on this machine, one at a time. Take it with \
laptop_acquire(purpose, minutes) before anything else: ask up front for the time the task needs, 15 \
minutes by default, at most 30 (it cannot be extended). Waiting in line is normal: if it answers \
WAITING, call it again with the ticket it gives. Pass the lease it returns as lease="..." to every \
other tool, and call laptop_release(lease) the moment you are done (also when you give up). When your \
time runs out the laptop goes to the next agent and every call answers TIME UP: your task has failed; \
stop and report that. Use the laptop for what web search and page fetching cannot do: pages behind \
bot checks, JavaScript apps, a site's own search, 'show more' and tabs, and information behind a \
login: the laptop's identity has a password vault with its accounts, and you may and should add \
accounts to it (Accounts, below).

""" if EXPLICIT else ""

INSTRUCTIONS = QUEUE_RULES + """\
A real Chrome on a real Windows laptop (residential connection), for pages that plain fetching \
cannot get: bot interstitials, JavaScript-heavy sites, viewers, account-only pages. Every call is \
recorded for review.

Work like this:
1. browser_open(url): loads the page and returns its title and the start of its text.
2. browser_read: the page as markdown, paged with offset. Prefer text to screenshots.
3. To navigate: browser_elements or browser_find, then browser_click(i) / browser_type(...).
4. screenshot when layout, images or something outside the page matter (dialogs, downloads); the \
desktop tools (click, scroll, drag) take coordinates as {XY}.
5. A PDF in the tab: browser_pdf_text.

Rules: never buy anything, never enter payment details, ID documents or anyone's real personal \
data, and never answer a CAPTCHA or a 'verify you are human' check (no checkbox, no puzzle): those \
are for the owner. The browser tools already wait for automatic checks, reload, and come in through \
the site's front page; a page still behind a check is parked for the owner automatically, and you \
should carry on with other sources (the same facts elsewhere, an archived copy such as \
web.archive.org, the site's other pages). For a consent you cannot get past, call escalate. Quote \
what pages actually say; a page you could not load is not a source.
""".replace("{XY}", XY)

IDENTITY = vault.config()
ACCOUNTS = """
Accounts. This browser belongs to an agent identity, not a person: {email} (a throwaway Gmail, \
signed in here), name {name}. The identity has its own password vault (a Vaultwarden/Bitwarden account of its own): every \
account it holds is there, and the account_* tools read and write it, so every agent on the laptop \
shares the same accounts. Use them freely, and when information you need sits behind a login \
(a login wall, members-only pages, a forum or database that wants an account), make one: that is \
what the identity is for. Passwords never pass through you: the vault generates, keeps and types them.
1. Always account_lookup(site) first: another agent may have made the account already. If one \
exists, sign in with it: account_fill(item_id, "username", index), then account_fill(item_id, "password", index). \
Status pending means a sign-up was started: finish it.
2. If none exists, sign up once: open the site's sign-up page and read its username and password \
rules, then account_create(site, url, username): the password manager makes the password and saves \
the account; you never see the password. The username is what the site signs in with: the email \
unless the site signs in by name (a public screen name goes in account_update's note). Fill the form: \
email {email}, any screen name (short, from the email's name, a variant if taken), and every \
password field (the confirm one too) only with account_fill(item_id, "password", index). Leave newsletter and marketing boxes \
unticked; accepting the site's terms is fine.
3. Password refused by the site: account_new_password(item_id, ...) with options that meet its rules \
(length, special=false, append a required character), then fill again.
4. Email confirmation: browser_new_tab("https://mail.google.com/mail/u/0/#search/<site name>"), \
open the newest message, follow its link or read its code, then browser_switch_tab back.
5. account_update(item_id, "active") once signed in; "failed" with the reason if the site refuses.
Never create a second account on a site that has one, or to get around a limit, ban or trial; never \
type a password with browser_type or type_text; never turn on optional two-factor sign-in. A site \
that wants a phone number, payment or an ID: escalate(kind="phone" or "other") and use other sources.
Google may ask the identity to "Verify it's you" (or "Verifica la tua identità": a password page on \
accounts.google.com): that is its own sign-in, so fill it from the vault, account_fill(item_id=<the www.google.com \
item account_lookup("google.com") lists>, field="password", index=<the password field>), and carry on. If it wants a code from a phone, \
another device or a recovery address instead, escalate(kind="phone" or "other") and use other sources. \
The Google account is the identity itself: never create or add a passkey for it (Google and Chrome \
offer one: choose "Not now", "Skip", "Non ora" or "Annulla"), never change its password, recovery \
email or phone, 2-Step Verification or other security settings, and never sign it out. When Chrome \
or Bitwarden offers to save a password, close the offer: the vault already has it.
""".format(email=IDENTITY.get("AGENT_EMAIL"), name=IDENTITY.get("AGENT_NAME")) if IDENTITY.get("AGENT_EMAIL") else """
Accounts: none are set up here. Never sign in or sign up; for a login wall, call escalate.
"""
INSTRUCTIONS += ACCOUNTS

# Google's account-security pages and interstitials (passkey enrolment, recovery prompts): agents
# may only decline there. The identity's Google account must never get a passkey (owner).
GOOGLE_ACCOUNT_HOSTS = {"accounts.google.com", "myaccount.google.com"}
GOOGLE_PROTECTED = re.compile(r"passkey|speedbump|^(/u/\d+)?/(security|signinoptions|recovery|two-step|"
                              r"account-recovery|device-activity)", re.I)
DECLINE = re.compile(r"\b(not now|skip|cancel|no,? thanks|maybe later|later|close|non ora|salta|annulla|"
                     r"no,? grazie|più tardi|ignora|chiudi)\b", re.I)
SAFE_KEYS_THERE = {"esc", "escape", "alt+left", "ctrl+w", "ctrl+tab", "ctrl+shift+tab"}


class Run:
    """The record of one MCP session (stdio) or one lease (HTTP): actions.jsonl plus a screenshot per visual step."""

    def __init__(self, name: str = ""):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name or os.environ.get("CU_RUN") or OWNER)[:60]
        self.dir = RUNS / (slug if os.environ.get("CU_RUN") and not name else f"{stamp}-{slug}")
        self.n = 0

    def write(self, entry, shot=None):
        self.dir.mkdir(parents=True, exist_ok=True)
        if self.n == 0 and entry.get("event") != "start":
            self.write({"event": "start", "owner": OWNER, "purpose": PURPOSE, "tools": TOOLSET, "coords": COORDS})
        self.n += 1
        entry = {"n": self.n, "t": datetime.datetime.now().isoformat(timespec="seconds"), **entry}
        if shot:
            name = f"{self.n:04d}.jpg"
            (self.dir / name).write_bytes(shot)
            entry["shot"] = name
        with (self.dir / "actions.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


class Session:
    def __init__(self):
        self.lap = Laptop()
        self.browser = None
        self.lock = asyncio.Lock()
        self.run = Run()
        self.scale = 1.5  # screen pixels per screenshot pixel, from the latest screenshot
        self.dpi = 96
        self.screen = (1920, 1080)
        self.vault_ = None
        self.token = LEASE_ENV       # the queue lease the next action runs under
        self.holder: dict = {}       # its holder record (owner, purpose, deadline, deskd lease id)
        self.mine: set[str] = set()  # leases this process took: given back when it ends
        self.run_token = ""

    async def use(self, lease: str = ""):
        """Before every laptop tool: the queue lease it runs under must hold the laptop now (TimeUp when its time
        ran out). Switching to another lease (another agent of the same session) takes over its deskd lease."""
        if EXPLICIT:
            if not lease:
                raise line.QueueError("take the laptop first: laptop_acquire(purpose, minutes) gives you a lease; "
                                      "pass it as lease=\"...\" to every laptop tool")
            tok = lease
        elif LEASE_ENV:
            tok = LEASE_ENV
        else:
            if not self.token:
                got = await self.call(line.acquire, OWNER, PURPOSE, SESSION_MINUTES, "",
                                      float(os.environ.get("CU_QUEUE_WAIT", "3600")))
                if got["status"] != "granted":
                    raise line.QueueError(f"the laptop stayed busy ({got.get('holder')}): gave up waiting in line")
                self.token = got["token"]
                self.mine.add(self.token)
                self.run.write({"event": "queue-grant", "minutes": SESSION_MINUTES})
            tok = self.token
        h = await self.call(line.check, tok)
        if tok != self.token or (h.get("deskd") and (self.lap.lease or {}).get("id") != h["deskd"]):
            self.lap.lease = {"id": h["deskd"]} if h.get("deskd") else None
        if HTTP["on"] and tok != self.run_token:  # one run record per lease, named after its holder
            self.run, self.run_token = Run(f"{h['owner']}-{h.get('purpose', '')[:40]}"), tok
            self.run.write({"event": "start", "owner": h["owner"], "purpose": h.get("purpose"), "tools": TOOLSET,
                            "coords": COORDS, "minutes": h["minutes"]})
        self.token, self.holder = tok, h

    async def call(self, fn, *args, **kw):
        return await asyncio.to_thread(fn, *args, **kw)

    async def ensure_lease(self):
        took = False
        if not self.lap.lease:
            who, why = self.holder.get("owner") or OWNER, self.holder.get("purpose") or PURPOSE
            try:
                await self.call(self.lap.take_lease, who, why)
            except DeskdError as e:
                if "owner (live view)" in str(e):
                    raise DeskdError(f"{e}. The owner has the laptop: wait a minute and try again (your time runs on)")
                if "leased to" not in str(e):
                    raise
                # left by an earlier holder (time up, process gone): the queue says the laptop is ours now
                await self.call(self.lap.take_lease, who, why, 600, True)
            if self.token:
                await self.call(line.set_deskd, self.token, self.lap.lease["id"])
            took = True
        if took or self.lap.deskd_port is None:  # a lease borrowed from the holder's record still needs the tunnel
            h = await self.call(self.lap.health)
            self.dpi, self.screen = h["dpi"], tuple(h["screen"])
            if h["desktop"] != "Default":
                raise DeskdError(f"the laptop's session is locked or at a secure prompt ({h['desktop']}): needs the owner")
            self.run.write({"event": "deskd", "owner": self.holder.get("owner") or OWNER,
                            "purpose": self.holder.get("purpose") or PURPOSE, "health": h})

    async def deskd(self, fn, *args, **kw):
        """A deskd action under our lease. deskd forgets leases when it restarts (a reboot, a deploy) and they lapse
        while an agent thinks: take it again once."""
        await self.ensure_lease()
        try:
            return await self.call(fn, *args, **kw)
        except DeskdError as e:
            if "no active lease" not in str(e):
                raise
            self.lap.lease = None
            await self.ensure_lease()
            return await self.call(fn, *args, **kw)

    async def act(self, *steps):
        chars = sum(len(s.get("text", "")) for s in steps)
        return await self.deskd(self.lap.input, *steps, timeout=60 + chars / TYPE_CPS * 1.6)

    async def shot(self, quality=70):
        data, meta = await self.call(self.lap.screenshot, SHOT_W, "jpeg", quality)
        self.scale = meta["scale"]
        return data, meta

    async def follow_tunnel(self):
        """Points the Browser at the tunnel's CDP port as it is now. The tunnel reopens on new local ports whenever ssh
        died (the laptop rebooted, went off or left the network), and this process lives on: a Browser left on the old
        port saw a dead Chrome after every reboot, started another window and failed (2026-10-19, STATUS.md)."""
        await self.call(self.lap.open)
        if self.browser is not None and self.browser.port == self.lap.cdp_port:
            return self.browser
        if self.browser is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.browser.close(), 5)
        self.browser = Browser(self.lap.cdp_port)
        return self.browser

    async def ensure_browser(self):
        await self.ensure_lease()
        b = await self.follow_tunnel()
        if not await self.call(b.up):
            # deskd starts Chrome on its profile, or waits for one starting, or ends one that holds the profile
            # without answering on the port (it reports which in its log)
            await self.deskd(self.lap.browser_start, "chrome", timeout=90)
            b = await self.follow_tunnel()
            for _ in range(60):
                if await self.call(b.up):
                    break
                await asyncio.sleep(0.5)
            else:
                raise DeskdError("Chrome did not open its debugging port on the laptop (bin/cu log; bin/cu shot)")
            await asyncio.sleep(1.5)
        return b

    async def current_browser(self):
        """The Browser if this process has used one, on the tunnel's current port; None otherwise."""
        if self.browser is None:
            return None
        with contextlib.suppress(*FAILURES):
            return await self.follow_tunnel()
        return self.browser

    async def guard(self, points=(), keys=None):
        """In a browser session, refuses input that would reach anything but the agent's Chrome."""
        if TOOLSET == "all":
            return
        if keys:
            parts = {k.strip().lower() for k in keys.split("+")}
            if any(b <= parts for b in BLOCKED_KEYS):
                raise ValueError(f"{keys} is not available in a browser session")
        fg = next((w for w in await self.call(self.lap.windows) if w["foreground"]), None)
        if not fg or (fg["exe"] or "").lower() != "chrome.exe":
            raise ValueError(f"browser session: the window in front is {fg and fg['title']!r}, not the browser; "
                             "only the browser can be driven")
        x0, y0, w, h = fg["rect"]
        for x, y in points:
            if not (x0 <= x < x0 + w and y0 <= y < y0 + h):
                raise ValueError("that point is outside the browser window; only the browser can be driven")

    async def google_guard(self, label=None, keys=None):
        """On Google's account-security pages only a decline (Not now, Skip, Annulla) gets through."""
        b = await self.current_browser()
        if b is None:
            if TOOLSET == "all":
                return  # a desktop task that has not used the browser
            b = await self.ensure_browser()
        if not await self.call(b.up):
            return
        tab, _ = await b.active()
        u = urllib.parse.urlparse(tab["url"])
        if u.hostname not in GOOGLE_ACCOUNT_HOSTS or not GOOGLE_PROTECTED.search(u.path):
            return
        if label is not None and DECLINE.search(label):
            return
        if keys is not None and keys.strip().lower() in SAFE_KEYS_THERE:
            return
        raise ValueError("this is a Google account-security page (passkeys, recovery, sign-in options): only a "
                         "decline is allowed here. Use browser_find('Not now'), 'Skip', 'Non ora' or 'Annulla' "
                         "and browser_click it, or leave the page.")

    async def password_guard(self, index=None):
        """Passwords only go in through account_fill, so they never reach a model or a log."""
        b = await self.current_browser()
        if b is None or not await self.call(b.up):
            return
        _, page = await b.active()
        with contextlib.suppress(CDPError, TimeoutError):
            info = await page.call("field", index)
            if info and info.get("type") == "password":
                raise ValueError("that is a password field: passwords only go in with account_fill(item_id, 'password', "
                                 "index), from the vault")

    def vault(self):
        if self.vault_ is None:
            self.vault_ = vault.Vault()
        return self.vault_

    def phys(self, x, y):
        """A point the model gave (in COORDS units over the latest screenshot) -> screen pixels."""
        if COORDS == "norm1000":
            return round(x / 1000 * self.screen[0]), round(y / 1000 * self.screen[1])
        return round(x * self.scale), round(y * self.scale)

    def to_screen(self, x, y, geo):
        """CSS pixels in the viewport -> physical screen pixels (Chrome maximized, any zoom)."""
        os_scale = self.dpi / 96
        zoom = geo["dpr"] / os_scale
        border = max(0.0, (geo["ow"] - geo["iw"] * zoom) / 2)
        left = geo["sx"] + border
        top = geo["sy"] + geo["oh"] - geo["ih"] * zoom - border
        return round((left + x * zoom) * os_scale), round((top + y * zoom) * os_scale)

    async def close(self):
        if self.browser and self.lap.lease:  # a session leaves one blank tab behind (owner, 2026-10-16)
            with contextlib.suppress(Exception):
                held = (await self.call(self.lap.health)).get("lease") or {}
                ours = held.get("id") == self.lap.lease.get("id") if "id" in held else held.get("owner") == OWNER
                if ours:  # never under the owner's hands (live view takes the lease)
                    n = await self.browser.tidy()
                    self.run.write({"event": "tidy", "closed_tabs": n})
        if self.browser:
            await self.browser.close()
        with contextlib.suppress(Exception):
            await self.call(self.lap.release_lease)
        for tok in list(self.mine):  # an agent that forgot laptop_release, or a session-mode server ending
            with contextlib.suppress(Exception):
                await self.call(line.release, tok)
        self.run.write({"event": "end"})
        self.lap.close()


S = Session()


@contextlib.asynccontextmanager
async def lifespan(_server):
    try:
        yield {}
    finally:
        if not HTTP["on"]:  # over HTTP this runs per client session: the laptop link is shared, leases expire
            await S.close()


mcp = MCPServer("computer-use", instructions=INSTRUCTIONS, lifespan=lifespan)


FAILURES = (DeskdError, CDPError, TimeoutError, OSError, ValueError, VaultError, subprocess.SubprocessError,
            line.QueueError)


def tool(fn):
    """Registers a laptop tool: it runs under the caller's queue lease (a `lease` parameter when agents take the
    laptop themselves), serializes with the others, is logged to the run (with its screenshot, if it returns one),
    and turns failures into readable text for the agent."""

    @functools.wraps(fn)
    async def inner(*args, lease: str = "", **kw):
        t0 = time.monotonic()
        async with S.lock:
            try:
                await S.use(lease)
                out = await fn(*args, **kw)
                err = None
            except line.TimeUp as e:
                out, err = str(e), "time-up"
            except FAILURES as e:
                out, err = f"ERROR: {e}", str(e)
        _record(fn.__name__, kw or list(args), out, err, t0)
        return out

    inner.__doc__ = (fn.__doc__ or "").replace("{XY}", XY)
    if EXPLICIT:  # the schema the agent sees gets the lease parameter
        sig = inspect.signature(fn)
        inner.__signature__ = sig.replace(parameters=[*sig.parameters.values(), inspect.Parameter(
            "lease", inspect.Parameter.KEYWORD_ONLY, default="", annotation=str)])
        inner.__annotations__ = {**fn.__annotations__, "lease": str}
        inner.__doc__ += "\n\nlease: the lease laptop_acquire gave you."
    return mcp.tool(structured_output=False)(inner)


def queue_tool(fn):
    """Registers a laptop-queue tool: no lease needed and outside the action lock, so an agent waiting in line never
    holds up the one on the laptop (subagents of one session share this process)."""

    @functools.wraps(fn)
    async def inner(*args, **kw):
        t0 = time.monotonic()
        try:
            out, err = await fn(*args, **kw), None
        except FAILURES as e:
            out, err = f"ERROR: {e}", str(e)
        _record(fn.__name__, {k: v for k, v in kw.items() if k != "ctx"} or list(args), out, err, t0)
        return out
    return mcp.tool(structured_output=False)(inner)


def _record(name, args, out, err, t0):
    parts = out if isinstance(out, list) else [out]
    text = "\n".join(p for p in parts if isinstance(p, str))
    shot = next((p.data for p in parts if isinstance(p, Image)), None)
    S.run.write({"tool": name, "args": args, "ms": round((time.monotonic() - t0) * 1000),
                 "result": text[:200000], **({"error": err} if err else {})}, shot)


def _clock(ts):
    return time.strftime("%H:%M", time.localtime(ts))


def _client(ctx) -> str:
    """Which client (a PC's token name in the clients file) is asking, over HTTP; this process's owner on stdio."""
    if not HTTP["on"]:
        return OWNER
    try:
        headers = getattr(ctx, "headers", None)
        if headers is None:  # mcp 1.x
            headers = ctx.request_context.request.headers
        tok = (headers.get("authorization") or "").split(" ", 1)[-1]
        return _clients().get(hashlib.sha256(tok.encode()).hexdigest(), "?")
    except Exception:
        return "?"


@queue_tool
async def laptop_acquire(purpose: str, minutes: int = line.DEFAULT_MINUTES, ticket: str = "",
                         wait_minutes: int = 5, ctx: Context = None) -> str:
    """Takes the laptop for one task, waiting in line behind other agents (first come, first served).
    purpose: one line on what you need it for (others see it). minutes: how long you need it, 15 by
    default, at most 30; decide up front, it cannot be extended. When the time runs out the laptop goes
    to the next agent and your calls answer TIME UP (your task failed). Returns a lease: pass it as
    lease="..." to every laptop tool, and laptop_release(lease) as soon as you are done. If it answers
    WAITING, call it again with the ticket it gives to keep your place. wait_minutes: how long this
    call waits in line before answering WAITING (at most 10)."""
    if not EXPLICIT:
        return "This server takes the laptop by itself (session mode): no laptop_acquire needed."
    got = await S.call(line.acquire, _client(ctx), purpose, minutes, ticket, min(max(1, wait_minutes), 10) * 60)
    if got["status"] != "granted":
        h = got.get("holder") or {}
        return (f"WAITING: you are number {got['position']} in line; the laptop is with {h.get('owner')} "
                f"({h.get('purpose')}) until {_clock(h['deadline']) if h else '?'}. Call "
                f"laptop_acquire(purpose, minutes, ticket=\"{got['ticket']}\") again to keep your place.")
    S.mine.add(got["token"])
    note = ""
    async with S.lock:  # a clean browser for the new holder: the last one's tabs closed
        try:
            await S.use(got["token"])
            n = await (await S.ensure_browser()).tidy()
            note = f" Closed {n} tab(s) the last holder left." if n else ""
        except FAILURES as e:
            note = f" (Could not tidy the browser: {e})"
    return (f"GRANTED: lease=\"{got['token']}\" for {got['minutes']:g} minutes, until {_clock(got['deadline'])}. "
            f"Pass it as lease=\"...\" to every laptop tool and call laptop_release when done.{note}")


@queue_tool
async def laptop_release(lease: str) -> str:
    """Gives the laptop back to the next agent in line (also when you give up or fail)."""
    async with S.lock:
        with contextlib.suppress(*FAILURES):
            await S.use(lease)
            if b := await S.current_browser():
                await b.tidy()
        with contextlib.suppress(*FAILURES):
            if S.lap.lease and S.token == lease:
                await S.call(S.lap.release_lease)
        done = await S.call(line.release, lease)
        S.mine.discard(lease)
        if S.token == lease:
            S.token, S.holder = "", {}
    return "Released: the laptop went to the next in line." if done else "That lease was not holding the laptop."


@queue_tool
async def laptop_status() -> str:
    """Who has the laptop, until when, and who is waiting."""
    st = await S.call(line.status)
    h = st["holder"]
    lines = [f"With {h['owner']} ({h['purpose']}) until {_clock(h['deadline'])}, {h['left_min']} min left."
             if h else "Free."]
    lines += [f"  waiting: {w['owner']} ({w['purpose']}), {w['minutes']:g} min asked, waited {w['waited_min']} min"
              for w in st["waiting"]]
    return "\n".join(lines)


async def screen_result(note, settle=0.6):
    await asyncio.sleep(settle)
    data, meta = await S.shot()
    h = await S.call(S.lap.health)
    fg = h["foreground"]["title"]
    return [f"{note}\nScreenshot {meta['width']}x{meta['height']}; foreground window: {fg}", Image(data=data, format="jpeg")]


def state_text(st, text=None):
    lines = [f"URL: {st['url']}", f"Title: {st['title']}"]
    if st.get("challenge"):
        lines.append(f"BLOCKED: a {st['challenge']} check is still showing after {', '.join(st.get('tried') or ['waiting'])}. "
                     "It is parked for the owner and will be retried after they clear it. Do not answer it; "
                     "carry on with other sources.")
    if text is not None:
        lines += ["", text]
    return "\n".join(lines)


# --- desktop -----------------------------------------------------------------------------------

@tool
async def screenshot() -> list:
    """The whole screen as the user would see it. click/scroll/drag take points as {XY}."""
    return await screen_result("Current screen.", settle=0)


@tool
async def zoom(x0: int, y0: int, x1: int, y1: int) -> list:
    """A region of the screen at full resolution, to read small text or check a detail. The corners
    (top left x0,y0 and bottom right x1,y1) are in {XY}; clicks afterwards still use the full
    screenshot's coordinates."""
    await S.ensure_lease()
    (a, b), (c, d) = S.phys(x0, y0), S.phys(x1, y1)
    if c <= a or d <= b:
        raise ValueError("zoom needs x1 > x0 and y1 > y0")
    data, meta = await S.call(S.lap.screenshot, None, "jpeg", 85, (a, b, c - a, d - b))
    return [f"Region {x0},{y0}-{x1},{y1} at full resolution ({meta['width']}x{meta['height']})",
            Image(data=data, format="jpeg")]


@tool
async def click(x: int, y: int, button: str = "left", clicks: int = 1) -> list:
    """Moves the mouse to (x, y) and clicks; x and y are {XY}. button: left|right|middle;
    clicks: 2 for a double click."""
    px, py = S.phys(x, y)
    await S.guard([(px, py)])
    await S.google_guard()
    await S.act({"action": "click", "x": px, "y": py, "button": button, "count": clicks})
    return await screen_result(f"Clicked {button} x{clicks} at ({x}, {y}).")


@tool
async def type_text(text: str, press_enter: bool = False) -> list:
    """Types text into whatever has keyboard focus (click the field first), at a person's pace
    (about 9 keys a second), so keep it to what a person would type."""
    await S.guard()
    await S.google_guard()
    await S.password_guard()
    await S.act({"action": "type", "text": text, "cps": TYPE_CPS})
    if press_enter:
        await S.act({"action": "key", "combo": "enter"})
    return await screen_result(f"Typed {len(text)} characters{' and pressed Enter' if press_enter else ''}.")


@tool
async def press_keys(keys: str, repeat: int = 1) -> list:
    """Presses a key or a combination: 'enter', 'esc', 'tab', 'pagedown', 'ctrl+l', 'alt+left',
    'ctrl+shift+t'."""
    await S.guard(keys=keys)
    await S.google_guard(keys=keys)
    await S.act({"action": "key", "combo": keys, "repeat": max(1, min(repeat, 50))})
    return await screen_result(f"Pressed {keys}" + (f" x{repeat}" if repeat > 1 else "") + ".")


@tool
async def scroll(x: int, y: int, direction: str = "down", amount: int = 5) -> list:
    """Scrolls with the mouse wheel over (x, y), which are {XY}. direction: up|down|left|right;
    amount: wheel notches (about 3 lines each)."""
    px, py = S.phys(x, y)
    await S.guard([(px, py)])
    sign = 1 if direction in ("down", "right") else -1
    key = "dx" if direction in ("left", "right") else "dy"
    await S.act({"action": "scroll", "x": px, "y": py, key: sign * amount})
    return await screen_result(f"Scrolled {direction} {amount}.")


@tool
async def drag(x: int, y: int, to_x: int, to_y: int) -> list:
    """Drags with the left button from (x, y) to (to_x, to_y); all are {XY}."""
    (px, py), (qx, qy) = S.phys(x, y), S.phys(to_x, to_y)
    await S.guard([(px, py), (qx, qy)])
    await S.act({"action": "drag", "x": px, "y": py, "x2": qx, "y2": qy})
    return await screen_result(f"Dragged ({x}, {y}) -> ({to_x}, {to_y}).")


@tool
async def wait(seconds: float = 2.0) -> str:
    """Waits for something on screen to finish (at most 30 s)."""
    await asyncio.sleep(max(0.0, min(seconds, 30.0)))
    return f"Waited {seconds:g} s."


# --- browser -----------------------------------------------------------------------------------

def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def site_of(url):
    return (urllib.parse.urlparse(url).hostname or "").removeprefix("www.")


async def outcome(b, page, st, url):
    """After a load: a check that will not clear by itself is retried the way a person would (a
    reload, then the site's front page and back), then parked for the owner; a clean load closes
    the site's open escalations."""
    tried = ["waiting"]
    if st.get("challenge"):
        await page.send("Page.reload")
        page.ctx = None
        st = await b.settle(page, CHALLENGE_WAIT)
        tried.append("a reload")
    parts = urllib.parse.urlparse(url)
    front = f"{parts.scheme}://{parts.netloc}/"
    if st.get("challenge") and url.rstrip("/") != front.rstrip("/"):
        first = await b.navigate(front, wait=CHALLENGE_WAIT)
        tried.append("the front page")
        if not first.get("challenge"):
            await asyncio.sleep(2.5)
            _, page = await b.active()
            r = await page.send("Page.navigate", {"url": url, "referrer": front, "transitionType": "link"})
            if not r.get("errorText"):
                page.ctx = None
                st = await b.settle(page, CHALLENGE_WAIT)
    st["tried"] = tried
    if st.get("challenge"):
        data, _ = await S.shot()
        added = report.add_escalation({"t": now(), "owner": OWNER, "purpose": PURPOSE, "kind": "challenge",
                                       "check": st["challenge"], "site": site_of(st["url"]), "url": url,
                                       "reason": f"{st['challenge']} check after {', '.join(tried)}",
                                       "run": S.run.dir.name})
        S.run.write({"event": "parked", "url": url, "check": st["challenge"], "new": added}, data)
    else:
        report.resolve_site(site_of(st["url"]), now(), S.run.dir.name)
    return st

@tool
async def browser_open(url: str, max_chars: int = 6000) -> str:
    """Opens url in the browser's current tab, waits for it to load (and for automatic bot checks
    to pass), and returns the title plus the first max_chars of the page text."""
    return await open_url(url, max_chars)


@tool
async def browser_new_tab(url: str, max_chars: int = 6000) -> str:
    """Opens a new tab (Ctrl+T) and loads url in it, keeping the current tab as it is (a sign-up
    form while you read a confirmation mail). browser_switch_tab goes back."""
    b = await S.ensure_browser()
    await S.guard(keys="ctrl+t")
    before = {t["id"] for t in b.tabs()}
    await S.act({"action": "key", "combo": "ctrl+t"})
    for _ in range(20):
        await asyncio.sleep(0.25)
        if {t["id"] for t in b.tabs()} - before:
            break
    else:
        raise CDPError("the new tab did not appear")
    return await open_url(url, max_chars)


@tool
async def browser_switch_tab(index: int) -> str:
    """Brings tab [index] from browser_tabs to the front and returns where it is."""
    b = await S.ensure_browser()
    tabs = b.tabs()
    if not 0 <= index < len(tabs):
        raise ValueError(f"there is no tab [{index}]: browser_tabs lists them")
    await S.call(b.activate, tabs[index]["id"])
    await asyncio.sleep(0.5)
    _, page = await b.active()
    page.ctx = None
    return state_text(await b.settle(page, 10))


async def open_url(url, max_chars):
    b = await S.ensure_browser()
    st = await b.navigate(url, wait=CHALLENGE_WAIT)
    _, page = await b.active()
    st = await outcome(b, page, st, url)
    if st.get("challenge"):
        return state_text(st)
    _, page = await b.active()
    r = await page.call("read", 0, max_chars, False)
    more = f"\n\n[{r['total']} characters in all; browser_read(offset={r['next']}) for more]" if r["next"] else ""
    return state_text(st, r["text"] + more)


@tool
async def browser_read(offset: int = 0, max_chars: int = 20000, main_only: bool = False) -> str:
    """The current page as markdown (links included), from offset. main_only keeps just the
    page's <main>/<article> when it has one."""
    b = await S.ensure_browser()
    tab, page = await b.active()
    r = await page.call("read", offset, max_chars, main_only)
    more = f"\n\n[next: browser_read(offset={r['next']})]" if r["next"] else "\n\n[end of page]"
    return f"URL: {r['url']}\nTitle: {r['title']}\nCharacters {offset}-{offset + len(r['text'])} of {r['total']}\n\n{r['text']}{more}"


def element_lines(els):
    out = []
    for e in els:
        bits = [f"[{e['i']}] {e.get('role') or e['tag']}"]
        if e.get("type"):
            bits.append(f"type={e['type']}")
        bits.append(json.dumps(e["label"], ensure_ascii=False))
        if e.get("href"):
            bits.append(f"-> {e['href']}")
        if not e.get("in_view", True):
            bits.append("(off screen)")
        if e.get("covered"):
            bits.append("(covered)")
        if e.get("disabled"):
            bits.append("(disabled)")
        out.append(" ".join(bits))
    return "\n".join(out) or "(none)"


@tool
async def browser_elements(include_off_screen: bool = False) -> str:
    """Numbers the links, buttons and fields on the page (the visible part by default). Use the
    numbers with browser_click and browser_type."""
    b = await S.ensure_browser()
    _, page = await b.active()
    r = await page.call("elements", include_off_screen)
    return element_lines(r["elements"])


@tool
async def browser_find(text: str) -> str:
    """Finds visible elements whose text contains `text` (case-insensitive) and numbers them for
    browser_click."""
    b = await S.ensure_browser()
    _, page = await b.active()
    r = await page.call("find", text)
    return element_lines(r["elements"])


async def click_element(page, index):
    p = await page.call("point", index)
    x, y = S.to_screen(p["x"], p["y"], p["geometry"])
    await S.act({"action": "click", "x": x, "y": y})
    return p


async def focus_field(page, index):
    """Clicks field [index] and makes sure it has the keyboard focus before anything is typed: a
    popup on top of it (Chrome's autofill, a site's suggestions) takes the click otherwise, and the
    typing would land somewhere else. One Esc and a second click, then give up."""
    for attempt in range(2):
        try:
            await click_element(page, index)
        except CDPError:
            if attempt == 0:
                raise
            break  # the field went away after the first click
        await asyncio.sleep(0.2)
        if await page.call("focusOn", index):
            return
        if attempt == 0:
            await S.act({"action": "key", "combo": "esc"})
            await asyncio.sleep(0.3)
    raise ValueError(f"field [{index}] did not take the focus (something covers it, or the click opened something "
                     "else); nothing was typed. Look with screenshot, then list the elements again")


@tool
async def browser_click(index: int, screenshot: bool = False) -> list:
    """Clicks element [index] from browser_elements/browser_find with the real mouse (it scrolls
    into view first), waits for any navigation, and returns where the browser is now."""
    b = await S.ensure_browser()
    tab, page = await b.active()
    before = tab["url"]
    target = await page.call("field", index)
    await S.google_guard(label=(target or {}).get("label", ""))
    p = await click_element(page, index)
    await asyncio.sleep(0.8)
    tab, page = await b.active()
    st = await b.settle(page, CHALLENGE_WAIT)
    if st.get("challenge"):
        st = await outcome(b, page, st, st["url"])
    note = f"Clicked [{index}] {p['tag']} {json.dumps(p['label'], ensure_ascii=False)}." + \
        (" The page changed." if st["url"] != before else "")
    out = [state_text(st) + "\n" + note]
    if screenshot:
        data, _ = await S.shot()
        out.append(Image(data=data, format="jpeg"))
    return out


@tool
async def browser_type(text: str, index: int | None = None, submit: bool = False, clear: bool = True) -> str:
    """Types into field [index] (or the focused field): clicks it, replaces its content unless
    clear=False, types text, and presses Enter when submit is true."""
    b = await S.ensure_browser()
    tab, page = await b.active()
    await S.google_guard()
    await S.password_guard(index)
    if index is not None:
        await focus_field(page, index)
    if clear:
        await S.act({"action": "key", "combo": "ctrl+a"}, {"action": "key", "combo": "backspace"})
    await S.act({"action": "type", "text": text, "cps": TYPE_CPS})
    typed = await page.call("value", index) if index is not None else None
    if submit:
        await S.act({"action": "key", "combo": "enter"})
        await asyncio.sleep(1.0)
        tab, page = await b.active()
        st = await b.settle(page, 15)
        return state_text(st) + f"\nTyped {len(text)} characters and submitted."
    check = "" if typed is None else (" The field now reads: " + json.dumps(str(typed)[:200], ensure_ascii=False))
    return f"Typed {len(text)} characters.{check}"


@tool
async def browser_scroll(direction: str = "down", pages: float = 1.0) -> str:
    """Scrolls the page with the mouse wheel: direction up|down, pages in screen heights."""
    b = await S.ensure_browser()
    _, page = await b.active()
    geo = await page.call("geometry")
    x, y = S.to_screen(geo["iw"] / 2, geo["ih"] / 2, geo)
    notches = max(1, round(pages * geo["ih"] / 100))
    await S.act({"action": "scroll", "x": x, "y": y, "dy": notches if direction == "down" else -notches})
    await asyncio.sleep(0.5)
    g2 = await page.call("geometry")
    return f"Scrolled {direction}: now at {g2['scroll_y']:.0f} of {g2['doc_h']:.0f} px."


@tool
async def browser_back() -> str:
    """Goes back one page (Alt+Left)."""
    b = await S.ensure_browser()
    await S.act({"action": "key", "combo": "alt+left"})
    await asyncio.sleep(1.0)
    _, page = await b.active()
    page.ctx = None
    return state_text(await b.settle(page, 15))


@tool
async def browser_close_tabs() -> str:
    """Closes every tab but one and leaves that one blank. Every session does this when it ends."""
    b = await S.ensure_browser()
    n = await b.tidy()
    return f"closed {n} tab(s); one blank tab left"


@tool
async def browser_tabs() -> str:
    """Lists the open tabs, the one in front first."""
    b = await S.ensure_browser()
    return "\n".join(f"[{n}] {t['title'][:80]} - {t['url']}" for n, t in enumerate(b.tabs())) or "(no tabs)"


@tool
async def browser_pdf_text(first_page: int = 1, last_page: int = 20) -> str:
    """Text of the PDF open in the current tab (pages first_page..last_page), fetched by the
    browser itself so cookies and checks it already passed still apply."""
    b = await S.ensure_browser()
    tab, page = await b.active()
    data = await b.pdf_bytes(page)
    if not data.startswith(b"%PDF"):
        return f"The current tab ({tab['url']}) is not a PDF."
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        r = subprocess.run(["pdftotext", "-layout", "-f", str(first_page), "-l", str(last_page), f.name, "-"],
                           capture_output=True, text=True, timeout=60)
    (S.run.dir / "pdfs").mkdir(parents=True, exist_ok=True)
    (S.run.dir / "pdfs" / f"{S.run.n + 1:04d}.pdf").write_bytes(data)
    return f"URL: {tab['url']}\nPages {first_page}-{last_page}, {len(data)} bytes\n\n{r.stdout[:60000]}"


@tool
async def escalate(kind: str, reason: str, url: str = "") -> list:
    """Records that a page needs the owner, with a screenshot, then carry on with other sources.
    kind: login (an account you could not create or use), phone (the site wants a phone number),
    consent (a cookie/consent wall the page cannot be read past), challenge (a CAPTCHA or 'verify
    you are human' the browser tools did not already park), paywall, other. The owner clears these
    from the live view."""
    data, _ = await S.shot()
    added = report.add_escalation({"t": now(), "owner": OWNER, "purpose": PURPOSE, "kind": kind,
                                   "site": site_of(url), "url": url, "reason": reason, "run": S.run.dir.name})
    note = "Recorded for the owner." if added else "Already waiting for the owner."
    return [note + " Continue with other sources.", Image(data=data, format="jpeg")]


# --- accounts ----------------------------------------------------------------------------------

def item_text(item):
    d = vault.summary(item)
    return (f"[{d['id']}] {d['site']}: username {d['username']!r}, status {d['status']}"
            + (", PROTECTED (the identity's own Google account)" if d["protected"] else "")
            + (f", urls {', '.join(d['urls'])}" if d["urls"] else "")
            + ("".join(f"\n    {n}" for n in d["notes"]) if d["notes"] else ""))


def editable(item, while_pending=False):
    if vault.is_protected(item):
        raise ValueError("that is the identity's own Google account: agents never change it")
    if while_pending and (vault.field(item, "status") or "active") != "pending":
        raise ValueError("only while signing up (status pending): once a site has accepted a password, changing "
                         "it here would lock the account out")


@tool
async def account_lookup(site: str = "") -> str:
    """The agent identity's accounts for a site (a domain or URL), or all of them when site is
    empty: id, username, status (pending: sign-up not finished; active; failed). Passwords are
    never shown."""
    items = await S.call(S.vault().items, site or None)
    head = f"Identity: {IDENTITY.get('AGENT_EMAIL')} ({IDENTITY.get('AGENT_NAME')})."
    if not items:
        return head + f"\nNo account{' for ' + vault.base_domain(site) if site else 's'} yet."
    return head + "\n" + "\n".join(item_text(i) for i in items)


@tool
async def account_create(site: str, url: str, username: str = "", length: int = 20, uppercase: bool = True,
                         lowercase: bool = True, numbers: bool = True, special: bool = True,
                         append: str = "") -> str:
    """Starts a sign-up: the password manager generates a password to the site's rules and saves
    the account (status pending) before you fill the form. site: the site's domain; url: its
    sign-up page; username: what the site signs in with (default: the identity's email; a public
    screen name that is not the sign-in goes in account_update's note). Password
    options: length, the kinds of characters, and append (up to 4 characters a site insists on).
    Returns the item id for account_fill; the password itself is never shown."""
    site = vault.base_domain(site or url)
    if site == "google.com":
        raise ValueError("the Google account is the identity itself; it is not created here")
    if len(append) > 4:
        raise ValueError("append at most 4 characters")
    v = S.vault()
    live = [i for i in await S.call(v.items, site) if vault.field(i, "status") != "failed"]
    if live:
        raise ValueError(f"{site} already has an account: use it, or finish its sign-up\n" +
                         "\n".join(item_text(i) for i in live))
    pw = await S.call(v.generate, length, uppercase, lowercase, numbers, special, append)
    item = await S.call(v.create, site, url, username or IDENTITY.get("AGENT_EMAIL", ""), pw,
                        f"{OWNER} ({S.run.dir.name})", PURPOSE)
    return (f"Saved {item_text(item)}\nA {len(pw)}-character password from the password manager is in it. "
            f"Fill the form with account_fill(\"{item['id']}\", \"password\", index) for each password field.")


@tool
async def account_new_password(item_id: str, length: int = 20, uppercase: bool = True, lowercase: bool = True,
                               numbers: bool = True, special: bool = True, append: str = "") -> str:
    """When a site refuses the generated password during sign-up: generates a new one with
    options that meet its rules and saves it in place of the old one. Then fill the password
    fields again."""
    v = S.vault()
    item = await S.call(v.get, item_id)
    editable(item, while_pending=True)
    if len(append) > 4:
        raise ValueError("append at most 4 characters")
    pw = await S.call(v.generate, length, uppercase, lowercase, numbers, special, append)
    item = await S.call(v.set_password, item, pw)
    return f"New {len(pw)}-character password saved for {item['name']}; fill every password field again."


@tool
async def account_fill(item_id: str, field: str = "password", index: int | None = None) -> str:
    """Types the account's username or password from the vault into field [index] from
    browser_elements/browser_find (or the focused field). Only on the account's own site, and a
    password only into a password field. The value is never shown to you or written to a log."""
    if field not in ("username", "password"):
        raise ValueError("field is username or password")
    item = await S.call(S.vault().get, item_id)
    b = await S.ensure_browser()
    tab, page = await b.active()
    sites = {vault.base_domain(item["name"])} | {vault.base_domain(u["uri"]) for u in item["login"].get("uris") or []}
    here = vault.base_domain(tab["url"])
    if here not in sites:
        raise ValueError(f"this page is on {here}, but the account belongs to {', '.join(sorted(sites))}: "
                         "account details only go to their own site")
    info = await page.call("field", index)
    if info is None:
        raise ValueError("no field is focused: give the field's index from browser_elements")
    is_pw = info.get("type") == "password"
    if is_pw != (field == "password"):
        raise ValueError(f"that field is {info['tag']} type={info.get('type')} {info['label']!r}: a password goes "
                         "only into a password field, a username never into one")
    value = item["login"].get(field) or ""
    if not value:
        raise ValueError(f"the account has no {field}")
    if index is not None:
        await focus_field(page, index)
    if (tab["url"], here) != ((t := (await b.active())[0])["url"], vault.base_domain(t["url"])):
        raise ValueError("the tab changed while focusing the field; nothing was typed")
    await S.act({"action": "key", "combo": "ctrl+a"}, {"action": "key", "combo": "backspace"})
    await S.act({"action": "type", "text": value, "cps": TYPE_CPS, "secret": is_pw})
    after = await page.call("field", index)
    n = after["length"] if after else None
    if n == len(value):
        return f"Filled the {field} of {item['name']} ({len(value)} characters)."
    return (f"The field holds {n} characters, not {len(value)}: the site may cap the length. Try once more; if it "
            "still differs, account_new_password with a length the site accepts.")


@tool
async def account_update(item_id: str, status: str = "", note: str = "", username: str = "") -> str:
    """Records how a sign-up went: status active (signed in and working), pending, or failed (with
    the reason in note). username: the name the site finally accepted, while still pending."""
    v = S.vault()
    item = await S.call(v.get, item_id)
    editable(item, while_pending=bool(username))
    if username:
        item["login"]["username"] = username
    item = await S.call(v.note, item, status or None, note or (f"username {username}" if username else ""))
    return "Saved " + item_text(item)


def _clients() -> dict:
    """sha256(token) -> client name, from the clients file (cu/cli.py add-client); re-read when it changes."""
    path = HTTP["clients"]
    try:
        mtime = path.stat().st_mtime
    except (OSError, AttributeError):
        return {}
    if HTTP.get("mtime") != mtime:
        doc = json.loads(path.read_text() or "{}")
        HTTP["map"], HTTP["mtime"] = {c["sha256"]: c["name"] for c in doc.get("clients", [])}, mtime
    return HTTP["map"]


def serve_http(host: str, port: int, clients: pathlib.Path) -> None:
    """Every agent session, on any PC, through one process: one tunnel to the laptop, one browser link, one queue.
    Each request needs a client token (Authorization: Bearer); the Host header is rewritten to this address, since
    the SDK's DNS-rebinding guard knows only localhost and a reverse proxy forwards the public name."""
    import logging
    import uvicorn
    logging.getLogger("mcp").setLevel(logging.WARNING)  # no line per request in the journal
    HTTP.update(on=True, clients=clients)
    app = mcp.streamable_http_app()
    local = f"127.0.0.1:{port}".encode()

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            tok = headers.get(b"authorization", b"").decode().split(" ", 1)[-1]
            if not tok or hashlib.sha256(tok.encode()).hexdigest() not in _clients():
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain"), (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": b"a client token is needed"})
                return
            scope = {**scope, "headers": [(k, local if k == b"host" else v) for k, v in scope["headers"]
                                          if k != b"origin"]}
        await app(scope, receive, send)
    uvicorn.run(guarded, host=host, port=port, log_level="warning")


def main():
    ap = argparse.ArgumentParser(prog="cu-mcp")
    ap.add_argument("--http", help="HOST:PORT: serve every client over streamable HTTP instead of one over stdio")
    ap.add_argument("--clients", default=os.environ.get("CU_CLIENTS", ""), help="client token hashes (--http)")
    a = ap.parse_args()
    if a.http:
        host, port = a.http.rsplit(":", 1)
        serve_http(host, int(port), pathlib.Path(a.clients))
    else:
        # stdio: one client per process. Every stdio server on this machine shares the queue under CU_STATE
        # (cu/queue.py), so several harness sessions on one PC still take turns on the laptop.
        mcp.run("stdio")


if __name__ == "__main__":
    main()
