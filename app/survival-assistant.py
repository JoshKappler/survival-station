#!/usr/bin/env python3
"""
Survival Hub - the offline integrated front-end for the Survival Station.

ONE app, served on http://127.0.0.1:8080, that ties the whole station together
behind a persistent navigation bar (Home / Back / Forward / Search), so you can
always get back to the home screen. It serves:

  /                 the shell: a fixed top bar over a full-window content frame
  /home             the home screen (big friendly tiles)
  /assistant        the offline AI helper (chat, powered by local Ollama)
  /search?q=...     ONE search box across the whole station:
                      - the library (PDFs, books, references)  [SQLite FTS5]
                      - the encyclopedias & wikis              [live Kiwix]
  /food             the Food & Foraging section
  /guides/<name>    authored how-to guides (hunting, fishing, butchering, ...)
  /library/<path>   the reference library files (PDFs/HTML), shown in the shell
  /read/<book.epub> a simple built-in reader for the Project Gutenberg books
  /docs/<path>      the user guide / quick cards
  /api/models       list local Ollama models
  /api/chat         stream a chat answer from Ollama
  /api/guides       grounded references from Kiwix (used by the assistant)
  /api/stop         stop the station (used by the on-screen Shut Down button)
  /healthz          health check

Pure Python standard library only (no pip packages) so it runs reliably on this
locked-down, fully-offline machine. The Encyclopedia (Kiwix, :8081) and Maps
(:8082) run as their own local servers and are shown inside the content frame.
Everything stays on this computer; no internet is used.
"""

import json
import os
import re
import sys
import html
import sqlite3
import zipfile
import mimetypes
import posixpath
import subprocess
import urllib.request
import urllib.error
import urllib.parse
import http.server
import socketserver
from html.parser import HTMLParser
from http import HTTPStatus

# ----------------------------------------------------------------------------
# Configuration (overridable via environment, but sane offline defaults)
# ----------------------------------------------------------------------------
HOST = os.environ.get("ASSISTANT_HOST", "127.0.0.1")
PORT = int(os.environ.get("ASSISTANT_PORT", "8080"))
OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")

# Single good text model (image recognition retired to save space).
DEFAULT_MODEL = os.environ.get("ASSISTANT_DEFAULT_MODEL", "llama3.1:8b")

# Filesystem roots.
ROOT = r"C:\Survival"
APP_DIR = os.path.join(ROOT, "app")
GUIDES_DIR = os.path.join(APP_DIR, "guides")
LIBRARY_DIR = os.path.join(ROOT, "library")
DOCS_DIR = os.path.join(ROOT, "docs")
INDEX_DB = os.path.join(APP_DIR, "search-index.db")

# How long to wait on Ollama (CPU inference can be slow).
OLLAMA_TIMEOUT = int(os.environ.get("ASSISTANT_OLLAMA_TIMEOUT", "1800"))  # seconds

# Where the BROWSER reaches the Encyclopedia (Kiwix) and Maps (shown in-frame).
KIWIX_PUBLIC_BASE = os.environ.get("KIWIX_PUBLIC_BASE_URL", "http://localhost:8081").rstrip("/")
MAPS_PUBLIC_BASE = os.environ.get("MAPS_PUBLIC_BASE_URL", "http://localhost:8082").rstrip("/")

# Where THIS server reaches Kiwix to fetch grounded references / search results.
KIWIX_BASE = os.environ.get("KIWIX_BASE_URL", "http://127.0.0.1:8081").rstrip("/")
KIWIX_TIMEOUT = float(os.environ.get("ASSISTANT_KIWIX_TIMEOUT", "4"))  # seconds
KIWIX_RESULTS = int(os.environ.get("ASSISTANT_KIWIX_RESULTS", "8"))

mimetypes.add_type("application/epub+zip", ".epub")
mimetypes.add_type("text/markdown", ".md")

# The required global default system prompt (safety-first; text-only now).
SYSTEM_PROMPT = (
    "You are 'Survival Helper', a calm, practical, friendly assistant on an "
    "OFFLINE emergency computer. The person may be stressed, tired, or not "
    "technical - explain simply, step by step, in plain language, and be "
    "reassuring. SAFETY FIRST: for eating wild plants/mushrooms, medical "
    "treatment, water safety, or dangerous tasks, ALWAYS give clear safety "
    "warnings and state your uncertainty. NEVER call a plant or mushroom safe "
    "to eat from a description alone - explain that misidentification can be "
    "deadly, tell them how to cross-check with the offline guides, and describe "
    "the Universal Edibility Test when relevant. For medical issues give clear "
    "first-aid steps and say when something is beyond home care. You have NO "
    "internet; if unsure, say so and suggest which offline resource (the "
    "Encyclopedia, the Medical books, the Food & Foraging guides, or the "
    "Manuals) might help. Point people to the Search box for finding things. "
    "Keep answers focused. Above all, keep the person safe, calm, and alive."
)

# ============================================================================
#  Shared look & feel
# ============================================================================
BASE_CSS = """
:root{
  --bg1:#1f3b30; --bg2:#2c5446; --card:#ffffff; --ink:#1c2b25; --ink-soft:#3f5249;
  --accent:#b5651d; --line:#d9e2dc; --chip:#eef4f0;
  --safe-bg:#fff6e6; --safe-bd:#e0a32e; --safe-ink:#5a3d12;
}
*{box-sizing:border-box;}
html,body{margin:0;padding:0;}
body{font-family:"Segoe UI",Arial,Helvetica,sans-serif;color:var(--ink);background:#f4efe7;}
a{color:#0a5; text-decoration:none;}
"""

