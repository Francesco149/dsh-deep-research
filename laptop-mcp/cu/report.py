"""Supervision views over state/: the runs, one run as an HTML timeline, the escalation queue.

bin/cu runs [n]          newest runs: when, who, steps, errors, outcome
bin/cu report <run>      state/runs/<run>/index.html: every tool call and model turn, with screenshots
bin/cu escalations       what needs the owner, grouped by site (sign in, consent, challenge);
                         an entry closes when a later page of its site loads without a check
"""
import collections
import html
import json
import os
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
# Runtime state: the repo's state/ by default, CU_STATE where the server runs as a service (e.g. /var/lib/computer-use)
STATE = pathlib.Path(os.environ.get("CU_STATE") or REPO / "state")
RUNS = STATE / "runs"
ESCALATIONS = STATE / "escalations.jsonl"


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def summary(run):
    actions = read_jsonl(run / "actions.jsonl")
    agent = read_jsonl(run / "agent.jsonl")
    calls = [a for a in actions if a.get("tool")]
    lease = next((a for a in actions if a.get("event") in ("start", "lease")), {})
    finish = next((a for a in agent if a.get("event") == "finish"), None)
    return {"run": run.name, "owner": lease.get("owner", "?"), "purpose": lease.get("purpose", ""),
            "calls": len(calls), "errors": sum(1 for a in calls if a.get("error")),
            "start": actions[0]["t"] if actions else "", "end": actions[-1]["t"] if actions else "",
            "outcome": (finish or {}).get("status") or ("ended" if any(a.get("event") == "end" for a in actions) else "open")}


def runs(n=20):
    dirs = sorted((d for d in RUNS.iterdir() if d.is_dir()), key=lambda d: d.name)[-n:] if RUNS.exists() else []
    for d in dirs:
        s = summary(d)
        print(f"{s['run']:<40} {s['calls']:>4} calls {s['errors']:>3} err  {s['outcome']:<8} {s['purpose'][:70]}")


def open_escalations():
    """Escalations not yet followed by a clean load of the same site (a "resolved" record)."""
    out = []
    for r in read_jsonl(ESCALATIONS):
        if r.get("resolved"):
            out = [o for o in out if o.get("site") != r.get("site")]
        else:
            out.append(r)
    return out


def add_escalation(entry):
    """Appends an escalation unless the same URL is already open. Returns True if added."""
    if entry.get("url") and any(o.get("url") == entry["url"] for o in open_escalations()):
        return False
    ESCALATIONS.parent.mkdir(parents=True, exist_ok=True)
    with ESCALATIONS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return True


def resolve_site(site, t, run):
    """A page of `site` loaded cleanly: its open escalations are done (the owner cleared them, or
    the check went away)."""
    if site and any(o.get("site") == site for o in open_escalations()):
        with ESCALATIONS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": t, "site": site, "resolved": True, "run": run}) + "\n")


def escalations(urls_only=False):
    rows = open_escalations()
    if urls_only:
        for r in rows:
            print(r.get("url", ""))
        return
    if not rows:
        print("nothing waiting for the owner")
        return
    by_site = collections.defaultdict(list)
    for r in rows:
        by_site[r.get("site") or "?"].append(r)
    for site, items in sorted(by_site.items(), key=lambda kv: -len(kv[1])):
        kinds = collections.Counter(i.get("kind", "other") for i in items)
        print(f"{site}: {len(items)}x ({', '.join(f'{k} {v}' for k, v in kinds.most_common())}); last {items[-1]['t']}")
        print(f"    {items[-1].get('reason', '')[:140]}")
    print("\nchallenge: open `bin/cu live`, take control, load the URL in the agent's Chrome and pass the check;")
    print("           the clearance stays in the profile and the next clean load marks the site done.")
    print("login / consent: the same, signing in or answering the consent once.")
    print("`bin/cu escalations --urls` lists the parked URLs.")


