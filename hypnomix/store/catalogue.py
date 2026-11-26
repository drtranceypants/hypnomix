"""The store's catalogue (catalogue.json next to this file): load it, check it, search it.

Every item says what it is (kind), who makes it (vendor), its exact licence and whether it is open source, its
formats, whether it runs natively on Apple Silicon (true, false, or null for "not checked"), its homepage, and
where it is downloaded from:

  {"type": "github", "repo": "owner/name", "asset": "<regex>", "tag": "<optional tag, else the latest release>",
   "sha256": "<optional; only meaningful with a tag>"}
  {"type": "url", "url": "https://…", "version": "…", "sha256": "<optional>"}
  {"type": "page", "note": "…"}         the publisher does not allow direct downloads: the store opens the page

Optional fields: "size" ("190 MB", "3 GB": about how big the download is; it sets the store's download limit and its
free-space check) and "credit" (the credit line a licence REQUIRES, e.g. CC-BY; it is shown in the item's details and
is mandatory for the CC-BY licences). Personal names appear only there; elsewhere use the project or organisation.

A catalogue is checked when it is loaded (validate below): a bad one is refused, not used.
"""
import json
import re
import urllib.parse
from pathlib import Path

HERE = Path(__file__).with_name("catalogue.json")

KINDS = ("effect", "instrument", "synth", "drum kit", "sample pack", "sfz instrument")
CONTENT_KINDS = ("drum kit", "sample pack", "sfz instrument")          # files, not plug-ins
FORMATS = ("VST3", "AU", "CLAP", "LV2", "VST", "AAX", "SFZ", "SF2", "WAV", "FLAC")
METHODS = ("bundles", "pkg", "content", "page")
# SPDX ids (and "freeware" for closed, free-to-use software). Add to this list when a new licence appears.
LICENCES = ("GPL-2.0", "GPL-2.0-or-later", "GPL-3.0", "AGPL-3.0", "LGPL-2.1", "LGPL-3.0", "MIT", "BSD-2-Clause",
            "BSD-3-Clause", "ISC", "Apache-2.0", "MPL-2.0", "CC0-1.0", "CC-BY-3.0", "CC-BY-4.0", "CC-BY-SA-3.0",
            "CC-BY-SA-4.0", "freeware")
OPEN = {"GPL-2.0", "GPL-2.0-or-later", "GPL-3.0", "AGPL-3.0", "LGPL-2.1", "LGPL-3.0", "MIT", "BSD-2-Clause",
        "BSD-3-Clause", "ISC", "Apache-2.0", "MPL-2.0", "CC0-1.0", "CC-BY-3.0", "CC-BY-4.0", "CC-BY-SA-3.0", "CC-BY-SA-4.0"}
REQUIRED = ("id", "name", "kind", "vendor", "licence", "open_source", "formats", "macos_arm64", "homepage", "about",
            "source", "method")


class CatalogueError(ValueError):
    """The catalogue file is not valid (the message lists every problem)."""


def load(path=None, check=True):
    """The catalogue as a dict. It is validated first (ids and names must be safe as path parts, downloads https
    only), because the installer uses them to build folders and file names. check=False is for `store check`, which
    lists the problems itself."""
    data = json.loads(Path(path or HERE).read_text(encoding="utf-8"))
    if check:
        errs = validate(data)
        if errs:
            raise CatalogueError("the store's catalogue is not valid, so nothing was used from it: " + "; ".join(errs[:6])
                                 + (f" (and {len(errs) - 6} more)" if len(errs) > 6 else ""))
    return data


def items(path=None):
    return load(path)["items"]


def get(item_id, path=None):
    for it in items(path):
        if it["id"] == item_id:
            return it
    raise KeyError(f"no item {item_id!r} in the store's catalogue")


def safe_part(name):
    """True when name is fine as one file or folder name: not empty, not . or .., no slash, backslash, colon or
    control character."""
    name = str(name)
    return bool(name.strip()) and name.strip() not in (".", "..") and not re.search(r"[/\\:\x00-\x1f]", name) and name == name.strip()


def url_filename(url):
    """The file name a download URL ends in, decoded (%2F stays a slash so it can be refused) -> str or ''."""
    return urllib.parse.unquote(urllib.parse.urlparse(str(url)).path.rsplit("/", 1)[-1])


_SIZE = re.compile(r"^(\d+(?:\.\d+)?) ?(KB|MB|GB)$")


def size_bytes(item):
    """The catalogue's rough size for an item ("190 MB", "3 GB") in bytes, or 0 when it does not say."""
    m = _SIZE.match(str(item.get("size", "")).strip())
    return int(float(m.group(1)) * {"KB": 1e3, "MB": 1e6, "GB": 1e9}[m.group(2)]) if m else 0


def verification(item):
    """How a download of this item can be checked before it is trusted:
       "pinned"  the catalogue holds the publisher's sha256 (url items, or a github item with a fixed tag)
       "github"  checked against the fingerprint GitHub publishes for the release file, when it publishes one
       "none"    nothing to check it against: the person must confirm, in plain words, that it is not verified"""
    s = item["source"]
    if s.get("sha256"):
        return "pinned"
    return "github" if s.get("type") == "github" else "none"


def _https_ok(url):
    """True for an https URL with a host and no user:password@ part (a link like https://good.example@evil.example/x
    would otherwise look right at a glance)."""
    try:
        p = urllib.parse.urlparse(str(url))
        return str(url).startswith("https://") and bool(p.hostname) and "@" not in p.netloc
    except ValueError:
        return False


