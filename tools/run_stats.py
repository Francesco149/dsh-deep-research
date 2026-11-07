# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib>=3.9", "zstandard>=0.23"]
# ///
"""run_stats.py: what a deep-research run did, from dsh's own session files.

    uv run tools/run_stats.py SESSIONS_DIR [--root SESSION_ID] [--timeline out.png] [--json out.json]

SESSIONS_DIR is one workspace's folder under $DSH_HOME/sessions/ (e.g. ~/.dsh/sessions/--home-me-research--/).
Without --root it picks the newest session whose preset is `deep-research`. Prints one row per subagent
(server, role, duration, tool calls, status) and the totals; --timeline draws the swarm: one row per lane,
each subagent a bar coloured by role. Reads only; touches nothing.
"""
import argparse
import collections
import datetime as dt
import json
import pathlib
import sys

import zstandard

ROLES = {"dr-worker": "worker", "dr-laptop": "laptop pass", "dr-critic": "critic", "dr-writer": "writer"}
# categorical slots 1-4 of the dataviz reference palette (light surface), fixed order
COLORS = {"worker": "#2a78d6", "laptop pass": "#eb6834", "critic": "#1baf7a", "writer": "#6250d6"}


def events(path: pathlib.Path):
    with path.open("rb") as f, zstandard.ZstdDecompressor().stream_reader(f) as r:
        buf = b""
        while chunk := r.read(1 << 20):
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for line in lines:
                if line.strip():
                    yield json.loads(line)
        if buf.strip():
            yield json.loads(buf)


def read_session(d: pathlib.Path) -> dict | None:
    f = d / "session.v4.jsonl.zstd"
    if not f.exists():
        return None
    s = {"id": d.name, "tools": 0, "t0": None, "t1": None, "preset": None, "server": None, "label": None,
         "parent": None, "status": "completed", "tool_names": collections.Counter()}
    for o in events(f):
        t = o.get("type")
        if t == "session":
            s.update(parent=o.get("parentSession"), preset=o.get("agentPreset"), t0=o.get("createdAt"))
        if "time" in o:
            s["t1"] = o["time"]
        if t == "agent-preset/selected":  # the last selection wins (a session can switch preset)
            s["preset"] = (o.get("data") or {}).get("agentPreset")
        elif t == "subagent/descriptor":
            s["server"] = o["data"].get("agentProvider")
            s["label"] = o["data"].get("label")
        elif t == "tool/call":
            s["tools"] += 1
            d_ = o.get("data") or {}
            s["tool_names"][d_.get("name") or d_.get("toolName") or "?"] += 1
        elif t == "turn/end":
            kind = ((o.get("data") or {}).get("reason") or {}).get("kind")
            s["status"] = "completed" if kind == "completed" else (kind or "?")
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sessions")
    ap.add_argument("--root")
    ap.add_argument("--timeline")
    ap.add_argument("--json")
    ap.add_argument("--title", default="")
    a = ap.parse_args()
    root_dir = pathlib.Path(a.sessions).expanduser()
    sess = [s for d in root_dir.iterdir() if d.is_dir() and (s := read_session(d))]
    by_id = {s["id"]: s for s in sess}
    if a.root:
        root = by_id.get(a.root) or by_id.get("session-" + a.root) or sys.exit(f"no session {a.root}")
    else:
        kids_of = collections.Counter(s["parent"].removeprefix("session-") for s in sess if s["parent"])
        roots = [s for s in sess if not s["parent"] and kids_of[s["id"].removeprefix("session-")]]
        cands = [s for s in roots if s["preset"] == "deep-research"] or roots
        cands or sys.exit("no session with subagents here")
        root = max(cands, key=lambda s: s["t0"] or 0)
    rid = root["id"]
    kids = sorted((s for s in sess if s["parent"] and s["parent"].removeprefix("session-") == rid.removeprefix("session-")),
                  key=lambda s: s["t0"])
    if not kids:
        sys.exit(f"{rid}: no subagents found (is it a deep-research orchestrator session?)")
    t0 = root["t0"]
    end = max([root["t1"]] + [k["t1"] for k in kids])
    print(f"run {rid}: {dt.datetime.fromtimestamp(t0 / 1000):%Y-%m-%d %H:%M} -> "
          f"{dt.datetime.fromtimestamp(end / 1000):%H:%M}, {(end - t0) / 3.6e6:.1f} h wall clock")
    print(f"{'server':<10} {'role':<12} {'min':>6} {'calls':>6}  status     task")
    for k in kids:
        print(f"{k['server'] or '?':<10} {ROLES.get(k['preset'], k['preset'] or '?'):<12} "
              f"{(k['t1'] - k['t0']) / 60000:6.1f} {k['tools']:6}  {k['status']:<10} {k['label'] or ''}")
    per_server = collections.Counter(k["server"] for k in kids)
    per_role = collections.Counter(ROLES.get(k["preset"], k["preset"]) for k in kids)
    calls = sum(k["tools"] for k in kids) + root["tools"]
    print(f"\n{len(kids)} subagents ({', '.join(f'{v} {r}' for r, v in per_role.items())}); "
          f"per server: {', '.join(f'{s}: {v}' for s, v in per_server.items())}; "
          f"{calls} tool calls in all ({root['tools']} by the orchestrator); "
          f"{sum(k['status'] != 'completed' for k in kids)} failed")
    summary = {"root": rid, "start_ms": t0, "end_ms": end, "subagents": [
        {k_: v for k_, v in k.items() if k_ != "tool_names"} for k in kids], "orchestrator_tool_calls": root["tools"]}
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(summary, indent=1))
    if a.timeline:
        draw(kids, t0, end, a.timeline, a.title)


