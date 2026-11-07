# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "trafilatura>=2.0",  # main content of a page as markdown, with title, date, links and tables
#   "pypdf>=5.0",        # text of PDFs
# ]
# ///
"""fetch URL [--offset N] [--max-chars N] [--full-page] [--raw]: a web page as readable markdown, for research agents.

dsh port: the deep-research agents run scripts/fetch with their bash tool (dsh's own web_fetch rejects PDFs and
has no BLOCKED detection). The wrapper runs this file with `uv run --script`, which builds a cached environment
from the inline metadata above (trafilatura for the main content of HTML pages, pypdf for PDFs): no venv to install.

Output: a header (URL after redirects, HTTP status, type, title, date, which characters of how many), a blank line,
then the text. Page through long pages with --offset.

When the page cannot be read here, the first line starts with BLOCKED: and says why (HTTP 401/403/429/451/503, a
bot check, a page that needs JavaScript, a log-in wall, a PDF without extractable text), and the exit code is 3:
the page belongs on the laptop's real browser. A YouTube video's page says so too, and points to the frames helper:
its text tells what the video is about, never what it shows. Network errors and other HTTP errors exit 2.
"""
import argparse
import io
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import trafilatura
from pypdf import PdfReader

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/141.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9"}
MAX_BYTES = 25_000_000
BOT_SIGNS = re.compile(
    r"cf-challenge|cf_chl_|challenge-platform|<title>just a moment|attention required! \| cloudflare|"
    r"verify you are (a )?human|are you a robot|captcha-delivery|px-captcha|perimeterx|datadome|"
    r"/cdn-cgi/challenge|<title>access denied|request unsuccessful\. incapsula|checking your browser", re.I)
LOGIN_SIGNS = re.compile(r"<title>[^<]*(log ?in|sign ?in|accedi)\b[^<]*</title>", re.I)
JS_SIGNS = re.compile(r"enable javascript|requires javascript|javascript is (disabled|required)|<noscript>", re.I)


def ascii_url(url):
    """An address with accents or other non-ASCII characters (wiki.pokemoncentral.it/Leggende_Pokémon_(GCC),
    wikidex.net/wiki/Colección_Legendaria) as urllib needs it: each such character percent-encoded as UTF-8, the host
    in IDNA. An address already encoded stays as it is (2026-11-03: every accented address failed with
    UnicodeEncodeError)."""
    p = urllib.parse.urlsplit(url)
    host = p.netloc
    if not host.isascii():
        userinfo, at, hostport = host.rpartition("@")
        name, colon, port = hostport.partition(":")
        host = userinfo + at + name.encode("idna").decode("ascii") + colon + port
    enc = lambda s: re.sub(r"[^\x21-\x7e]", lambda m: urllib.parse.quote(m.group(0)), s)
    return urllib.parse.urlunsplit((p.scheme, host, enc(p.path), enc(p.query), enc(p.fragment)))


def fetch(url, timeout):
    req = urllib.request.Request(ascii_url(url), headers=HEADERS)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        status = r.status
    except urllib.error.HTTPError as e:
        r, status = e, e.code
    return r.geturl(), status, (r.headers.get("Content-Type") or "").lower(), r.read(MAX_BYTES)


def pdf_text(data):
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for n, page in enumerate(reader.pages, 1):
        try:
            pages.append(f"--- page {n} ---\n{page.extract_text() or ''}")
        except Exception as e:  # one broken page must not lose the rest
            pages.append(f"--- page {n} --- (unreadable: {e})")
    meta = reader.metadata or {}
    return "\n\n".join(pages).strip(), (meta.get("/Title") or ""), ""