def validate(data):
    """-> a list of problems (empty when the catalogue is good)."""
    errs = []
    if not isinstance(data, dict):
        return ["the catalogue must be a JSON object"]
    if data.get("schema") != 1:
        errs.append("schema must be 1")
    if not re.match(r"^\d{4}\.\d{1,2}\.\d{1,2}$", str(data.get("version", ""))):
        errs.append("version must look like 2026.11.26")
    seen = set()
    if not isinstance(data.get("items"), list):
        return errs + ["items must be a list"]
    for n, it in enumerate(data["items"]):
        if not isinstance(it, dict):
            errs.append(f"item {n}: must be an object")
            continue
        where = str(it.get("id") or f"item {n}")
        if not isinstance(it.get("source"), dict):
            errs.append(f"{where}: source must be an object")
            continue
        for k in REQUIRED:
            if k not in it:
                errs.append(f"{where}: missing {k}")
        if errs and errs[-1].startswith(f"{where}: missing"):
            continue
        if not isinstance(it["id"], str) or not re.match(r"^[a-z0-9][a-z0-9-]*$", it["id"]):
            errs.append(f"{where}: id must be a string of lower-case letters, digits and dashes")
            continue
        if not isinstance(it["name"], str) or not safe_part(it["name"]) or it["name"].startswith((".", "~")):
            errs.append(f"{where}: name must be usable as a folder name (not empty, not starting with . or ~, no / \\ : or control characters)")
        if "size" in it and not _SIZE.match(str(it["size"]).strip()):
            errs.append(f"{where}: size must look like '190 MB' or '3 GB'")
        if "credit" in it and not (isinstance(it["credit"], str) and it["credit"].strip()):
            errs.append(f"{where}: credit must be a non-empty line of text")
        if str(it["licence"]).startswith("CC-BY") and not str(it.get("credit", "")).strip():
            errs.append(f"{where}: the licence {it['licence']} requires a credit: add a 'credit' field")
        if it["id"] in seen:
            errs.append(f"{where}: duplicate id")
        seen.add(it["id"])
        if it["kind"] not in KINDS:
            errs.append(f"{where}: kind {it['kind']!r} is not one of {KINDS}")
        if it["licence"] not in LICENCES:
            errs.append(f"{where}: licence {it['licence']!r} is not a known SPDX id (or 'freeware')")
        if not isinstance(it["open_source"], bool) or it["open_source"] != (it["licence"] in OPEN):
            errs.append(f"{where}: open_source must be {it['licence'] in OPEN} for {it['licence']}")
        if not isinstance(it["formats"], list) or not it["formats"] or any(f not in FORMATS for f in it["formats"]):
            errs.append(f"{where}: formats must be some of {FORMATS}")
        if it["macos_arm64"] not in (True, False, None):
            errs.append(f"{where}: macos_arm64 must be true, false or null")
        if not _https_ok(it["homepage"]):
            errs.append(f"{where}: homepage must be https, with a host and no user name or password in it")
        if it["method"] not in METHODS:
            errs.append(f"{where}: method must be one of {METHODS}")
        if (it["kind"] in CONTENT_KINDS) != (it["method"] == "content"):
            errs.append(f"{where}: content kinds (and only they) install as method 'content'")
        s = it["source"]
        t = s.get("type")
        if t == "github":
            if not re.match(r"^[\w.-]+/[\w.-]+$", str(s.get("repo", ""))) or ".." in str(s.get("repo", "")):
                errs.append(f"{where}: github source needs repo 'owner/name'")
            if "tag" in s and not re.match(r"^[\w.+-]+$", str(s["tag"])):
                errs.append(f"{where}: github tag must be letters, digits and . _ + - only")
            if s.get("sha256") and (not s.get("tag") or not re.match(r"^[0-9a-f]{64}$", str(s["sha256"]))):
                errs.append(f"{where}: a github sha256 must be 64 lower-case hex digits and needs a fixed tag")
            try:
                re.compile(str(s.get("asset", "")))
                if not s.get("asset"):
                    raise re.error("empty")
            except re.error as e:
                errs.append(f"{where}: asset pattern: {e}")
        elif t == "url":
            if not _https_ok(s.get("url", "")):
                errs.append(f"{where}: url sources must be https, with a host and no user name or password in it")
            elif not safe_part(url_filename(s["url"])):
                errs.append(f"{where}: the download's file name ({url_filename(s['url'])!r}) is not a plain file name")
            if not s.get("version"):
                errs.append(f"{where}: url sources need a version")
            if s.get("sha256") and not re.match(r"^[0-9a-f]{64}$", str(s["sha256"])):
                errs.append(f"{where}: sha256 must be 64 lower-case hex digits")
        elif t == "page":
            if it["method"] != "page":
                errs.append(f"{where}: a page source installs as method 'page'")
        else:
            errs.append(f"{where}: source type must be github, url or page")
    return errs


def search(its, q="", kind="", fmt="", licence="", open_source=None):
    """Filter items. q matches name, vendor, about, kind and formats; licence 'open' / 'freeware' or an exact id."""
    words = [w for w in q.lower().split() if w]
    out = []
    for it in its:
        hay = " ".join([it["name"], it["vendor"], it["about"], it["kind"], " ".join(it["formats"]), it["licence"]]).lower()
        if any(w not in hay for w in words):
            continue
        if kind and it["kind"] != kind:
            continue
        if fmt and fmt not in it["formats"]:
            continue
        if licence == "open" and not it["open_source"] or licence == "freeware" and it["open_source"]:
            continue
        if licence not in ("", "open", "freeware") and it["licence"] != licence:
            continue
        if open_source is not None and it["open_source"] != open_source:
            continue
        out.append(it)
    return out
