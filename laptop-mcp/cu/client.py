"""A client of the laptop's MCP service (`bin/cu-mcp --http`, e.g. https://laptop.example.lan/mcp behind your reverse proxy),
for programs (tests, scripts); agent harnesses reach it as the MCP server `laptop`. Without service settings
it starts bin/cu-mcp over stdio instead.

The URL and this PC's client token come from CU_URL / CU_TOKEN, or ~/.config/computer-use/client.env (mode 600;
`bin/cu add-client NAME` on the service host prints a token once). Every client waits in the one queue the service keeps.

    async with session() as s, lease(s, "what for", minutes=10) as tok:
        await s.call_tool("browser_open", {"url": ..., "lease": tok})
"""
from __future__ import annotations

import contextlib
import os
import pathlib
import re

from mcp import ClientSession

CONFIG = pathlib.Path(os.environ.get("CU_CLIENT_ENV") or pathlib.Path.home() / ".config/computer-use/client.env")


class ServiceError(RuntimeError):
    pass


def settings() -> tuple[str, str]:
    url, tok = os.environ.get("CU_URL", ""), os.environ.get("CU_TOKEN", "")
    if (not url or not tok) and CONFIG.exists():
        for line in CONFIG.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "CU_URL" and not url:
                url = v.strip()
            elif k.strip() == "CU_TOKEN" and not tok:
                tok = v.strip()
    if not url or not tok:
        raise ServiceError(f"no laptop service settings: CU_URL and CU_TOKEN, or {CONFIG}")
    return url, tok


def text(result) -> str:
    return "\n".join(c.text for c in result.content if c.type == "text")


@contextlib.asynccontextmanager
async def session():
    """A ClientSession to the HTTP service when CU_URL/CU_TOKEN (or client.env) are set, else to a bin/cu-mcp
    started over stdio on this machine (mcp 2.x or 1.x client)."""
    try:
        url, tok = settings()
    except ServiceError:
        from mcp.client.stdio import StdioServerParameters, stdio_client
        server = StdioServerParameters(command=str(pathlib.Path(__file__).resolve().parent.parent / "bin" / "cu-mcp"),
                                       env=dict(os.environ))
        async with stdio_client(server) as (r, w), ClientSession(r, w) as s:
            init = await s.initialize()
            s.cu_instructions = getattr(init, "instructions", "") or ""
            yield s
        return
    headers = {"Authorization": f"Bearer {tok}"}
    try:  # mcp 2.x
        from mcp.client.streamable_http import streamable_http_client
        import httpx2
        cm = streamable_http_client(url, http_client=httpx2.AsyncClient(headers=headers, timeout=None))
    except ImportError:  # mcp 1.x
        from mcp.client.streamable_http import streamablehttp_client
        cm = streamablehttp_client(url, headers=headers)
    async with cm as streams, ClientSession(streams[0], streams[1]) as s:
        init = await s.initialize()
        s.cu_instructions = getattr(init, "instructions", "") or ""  # the server's, for a model driving it
        yield s


async def acquire(s: ClientSession, purpose: str, minutes: float = 15, on_wait=None, give_up_s: float = 3600) -> str:
    """Waits in the service's line (asking again with the ticket) until the laptop is ours: the lease."""
    import time
    ticket, t0 = "", time.monotonic()
    while True:
        out = text(await s.call_tool("laptop_acquire", {"purpose": purpose, "minutes": minutes, "ticket": ticket,
                                                         "wait_minutes": 5}))
        m = re.search(r'lease="([^"]+)"', out)
        if m:
            return m.group(1)
        t = re.search(r'ticket="([^"]+)"', out)
        if not t:
            raise ServiceError(out[:300])
        ticket = t.group(1)
        if on_wait:
            on_wait(out)
        if time.monotonic() - t0 > give_up_s:
            raise ServiceError(f"the laptop stayed busy for {give_up_s / 60:.0f} minutes: {out[:200]}")


@contextlib.asynccontextmanager
async def lease(s: ClientSession, purpose: str, minutes: float = 15, on_wait=None, held: str = ""):
    """The laptop for one task (or `held`, a lease someone else holds and gives back itself)."""
    tok = held or await acquire(s, purpose, minutes, on_wait)
    try:
        yield tok
    finally:
        if not held:
            with contextlib.suppress(Exception):
                await s.call_tool("laptop_release", {"lease": tok})