# The persistent shell: fixed top bar + a content iframe that fills the rest.
SHELL_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Survival Station</title>
<style>
  html,body{height:100%;margin:0;}
  body{display:flex;flex-direction:column;background:#13241d;font-family:"Segoe UI",Arial,sans-serif;}
  #bar{
    flex:0 0 auto;display:flex;align-items:center;gap:10px;
    background:linear-gradient(180deg,#2c5446,#22443a);
    border-bottom:3px solid #16302a;padding:8px 12px;color:#fff;
    box-shadow:0 3px 10px rgba(0,0,0,.35);
  }
  #bar button, #bar a.btn{
    font:inherit;font-size:17px;font-weight:600;cursor:pointer;
    background:#3c6d5c;color:#fff;border:1px solid #1d3c33;border-radius:10px;
    padding:9px 13px;line-height:1;display:inline-flex;align-items:center;gap:7px;
    text-decoration:none;white-space:nowrap;
  }
  #bar button:hover,#bar a.btn:hover{background:#4a8270;}
  #bar button:active{transform:translateY(1px);}
  #home{background:#b5651d;border-color:#7d440f;font-size:18px;}
  #home:hover{background:#cf7626;}
  .nav{background:#274a3f;font-size:20px;padding:9px 12px;}
  #spacer{flex:0 0 6px;}
  form#searchform{flex:1 1 auto;display:flex;gap:0;max-width:680px;}
  form#searchform input{
    flex:1 1 auto;font-size:17px;padding:11px 14px;border:2px solid #16302a;
    border-right:none;border-radius:12px 0 0 12px;outline:none;min-width:120px;
  }
  form#searchform button{border-radius:0 12px 12px 0;background:#1f7a52;font-size:18px;}
  form#searchform button:hover{background:#27955f;}
  .chips{display:flex;gap:7px;flex-wrap:nowrap;overflow:hidden;}
  .chip{background:#274a3f;border:1px solid #1d3c33;color:#eaf3ee;border-radius:999px;
    padding:8px 13px;font-size:15px;cursor:pointer;white-space:nowrap;}
  .chip:hover{background:#356152;}
  #shut{margin-left:auto;background:#7a2e1c;border-color:#511a0e;}
  #shut:hover{background:#9a3a24;}
  #frameWrap{flex:1 1 auto;position:relative;}
  #content{position:absolute;inset:0;width:100%;height:100%;border:0;background:#f4efe7;}
  @media (max-width:1024px){ .chips .opt{display:none;} }
</style>
</head>
<body>
  <div id="bar">
    <button id="home" title="Go to the home screen">&#127957; Home</button>
    <button class="nav" id="back" title="Go back">&#9664;</button>
    <button class="nav" id="fwd" title="Go forward">&#9654;</button>
    <span id="spacer"></span>
    <form id="searchform" autocomplete="off">
      <input id="q" name="q" type="search" placeholder="Search everything: first aid, water, snares, solar...">
      <button type="submit" title="Search">&#128269; Search</button>
    </form>
    <div class="chips">
      <span class="chip" data-go="/assistant">&#128172; Ask AI</span>
      <span class="chip" data-go="ENCY">&#128214; Encyclopedia</span>
      <span class="chip opt" data-go="/food">&#127807; Food</span>
      <span class="chip opt" data-go="/library/index.html#medical">&#9877; Medical</span>
      <span class="chip opt" data-go="MAPS">&#128506; Maps</span>
      <span class="chip opt" data-go="/library/index.html">&#128218; Library</span>
    </div>
    <button id="shut" title="Stop the Survival Station">&#9211; Shut Down</button>
  </div>
  <div id="frameWrap"><iframe id="content" name="content" src="/home"></iframe></div>

<script>
"use strict";
var ENCY = %ENCY_JSON%, MAPS = %MAPS_JSON%;
var content = document.getElementById("content");
function go(url){
  if(url === "ENCY") url = ENCY;
  else if(url === "MAPS") url = MAPS;
  content.src = url;             // programmatic nav -> a top-level history entry
}
document.getElementById("home").addEventListener("click", function(){ go("/home"); });
document.getElementById("back").addEventListener("click", function(){ history.back(); });
document.getElementById("fwd").addEventListener("click", function(){ history.forward(); });
document.querySelectorAll(".chip").forEach(function(c){
  c.addEventListener("click", function(){ go(c.getAttribute("data-go")); });
});
document.getElementById("searchform").addEventListener("submit", function(e){
  e.preventDefault();
  var q = document.getElementById("q").value.trim();
  if(q) go("/search?q=" + encodeURIComponent(q));
});
document.getElementById("shut").addEventListener("click", function(){
  if(!confirm("Stop the Survival Station?\n\nThis closes the helpers (Assistant, Encyclopedia, Maps). To use it again, double-click the green 'Survival Station - START HERE' icon.")) return;
  fetch("/api/stop", {method:"POST"}).catch(function(){});
  document.open();
  document.write("<body style='font-family:Segoe UI,Arial;background:#1f3b30;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center'><div><div style='font-size:64px'>&#127957;</div><h1>Survival Station is shutting down.</h1><p style='font-size:20px'>You can close this window. To start again, double-click<br><b>&#127957; Survival Station - START HERE</b>.</p></div></body>");
  setTimeout(function(){ try{ window.close(); }catch(e){} }, 1500);
});
// Keep the search box in sync if the user navigates via the home tiles.
window.addEventListener("keydown", function(e){
  if(e.key === "/" && document.activeElement !== document.getElementById("q")){
    // quick focus search with "/" (harmless if typing in the frame)
  }
});
</script>
</body>
</html>
"""

# Home screen (loaded inside the content frame). Links navigate the frame, so
# the top bar always stays put.
HOME_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Survival Station - Home</title>
<style>
""" + BASE_CSS + r"""
  body{background:linear-gradient(160deg,var(--bg1),var(--bg2));min-height:100%;padding:26px 18px 50px;}
  .wrap{max-width:1180px;margin:0 auto;}
  header{text-align:center;color:#fff;margin-bottom:14px;}
  header .logo{font-size:54px;line-height:1;}
  header h1{font-size:40px;margin:4px 0 4px;font-weight:800;text-shadow:0 2px 6px rgba(0,0,0,.35);}
  header p.tag{font-size:20px;margin:0;color:#e9f3ee;}
  .hero{max-width:760px;margin:16px auto 6px;display:flex;}
  .hero input{flex:1 1 auto;font-size:19px;padding:14px 16px;border:0;border-radius:14px 0 0 14px;outline:none;}
  .hero button{border:0;border-radius:0 14px 14px 0;background:var(--accent);color:#fff;font-size:19px;font-weight:700;padding:0 22px;cursor:pointer;}
  .hero button:hover{background:#cf7626;}
  .hint{text-align:center;color:#cfe0d8;font-size:14px;margin:8px 0 20px;}
  .safety{background:var(--safe-bg);border:3px solid var(--safe-bd);border-radius:16px;padding:14px 20px;
    margin:0 auto 22px;max-width:980px;display:flex;gap:14px;align-items:flex-start;color:var(--safe-ink);font-size:18px;font-weight:600;}
  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:20px;}
  @media (max-width:760px){.grid{grid-template-columns:1fr;}}
  a.tile{display:flex;align-items:center;gap:20px;background:var(--card);color:var(--ink);border-radius:18px;
    padding:24px 26px;box-shadow:0 6px 16px rgba(0,0,0,.22);border:2px solid rgba(0,0,0,.05);min-height:104px;
    transition:transform .08s,box-shadow .08s;}
  a.tile:hover{transform:translateY(-3px);box-shadow:0 12px 26px rgba(0,0,0,.32);background:#fffdf8;}
  a.tile .emoji{font-size:52px;width:64px;text-align:center;flex:0 0 auto;}
  a.tile .t{font-size:27px;font-weight:800;line-height:1.1;}
  a.tile .s{font-size:16px;color:var(--ink-soft);margin-top:5px;}
  a.assist{border-left:10px solid #2e7d6b;} a.ency{border-left:10px solid #3a6ea5;}
  a.med{border-left:10px solid #c0392b;} a.food{border-left:10px solid #4a8a3c;}
  a.maps{border-left:10px solid #8a6d3b;} a.lib{border-left:10px solid #6a4fb0;}
  a.tech{border-left:10px solid #b5651d;} a.help{border-left:10px solid #555f5a;}
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="logo">&#127957;</div>
      <h1>Survival Station</h1>
      <p class="tag">Everything you need works right here &mdash; no internet required.</p>
    </header>
    <form class="hero" action="/search" method="get">
      <input name="q" type="search" placeholder="Search everything &mdash; type a question or a thing...">
      <button type="submit">&#128269; Search</button>
    </form>
    <div class="hint">One search looks through the encyclopedias, the wikis, AND all the books &amp; manuals.</div>
    <div class="safety"><div style="font-size:34px">&#128161;</div>
      <div>This works with <b>no internet</b>. For foraging or medical choices, <b>never trust one source or the AI alone</b> &mdash; check the guides, and when unsure, <b>don&rsquo;t</b>.</div></div>
    <div class="grid">
      <a class="tile assist" href="/assistant"><div class="emoji">&#128172;</div><div><div class="t">Ask the Survival Assistant</div><div class="s">Type a question, get help in plain words</div></div></a>
      <a class="tile ency" href="ENCY_HREF"><div class="emoji">&#128214;</div><div><div class="t">Encyclopedia</div><div class="s">Wikipedia &amp; more &mdash; look up almost anything</div></div></a>
      <a class="tile med" href="/library/index.html#medical"><div class="emoji">&#9877;</div><div><div class="t">Medical &amp; First Aid</div><div class="s">Treating injuries, illness and emergencies</div></div></a>
      <a class="tile food" href="/food"><div class="emoji">&#127807;</div><div><div class="t">Food &amp; Foraging</div><div class="s">Hunting, fishing, butchering, farming, foraging</div></div></a>
      <a class="tile maps" href="MAPS_HREF"><div class="emoji">&#128506;</div><div><div class="t">Maps</div><div class="s">See where you are and what&rsquo;s nearby</div></div></a>
      <a class="tile lib" href="/library/index.html"><div class="emoji">&#128218;</div><div><div class="t">Library &amp; Manuals</div><div class="s">Books, how-to guides and reference</div></div></a>
      <a class="tile tech" href="/library/index.html#tech-power"><div class="emoji">&#128295;</div><div><div class="t">Repair, Power &amp; Radio</div><div class="s">Fixing things, electricity &amp; getting on the air</div></div></a>
      <a class="tile help" href="/docs/user-guide.html"><div class="emoji">&#10067;</div><div><div class="t">How to use this computer</div><div class="s">Simple step-by-step guide &mdash; start here if unsure</div></div></a>
    </div>
  </div>
</body>
</html>
"""


def page_wrap(title, body_html, accent="#2c5446"):
    """Wrap dynamic content (search results, errors) in the station's style."""
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>" + html.escape(title) + "</title><style>" + BASE_CSS +
        "body{background:#f4efe7;padding:0;}"
        ".top{background:" + accent + ";color:#fff;padding:18px 22px;}"
        ".top h1{margin:0;font-size:27px;} .top p{margin:6px 0 0;color:#dceae3;font-size:16px;}"
        ".wrap{max-width:1000px;margin:0 auto;padding:18px 22px 60px;}"
        "</style></head><body>" + body_html + "</body></html>"
    )


