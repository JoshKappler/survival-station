#!/usr/bin/env python3
"""
Survival Assistant - a calm, offline chat helper with photo input.

Pure Python standard library only (no pip packages), because this machine
has Smart App Control enforcing, which blocks unsigned compiled binaries
(numpy/torch/etc.). The signed CPython interpreter and its signed stdlib
extensions ARE allowed, so this app runs where Open WebUI / AnythingLLM
cannot.

It serves a friendly browser chat UI on http://127.0.0.1:8080 and talks to
the local, already-running Ollama server (http://localhost:11434) for both
text and vision (image) chat. Everything is local; no internet is used.

Bind:   127.0.0.1:8080   (localhost only)
Ollama: http://localhost:11434
"""

import json
import os
import re
import sys
import socket
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

DEFAULT_MODEL = os.environ.get("ASSISTANT_DEFAULT_MODEL", "gemma3:4b")

# Models known to accept images (vision). Used to hint the UI.
VISION_MODELS = ["gemma3:4b", "moondream", "moondream:latest", "llava:7b", "llava"]

# The required global default system prompt (verbatim).
SYSTEM_PROMPT = (
    "You are 'Survival Helper', a calm, practical, friendly assistant on an "
    "OFFLINE emergency computer. The person may be stressed, tired, or not "
    "technical — explain simply, step by step, in plain language, and be "
    "reassuring. SAFETY FIRST: for eating wild plants/mushrooms, medical "
    "treatment, water safety, or dangerous tasks, ALWAYS give clear safety "
    "warnings and state your uncertainty. NEVER call a plant or mushroom safe "
    "to eat from a photo or description alone — explain that "
    "misidentification can be deadly, tell them how to cross-check with the "
    "offline guides, and describe the Universal Edibility Test when relevant. "
    "For medical issues give clear first-aid steps and say when something is "
    "beyond home care. You have NO internet; if unsure, say so and suggest "
    "which offline resource (the Encyclopedia, the Medical books, or the "
    "Manuals) might help. When given a photo, describe what you see and give a "
    "best, clearly-hedged guess plus how to confirm it safely. Keep answers "
    "focused. Above all, keep the person safe, calm, and alive."
)

# How long to wait on Ollama (CPU inference, especially vision, can be slow).
OLLAMA_TIMEOUT = int(os.environ.get("ASSISTANT_OLLAMA_TIMEOUT", "1800"))  # seconds

# ----------------------------------------------------------------------------
# Kiwix offline library (already running) — used to ground answers in the real
# offline guides. This is a BEST-EFFORT, FAIL-OPEN feature: the search runs in
# a completely separate request from the chat, with a short timeout, and if it
# is unreachable the chat is entirely unaffected and no references are shown.
# ----------------------------------------------------------------------------
# Where the assistant's server talks to Kiwix (loopback by spec).
KIWIX_BASE = os.environ.get("KIWIX_BASE_URL", "http://127.0.0.1:8081").rstrip("/")
# The base the BROWSER should use for clickable article links (per spec).
KIWIX_PUBLIC_BASE = os.environ.get(
    "KIWIX_PUBLIC_BASE_URL", "http://localhost:8081"
).rstrip("/")
# Keep this short so a slow/missing Kiwix never holds up the experience.
KIWIX_TIMEOUT = float(os.environ.get("ASSISTANT_KIWIX_TIMEOUT", "3"))  # seconds
# How many guide references to show under an answer.
KIWIX_RESULTS = int(os.environ.get("ASSISTANT_KIWIX_RESULTS", "5"))


