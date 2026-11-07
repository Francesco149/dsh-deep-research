"""Drives bin/cu-mcp through a real MCP stdio client: tools list, consent click, search, read.
Run: uv run python tests/smoke_mcp.py  (the laptop must be up; takes the lease for ~1 minute)."""
import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
from cu import client  # noqa: E402


REPO = pathlib.Path(__file__).resolve().parent.parent


def show(name, res):
    for c in res.content:
        if c.type == "text":
            print(f"--- {name}\n{c.text[:1500]}")
        else:
            print(f"--- {name}: {c.type} {getattr(c, 'mime_type', '')} {len(getattr(c, 'data', ''))} b64 chars")


async def main():
    # the HTTP service when CU_URL/CU_TOKEN are set, else bin/cu-mcp over stdio; in the queue like every client
    async with client.session() as s, client.lease(s, "tests/smoke_mcp.py", 5) as tok:
        tools = (await s.list_tools()).tools
        print("tools:", ", ".join(t.name for t in tools))
        call = lambda n, **a: s.call_tool(n, {**a, "lease": tok})
        show("open google", await call("browser_open", url="https://www.google.com/", max_chars=400))
        found = await call("browser_find", text=sys.argv[1] if len(sys.argv) > 1 else "Reject all")
        show("find", found)
        first = found.content[0].text.split("]")[0].lstrip("[")
        if first.isdigit():
            show("click consent", await call("browser_click", index=int(first)))
        show("open wikipedia", await call("browser_open", url="https://en.wikipedia.org/wiki/Main_Page", max_chars=300))
        box = await call("browser_find", text="Search Wikipedia")
        show("find search", box)
        els = await call("browser_elements")
        line = next((l for l in els.content[0].text.splitlines() if "searchbox" in l or 'type=search' in l), None)
        print("search field:", line)
        idx = int(line.split("]")[0].lstrip("[")) if line else None
        show("type", await call("browser_type", text="Banjo-Kazooie", index=idx, submit=True))
        show("read", await call("browser_read", max_chars=800, main_only=True))
        show("screenshot", await call("screenshot"))


asyncio.run(main())