def draw(kids, t0, end, out, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    # Lanes: greedy per server, so overlapping subagents on one server get their own row.
    lanes = collections.defaultdict(list)  # server -> [last end per lane]
    rows = []
    for k in kids:
        srv = k["server"] or "?"
        ends = lanes[srv]
        for i, e in enumerate(ends):
            if e <= k["t0"]:
                ends[i] = k["t1"]
                break
        else:
            ends.append(k["t1"])
            i = len(ends) - 1
        rows.append((srv, i, k))
    order = [(srv, i) for srv in lanes for i in range(len(lanes[srv]))]
    y = {key: n for n, key in enumerate(order)}
    ink, muted, grid, surface = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
    fig, ax = plt.subplots(figsize=(12, 0.55 * len(order) + 1.9), dpi=150)
    fig.patch.set_facecolor(surface)
    ax.set_facecolor(surface)
    for srv, i, k in rows:
        role = ROLES.get(k["preset"], "worker")
        x0, w = (k["t0"] - t0) / 3.6e6, (k["t1"] - k["t0"]) / 3.6e6
        ax.barh(y[(srv, i)], w, left=x0, height=0.62, color=COLORS[role], edgecolor=surface, linewidth=1.5,
                hatch="///" if k["status"] != "completed" else None)
    ax.set_yticks(range(len(order)), [f"{srv} · lane {i + 1}" for srv, i in order], color=ink, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, (end - t0) / 3.6e6)
    ax.set_xlabel("hours since the run started", color=muted, fontsize=9)
    ax.tick_params(colors=muted, labelsize=9, length=0)
    ax.grid(axis="x", color=grid, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)
    used = [r for r in COLORS if any(ROLES.get(k["preset"], "worker") == r for k in kids)]
    handles = [Patch(color=COLORS[r], label=r) for r in used]
    if any(k["status"] != "completed" for k in kids):
        handles.append(Patch(facecolor=surface, edgecolor=muted, hatch="///", label="failed"))
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.32 if len(order) < 5 else -0.18),
              ncol=len(handles), frameon=False, fontsize=9, labelcolor=ink)
    if title:
        ax.set_title(title, loc="left", color=ink, fontsize=11, pad=10)
    fig.tight_layout()
    fig.savefig(out, facecolor=surface)
    print(f"timeline: {out}")


if __name__ == "__main__":
    main()