# ----------------------------------------------------------------------------
# The single-page UI (all assets inline; nothing loaded from the internet)
# ----------------------------------------------------------------------------
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Survival Assistant</title>
<style>
  :root {
    --bg: #0f1720; --panel: #16212e; --panel2: #1d2a3a; --text: #e8eef5;
    --muted: #9fb0c3; --accent: #4ea1ff; --accent2: #2f7fd6;
    --user-bg: #1f3147; --bot-bg: #18242f;
    --warn-bg: #3a2a14; --warn-bd: #7a5a1f; --ok: #6fcf97;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg); color: var(--text);
    font-family: "Segoe UI", system-ui, -apple-system, Arial, sans-serif;
    display: flex; flex-direction: column; height: 100vh;
  }
  header {
    background: var(--panel); padding: 12px 18px; display: flex;
    align-items: center; gap: 12px; border-bottom: 1px solid #243343;
    flex: 0 0 auto;
  }
  header .logo { font-size: 26px; }
  header h1 { font-size: 18px; margin: 0; font-weight: 650; }
  header .sub { color: var(--muted); font-size: 12.5px; margin-top: 2px; }
  header .right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
  header select {
    background: var(--panel2); color: var(--text); border: 1px solid #2c3e52;
    border-radius: 8px; padding: 7px 10px; font-size: 14px;
  }
  #status { font-size: 12px; color: var(--muted); }
  #status.ok { color: var(--ok); }
  #status.err { color: #ff8a8a; }

  #chat {
    flex: 1 1 auto; overflow-y: auto; padding: 18px;
    display: flex; flex-direction: column; gap: 14px;
  }
  .msg { max-width: 860px; width: fit-content; padding: 12px 15px;
         border-radius: 12px; line-height: 1.5; white-space: pre-wrap;
         word-wrap: break-word; font-size: 15px; }
  .msg.user { align-self: flex-end; background: var(--user-bg);
              border: 1px solid #2a456b; }
  .msg.bot  { align-self: flex-start; background: var(--bot-bg);
              border: 1px solid #243343; }
  .msg.bot .who, .msg.user .who { font-size: 11.5px; color: var(--muted);
              margin-bottom: 5px; text-transform: uppercase; letter-spacing: .04em; }
  .msg img.thumb { max-width: 220px; max-height: 220px; border-radius: 8px;
              display: block; margin-top: 8px; border: 1px solid #34506b; }
  .welcome { align-self: center; max-width: 720px; text-align: center;
             color: var(--muted); background: var(--panel); border: 1px solid #243343;
             border-radius: 12px; padding: 18px 20px; }
  .welcome h2 { color: var(--text); margin: 0 0 8px; font-size: 17px; }
  .welcome .tip { margin: 6px 0; }
  .safety { background: var(--warn-bg); border: 1px solid var(--warn-bd);
            color: #f0d9a8; border-radius: 10px; padding: 10px 12px; font-size: 13px;
            margin-top: 10px; text-align: left; }

  /* "From your offline guides" reference list under an answer */
  .guides { align-self: flex-start; max-width: 860px; width: fit-content;
            background: var(--panel); border: 1px solid #2c3e52;
            border-radius: 12px; padding: 10px 14px; margin-top: -4px; }
  .guides .ghead { font-size: 12.5px; color: var(--muted); font-weight: 600;
            margin-bottom: 8px; letter-spacing: .02em; }
  .guides ul { list-style: none; margin: 0; padding: 0; }
  .guides li { margin: 7px 0; line-height: 1.4; }
  .guides a { color: var(--accent); text-decoration: none; font-size: 14.5px;
            font-weight: 600; }
  .guides a:hover { text-decoration: underline; }
  .guides .gsrc { display: inline-block; font-size: 11px; color: #cfe0f3;
            background: #243a55; border: 1px solid #2f567c; border-radius: 999px;
            padding: 1px 9px; margin-left: 8px; vertical-align: middle; }
  .guides .gsnip { color: var(--muted); font-size: 12.5px; margin-top: 2px; }

  footer { flex: 0 0 auto; background: var(--panel); border-top: 1px solid #243343;
           padding: 12px; }
  .composer { max-width: 980px; margin: 0 auto; display: flex; flex-direction: column;
              gap: 8px; }
  #preview { display: none; align-items: center; gap: 10px; }
  #preview img { max-height: 64px; border-radius: 8px; border: 1px solid #34506b; }
  #preview button { background: #3a2330; color: #ffcaca; border: 1px solid #5a3340;
                    border-radius: 7px; padding: 5px 9px; cursor: pointer; font-size: 12px; }
  .row { display: flex; gap: 10px; align-items: flex-end; }
  textarea#input {
    flex: 1 1 auto; resize: none; min-height: 48px; max-height: 200px;
    background: var(--panel2); color: var(--text); border: 1px solid #2c3e52;
    border-radius: 12px; padding: 12px 14px; font-size: 15px; font-family: inherit;
    line-height: 1.4;
  }
  .btn { border: none; border-radius: 12px; padding: 0 18px; height: 48px;
         font-size: 15px; cursor: pointer; font-weight: 600; }
  .btn.send { background: var(--accent2); color: #fff; }
  .btn.send:hover { background: var(--accent); }
  .btn.send:disabled { background: #34465a; color: #889; cursor: default; }
  .btn.photo { background: var(--panel2); color: var(--text); border: 1px solid #2c3e52;
               font-weight: 500; }
  .btn.photo:hover { border-color: var(--accent); }
  .hint { text-align: center; color: var(--muted); font-size: 12px; }
  .typing { color: var(--muted); font-style: italic; }
  .controls { display: flex; gap: 10px; align-items: center; justify-content: space-between; }
  .controls .left { display: flex; gap: 10px; align-items: center; }
  #newchat { background: transparent; color: var(--muted); border: 1px solid #2c3e52;
             border-radius: 8px; padding: 6px 12px; cursor: pointer; font-size: 13px; }
  #newchat:hover { color: var(--text); border-color: var(--accent); }
</style>
</head>
<body>
  <header>
    <div class="logo">⛑️</div>
    <div>
      <h1>Survival Assistant</h1>
      <div class="sub">A calm, offline helper &mdash; ask anything, or add a photo</div>
    </div>
    <div class="right">
      <span id="status">connecting&hellip;</span>
      <label class="hint" for="model">Model</label>
      <select id="model" title="Which local AI model to use"></select>
    </div>
  </header>

  <div id="chat">
    <div class="welcome">
      <h2>Hello. I'm here to help, and you're going to be okay.</h2>
      <div class="tip">Ask me about first aid, water, shelter, food, repairs, or anything you're facing.</div>
      <div class="tip">You can add a <strong>photo</strong> of a plant, a wound, or an object and I'll describe what I see.</div>
      <div class="safety">⚠️ I'm an AI and I can be wrong. For wild food and medical decisions I will always be cautious and tell you how to double-check. Never eat a wild plant or mushroom based only on a photo.</div>
    </div>
  </div>

  <footer>
    <div class="composer">
      <div id="preview">
        <img id="previewImg" alt="attached photo">
        <button id="removeImg" type="button">Remove photo</button>
      </div>
      <div class="row">
        <button class="btn photo" id="photoBtn" type="button" title="Add a photo">📷 Photo</button>
        <textarea id="input" placeholder="Type your question and press Enter&hellip;  (Shift+Enter for a new line)"></textarea>
        <button class="btn send" id="sendBtn" type="button">Send</button>
      </div>
      <div class="controls">
        <div class="left">
          <button id="newchat" type="button">↻ Start a new chat</button>
        </div>
        <div class="hint">Everything stays on this computer. No internet is used. Answers may take a little while.</div>
      </div>
      <input type="file" id="fileInput" accept="image/*" style="display:none">
    </div>
  </footer>

<script>
"use strict";
const chatEl = document.getElementById("chat");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("sendBtn");
const modelSel = document.getElementById("model");
const statusEl = document.getElementById("status");
const photoBtn = document.getElementById("photoBtn");
const fileInput = document.getElementById("fileInput");
const preview = document.getElementById("preview");
const previewImg = document.getElementById("previewImg");
const removeImg = document.getElementById("removeImg");
const newchatBtn = document.getElementById("newchat");

let history = [];          // [{role, content}]
let pendingImage = null;   // base64 (no data: prefix)
let busy = false;
const DEFAULT_MODEL = %DEFAULT_MODEL_JSON%;
const VISION_HINT = %VISION_MODELS_JSON%;

function isVision(m){ return VISION_HINT.some(v => m === v || m.startsWith(v.split(':')[0])); }

async function loadModels(){
  try{
    const r = await fetch("/api/models");
    const j = await r.json();
    const models = j.models || [];
    modelSel.innerHTML = "";
    models.forEach(m => {
      const o = document.createElement("option");
      o.value = m;
      o.textContent = m + (isVision(m) ? "  👁 sees photos" : "");
      modelSel.appendChild(o);
    });
    if (models.includes(DEFAULT_MODEL)) modelSel.value = DEFAULT_MODEL;
    statusEl.textContent = "ready • offline";
    statusEl.className = "ok";
  }catch(e){
    statusEl.textContent = "cannot reach the AI engine";
    statusEl.className = "err";
  }
}

function addMsg(role, text, imgB64){
  const w = document.querySelector(".welcome"); if (w) w.remove();
  const d = document.createElement("div");
  d.className = "msg " + (role === "user" ? "user" : "bot");
  const who = document.createElement("div");
  who.className = "who";
  who.textContent = role === "user" ? "You" : "Survival Helper";
  d.appendChild(who);
  const body = document.createElement("div");
  body.textContent = text;
  d.appendChild(body);
  if (imgB64){
    const im = document.createElement("img");
    im.className = "thumb";
    im.src = "data:image/*;base64," + imgB64;
    d.appendChild(im);
  }
  chatEl.appendChild(d);
  chatEl.scrollTop = chatEl.scrollHeight;
  return body;
}

// Build a "From your offline guides" reference card. Returns the element,
// or null if there is nothing to show. Purely cosmetic; never throws.
function renderGuides(results){
  if (!results || !results.length) return null;
  const box = document.createElement("div");
  box.className = "guides";
  const h = document.createElement("div");
  h.className = "ghead";
  h.textContent = "📚 From your offline guides:";
  box.appendChild(h);
  const ul = document.createElement("ul");
  results.forEach(it => {
    if (!it || !it.url || !it.title) return;
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = it.url;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = it.title;
    li.appendChild(a);
    if (it.source){
      const s = document.createElement("span");
      s.className = "gsrc";
      s.textContent = it.source;
      li.appendChild(s);
    }
    if (it.snippet){
      const sn = document.createElement("div");
      sn.className = "gsnip";
      sn.textContent = it.snippet;
      li.appendChild(sn);
    }
    ul.appendChild(li);
  });
  box.appendChild(ul);
  return box;
}

// Fetch grounded references for a query. FAIL-OPEN: returns [] on any
// problem (Kiwix down, timeout, network error) and never throws. Has its
// own short client-side timeout so it can never hold up the chat.
async function fetchGuides(query){
  if (!query) return [];
  try{
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 4000);
    const r = await fetch("/api/guides?q=" + encodeURIComponent(query),
                          { signal: ctrl.signal });
    clearTimeout(t);
    if (!r.ok) return [];
    const j = await r.json();
    return (j && j.results) ? j.results : [];
  }catch(_){
    return [];   // fail open, silently
  }
}

function setBusy(b){
  busy = b;
  sendBtn.disabled = b;
  sendBtn.textContent = b ? "Thinking…" : "Send";
}

async function send(){
  if (busy) return;
  const text = inputEl.value.trim();
  if (!text && !pendingImage) return;
  const model = modelSel.value || DEFAULT_MODEL;
  const imgForThisMsg = pendingImage;

  addMsg("user", text || "(photo)", imgForThisMsg);
  inputEl.value = "";
  clearImage();
  setBusy(true);

  const botBody = addMsg("bot", "");
  botBody.className = "typing";
  botBody.textContent = isVision(model) && imgForThisMsg
      ? "Looking at your photo… this can take a minute on this computer."
      : "Thinking…";

  const userMsg = { role: "user", content: text };
  if (imgForThisMsg) userMsg.images = [imgForThisMsg];
  const sendHistory = history.concat([userMsg]);

  // Kick off the offline-guides lookup in PARALLEL with the model answer.
  // It is fail-open and self-timing, so it never blocks or breaks the chat.
  const guidesPromise = text ? fetchGuides(text) : Promise.resolve([]);

  try{
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ model: model, messages: sendHistory })
    });
    if (!resp.ok || !resp.body){
      const t = await resp.text();
      botBody.className = "";
      botBody.textContent = "Sorry — something went wrong talking to the AI engine.\n\n" + t;
      setBusy(false);
      return;
    }
    botBody.className = "";
    botBody.textContent = "";
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "", full = "";
    while (true){
      const {done, value} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream: true});
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0){
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        try{
          const obj = JSON.parse(line);
          if (obj.message && obj.message.content){
            full += obj.message.content;
            botBody.textContent = full;
            chatEl.scrollTop = chatEl.scrollHeight;
          }
          if (obj.error){
            full += "\n[Engine error: " + obj.error + "]";
            botBody.textContent = full;
          }
        }catch(_){ /* ignore partial */ }
      }
    }
    if (!full) botBody.textContent = "(The AI gave an empty answer. Try rephrasing, or pick a different model.)";
    history.push(userMsg);
    history.push({ role: "assistant", content: full });

    // Show grounded references under this answer (if any). Fail-open: a
    // problem here is swallowed and the answer above stays intact.
    try{
      const refs = await guidesPromise;
      const card = renderGuides(refs);
      if (card){
        const botMsgEl = botBody.parentElement;   // the .msg.bot container
        if (botMsgEl && botMsgEl.parentNode){
          botMsgEl.parentNode.insertBefore(card, botMsgEl.nextSibling);
        }else{
          chatEl.appendChild(card);
        }
        chatEl.scrollTop = chatEl.scrollHeight;
      }
    }catch(_){ /* references are optional; ignore */ }
  }catch(e){
    botBody.className = "";
    botBody.textContent = "Sorry — I couldn't get a response.\n\n" + e;
  }finally{
    setBusy(false);
    inputEl.focus();
  }
}

