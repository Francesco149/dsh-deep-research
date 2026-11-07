"""The laptop queue: one agent at a time on the laptop, for every client on this machine (any agent session and its
subagents through bin/cu-mcp, scripts, tests).

The owner's rule (2026-10-17): an agent marks the laptop busy for the time it asks for (15 minutes by default, at
most 30); the others wait in line, first come first served; when the time is up the laptop goes to the next in line
and the late holder's task fails (its next call says TIME UP).

Plain files under state/laptop/ with an flock, so any process can take part:

  holder.json    {token, owner, purpose, minutes, granted, deadline, pid, deskd}   who is on the laptop now
  tickets/*.json {owner, purpose, minutes, since, seen, pid}                         waiting, oldest first
  expired.jsonl  {token, owner, at, why}: leases taken away (time up, process gone, released)
  events.jsonl   grants, releases, expiries

A waiter keeps its place by asking again (each ask refreshes `seen`); a ticket not asked about for TICKET_TTL
seconds is dropped, as is one whose process is gone. A holder whose process is gone frees the laptop at once.
deskd's own lease (on the laptop, sliding 10 minutes) stays the backstop; its id is kept in holder.json so every
process working under one token (a researcher's MCP session and the harness reading a page for it) shares it.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import pathlib
import secrets
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
DIR = pathlib.Path(os.environ.get("CU_QUEUE_DIR") or pathlib.Path(os.environ.get("CU_STATE") or REPO / "state") / "laptop")
DEFAULT_MINUTES, MAX_MINUTES = 15, 30
TICKET_TTL = 360


class QueueError(RuntimeError):
    pass


class TimeUp(QueueError):
    pass


@contextlib.contextmanager
def _locked():
    (DIR / "tickets").mkdir(parents=True, exist_ok=True)
    with open(DIR / "lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read(p: pathlib.Path):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _write(p: pathlib.Path, data) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def _log(name: str, entry: dict) -> None:
    with (DIR / name).open("a") as f:
        f.write(json.dumps({"t": round(time.time(), 1), **entry}) + "\n")


def _drop_holder(h: dict, why: str) -> None:
    (DIR / "holder.json").unlink(missing_ok=True)
    _log("expired.jsonl", {"token": h["token"], "owner": h["owner"], "at": time.time(), "why": why})
    _log("events.jsonl", {"event": why, "owner": h["owner"], "purpose": h.get("purpose"),
                          "held_min": round((time.time() - h["granted"]) / 60, 1)})


def _tidy(now: float) -> dict | None:
    """Under the lock: the holder (None once its time ran out or its process died), stale tickets dropped."""
    h = _read(DIR / "holder.json")
    if h and now >= h["deadline"]:
        _drop_holder(h, "time-up")
        h = None
    elif h and not _alive(h["pid"]):
        _drop_holder(h, "process-gone")
        h = None
    for t in (DIR / "tickets").glob("*.json"):
        tk = _read(t)
        if not tk or not _alive(tk["pid"]) or now - tk["seen"] > TICKET_TTL:
            t.unlink(missing_ok=True)
    return h


def _tickets() -> list[pathlib.Path]:
    return sorted((DIR / "tickets").glob("*.json"))


def public(h: dict | None) -> dict | None:
    """The holder as others may see it (no token, no deskd lease)."""
    if not h:
        return None
    return {"owner": h["owner"], "purpose": h.get("purpose", ""), "minutes": h["minutes"],
            "granted": h["granted"], "deadline": h["deadline"],
            "left_min": round(max(0.0, h["deadline"] - time.time()) / 60, 1)}


def acquire(owner: str, purpose: str = "", minutes: float = DEFAULT_MINUTES, ticket: str = "", wait: float = 1800,
            pid: int | None = None) -> dict:
    """Waits in line up to `wait` seconds. Returns {"status": "granted", "token", "deadline", ...} or
    {"status": "waiting", "ticket", "position", "holder"}: ask again with the ticket to keep the place."""
    minutes = max(1.0, min(float(minutes or DEFAULT_MINUTES), MAX_MINUTES))
    pid = pid or os.getpid()
    until = time.time() + wait
    while True:
        with _locked():
            now = time.time()
            h = _tidy(now)
            path = DIR / "tickets" / f"{ticket}.json" if ticket else None
            if not path or not path.exists():  # a new ticket (or a dropped one: back in line)
                ticket = f"{time.time_ns()}-{pid}-{secrets.token_hex(3)}"
                path = DIR / "tickets" / f"{ticket}.json"
                _write(path, {"owner": owner, "purpose": purpose, "minutes": minutes, "since": now, "seen": now,
                              "pid": pid})
            else:
                tk = _read(path) or {}
                tk.update(seen=now, minutes=minutes, purpose=purpose or tk.get("purpose", ""))
                _write(path, tk)
            line = _tickets()
            if h is None and line and line[0] == path:
                since = (_read(path) or {}).get("since", now)
                path.unlink()
                h = {"token": secrets.token_urlsafe(18), "owner": owner, "purpose": purpose, "minutes": minutes,
                     "granted": now, "deadline": now + minutes * 60, "pid": pid, "deskd": None}
                _write(DIR / "holder.json", h)
                _log("events.jsonl", {"event": "grant", "owner": owner, "purpose": purpose, "minutes": minutes,
                                      "waited_s": round(now - since)})
                return {"status": "granted", **h}
            position = line.index(path) + 1
        if time.time() >= until:
            return {"status": "waiting", "ticket": ticket, "position": position, "holder": public(h),
                    "waiting": len(line)}
        time.sleep(2)


def check(token: str) -> dict:
    """The holder record when `token` holds the laptop now; TimeUp when its lease was taken away; QueueError when it
    never held it."""
    with _locked():
        h = _tidy(time.time())
        if h and token and h["token"] == token:
            return h
        for line in reversed((DIR / "expired.jsonl").read_text().splitlines() if (DIR / "expired.jsonl").exists() else []):
            e = json.loads(line)
            if e["token"] == token:
                if e["why"] == "released":
                    raise QueueError("that lease was released: laptop_acquire again if you still need the laptop")
                raise TimeUp(f"TIME UP: your laptop time ran out ({e['why']}) and the laptop went to the next in line. "
                             "Your task has failed: stop using the laptop and report that it ran out of time.")
        who = f" (it is with {h['owner']}: {h.get('purpose', '')})" if h else ""
        raise QueueError(f"that is not a current laptop lease{who}: take one with laptop_acquire")


def set_deskd(token: str, deskd_id: str | None) -> None:
    with _locked():
        h = _read(DIR / "holder.json")
        if h and h["token"] == token:
            h["deskd"] = deskd_id
            _write(DIR / "holder.json", h)


def release(token: str) -> bool:
    with _locked():
        h = _read(DIR / "holder.json")
        if not h or h["token"] != token:
            return False
        _drop_holder(h, "released")
        return True


def status() -> dict:
    with _locked():
        h = _tidy(time.time())
        line = [_read(p) or {} for p in _tickets()]
    return {"holder": public(h), "waiting": [{"owner": t.get("owner"), "purpose": t.get("purpose"),
                                              "minutes": t.get("minutes"),
                                              "waited_min": round((time.time() - t.get("since", time.time())) / 60, 1)}
                                             for t in line]}