# ============================================================================
#  Kiwix helpers (friendly source labels + parse search-result HTML)
# ============================================================================
def friendly_source(slug):
    s = (slug or "").lower()
    if ".stackexchange.com" in s:
        site = s.split(".stackexchange.com", 1)[0].split("/")[-1]
        site = re.sub(r"[_-]", " ", site).strip()
        return "Q&A: " + (site.title() if site else "Stack Exchange")
    if s.startswith("wikipedia_en_medicine"):
        return "Medical Encyclopedia"
    if s.startswith("mdwiki"):
        return "Clinical Medicine"
    if s.startswith("zimgit"):
        return "Prepper Pack"
    if s.startswith("wikipedia"):
        return "Wikipedia"
    if s.startswith("wikibooks"):
        return "Wikibooks (how-to)"
    if s.startswith("ifixit"):
        return "iFixit (repair)"
    if s.startswith("gutenberg"):
        return "Gutenberg Books"
    if s.startswith("energypedia"):
        return "Energy"
    if s.startswith("appropedia"):
        return "Appropriate Tech"
    if s.startswith("wikivoyage"):
        return "Geography/Travel"
    if s.startswith("wikiversity"):
        return "Learning"
    if s.startswith("vikidia"):
        return "Vikidia (simple)"
    cleaned = re.sub(r"_\d{4}-\d{2}.*$", "", s)
    cleaned = re.sub(r"_(en|all|maxi|nopic|mini)\b", " ", cleaned)
    cleaned = re.sub(r"[\s_-]+", " ", cleaned).strip()
    return cleaned.title() if cleaned else (slug or "Guide")