function clearImage(){
  pendingImage = null;
  preview.style.display = "none";
  previewImg.src = "";
  fileInput.value = "";
}

photoBtn.addEventListener("click", () => fileInput.click());
removeImg.addEventListener("click", clearImage);
fileInput.addEventListener("change", () => {
  const f = fileInput.files[0];
  if (!f) return;
  const reader = new FileReader();
  reader.onload = () => {
    const s = reader.result;
    const b64 = s.substring(s.indexOf(",") + 1);
    pendingImage = b64;
    previewImg.src = s;
    preview.style.display = "flex";
  };
  reader.readAsDataURL(f);
});

sendBtn.addEventListener("click", send);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey){ e.preventDefault(); send(); }
});
newchatBtn.addEventListener("click", () => {
  history = [];
  clearImage();
  chatEl.innerHTML = '<div class="welcome"><h2>New chat started.</h2><div class="tip">What can I help you with?</div></div>';
});

inputEl.addEventListener("input", () => {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 200) + "px";
});

loadModels();
inputEl.focus();
</script>
</body>
</html>
"""


# ----------------------------------------------------------------------------
# Kiwix helpers: friendly source labels + parse search-result HTML
# ----------------------------------------------------------------------------
def friendly_source(slug: str) -> str:
    """Turn a Kiwix ZIM slug into a friendly, human source label.

    Rules per spec; order matters (more specific first). Anything unmatched
    falls back to a cleaned-up version of the slug.
    """
    s = (slug or "").lower()

    # Q&A: <sitename>  (e.g. medicalsciences.stackexchange.com -> "Q&A: Medicalsciences")
    if ".stackexchange.com" in s:
        site = s.split(".stackexchange.com", 1)[0]
        site = site.split("/")[-1]  # be safe if any path leaked in
        site = site.replace("_", " ").replace("-", " ").strip()
        site = site.title() if site else "Stack Exchange"
        return "Q&A: " + site

    # Medical encyclopedia must win over generic wikipedia_en_*.
    if s.startswith("wikipedia_en_medicine"):
        return "Medical Encyclopedia"
    if s.startswith("mdwiki"):
        return "Clinical Medicine"
    if s.startswith("zimgit-") or s.startswith("zimgit_"):
        return "Prepper Pack"
    if s.startswith("wikipedia_en_all") or s.startswith("wikipedia_en"):
        return "Wikipedia"
    if s.startswith("wikibooks"):
        return "Wikibooks (how-to)"
    if s.startswith("ifixit"):
        return "iFixit (repair)"
    if s.startswith("energypedia"):
        return "Energy"
    if s.startswith("appropedia"):
        return "Appropriate Tech"
    if s.startswith("wikivoyage"):
        return "Geography"

    # Fallback: drop the trailing date/locale noise and prettify.
    cleaned = re.sub(r"_\d{4}-\d{2}.*$", "", s)        # strip _2026-03...
    cleaned = re.sub(r"_(en|all|maxi|nopic|mini)\b", " ", cleaned)
    cleaned = cleaned.replace("_", " ").replace("-", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.title() if cleaned else (slug or "Guide")


class _KiwixResultsParser(HTMLParser):
    """Parse a Kiwix /search results page (stdlib only).

    The page lists each hit as:
        <li>
          <a href="/content/<zimslug>/<path>">Title</a>
          <cite>...snippet...</cite>
          <div class="book-title">from X</div>
        </li>
    We collect href, title text, and the <cite> snippet text.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []          # list of {href, title, snippet}
        self._in_results = False   # inside <div class="results">
        self._depth_results = 0
        self._cur = None           # current item being built
        self._capture = None       # "title" | "snippet" | None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "div" and a.get("class") == "results":
            self._in_results = True
            self._depth_results = 1
            return
        if not self._in_results:
            return
        if tag == "div":
            self._depth_results += 1
        if tag == "a":
            href = a.get("href", "")
            # Only treat article links (/content/...) as new results.
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
            # Finish this result.
            self._cur["title"] = re.sub(r"\s+", " ", self._cur["title"]).strip()
            self._cur["snippet"] = re.sub(r"\s+", " ", self._cur["snippet"]).strip()
            if self._cur["href"] and self._cur["title"]:
                self.results.append(self._cur)
            self._cur = None
            self._capture = None
        elif tag == "div":
            self._depth_results -= 1
            if self._depth_results <= 0:
                self._in_results = False

    def handle_data(self, data):
        if self._capture == "title" and self._cur is not None:
            self._cur["title"] += data
        elif self._capture == "snippet" and self._cur is not None:
            self._cur["snippet"] += data