CSS = """
:root{--bg:#fbfbfa;--fg:#1d1d1b;--mut:#6b6b66;--line:#e4e3df;--card:#fff;--err:#b3261e;--ok:#2e7d32;--acc:#3557a6}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe8;--mut:#9a9994;--line:#2c2c2a;--card:#1e1e1c;--err:#f2b8b5;--ok:#a5d6a7;--acc:#9db4f0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px}h1{font-size:20px;margin:0 0 4px}.mut{color:var(--mut)}
.step{display:grid;grid-template-columns:56px 1fr;gap:12px;padding:12px 0;border-top:1px solid var(--line)}
.n{font-variant-numeric:tabular-nums;color:var(--mut)}.tool{font-weight:600}.model .tool{color:var(--acc)}
.err .tool{color:var(--err)}pre{white-space:pre-wrap;word-break:break-word;background:var(--card);border:1px solid var(--line);
border-radius:6px;padding:8px;margin:6px 0;max-height:320px;overflow:auto;font:12px/1.4 ui-monospace,monospace}
img{max-width:100%;border:1px solid var(--line);border-radius:6px;margin-top:6px}details summary{cursor:pointer;color:var(--mut)}
.final{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--ok);padding:12px;border-radius:6px;margin:16px 0}
"""


def report(name):
    run = RUNS / name
    s = summary(run)
    events = [("action", a) for a in read_jsonl(run / "actions.jsonl")] + \
             [("model", a) for a in read_jsonl(run / "agent.jsonl")]
    events.sort(key=lambda e: (e[1].get("t", ""), 0 if e[0] == "model" else 1))
    e = html.escape
    out = [f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<title>Run {e(name)}</title><style>{CSS}</style><main><h1>{e(s['purpose'] or name)}</h1>"
           f"<div class=mut>{e(name)} · {e(s['owner'])} · {s['calls']} calls · {s['errors']} errors · {e(s['outcome'])}"
           f" · {e(s['start'])} → {e(s['end'])}</div>"]
    finish = next((a for k, a in events if k == "model" and a.get("event") == "finish"), None)
    if finish:
        out.append(f"<div class=final><b>{e(finish.get('status', ''))}</b><pre>{e(finish.get('answer', ''))}</pre>"
                   + "".join(f"<div><a href='{e(u)}'>{e(u)}</a></div>" for u in finish.get("sources") or []) + "</div>")
    for kind, a in events:
        if kind == "model":
            if "step" not in a:
                continue
            calls = "; ".join(f"{c['name']}({json.dumps(c.get('args', {}), ensure_ascii=False)})" for c in a.get("calls", []))
            out.append(f"<div class='step model'><div class=n>m{a['step']}</div><div><span class=tool>model</span>"
                       f" <span class=mut>{a.get('s')} s · tokens {a.get('tokens')}</span>"
                       + (f"<pre>{e(a['text'])}</pre>" if a.get("text") else "") + f"<pre>{e(calls)}</pre></div></div>")
            continue
        if not a.get("tool"):
            out.append(f"<div class=step><div class=n>{a['n']}</div><div class=mut>{e(a.get('event', ''))} {e(a.get('t', ''))}</div></div>")
            continue
        cls = "step err" if a.get("error") else "step"
        res = a.get("result", "")
        body = f"<pre>{e(res)}</pre>" if len(res) < 600 else f"<details><summary>{len(res)} characters</summary><pre>{e(res)}</pre></details>"
        shot = f"<a href='{a['shot']}'><img loading=lazy src='{a['shot']}'></a>" if a.get("shot") else ""
        out.append(f"<div class='{cls}'><div class=n>{a['n']}</div><div><span class=tool>{e(a['tool'])}</span> "
                   f"<span class=mut>{e(json.dumps(a.get('args'), ensure_ascii=False))} · {a.get('ms')} ms · {e(a['t'])}</span>"
                   f"{body}{shot}</div></div>")
    out.append("</main>")
    path = run / "index.html"
    path.write_text("\n".join(out), encoding="utf-8")
    print(path)
