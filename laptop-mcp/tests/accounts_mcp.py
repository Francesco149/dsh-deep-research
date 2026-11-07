"""Checks the account guards through a real MCP stdio client, creating nothing: passwords refused
outside account_fill, account details refused on another site, Google's security pages decline-
only, the Google account protected, and the tab tools.
Run: uv run python tests/accounts_mcp.py  (the laptop must be up; takes the lease for ~1 minute)."""
import asyncio
import os
import pathlib
import re

import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from cu import client  # noqa: E402
LOGIN = "https://github.com/login"  # a plain form the identity is not signed into


def text(res):
    return "\n".join(c.text for c in res.content if c.type == "text")


async def main():
    failures = []

    def check(name, ok, detail=""):
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {detail[:200]}" if detail and not ok else ""))
        if not ok:
            failures.append(name)

    # the HTTP service when CU_URL/CU_TOKEN are set, else bin/cu-mcp over stdio; in the queue like every client
    async with client.session() as s, client.lease(s, "tests/accounts_mcp.py", 5) as tok:
        call = lambda n, **a: s.call_tool(n, {**a, "lease": tok})
        names = {t.name for t in (await s.list_tools()).tools}
        check("account tools listed", {"account_lookup", "account_create", "account_fill", "account_new_password",
                                       "account_update", "browser_new_tab", "browser_switch_tab"} <= names)
        check("instructions carry the identity", "never create or add a passkey" in (s.cu_instructions or ""))

        look = text(await call("account_lookup", site="google.com"))
        google = re.search(r"\[([0-9a-f-]{36})\] .*PROTECTED", look)
        check("Google account found and protected", bool(google), look)
        gid = google.group(1) if google else "none"
        check("protected: no new password", "never change" in text(await call("account_new_password", item_id=gid)))
        check("protected: no status change", "never change" in text(await call("account_update", item_id=gid, status="failed")))
        check("no second Google account", "identity itself" in text(await call(
            "account_create", site="google.com", url="https://accounts.google.com/signup")))

        await call("browser_open", url=LOGIN, max_chars=200)
        els = text(await call("browser_elements"))
        pw = re.search(r"\[(\d+)\] \S+ type=password", els)
        check("login page has a password field", bool(pw), els)
        if pw:
            i = int(pw.group(1))
            out = text(await call("browser_type", text="hunter2", index=i))
            check("browser_type refuses a password field", "account_fill" in out, out)
            out = text(await call("account_fill", item_id=gid, field="password", index=i))
            check("account_fill refuses another site", "own site" in out, out)

        # A popup over the field (Chrome's autofill did this on 2026-10-16) must stop the typing.
        await call("browser_open", url="data:text/html,<input placeholder=covered style='position:absolute;top:100px;"
                   "left:100px;width:300px'><div style='position:absolute;top:90px;left:90px;width:400px;height:60px;"
                   "background:rgba(0,0,0,.2)'></div>", max_chars=100)
        field = re.search(r"\[(\d+)\] input", text(await call("browser_elements")))
        out = text(await call("browser_type", text="typed into the wrong place", index=int(field.group(1)))) if field else ""
        check("a covered field gets no typing", "did not take the focus" in out, out)

        # Google asks for the password again before its security pages: either guard must hold.
        await call("browser_open", url="https://myaccount.google.com/signinoptions/passkeys", max_chars=200)
        out = text(await call("browser_type", text="x"))
        check("Google passkey page: typing refused", "only a decline" in out or "account_fill" in out, out)

        tabs_before = text(await call("browser_tabs"))
        await call("browser_new_tab", url="https://example.com/", max_chars=100)
        tabs = text(await call("browser_tabs"))
        check("new tab opened", tabs.count("\n") == tabs_before.count("\n") + 1 and "example.com" in tabs.splitlines()[0], tabs)
        other = next(int(l[1:l.index("]")]) for l in tabs.splitlines() if "example.com" not in l)
        out = text(await call("browser_switch_tab", index=other))
        check("switched back", "example.com" not in out.splitlines()[0], out)
        tabs = text(await call("browser_tabs"))
        ex = next(int(l[1:l.index("]")]) for l in tabs.splitlines() if "example.com" in l)
        await call("browser_switch_tab", index=ex)
        await call("press_keys", keys="ctrl+w")

        out = text(await call("browser_open", url="chrome://policy", max_chars=20000))
        row = out[out.find("PasswordManagerEnabled"):][:200]
        check("Chrome's password manager is off by policy", "false" in row and "OK" in row, row)
        await call("browser_open", url="https://www.google.com/", max_chars=50)
    print("all passed" if not failures else f"{len(failures)} failed: {', '.join(failures)}")


asyncio.run(main())