def kiwix_search(query: str, limit: int = KIWIX_RESULTS):
    """Search the offline Kiwix library and return up to `limit` references.

    Returns a list of dicts: {title, url, snippet, source}. FAIL-OPEN: any
    problem (Kiwix down, timeout, parse error, empty query) returns [] and
    never raises. This runs in its own request, separate from chat.
    """
    q = (query or "").strip()
    if not q:
        return []
    try:
        params = urllib.parse.urlencode({"pattern": q, "pageLength": limit})
        url = KIWIX_BASE + "/search?" + params
        req = urllib.request.Request(url, headers={"Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=KIWIX_TIMEOUT) as r:
            raw = r.read()
        text = raw.decode("utf-8", "replace")

        parser = _KiwixResultsParser()
        parser.feed(text)

        out = []
        for item in parser.results[:limit]:
            href = item["href"]
            # Derive the ZIM slug: /content/<slug>/<path...>
            slug = ""
            m = re.match(r"^/content/([^/]+)/", href)
            if m:
                slug = urllib.parse.unquote(m.group(1))
            # Absolute, browser-clickable URL.
            full_url = KIWIX_PUBLIC_BASE + href
            snippet = item["snippet"]
            if len(snippet) > 280:
                snippet = snippet[:277].rstrip() + "..."
            out.append({
                "title": item["title"],
                "url": full_url,
                "snippet": snippet,
                "source": friendly_source(slug),
            })
        return out
    except Exception:
        # Fail open — never let library trouble affect the assistant.
        return []


# ----------------------------------------------------------------------------
# HTTP handler
# ----------------------------------------------------------------------------
class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "SurvivalAssistant/1.0"
    protocol_version = "HTTP/1.1"

    # Quieter logging
    def log_message(self, fmt, *args):
        sys.stderr.write("[assistant] " + (fmt % args) + "\n")

    def _send_headers(self, status, ctype, length=None, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        # localhost-only app; no caching of the dynamic page
        self.send_header("Cache-Control", "no-store")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            html = INDEX_HTML
            html = html.replace("%DEFAULT_MODEL_JSON%", json.dumps(DEFAULT_MODEL))
            html = html.replace("%VISION_MODELS_JSON%", json.dumps(VISION_MODELS))
            data = html.encode("utf-8")
            self._send_headers(HTTPStatus.OK, "text/html; charset=utf-8", len(data))
            self.wfile.write(data)
        elif path == "/api/models":
            self._handle_models()
        elif path == "/api/guides":
            self._handle_guides()
        elif path == "/healthz":
            data = b'{"ok":true}'
            self._send_headers(HTTPStatus.OK, "application/json", len(data))
            self.wfile.write(data)
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/chat":
            self._handle_chat()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    # -- /api/models : list models from Ollama ------------------------------
    def _handle_models(self):
        try:
            req = urllib.request.Request(OLLAMA_BASE + "/api/tags")
            with urllib.request.urlopen(req, timeout=20) as r:
                tags = json.loads(r.read().decode("utf-8"))
            names = [m.get("name", "") for m in tags.get("models", []) if m.get("name")]
            # Put the default model first if present, keep the rest sorted.
            names = sorted(set(names))
            if DEFAULT_MODEL in names:
                names.remove(DEFAULT_MODEL)
                names.insert(0, DEFAULT_MODEL)
            body = json.dumps({"models": names}).encode("utf-8")
            self._send_headers(HTTPStatus.OK, "application/json", len(body))
            self.wfile.write(body)
        except Exception as e:
            body = json.dumps({"models": [], "error": str(e)}).encode("utf-8")
            self._send_headers(HTTPStatus.OK, "application/json", len(body))
            self.wfile.write(body)

    # -- /api/guides : grounded references from the offline Kiwix library ---
    #    FAIL-OPEN: always returns HTTP 200 with a (possibly empty) list.
    #    This request is fully independent of /api/chat, so any trouble here
    #    can never break, hang, or slow the actual answer.
    def _handle_guides(self):
        try:
            qs = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(qs)
            query = (params.get("q", [""])[0] or "").strip()
            results = kiwix_search(query, KIWIX_RESULTS)
        except Exception:
            results = []
        body = json.dumps({"results": results}).encode("utf-8")
        self._send_headers(HTTPStatus.OK, "application/json", len(body))
        self.wfile.write(body)

    # -- /api/chat : stream a chat completion from Ollama -------------------
    def _handle_chat(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8"))
        except Exception as e:
            self.send_error(HTTPStatus.BAD_REQUEST, "Bad request: %s" % e)
            return

        model = payload.get("model") or DEFAULT_MODEL
        messages = payload.get("messages") or []

        # Always prepend the global safety system prompt.
        full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

        ollama_payload = {
            "model": model,
            "messages": full_messages,
            "stream": True,
        }
        data = json.dumps(ollama_payload).encode("utf-8")
        req = urllib.request.Request(
            OLLAMA_BASE + "/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
        )

        try:
            upstream = urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT)
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")
            self._stream_error("The AI engine returned an error (%d): %s" % (e.code, msg))
            return
        except Exception as e:
            self._stream_error("Could not reach the AI engine: %s" % e)
            return

        # Stream NDJSON straight through to the browser as it arrives.
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            for line in upstream:
                if not line:
                    continue
                self._write_chunk(line if line.endswith(b"\n") else line + b"\n")
            self._write_chunk(b"")  # terminating chunk
        except Exception as e:
            try:
                self._write_chunk(
                    (json.dumps({"error": str(e)}) + "\n").encode("utf-8")
                )
                self._write_chunk(b"")
            except Exception:
                pass
        finally:
            try:
                upstream.close()
            except Exception:
                pass

    def _write_chunk(self, data: bytes):
        # HTTP/1.1 chunked transfer encoding
        self.wfile.write(("%X\r\n" % len(data)).encode("ascii"))
        if data:
            self.wfile.write(data)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _stream_error(self, message: str):
        body = (json.dumps({"error": message}) + "\n").encode("utf-8")
        self._send_headers(HTTPStatus.OK, "application/x-ndjson", len(body))
        self.wfile.write(body)


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def preflight_ollama():
    try:
        with urllib.request.urlopen(OLLAMA_BASE + "/api/tags", timeout=10) as r:
            tags = json.loads(r.read().decode("utf-8"))
        names = [m.get("name", "") for m in tags.get("models", [])]
        print("[assistant] Ollama OK at %s  (%d models)" % (OLLAMA_BASE, len(names)))
        if DEFAULT_MODEL not in names:
            print("[assistant] WARNING: default model '%s' not found in Ollama."
                  % DEFAULT_MODEL)
        return True
    except Exception as e:
        print("[assistant] WARNING: could not reach Ollama at %s: %s"
              % (OLLAMA_BASE, e))
        print("[assistant] The page will still load; make sure Ollama is running.")
        return False


def main():
    print("=" * 60)
    print(" Survival Assistant  (offline chat + photo, powered by Ollama)")
    print("=" * 60)
    preflight_ollama()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print("[assistant] Serving on http://%s:%d" % (HOST, PORT))
    print("[assistant] Open that address in your web browser.")
    print("[assistant] Press Ctrl+C in this window to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[assistant] Stopping.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