def html_text(raw, url, full_page):
    doc = trafilatura.bare_extraction(raw, url=url, output_format="python", include_links=True,
                                      include_tables=True, include_formatting=True, favor_recall=True,
                                      with_metadata=True) if not full_page else None
    if doc is not None:
        d = doc if isinstance(doc, dict) else doc.as_dict()
        text = trafilatura.extract(raw, url=url, output_format="markdown", include_links=True,
                                   include_tables=True, include_formatting=True, favor_recall=True) or ""
        return text, d.get("title") or "", d.get("date") or ""
    text = trafilatura.html2txt(raw) or ""
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    return text, (m.group(1).strip() if m else ""), ""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("url")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--max-chars", type=int, default=20000)
    ap.add_argument("--full-page", action="store_true", help="all the page's text, not just its main content")
    ap.add_argument("--raw", action="store_true", help="the body as it came, no conversion")
    ap.add_argument("--timeout", type=float, default=40)
    a = ap.parse_args()
    url = a.url if re.match(r"https?://", a.url) else "https://" + a.url
    try:
        final, status, ctype, data = fetch(url, a.timeout)
    except Exception as e:
        print(f"ERROR: could not fetch {url}: {type(e).__name__}: {e}")
        return 2

    title, date, blocked = "", "", ""
    if "pdf" in ctype or data[:5] == b"%PDF-":
        kind = "pdf"
        try:
            text, title, date = pdf_text(data)
        except Exception as e:
            text = ""
            blocked = f"a PDF this helper cannot parse ({type(e).__name__}); read it on the laptop: browser_pdf_text"
        if not blocked and len(re.sub(r"--- page \d+ ---|\s", "", text)) < 200:
            blocked = "a PDF without extractable text (scanned?); read it on the laptop: browser_pdf_text"
    elif "html" in ctype or data.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
        kind = "html"
        m_cs = re.search(rb"<meta[^>]+content=[\x27\"][^>]*charset=([a-zA-Z0-9_\-]+)", data[:15000], re.I)
        if not m_cs:
            m_cs = re.search(rb"<meta[^>]+charset=[\x27\"]?([a-zA-Z0-9_\-]+)", data[:15000], re.I)
        if not m_cs:
            m_cs = re.search(rb"charset=[\"']?([a-zA-Z0-9_\-]+)", data[:3000], re.I)
        cs = m_cs.group(1).decode("ascii", errors="ignore").lower() if m_cs else ""
        if cs in ("shift_jis", "sjis", "x-sjis", "windows-31j", "cp932"):
            raw = data.decode("cp932", errors="replace")
        elif cs in ("euc-jp", "x-euc-jp"):
            raw = data.decode("euc_jp", errors="replace")
        elif cs in ("iso-8859-1", "windows-1252", "cp1252"):
            raw = data.decode("cp1252", errors="replace")
        else:
            raw = data.decode("utf-8", errors="replace")
        text, title, date = (raw, "", "") if a.raw else html_text(raw, final, a.full_page)
        if BOT_SIGNS.search(raw[:300000]):
            blocked = "a bot check or access-denied page"
        elif LOGIN_SIGNS.search(raw[:30000]) and len(text) < 3000:
            blocked = "a log-in wall"
        elif len(text.strip()) < 300 and (JS_SIGNS.search(raw) or len(raw) > 5000):
            blocked = "a page that needs JavaScript (almost no text without it)"
    else:
        kind = ctype.split(";")[0] or "text"
        text = data.decode("utf-8", errors="replace")

    if status in (401, 403, 407, 429, 451, 503) and not blocked:
        blocked = f"HTTP {status}"
    elif status >= 400 and not blocked:
        print(f"ERROR: HTTP {status} for {final}")
        return 2

    chunk = text[a.offset:a.offset + a.max_chars]
    youtube = re.match(r"https?://(www\.|m\.)?(youtube\.com/(watch|shorts/|live/)|youtu\.be/)", final)
    if youtube:  # its page text says what the video is about, never what it shows
        blocked = blocked and ("a YouTube video, whose page needs JavaScript: look at it with the frames helper (it "
                               "also prints the title, channel, length and chapters); the laptop only for what its "
                               "frames cannot show")
    if blocked:
        print(f"BLOCKED: {blocked} ({final})")
    elif youtube:
        print("NOTE: a YouTube video: below is its page text, which says what the video is about, not what it "
              "shows; to see it, use the frames helper.")
    elif kind == "html" and len(text) < 2000 and len(data) > 100_000:
        print(f"NOTE: only {len(text)} characters of text from a {len(data) // 1000} kB page: the content may need "
              "JavaScript; if what you need is not below, list the page for the laptop.")
    print(f"URL: {final}\nHTTP: {status}  Type: {kind}" + (f"\nTitle: {title}" if title else "") +
          (f"\nDate: {date}" if date else "") + f"\nCharacters {a.offset}-{a.offset + len(chunk)} of {len(text)}\n")
    print(chunk)
    nxt = a.offset + len(chunk)
    print(f"\n[next: --offset {nxt}]" if nxt < len(text) else "\n[end]")
    return 3 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
