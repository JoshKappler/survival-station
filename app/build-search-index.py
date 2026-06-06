#!/usr/bin/env python3
"""
build-search-index.py  --  Build the offline full-text search index.

Crawls the reference library (PDFs, Project Gutenberg EPUBs, HTML, TXT) and the
authored survival guides, extracts their text, and writes a SQLite FTS5 database
at C:\\Survival\\app\\search-index.db. The Survival Hub then searches this index
(plus the live Kiwix wikis) from one search box.

Run it again any time you add new books or manuals:  "Rebuild Search Index".

This is a BUILD-TIME tool. It may use the pure-Python 'pypdf' package (installed
on demand) to read PDF text. The Hub itself stays pure standard library at run
time -- it only ever READS this prebuilt database via the bundled sqlite3.
"""
import os
import re
import sys
import html
import zipfile
import sqlite3
import posixpath
import subprocess
import urllib.parse

ROOT = r"C:\Survival"
APP_DIR = os.path.join(ROOT, "app")
LIBRARY_DIR = os.path.join(ROOT, "library")
GUIDES_DIR = os.path.join(APP_DIR, "guides")
DB_PATH = os.path.join(APP_DIR, "search-index.db")
TMP_PATH = DB_PATH + ".tmp"

# Friendly "source" label per top-level library folder.
SOURCE_BY_FOLDER = {
    "manuals": "Survival Manual",
    "medical": "Medical & First Aid",
    "food-foraging": "Food & Foraging",
    "shelter-skills": "Shelter & Field Skills",
    "tech-power": "Power, Water & Tech",
    "comms": "Communications",
    "reference": "Emergency Reference",
    "books": "Gutenberg Book",
}


