"""Reading the agent browser over the DevTools protocol, quietly.

The page must not be able to tell it is observed, so this module:
- never calls Runtime.enable, Page.enable or any other *.enable (the classic CDP tell is the
  console serialization that Runtime.enable switches on), never adds init scripts;
- runs its JavaScript in an isolated world (Page.createIsolatedWorld): it shares the DOM, but the
  page's scripts cannot see its globals or patch the functions it calls;
- never clicks or types through CDP: actions go through deskd as real OS input, at screen
  coordinates computed here from element boxes.
"""
import asyncio
import contextlib
import base64
import itertools
import json
import pathlib
import urllib.request

import websockets

JS = (pathlib.Path(__file__).parent / "page.js").read_text()
WORLD = "cu"

# Titles and frames of interstitials: wait for the automatic ones, report the rest.
CHALLENGES = [
    ("cloudflare", lambda p: p["title"] in ("Just a moment...", "Attention Required! | Cloudflare")
     or "challenges.cloudflare.com" in p["frames"]),
    ("datadome", lambda p: "captcha-delivery.com" in p["frames"]),
    ("hcaptcha", lambda p: "hcaptcha.com" in p["frames"]),
    ("recaptcha", lambda p: "google.com/recaptcha" in p["frames"] and p["recaptcha_visible"]),
    ("perimeterx", lambda p: "px-captcha" in p["frames"] or p["title"] == "Access to this page has been denied"),
    ("akamai", lambda p: p["title"] == "Access Denied" and "Reference" in p["text_head"]),
]


class CDPError(RuntimeError):
    pass


class Page:
    """One page target. Holds its websocket and its isolated world (rebuilt after navigations)."""

    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self.ids = itertools.count(1)
        self.ctx = None  # (frame_id, loader_id, context_id)

    async def send(self, method, params=None, timeout=30):
        if self.ws is None:
            self.ws = await websockets.connect(self.ws_url, max_size=64 * 2**20, ping_interval=None)
        msg_id = next(self.ids)
        await self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        async with asyncio.timeout(timeout):
            while True:
                msg = json.loads(await self.ws.recv())
                if msg.get("id") == msg_id:
                    if "error" in msg:
                        raise CDPError(f"{method}: {msg['error'].get('message')}")
                    return msg["result"]

    async def close(self):
        if self.ws is not None:
            await self.ws.close()
            self.ws = None

    async def world(self):
        tree = (await self.send("Page.getFrameTree"))["frameTree"]["frame"]
        key = (tree["id"], tree.get("loaderId"))
        if not self.ctx or self.ctx[:2] != key:
            r = await self.send("Page.createIsolatedWorld", {"frameId": tree["id"], "worldName": WORLD,
                                                             "grantUniveralAccess": False})
            self.ctx = (*key, r["executionContextId"])
            await self.eval(JS, fresh=False)
        return self.ctx[2]

    async def eval(self, expression, fresh=True, timeout=30):
        ctx = await self.world() if fresh else self.ctx[2]
        r = await self.send("Runtime.evaluate", {"expression": expression, "contextId": ctx,
                                                 "returnByValue": True, "awaitPromise": True}, timeout)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise CDPError(d.get("exception", {}).get("description") or d.get("text"))
        return r["result"].get("value")

    async def call(self, fn, *args, timeout=30):
        """Calls a function page.js defined on the isolated world's `cu` object."""
        for attempt in range(2):
            try:
                return await self.eval(f"cu.{fn}(...{json.dumps(args)})", timeout=timeout)
            except CDPError as e:
                # The world dies with its document; one retry builds a new one.
                if attempt or "context" not in str(e).lower():
                    raise
                self.ctx = None


class Browser:
    """The agent browser behind the tunnel's CDP port."""

    def __init__(self, port):
        self.port = port
        self.pages = {}

    def _json(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as r:
            return json.load(r)

    def up(self):
        try:
            self._json("/json/version")
            return True
        except OSError:
            return False

    def tabs(self):
        return [t for t in self._json("/json/list") if t["type"] == "page"]

    def close_tab(self, tab_id):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/close/{tab_id}", timeout=10) as r:
            r.read()

    async def tidy(self):
        """Closes every tab but one and blanks that one (owner, 2026-10-16: tabs piled up across research
        sessions). Through Chrome's DevTools endpoint, no input on the desktop. Returns how many were closed."""
        tabs = self.tabs()
        if not tabs:
            return 0
        keep, rest = tabs[0], tabs[1:]
        for t in rest:
            page = self.pages.pop(t["id"], None)
            if page:
                with contextlib.suppress(Exception):
                    await page.close()
            with contextlib.suppress(OSError):
                self.close_tab(t["id"])
        with contextlib.suppress(Exception):
            await self.page(keep).send("Page.navigate", {"url": "about:blank"})
        return len(rest)

    def activate(self, tab_id):
        """Brings a tab to the front, as a click on it would."""
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/activate/{tab_id}", timeout=10) as r:
            r.read()

    def page(self, tab):
        if tab["id"] not in self.pages:
            ws = tab["webSocketDebuggerUrl"].replace("127.0.0.1:9222", f"127.0.0.1:{self.port}")
            self.pages[tab["id"]] = Page(ws)
        return self.pages[tab["id"]]

    async def active(self):
        """The tab the user would be looking at: visible, newest first."""
        tabs = self.tabs()
        if not tabs:
            raise CDPError("no open tab")
        for t in tabs:
            try:
                if await self.page(t).eval("document.visibilityState", timeout=5) == "visible":
                    return t, self.page(t)
            except (CDPError, TimeoutError):
                continue
        return tabs[0], self.page(tabs[0])

    async def navigate(self, url, wait=20.0):
        tab, page = await self.active()
        r = await page.send("Page.navigate", {"url": url, "transitionType": "typed"})
        if r.get("errorText"):
            raise CDPError(f"navigate {url}: {r['errorText']}")
        page.ctx = None
        return await self.settle(page, wait)

    async def settle(self, page, wait=20.0):
        """Waits for load, then for automatic interstitials to clear. Returns the page state."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait
        state = None
        while loop.time() < deadline:
            try:
                state = await page.call("state")
            except (CDPError, TimeoutError):
                page.ctx = None
                await asyncio.sleep(0.5)
                continue
            state["challenge"] = next((name for name, test in CHALLENGES if test(state)), None)
            if state["ready"] == "complete" and not state["challenge"]:
                return await self.until_stable(page, state, min(6.0, max(1.0, deadline - loop.time())))
            await asyncio.sleep(0.7)
        if state is None:
            raise CDPError("page never answered")
        return state

    async def until_stable(self, page, state, limit):
        """Pages that render after load (search results, listings): wait until the text stops
        growing, polling twice a second, for at most `limit` seconds."""
        loop = asyncio.get_running_loop()
        end = loop.time() + limit
        last, steady = -1, 0
        while loop.time() < end:
            n = await page.call("textLength")
            steady = steady + 1 if n == last else 0
            if steady >= 2:
                break
            last = n
            await asyncio.sleep(0.5)
        return state

    async def close(self):
        for p in self.pages.values():
            await p.close()
        self.pages.clear()

    async def pdf_bytes(self, page):
        """The current document's bytes, fetched by the page itself (its cookies, its referer)."""
        b64 = await page.call("fetchBase64", timeout=120)
        return base64.b64decode(b64)
