"""The app's Wiki tab: the website's training, how-to and FAQ articles, served from this computer.

The articles and their images and videos are copied from the site by `python -m hypnomix.app.wiki_sync`
into hypnomix/app/wiki/, so the Wiki works offline and matches the site.
"""
import json
import mimetypes
import re
from pathlib import Path

HERE = Path(__file__).with_name("wiki")
_CACHE = {}


def articles():
    f = HERE / "articles.json"
    if not f.exists():
        return {"articles": [], "synced": None, "source": None}
    m = f.stat().st_mtime
    if _CACHE.get("m") != m:
        _CACHE.update(m=m, data=json.loads(f.read_text()))
    return _CACHE["data"]


def index():
    d = articles()
    return {"synced": d.get("synced"), "source": d.get("source"),
            "articles": [{k: a.get(k, "") for k in ("id", "group", "title", "sub", "no", "text", "url")}
                         for a in d["articles"]]}


def article(aid):
    return next((a for a in articles()["articles"] if a["id"] == aid), None)


def asset(name, rng=None):
    """-> (code, body, type, extra headers). Videos need byte ranges to play in Safari and the Mac app."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name or ""):
        return 404, b'{"error":"not found"}', "application/json", None
    p = HERE / "assets" / name
    if not p.is_file():
        return 404, b'{"error":"not found"}', "application/json", None
    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    data = p.read_bytes()
    n = len(data)
    head = {"Accept-Ranges": "bytes"}
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", (rng or "").strip())
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            a = int(m.group(1))
            b = min(int(m.group(2)) if m.group(2) else n - 1, n - 1)
        else:
            a, b = max(0, n - int(m.group(2))), n - 1
        if a > b or a >= n:
            return 416, b"", ctype, {"Content-Range": f"bytes */{n}"}
        head["Content-Range"] = f"bytes {a}-{b}/{n}"
        return 206, data[a:b + 1], ctype, head
    return 200, data, ctype, head


def handle_get(path, q, headers=None):
    """-> (code, body, type[, extra headers]) for the Wiki's paths, else None."""
    if path == "/wiki.js":
        return 200, HERE.with_name("wiki.js").read_bytes(), "text/javascript; charset=utf-8"
    if path == "/api/wiki":
        return 200, json.dumps(index()).encode(), "application/json"
    if path == "/api/wiki/article":
        a = article(q.get("id", ""))
        if a is None:
            return 404, b'{"error":"no such article"}', "application/json"
        return 200, json.dumps(a).encode(), "application/json"
    if path.startswith("/wiki/assets/"):
        return asset(path.rsplit("/", 1)[1], (headers or {}).get("Range"))
    return None
