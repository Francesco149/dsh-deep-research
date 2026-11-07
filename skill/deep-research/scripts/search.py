# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "ddgs>=9.0",  # metasearch (DuckDuckGo, Brave, Bing, Mojeek, ...) without an API key
#   "google-auth>=2.30",  # vertex: the gcloud application-default credentials
#   "requests",
# ]
# ///
"""search QUERY [--max N] [--engine E] [--region R] [--timelimit d|w|m|y]: web search results for research agents.

Engines, tried in this order until one answers (ranked by two blind tests, 2026-11-05: 12 research queries, up to
10 results each, a judge scoring shuffled lists 0-10; docs/SEARCH.md):
  exa         Exa's search API (EXA_API_KEY; free credits, ~$0.007 a search): 8.25 both times, best on 11 of 12
  ddg         DuckDuckGo through ddgs (no key; rate-limited scraping): 7.17 / 7.33
  vertex      Gemini on Vertex AI with Google Search grounding (gcloud application-default credentials; project
              from GOOGLE_CLOUD_PROJECT or gcloud's config; VERTEX_MODEL, default gemini-3.5-flash-lite): 6.42.
              Always answers (~4 s), 4-10 results; titles are bare domains and the snippet is the model's own
              blurb, which can misname a source: trust the URL. Redirect links are resolved to the page's URL
  free        ddgs over its other free backends (brave, bing, mojeek, yahoo): 6.5-7.0 on the 4 of 12 queries it
              answered, throttled on the rest
  langsearch  LangSearch's web search API (LANGSEARCH_API_KEY; free credits): 2.83 / 3.0, off-topic and spun
              spam; last resort
Also available by name, not in the order until evaluated:
  deepseek    DeepSeek's native web search through its Anthropic-compatible endpoint (DEEPSEEK_API_KEY), as
              dsh's own web_search provider does (2026-11-05: the account had no balance)
An engine without its key is skipped; one that errors or returns nothing hands over to the next.
`--engine NAME` uses that engine alone (for comparisons); `--engine all` prints every engine's results.
Keys come from the environment (the dsh service loads ~/.config/dsh/search.env; docs/SEARCH.md).

Output: one block per result (title, URL, date when known, snippet), headed by the engine that answered.
Exit 0 with results, 1 with none, 2 when every engine failed. A result is a lead, never a source: read the
page with the fetch helper before citing it.
"""
import argparse
import json
import os
import sys
import urllib.request

ORDER = ["exa", "ddg", "vertex", "free", "langsearch"]
TIMELIMIT_DAYS = {"d": 1, "w": 7, "m": 31, "y": 365}


def post(url, headers, body, timeout=40):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def since(timelimit):
    if not timelimit:
        return None
    import datetime as dt
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=TIMELIMIT_DAYS[timelimit])).strftime("%Y-%m-%dT%H:%M:%SZ")


def exa(q, n, region, timelimit):
    key = os.environ.get("EXA_API_KEY")
    if not key:
        return None
    body = {"query": q, "numResults": n, "type": "auto",
            "contents": {"highlights": {"numSentences": 3, "highlightsPerUrl": 2}}}
    if timelimit:
        body["startPublishedDate"] = since(timelimit)
    d = post("https://api.exa.ai/search", {"x-api-key": key}, body)
    return [{"title": r.get("title") or "", "url": r.get("url") or "", "date": (r.get("publishedDate") or "")[:10],
             "snippet": " … ".join(h.strip() for h in (r.get("highlights") or []))} for r in d.get("results", [])]


def langsearch(q, n, region, timelimit):
    key = os.environ.get("LANGSEARCH_API_KEY")
    if not key:
        return None
    fresh = {"d": "oneDay", "w": "oneWeek", "m": "oneMonth", "y": "oneYear"}.get(timelimit, "noLimit")
    d = post("https://api.langsearch.com/v1/web-search", {"Authorization": f"Bearer {key}"},
             {"query": q, "count": min(n, 10), "summary": True, "freshness": fresh})
    if d.get("code") not in (200, None):
        raise RuntimeError(f"langsearch code {d.get('code')}: {d.get('msg')}")
    vals = ((d.get("data") or {}).get("webPages") or {}).get("value") or []
    return [{"title": r.get("name") or "", "url": r.get("url") or "", "date": (r.get("datePublished") or "")[:10],
             "snippet": (r.get("snippet") or r.get("summary") or "").strip()[:600]} for r in vals]


def _ddgs(q, n, region, timelimit, backend):
    from ddgs import DDGS
    rs = DDGS().text(q, region=region, safesearch="off", timelimit=timelimit, max_results=n, backend=backend) or []
    return [{"title": r.get("title") or "", "url": r.get("href") or "", "date": "",
             "snippet": (r.get("body") or "").strip()} for r in rs]


def ddg(q, n, region, timelimit):
    return _ddgs(q, n, region, timelimit, "duckduckgo")


def free(q, n, region, timelimit):
    return _ddgs(q, n, region, timelimit, "brave,bing,mojeek,yahoo")


def _gcloud_project():
    p = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if p:
        return p
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read(os.path.expanduser("~/.config/gcloud/configurations/config_default"))
    return cfg.get("core", "project", fallback=None)