class _KiwixResultsParser(HTMLParser):
    """Parse a Kiwix /search results page (stdlib only)."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._in_results = False
        self._depth = 0
        self._cur = None
        self._capture = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "div" and a.get("class") == "results":
            self._in_results = True
            self._depth = 1
            return
        if not self._in_results:
            return
        if tag == "div":
            self._depth += 1
        if tag == "a":
            href = a.get("href", "")
            if href.startswith("/content/"):
                self._cur = {"href": href, "title": "", "snippet": ""}
                self._capture = "title"
        elif tag == "cite" and self._cur is not None:
            self._capture = "snippet"

    def handle_endtag(self, tag):
        if not self._in_results:
            return
        if tag == "a" and self._capture == "title":
            self._capture = None
        elif tag == "cite" and self._capture == "snippet":
            self._capture = None
        elif tag == "li" and self._cur is not None:
            self._cur["title"] = re.sub(r"\s+", " ", self._cur["title"]).strip()
            self._cur["snippet"] = re.sub(r"\s+", " ", self._cur["snippet"]).strip()
            if self._cur["href"] and self._cur["title"]:
                self.results.append(self._cur)
            self._cur = None
            self._capture = None
        elif tag == "div":
            self._depth -= 1
            if self._depth <= 0:
                self._in_results = False

    def handle_data(self, data):
        if self._capture == "title" and self._cur is not None:
            self._cur["title"] += data
        elif self._capture == "snippet" and self._cur is not None:
            self._cur["snippet"] += data


def kiwix_search(query, limit=KIWIX_RESULTS):
    """Search the offline Kiwix library. FAIL-OPEN: returns [] on any problem."""
    q = (query or "").strip()
    if not q:
        return []
    try:
        params = urllib.parse.urlencode({"pattern": q, "pageLength": limit})
        url = KIWIX_BASE + "/search?" + params
        req = urllib.request.Request(url, headers={"Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=KIWIX_TIMEOUT) as r:
            text = r.read().decode("utf-8", "replace")
        parser = _KiwixResultsParser()
        parser.feed(text)
        out = []
        for item in parser.results[:limit]:
            href = item["href"]
            m = re.match(r"^/content/([^/]+)/", href)
            slug = urllib.parse.unquote(m.group(1)) if m else ""
            snippet = item["snippet"]
            if len(snippet) > 280:
                snippet = snippet[:277].rstrip() + "..."
            out.append({
                "title": item["title"],
                "url": KIWIX_PUBLIC_BASE + href,
                "snippet": snippet,
                "source": friendly_source(slug),
            })
        return out
    except Exception:
        return []


# ============================================================================
#  Library full-text search (SQLite FTS5, built offline by build-search-index.py)
# ============================================================================
def _fts_match_expr(q):
    """Turn free text into a safe FTS5 MATCH expression (prefix, implicit AND)."""
    terms = re.findall(r"[0-9A-Za-z']+", q or "")
    terms = [t for t in terms if len(t) >= 2][:10]
    if not terms:
        return None
    return " ".join('"%s"*' % t.replace('"', '') for t in terms)


def library_search(query, limit=20):
    """Full-text search of the library index. FAIL-OPEN: [] if index missing."""
    expr = _fts_match_expr(query)
    if not expr or not os.path.exists(INDEX_DB):
        return []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % INDEX_DB.replace("\\", "/"), uri=True, timeout=2.0)
        try:
            cur = con.execute(
                "SELECT title, source, loc, path, kind, "
                "snippet(docs, 2, '<b>', '</b>', '...', 14) AS snip "
                "FROM docs WHERE docs MATCH ? ORDER BY bm25(docs, 8.0, 4.0, 1.0) LIMIT ?",
                (expr, max(limit * 6, 60)),
            )
            rows = cur.fetchall()
        finally:
            con.close()
    except Exception:
        return []
    # Keep at most 2 hits per document so one big PDF can't crowd out other
    # sources -- the goal is to surface variety, then let the user click in.
    out = []
    per_file = {}
    for title, source, loc, path, kind, snip in rows:
        base = (path or "").split("#", 1)[0]
        if per_file.get(base, 0) >= 2:
            continue
        per_file[base] = per_file.get(base, 0) + 1
        out.append({
            "title": title or "(untitled)",
            "source": source or "Library",
            "loc": loc or "",
            "url": path,
            "kind": kind or "",
            "snippet": re.sub(r"\s+", " ", snip or "").strip(),
        })
        if len(out) >= limit:
            break
    return out


def render_search_page(query):
    q = (query or "").strip()
    if not q:
        body = ("<div class='top'><h1>&#128269; Search</h1><p>Type something in the search box above.</p></div>"
                "<div class='wrap'><p style='font-size:18px;color:#444'>Try: <b>water purification</b>, "
                "<b>snare rabbit</b>, <b>treat a burn</b>, <b>canning tomatoes</b>, <b>solar battery</b>.</p></div>")
        return page_wrap("Search", body)

    lib = library_search(q, 20)
    zim = kiwix_search(q, KIWIX_RESULTS)

    def esc(x):
        return html.escape(x or "")

    parts = ["<div class='top'><h1>&#128269; Results for &ldquo;", esc(q),
             "&rdquo;</h1><p>", str(len(lib)), " from your books &amp; manuals &middot; ",
             str(len(zim)), " from the encyclopedias &amp; wikis</p></div><div class='wrap'>"]

    parts.append("<style>"
                 ".grp{margin:18px 0 6px;font-size:20px;color:#2c5446;border-bottom:2px solid #d9c9a3;padding-bottom:6px;}"
                 ".hit{background:#fff;border:1px solid #e1d8c6;border-radius:10px;padding:13px 16px;margin:12px 0;}"
                 ".hit a.t{font-size:20px;font-weight:700;color:#0a3d62;}"
                 ".badge{display:inline-block;font-size:12px;color:#234;background:#e7eef5;border:1px solid #cdd9e6;"
                 "border-radius:999px;padding:1px 9px;margin-left:8px;vertical-align:middle;}"
                 ".loc{color:#777;font-size:13px;margin-left:6px;}"
                 ".snip{color:#444;font-size:15px;margin-top:5px;line-height:1.45;}"
                 ".snip b{background:#fff2b0;}"
                 ".none{color:#666;font-size:16px;margin:8px 0 18px;}"
                 "</style>")

    parts.append("<div class='grp'>&#128218; From your books &amp; manuals</div>")
    if lib:
        for h in lib:
            loc = (" <span class='loc'>" + esc(h["loc"]) + "</span>") if h["loc"] else ""
            parts.append("<div class='hit'><a class='t' href='" + esc(h["url"]) + "'>" + esc(h["title"]) +
                         "</a><span class='badge'>" + esc(h["source"]) + "</span>" + loc +
                         ("<div class='snip'>" + h["snippet"] + "</div>" if h["snippet"] else "") + "</div>")
    else:
        if os.path.exists(INDEX_DB):
            parts.append("<div class='none'>No matches in the library files for this search.</div>")
        else:
            parts.append("<div class='none'>The library search index hasn't been built yet. "
                         "(Run &ldquo;Rebuild Search Index&rdquo;.) Encyclopedia results still work below.</div>")

    parts.append("<div class='grp'>&#128214; From the encyclopedias &amp; wikis</div>")
    if zim:
        for h in zim:
            parts.append("<div class='hit'><a class='t' href='" + esc(h["url"]) + "'>" + esc(h["title"]) +
                         "</a><span class='badge'>" + esc(h["source"]) + "</span>" +
                         ("<div class='snip'>" + esc(h["snippet"]) + "</div>" if h["snippet"] else "") + "</div>")
    else:
        parts.append("<div class='none'>No encyclopedia matches (or the Encyclopedia is still starting up).</div>")

    parts.append("<p style='margin-top:26px'><a href='/assistant' style='font-size:17px'>&#128172; "
                 "Ask the Survival Assistant about &ldquo;" + esc(q) + "&rdquo; instead &rarr;</a></p>")
    parts.append("</div>")
    return page_wrap("Search: " + q, "".join(parts))


# ============================================================================
#  Minimal EPUB reader (for the Project Gutenberg books in library\books)
# ============================================================================
def _safe_join(base, relpath):
    rel = urllib.parse.unquote(relpath)
    rel = rel.replace("\\", "/").lstrip("/")
    full = os.path.normpath(os.path.join(base, rel))
    base_n = os.path.normpath(base)
    if not (full == base_n or full.startswith(base_n + os.sep)):
        return None
    return full


def read_epub(relpath):
    """Render an EPUB as one clean scrollable HTML page. Returns html str or None."""
    full = _safe_join(LIBRARY_DIR, relpath)
    if not full or not os.path.exists(full) or not full.lower().endswith(".epub"):
        return None
    try:
        zf = zipfile.ZipFile(full)
    except Exception:
        return None
    try:
        names = zf.namelist()
        # Find the OPF via META-INF/container.xml
        opf_path = None
        try:
            cont = zf.read("META-INF/container.xml").decode("utf-8", "replace")
            m = re.search(r'full-path="([^"]+)"', cont)
            if m:
                opf_path = m.group(1)
        except Exception:
            opf_path = None
        if not opf_path:
            opf_path = next((n for n in names if n.lower().endswith(".opf")), None)
        if not opf_path:
            return None
        opf_dir = posixpath.dirname(opf_path)
        opf = zf.read(opf_path).decode("utf-8", "replace")

        # manifest id -> href
        manifest = {}
        for mm in re.finditer(r'<item\b[^>]*>', opf):
            tag = mm.group(0)
            idm = re.search(r'id="([^"]+)"', tag)
            hrefm = re.search(r'href="([^"]+)"', tag)
            if idm and hrefm:
                manifest[idm.group(1)] = urllib.parse.unquote(hrefm.group(1))
        # spine order
        spine = [s.group(1) for s in re.finditer(r'<itemref\b[^>]*idref="([^"]+)"', opf)]
        hrefs = [manifest[i] for i in spine if i in manifest] or list(manifest.values())

        title = re.search(r'<dc:title[^>]*>(.*?)</dc:title>', opf, re.S)
        book_title = html.unescape(re.sub(r"\s+", " ", title.group(1)).strip()) if title else os.path.basename(full)

        def res_url(href):
            p = posixpath.normpath(posixpath.join(opf_dir, href)) if opf_dir else href
            return "/read-asset/" + urllib.parse.quote(relpath) + "/" + urllib.parse.quote(p)

        chapters = []
        for href in hrefs:
            chap = posixpath.normpath(posixpath.join(opf_dir, href)) if opf_dir else href
            try:
                raw = zf.read(chap).decode("utf-8", "replace")
            except Exception:
                continue
            bm = re.search(r"<body[^>]*>(.*)</body>", raw, re.S | re.I)
            inner = bm.group(1) if bm else raw
            inner = re.sub(r"<script\b.*?</script>", "", inner, flags=re.S | re.I)
            inner = re.sub(r"<link\b[^>]*>", "", inner, flags=re.I)
            chap_dir = posixpath.dirname(chap)

            def fix(mo):
                attr, url = mo.group(1), mo.group(2)
                if re.match(r"^(https?:|data:|#|mailto:)", url):
                    return mo.group(0)
                p = posixpath.normpath(posixpath.join(chap_dir, urllib.parse.unquote(url)))
                return '%s="/read-asset/%s/%s"' % (attr, urllib.parse.quote(relpath), urllib.parse.quote(p))

            inner = re.sub(r'(src|href)="([^"]+)"', fix, inner)
            chapters.append(inner)

        reader_css = (
            "body{background:#f4efe7;margin:0;}"
            ".rd{max-width:760px;margin:0 auto;padding:26px 26px 80px;font-family:Georgia,'Times New Roman',serif;"
            "font-size:20px;line-height:1.6;color:#1a1a1a;}"
            ".rd img{max-width:100%;height:auto;}"
            ".rdhead{position:sticky;top:0;background:#7a2d00;color:#fff;padding:12px 18px;font-size:18px;}"
            ".rdhead a{color:#ffe;}"
            "hr.chap{border:0;border-top:1px dashed #bbb;margin:30px 0;}"
        )
        out = ["<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
               "<meta name='viewport' content='width=device-width, initial-scale=1'>",
               "<title>", html.escape(book_title), "</title><style>", reader_css, "</style></head><body>",
               "<div class='rdhead'>&#128214; ", html.escape(book_title),
               " &nbsp;&middot;&nbsp; <a href='/library/books/index.html'>All books</a></div><div class='rd'>"]
        out.append("<hr class='chap'>".join(chapters))
        out.append("</div></body></html>")
        return "".join(out)
    finally:
        zf.close()


def read_epub_asset(relpath, res):
    """Return (bytes, content_type) for a resource inside an EPUB, or None."""
    full = _safe_join(LIBRARY_DIR, relpath)
    if not full or not os.path.exists(full):
        return None
    try:
        zf = zipfile.ZipFile(full)
        try:
            data = zf.read(urllib.parse.unquote(res))
        finally:
            zf.close()
    except Exception:
        return None
    ctype = mimetypes.guess_type(res)[0] or "application/octet-stream"
    return data, ctype


# ============================================================================
#  Assistant chat page (text-only; image recognition retired)
# ============================================================================
ASSISTANT_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Survival Assistant</title>
<style>
  :root{--bg:#0f1720;--panel:#16212e;--panel2:#1d2a3a;--text:#e8eef5;--muted:#9fb0c3;
    --accent:#4ea1ff;--accent2:#2f7fd6;--user-bg:#1f3147;--bot-bg:#18242f;
    --warn-bg:#3a2a14;--warn-bd:#7a5a1f;--ok:#6fcf97;}
  *{box-sizing:border-box;} html,body{height:100%;margin:0;}
  body{background:var(--bg);color:var(--text);font-family:"Segoe UI",system-ui,Arial,sans-serif;display:flex;flex-direction:column;height:100vh;}
  header{background:var(--panel);padding:12px 18px;display:flex;align-items:center;gap:12px;border-bottom:1px solid #243343;flex:0 0 auto;}
  header .logo{font-size:26px;} header h1{font-size:18px;margin:0;font-weight:650;}
  header .sub{color:var(--muted);font-size:12.5px;margin-top:2px;}
  header .right{margin-left:auto;display:flex;align-items:center;gap:10px;}
  header select{background:var(--panel2);color:var(--text);border:1px solid #2c3e52;border-radius:8px;padding:7px 10px;font-size:14px;}
  #status{font-size:12px;color:var(--muted);} #status.ok{color:var(--ok);} #status.err{color:#ff8a8a;}
  #chat{flex:1 1 auto;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:14px;}
  .msg{max-width:860px;width:fit-content;padding:12px 15px;border-radius:12px;line-height:1.5;white-space:pre-wrap;word-wrap:break-word;font-size:15px;}
  .msg.user{align-self:flex-end;background:var(--user-bg);border:1px solid #2a456b;}
  .msg.bot{align-self:flex-start;background:var(--bot-bg);border:1px solid #243343;}
  .msg .who{font-size:11.5px;color:var(--muted);margin-bottom:5px;text-transform:uppercase;letter-spacing:.04em;}
  .welcome{align-self:center;max-width:720px;text-align:center;color:var(--muted);background:var(--panel);border:1px solid #243343;border-radius:12px;padding:18px 20px;}
  .welcome h2{color:var(--text);margin:0 0 8px;font-size:17px;} .welcome .tip{margin:6px 0;}
  .safety{background:var(--warn-bg);border:1px solid var(--warn-bd);color:#f0d9a8;border-radius:10px;padding:10px 12px;font-size:13px;margin-top:10px;text-align:left;}
  .guides{align-self:flex-start;max-width:860px;background:var(--panel);border:1px solid #2c3e52;border-radius:12px;padding:10px 14px;margin-top:-4px;}
  .guides .ghead{font-size:12.5px;color:var(--muted);font-weight:600;margin-bottom:8px;}
  .guides ul{list-style:none;margin:0;padding:0;} .guides li{margin:7px 0;line-height:1.4;}
  .guides a{color:var(--accent);text-decoration:none;font-size:14.5px;font-weight:600;}
  .guides a:hover{text-decoration:underline;}
  .guides .gsrc{display:inline-block;font-size:11px;color:#cfe0f3;background:#243a55;border:1px solid #2f567c;border-radius:999px;padding:1px 9px;margin-left:8px;}
  .guides .gsnip{color:var(--muted);font-size:12.5px;margin-top:2px;}
  footer{flex:0 0 auto;background:var(--panel);border-top:1px solid #243343;padding:12px;}
  .composer{max-width:980px;margin:0 auto;display:flex;flex-direction:column;gap:8px;}
  .row{display:flex;gap:10px;align-items:flex-end;}
  textarea#input{flex:1 1 auto;resize:none;min-height:48px;max-height:200px;background:var(--panel2);color:var(--text);border:1px solid #2c3e52;border-radius:12px;padding:12px 14px;font-size:15px;font-family:inherit;line-height:1.4;}
  .btn{border:none;border-radius:12px;padding:0 18px;height:48px;font-size:15px;cursor:pointer;font-weight:600;}
  .btn.send{background:var(--accent2);color:#fff;} .btn.send:hover{background:var(--accent);} .btn.send:disabled{background:#34465a;color:#889;cursor:default;}
  .hint{text-align:center;color:var(--muted);font-size:12px;} .typing{color:var(--muted);font-style:italic;}
  .controls{display:flex;gap:10px;align-items:center;justify-content:space-between;}
  #newchat{background:transparent;color:var(--muted);border:1px solid #2c3e52;border-radius:8px;padding:6px 12px;cursor:pointer;font-size:13px;}
  #newchat:hover{color:var(--text);border-color:var(--accent);}
</style>
</head>
<body>
  <header>
    <div class="logo">&#9937;</div>
    <div><h1>Survival Assistant</h1><div class="sub">A calm, offline helper &mdash; ask anything</div></div>
    <div class="right"><span id="status">connecting&hellip;</span>
      <label class="hint" for="model">Model</label><select id="model" title="Local AI model"></select></div>
  </header>
  <div id="chat">
    <div class="welcome"><h2>Hello. I'm here to help, and you're going to be okay.</h2>
      <div class="tip">Ask me about first aid, water, shelter, food, hunting, repairs, or anything you're facing.</div>
      <div class="tip">Tip: the <b>Search</b> box at the top finds answers across every book and wiki on this computer.</div>
      <div class="safety">&#9888;&#65039; I'm an AI and I can be wrong. For wild food and medical decisions I will always be cautious and tell you how to double-check. Never eat a wild plant or mushroom based only on a guess.</div></div>
  </div>
  <footer><div class="composer">
    <div class="row">
      <textarea id="input" placeholder="Type your question and press Enter&hellip;  (Shift+Enter for a new line)"></textarea>
      <button class="btn send" id="sendBtn" type="button">Send</button>
    </div>
    <div class="controls"><div class="left"><button id="newchat" type="button">&#8635; Start a new chat</button></div>
      <div class="hint">Everything stays on this computer. No internet is used. Answers may take a little while.</div></div>
  </div></footer>
<script>
"use strict";
const chatEl=document.getElementById("chat"),inputEl=document.getElementById("input"),sendBtn=document.getElementById("sendBtn"),
  modelSel=document.getElementById("model"),statusEl=document.getElementById("status"),newchatBtn=document.getElementById("newchat");
let history=[],busy=false;
const DEFAULT_MODEL=%DEFAULT_MODEL_JSON%;
async function loadModels(){
  try{const r=await fetch("/api/models");const j=await r.json();const models=j.models||[];modelSel.innerHTML="";
    models.forEach(m=>{const o=document.createElement("option");o.value=m;o.textContent=m;modelSel.appendChild(o);});
    if(models.includes(DEFAULT_MODEL))modelSel.value=DEFAULT_MODEL;
    statusEl.textContent="ready • offline";statusEl.className="ok";
  }catch(e){statusEl.textContent="cannot reach the AI engine";statusEl.className="err";}
}
function addMsg(role,text){const w=document.querySelector(".welcome");if(w)w.remove();
  const d=document.createElement("div");d.className="msg "+(role==="user"?"user":"bot");
  const who=document.createElement("div");who.className="who";who.textContent=role==="user"?"You":"Survival Helper";d.appendChild(who);
  const body=document.createElement("div");body.textContent=text;d.appendChild(body);
  chatEl.appendChild(d);chatEl.scrollTop=chatEl.scrollHeight;return body;}
function renderGuides(results){if(!results||!results.length)return null;
  const box=document.createElement("div");box.className="guides";
  const h=document.createElement("div");h.className="ghead";h.textContent="📚 From your offline guides:";box.appendChild(h);
  const ul=document.createElement("ul");
  results.forEach(it=>{if(!it||!it.url||!it.title)return;const li=document.createElement("li");
    const a=document.createElement("a");a.href=it.url;a.target="_top";a.textContent=it.title;li.appendChild(a);
    if(it.source){const s=document.createElement("span");s.className="gsrc";s.textContent=it.source;li.appendChild(s);}
    if(it.snippet){const sn=document.createElement("div");sn.className="gsnip";sn.textContent=it.snippet;li.appendChild(sn);}
    ul.appendChild(li);});box.appendChild(ul);return box;}
async function fetchGuides(query){if(!query)return[];try{const ctrl=new AbortController();const t=setTimeout(()=>ctrl.abort(),5000);
  const r=await fetch("/api/guides?q="+encodeURIComponent(query),{signal:ctrl.signal});clearTimeout(t);
  if(!r.ok)return[];const j=await r.json();return(j&&j.results)?j.results:[];}catch(_){return[];}}
function setBusy(b){busy=b;sendBtn.disabled=b;sendBtn.textContent=b?"Thinking…":"Send";}
async function send(){if(busy)return;const text=inputEl.value.trim();if(!text)return;const model=modelSel.value||DEFAULT_MODEL;
  addMsg("user",text);inputEl.value="";setBusy(true);
  const botBody=addMsg("bot","");botBody.className="typing";botBody.textContent="Thinking…";
  const userMsg={role:"user",content:text};const sendHistory=history.concat([userMsg]);
  const guidesPromise=fetchGuides(text);
  try{const resp=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({model:model,messages:sendHistory})});
    if(!resp.ok||!resp.body){const t=await resp.text();botBody.className="";botBody.textContent="Sorry — something went wrong talking to the AI engine.\n\n"+t;setBusy(false);return;}
    botBody.className="";botBody.textContent="";const reader=resp.body.getReader();const dec=new TextDecoder();let buf="",full="";
    while(true){const{done,value}=await reader.read();if(done)break;buf+=dec.decode(value,{stream:true});let nl;
      while((nl=buf.indexOf("\n"))>=0){const line=buf.slice(0,nl).trim();buf=buf.slice(nl+1);if(!line)continue;
        try{const obj=JSON.parse(line);if(obj.message&&obj.message.content){full+=obj.message.content;botBody.textContent=full;chatEl.scrollTop=chatEl.scrollHeight;}
          if(obj.error){full+="\n[Engine error: "+obj.error+"]";botBody.textContent=full;}}catch(_){}}}
    if(!full)botBody.textContent="(The AI gave an empty answer. Try rephrasing.)";
    history.push(userMsg);history.push({role:"assistant",content:full});
    try{const refs=await guidesPromise;const card=renderGuides(refs);if(card){const b=botBody.parentElement;if(b&&b.parentNode){b.parentNode.insertBefore(card,b.nextSibling);}else{chatEl.appendChild(card);}chatEl.scrollTop=chatEl.scrollHeight;}}catch(_){}
  }catch(e){botBody.className="";botBody.textContent="Sorry — I couldn't get a response.\n\n"+e;}
  finally{setBusy(false);inputEl.focus();}}
sendBtn.addEventListener("click",send);
inputEl.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();send();}});
newchatBtn.addEventListener("click",()=>{history=[];chatEl.innerHTML='<div class="welcome"><h2>New chat started.</h2><div class="tip">What can I help you with?</div></div>';});
inputEl.addEventListener("input",()=>{inputEl.style.height="auto";inputEl.style.height=Math.min(inputEl.scrollHeight,200)+"px";});
loadModels();inputEl.focus();
</script>
</body>
</html>
"""