def ensure_pypdf():
    try:
        import pypdf  # noqa
        return True
    except Exception:
        pass
    print("[index] Installing pypdf (one-time, build-time only)...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "pypdf"])
        import pypdf  # noqa
        return True
    except Exception as e:
        print("[index] WARNING: could not install pypdf (%s). PDFs will be indexed by title only." % e)
        return False


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def title_from_filename(path):
    name = os.path.splitext(os.path.basename(path))[0]
    name = re.sub(r"[_]+", " ", name)
    name = name.replace("-", " ")
    return clean(name)


def lib_url(relpath, anchor=""):
    quoted = "/".join(urllib.parse.quote(p) for p in relpath.split("/"))
    return "/library/" + quoted + anchor


def read_url(relpath, anchor=""):
    quoted = "/".join(urllib.parse.quote(p) for p in relpath.split("/"))
    return "/read/" + quoted + anchor


def strip_html(raw):
    raw = re.sub(r"<(script|style)\b.*?</\1>", " ", raw, flags=re.S | re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return clean(html.unescape(raw))


def iter_pdf_pages(full, have_pypdf):
    """Yield (page_number, text) for a PDF. Empty list if no text layer."""
    if not have_pypdf:
        return
    try:
        import pypdf
        reader = pypdf.PdfReader(full)
    except Exception as e:
        print("    ! could not open PDF (%s)" % e)
        return
    for i, page in enumerate(reader.pages, start=1):
        try:
            txt = clean(page.extract_text() or "")
        except Exception:
            txt = ""
        if len(txt) >= 25:
            yield i, txt


def iter_epub_chapters(full):
    """Yield (loc_label, text) for each EPUB spine chapter."""
    try:
        zf = zipfile.ZipFile(full)
    except Exception:
        return
    try:
        try:
            cont = zf.read("META-INF/container.xml").decode("utf-8", "replace")
            m = re.search(r'full-path="([^"]+)"', cont)
            opf_path = m.group(1) if m else None
        except Exception:
            opf_path = None
        if not opf_path:
            opf_path = next((n for n in zf.namelist() if n.lower().endswith(".opf")), None)
        if not opf_path:
            return
        opf_dir = posixpath.dirname(opf_path)
        opf = zf.read(opf_path).decode("utf-8", "replace")
        manifest = {}
        for mm in re.finditer(r'<item\b[^>]*>', opf):
            tag = mm.group(0)
            idm = re.search(r'id="([^"]+)"', tag)
            hrefm = re.search(r'href="([^"]+)"', tag)
            if idm and hrefm:
                manifest[idm.group(1)] = urllib.parse.unquote(hrefm.group(1))
        spine = [s.group(1) for s in re.finditer(r'<itemref\b[^>]*idref="([^"]+)"', opf)]
        hrefs = [manifest[i] for i in spine if i in manifest] or list(manifest.values())
        n = 0
        for href in hrefs:
            chap = posixpath.normpath(posixpath.join(opf_dir, href)) if opf_dir else href
            try:
                raw = zf.read(chap).decode("utf-8", "replace")
            except Exception:
                continue
            txt = strip_html(raw)
            if len(txt) >= 40:
                n += 1
                yield ("part %d" % n), txt
    finally:
        zf.close()


def epub_title(full):
    try:
        zf = zipfile.ZipFile(full)
        try:
            opf_path = None
            try:
                cont = zf.read("META-INF/container.xml").decode("utf-8", "replace")
                m = re.search(r'full-path="([^"]+)"', cont)
                opf_path = m.group(1) if m else None
            except Exception:
                pass
            if not opf_path:
                opf_path = next((n for n in zf.namelist() if n.lower().endswith(".opf")), None)
            if opf_path:
                opf = zf.read(opf_path).decode("utf-8", "replace")
                t = re.search(r'<dc:title[^>]*>(.*?)</dc:title>', opf, re.S)
                if t:
                    return clean(html.unescape(t.group(1)))
        finally:
            zf.close()
    except Exception:
        pass
    return title_from_filename(full)


def main():
    have_pypdf = ensure_pypdf()
    if os.path.exists(TMP_PATH):
        os.remove(TMP_PATH)
    con = sqlite3.connect(TMP_PATH)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute(
        "CREATE VIRTUAL TABLE docs USING fts5("
        "title, source, body, path UNINDEXED, loc UNINDEXED, kind UNINDEXED, "
        "tokenize='porter unicode61')"
    )
    rows = 0
    docs = 0

    def add(title, source, body, path, loc, kind):
        nonlocal rows
        con.execute("INSERT INTO docs(title, source, body, path, loc, kind) VALUES (?,?,?,?,?,?)",
                    (title, source, body, path, loc, kind))
        rows += 1

    # ---- library files ----
    for dirpath, _dirs, files in os.walk(LIBRARY_DIR):
        for fn in sorted(files):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, LIBRARY_DIR).replace("\\", "/")
            top = rel.split("/", 1)[0]
            ext = os.path.splitext(fn)[1].lower()
            if fn.startswith("_") or ext in (".csv", ".ps1", ".db", ".tmp"):
                continue
            source = SOURCE_BY_FOLDER.get(top, "Library")
            if ext == ".pdf":
                docs += 1
                title = title_from_filename(full)
                print("  [pdf]  %s" % rel)
                any_text = False
                for pageno, txt in iter_pdf_pages(full, have_pypdf):
                    any_text = True
                    add(title, source, txt, lib_url(rel, "#page=%d" % pageno), "p. %d" % pageno, "pdf")
                if not any_text:
                    add(title, source, title, lib_url(rel), "", "pdf")
            elif ext == ".epub":
                docs += 1
                title = epub_title(full)
                print("  [book] %s" % rel)
                topic = rel.split("/")[1] if rel.startswith("books/") and "/" in rel[6:] else ""
                src = "Gutenberg Book" + (" - " + topic.replace("-", " ").title() if topic else "")
                any_text = False
                for loc, txt in iter_epub_chapters(full):
                    any_text = True
                    add(title, src, txt, read_url(rel), loc, "epub")
                if not any_text:
                    add(title, src, title, read_url(rel), "", "epub")
            elif ext in (".html", ".htm"):
                if fn.lower() == "index.html":
                    continue  # skip directory landing pages
                docs += 1
                print("  [html] %s" % rel)
                try:
                    raw = open(full, "r", encoding="utf-8", errors="replace").read()
                except Exception:
                    continue
                tm = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
                title = clean(html.unescape(tm.group(1))) if tm else title_from_filename(full)
                add(title, source, strip_html(raw), lib_url(rel), "", "html")
            elif ext in (".txt", ".md"):
                docs += 1
                print("  [txt]  %s" % rel)
                try:
                    raw = open(full, "r", encoding="utf-8", errors="replace").read()
                except Exception:
                    continue
                add(title_from_filename(full), source, clean(raw), lib_url(rel), "", "txt")

    # ---- authored survival guides ----
    if os.path.isdir(GUIDES_DIR):
        for fn in sorted(os.listdir(GUIDES_DIR)):
            if not fn.lower().endswith(".html"):
                continue
            full = os.path.join(GUIDES_DIR, fn)
            try:
                raw = open(full, "r", encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            tm = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
            title = clean(html.unescape(tm.group(1))) if tm else title_from_filename(full)
            print("  [guide] %s" % fn)
            add(title, "Survival Guide", strip_html(raw), "/guides/" + urllib.parse.quote(fn), "", "guide")
            docs += 1

    con.commit()
    con.execute("INSERT INTO docs(docs) VALUES('optimize')")
    con.commit()
    con.close()

    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except Exception:
            pass
    os.replace(TMP_PATH, DB_PATH)
    print("=" * 60)
    print("[index] Done. %d documents, %d searchable sections." % (docs, rows))
    print("[index] Wrote %s" % DB_PATH)


if __name__ == "__main__":
    main()