def vertex(q, n, region, timelimit):
    try:
        import google.auth
        import google.auth.transport.requests
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    except Exception:
        return None  # no application-default credentials: skipped like a missing key
    project = _gcloud_project()
    if not project:
        return None
    import requests
    from concurrent.futures import ThreadPoolExecutor
    creds.refresh(google.auth.transport.requests.Request())
    model = os.environ.get("VERTEX_MODEL", "gemini-3.5-flash-lite")
    when = {"d": " from the last day", "w": " from the last week", "m": " from the last month",
            "y": " from the last year"}.get(timelimit, "")
    prompt = (f"Search the web for: {q}\nFind up to {n} of the most relevant, authoritative pages{when} "
              "(primary sources first) and say in one line each what they contain.")
    # The model may answer from memory and skip the search (about 1 call in 6): one retry that insists.
    for attempt in range(2):
        text = prompt if attempt == 0 else "Use Google Search now; do not answer from memory. " + prompt
        r = requests.post(
            f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/publishers/google/models/{model}:generateContent",
            headers={"Authorization": f"Bearer {creds.token}", "x-goog-user-project": project},
            json={"contents": [{"role": "user", "parts": [{"text": text}]}], "tools": [{"googleSearch": {}}]},
            timeout=90)
        r.raise_for_status()
        cand = r.json()["candidates"][0]
        gm = cand.get("groundingMetadata", {})
        if gm.get("groundingChunks"):
            break
    chunks = [c.get("web", {}) for c in gm.get("groundingChunks", [])]
    snips = {i: [] for i in range(len(chunks))}
    for sup in gm.get("groundingSupports", []):
        for i in sup.get("groundingChunkIndices", []):
            if i in snips:
                snips[i].append(sup.get("segment", {}).get("text", ""))

    def resolve(uri):  # grounding-api-redirect links -> the page's own URL
        try:
            h = requests.head(uri, allow_redirects=False, timeout=15)
            return h.headers.get("Location") or uri
        except Exception:
            return uri
    with ThreadPoolExecutor(8) as ex:
        urls = list(ex.map(resolve, [c.get("uri", "") for c in chunks]))
    out, seen = [], set()
    for i, (c, u) in enumerate(zip(chunks, urls)):
        if not u or u in seen:
            continue
        seen.add(u)
        out.append({"title": c.get("title") or "", "url": u, "date": "", "snippet": " … ".join(snips[i])[:600]})
    return out[:n]


def deepseek(q, n, region, timelimit):
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return None
    d = post("https://api.deepseek.com/anthropic/v1/messages",
             {"x-api-key": key, "authorization": f"Bearer {key}", "anthropic-version": "2023-06-01"},
             {"model": "deepseek-v4-flash", "max_tokens": 1024, "thinking": {"type": "disabled"},
              "messages": [{"role": "user", "content": [{"type": "text", "text": f"Perform a web search for the query: {q}"}]}],
              "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]}, timeout=90)
    out, seen = [], set()
    for b in d.get("content", []):
        if b.get("type") != "web_search_tool_result":
            continue
        for it in b.get("content") or []:
            u = it.get("url") or ""
            if it.get("type") == "web_search_result" and u and u not in seen:
                seen.add(u)
                out.append({"title": it.get("title") or "", "url": u, "date": (it.get("page_age") or "")[:10], "snippet": ""})
    return out[:n]


ENGINES = {"exa": exa, "langsearch": langsearch, "ddg": ddg, "free": free, "vertex": vertex, "deepseek": deepseek}


def show(engine, results):
    print(f"(engine: {engine})")
    for i, r in enumerate(results, 1):
        date = f"  [{r['date']}]" if r["date"] else ""
        print(f"[{i}] {r['title'].strip()}{date}\n    {r['url']}\n    {' '.join(r['snippet'].split())[:700]}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("query", nargs="+")
    ap.add_argument("--max", type=int, default=10, help="results to return (default 10)")
    ap.add_argument("--engine", default="auto", choices=["auto", "all", *ENGINES])
    ap.add_argument("--region", default="wt-wt", help="ddgs region, e.g. us-en, it-it (default worldwide)")
    ap.add_argument("--timelimit", choices=["d", "w", "m", "y"], help="only results from the last day/week/month/year")
    a = ap.parse_args()
    q = " ".join(a.query)
    names = ORDER if a.engine in ("auto", "all") else [a.engine]
    errors, shown = [], False
    for name in names:
        try:
            res = ENGINES[name](q, a.max, a.region, a.timelimit)
        except Exception as e:  # quota, rate limit, front-end change: hand over to the next engine
            errors.append(f"{name}: {type(e).__name__}: {e}"[:300])
            continue
        if res is None:
            errors.append(f"{name}: no API key")
            continue
        if not res:
            errors.append(f"{name}: no results")
            continue
        show(name, res)
        shown = True
        if a.engine != "all":
            break
    if errors and (not shown or a.engine == "all"):
        print("NOTE: " + "; ".join(errors))
    if shown:
        return 0
    print(f"ERROR: no engine answered for {q!r}")
    return 2 if any("no results" not in e for e in errors) else 1


if __name__ == "__main__":
    sys.exit(main())