# ============================================================================
#  HTTP handler
# ============================================================================
class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "SurvivalHub/2.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[hub] " + (fmt % args) + "\n")

    # -- helpers ------------------------------------------------------------
    def _headers(self, status, ctype, length=None, extra=None, cache=False):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-store")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()

    def _send_html(self, html_text, status=HTTPStatus.OK):
        data = html_text.encode("utf-8")
        self._headers(status, "text/html; charset=utf-8", len(data))
        if self.command != "HEAD":
            self.wfile.write(data)

    def _send_bytes(self, data, ctype, cache=True, extra=None):
        self._headers(HTTPStatus.OK, ctype, len(data), extra=extra, cache=cache)
        if self.command != "HEAD":
            self.wfile.write(data)

    # -- routing ------------------------------------------------------------
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                shell = (SHELL_HTML
                         .replace("%ENCY_JSON%", json.dumps(KIWIX_PUBLIC_BASE + "/"))
                         .replace("%MAPS_JSON%", json.dumps(MAPS_PUBLIC_BASE + "/")))
                return self._send_html(shell)
            if path == "/home":
                home = (HOME_HTML
                        .replace("ENCY_HREF", html.escape(KIWIX_PUBLIC_BASE + "/"))
                        .replace("MAPS_HREF", html.escape(MAPS_PUBLIC_BASE + "/")))
                return self._send_html(home)
            if path == "/assistant":
                return self._send_html(ASSISTANT_HTML.replace("%DEFAULT_MODEL_JSON%", json.dumps(DEFAULT_MODEL)))
            if path == "/food":
                return self._serve_static("/guides/food.html", GUIDES_DIR, "/guides")
            if path == "/search":
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("q", [""])[0]
                return self._send_html(render_search_page(q))
            if path == "/api/models":
                return self._handle_models()
            if path == "/api/guides":
                return self._handle_guides()
            if path == "/healthz":
                return self._send_bytes(b'{"ok":true}', "application/json", cache=False)
            if path.startswith("/guides/"):
                return self._serve_static(path, GUIDES_DIR, "/guides")
            if path.startswith("/library/"):
                return self._serve_static(path, LIBRARY_DIR, "/library")
            if path.startswith("/docs/"):
                return self._serve_static(path, DOCS_DIR, "/docs")
            if path.startswith("/read-asset/"):
                return self._handle_read_asset(path)
            if path.startswith("/read/"):
                return self._handle_read(path)
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/chat":
                return self._handle_chat()
            if path == "/api/stop":
                return self._handle_stop()
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except (BrokenPipeError, ConnectionResetError):
            pass

    # -- static file serving (with single-range support) --------------------
    def _serve_static(self, url_path, base_dir, prefix):
        rel = url_path[len(prefix):] if url_path.startswith(prefix) else url_path
        rel = rel.split("#", 1)[0]
        full = _safe_join(base_dir, rel)
        if full is None:
            return self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            return self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") and "charset" not in ctype:
            ctype += "; charset=utf-8"
        try:
            size = os.path.getsize(full)
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                start_s, _, end_s = rng[6:].partition("-")
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else size - 1
                end = min(end, size - 1)
                if start > end or start >= size:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.end_headers()
                    return
                length = end - start + 1
                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(length))
                self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                if self.command == "HEAD":
                    return
                with open(full, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            if self.command == "HEAD":
                return
            with open(full, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle_read(self, path):
        rel = path[len("/read/"):]
        rendered = read_epub(rel)
        if rendered is None:
            # Fail open: offer the raw file instead of an error.
            return self._serve_static("/library/" + rel, LIBRARY_DIR, "/library")
        return self._send_html(rendered)

    def _handle_read_asset(self, path):
        rest = path[len("/read-asset/"):]
        if "/" not in rest:
            return self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        # everything up to ".epub/" is the book; the remainder is the resource
        low = rest.lower()
        idx = low.find(".epub/")
        if idx < 0:
            return self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        book = rest[:idx + 5]
        res = rest[idx + 6:]
        got = read_epub_asset(book, res)
        if got is None:
            return self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        data, ctype = got
        return self._send_bytes(data, ctype, cache=True)

    # -- /api/models --------------------------------------------------------
    def _handle_models(self):
        try:
            with urllib.request.urlopen(OLLAMA_BASE + "/api/tags", timeout=20) as r:
                tags = json.loads(r.read().decode("utf-8"))
            names = sorted({m.get("name", "") for m in tags.get("models", []) if m.get("name")})
            if DEFAULT_MODEL in names:
                names.remove(DEFAULT_MODEL)
                names.insert(0, DEFAULT_MODEL)
            body = json.dumps({"models": names}).encode("utf-8")
        except Exception as e:
            body = json.dumps({"models": [], "error": str(e)}).encode("utf-8")
        self._send_bytes(body, "application/json", cache=False)

    # -- /api/guides --------------------------------------------------------
    def _handle_guides(self):
        try:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("q", [""])[0].strip()
            results = kiwix_search(q, KIWIX_RESULTS)
        except Exception:
            results = []
        body = json.dumps({"results": results}).encode("utf-8")
        self._send_bytes(body, "application/json", cache=False)

    # -- /api/stop : run the (fixed) stop script, then exit -----------------
    def _handle_stop(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length:
                self.rfile.read(length)
        except Exception:
            pass
        body = b'{"stopping":true}'
        self._headers(HTTPStatus.OK, "application/json", len(body), cache=False)
        try:
            self.wfile.write(body)
            self.wfile.flush()
        except Exception:
            pass
        # Launch the stop helper detached; it will stop Kiwix/Maps and this Hub
        # and close the Edge window. We also self-exit shortly as a backstop.
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-WindowStyle", "Hidden", "-File", os.path.join(APP_DIR, "stop-station.ps1")],
                creationflags=0x00000008,  # DETACHED_PROCESS
            )
        except Exception:
            pass

    # -- /api/chat : stream a chat completion from Ollama -------------------
    def _handle_chat(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8"))
        except Exception as e:
            return self.send_error(HTTPStatus.BAD_REQUEST, "Bad request: %s" % e)

        model = payload.get("model") or DEFAULT_MODEL
        messages = payload.get("messages") or []
        full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
        data = json.dumps({"model": model, "messages": full_messages, "stream": True}).encode("utf-8")
        req = urllib.request.Request(OLLAMA_BASE + "/api/chat", data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            upstream = urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT)
        except urllib.error.HTTPError as e:
            return self._stream_error("The AI engine returned an error (%d): %s"
                                      % (e.code, e.read().decode("utf-8", "replace")))
        except Exception as e:
            return self._stream_error("Could not reach the AI engine: %s" % e)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            for line in upstream:
                if line:
                    self._write_chunk(line if line.endswith(b"\n") else line + b"\n")
            self._write_chunk(b"")
        except Exception as e:
            try:
                self._write_chunk((json.dumps({"error": str(e)}) + "\n").encode("utf-8"))
                self._write_chunk(b"")
            except Exception:
                pass
        finally:
            try:
                upstream.close()
            except Exception:
                pass

    def _write_chunk(self, data):
        self.wfile.write(("%X\r\n" % len(data)).encode("ascii"))
        if data:
            self.wfile.write(data)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _stream_error(self, message):
        body = (json.dumps({"error": message}) + "\n").encode("utf-8")
        self._headers(HTTPStatus.OK, "application/x-ndjson", len(body), cache=False)
        try:
            self.wfile.write(body)
        except Exception:
            pass


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def preflight_ollama():
    try:
        with urllib.request.urlopen(OLLAMA_BASE + "/api/tags", timeout=10) as r:
            tags = json.loads(r.read().decode("utf-8"))
        names = [m.get("name", "") for m in tags.get("models", [])]
        print("[hub] Ollama OK at %s  (%d models)" % (OLLAMA_BASE, len(names)))
        if DEFAULT_MODEL not in names:
            print("[hub] NOTE: default model '%s' not found; the assistant will use whatever is available." % DEFAULT_MODEL)
    except Exception as e:
        print("[hub] NOTE: could not reach Ollama at %s: %s (the rest of the Hub still works)." % (OLLAMA_BASE, e))


def main():
    print("=" * 64)
    print(" Survival Hub  (offline home, search, library, assistant)")
    print("=" * 64)
    print("[hub] Search index: %s" % ("present" if os.path.exists(INDEX_DB) else "NOT BUILT YET (run build-search-index)"))
    preflight_ollama()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print("[hub] Serving the Survival Station on http://%s:%d/" % (HOST, PORT))
    print("[hub] Press Ctrl+C in this window to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[hub] Stopping.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
