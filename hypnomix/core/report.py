"""Problem reports and crash records: text written on this computer, shown to the person, sent only by them.

HypnoMix has no server of its own and never phones home. When something breaks it writes a REPORT here, on this
computer, shows it, and helps the person send it themselves (the project's public issue tracker, or anything else: it
is plain Markdown to copy or save). Nothing in this module touches the network, a DAW or the clipboard on its own; the
two helpers that do something outside the process (copy_text, open_issue_page) are called only for a click or an option
the person gave.

    build(kind, what_happened, expected, include, names, ...)   the report as text (compose() also says what could be included)
    Scrubber                      everything is scrubbed before it enters a report (below)
    write_crash(where, command, exc)   a crash record in <HypnoMix home>/crashes/ (20 kept; oldest removed), or None
    crashes(), crash(n), crash_text(rec), dismiss(...), offered(...)   reading them back
    record_last(...) / last_run()  the last command or job that ended badly (or, from the app, any job) and how it ended
    page_error(...)               a script error from the app's page, rate limited, recorded like a crash
    copy_text(text)               pbcopy / clip / wl-copy / xclip / xsel when present: (done, how or why not)
    open_issue_page(opener)       the project's new-issue page, opened with the TEMPLATE NAME ONLY in the address

What is scrubbed, always, before anything enters a report: the home folder becomes "~"; every other path becomes
"<file 1>.wav" (its last part replaced by a placeholder, the extension kept, the same file always the same number
within one report); song, project, track and clip names that a scan knows become "<track 3>" and the like; API keys and
tokens (the ones saved for the Assistant, any secret in the environment, and anything shaped like one) become
"<hidden>". Environment variables are never dumped: only a fixed list of HypnoMix's own switches, by name, set or not.
With "keep names" on, a path keeps its last part (the file name) and known names stay; the home folder and keys are
hidden whatever the choice.
"""
import getpass
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ISSUE_URL = "https://github.com/drtranceypants/hypnomix/issues/new?template=bug_report.yml"    # the template's name only
ISSUES = "github.com/drtranceypants/hypnomix/issues"
KEEP = 20                      # crash records kept; the oldest go
FRAMES = 30                    # traceback lines kept (the innermost)
LOG_LINES = 60                 # the tail of the last job's log
PART_NAMES = ("log", "crash", "scan")
ALL = PART_NAMES

# hypnomix's own switches: the only environment variables a report mentions, by name and whether they are set
ENV_NAMES = ("HYPNOMIX_HOME", "HYPNOMIX_APP_HOME", "HYPNOMIX_USER_HOME", "HYPNOMIX_OUT", "HYPNOMIX_DEBUG",
             "HYPNOMIX_DISKCARE", "HYPNOMIX_NO_CACHE", "HYPNOMIX_PORT", "HYPNOMIX_DAW", "HYPNOMIX_FORCE_LIVE_VERSION",
             "HYPNOMIX_STORE_ROOT", "HYPNOMIX_ENGINE", "HYPNOMIX_PYTHON")

_LOCK = threading.Lock()


# ---------------------------------------------------------------- where things are (read now, so a test can move them)
def home():
    env = os.environ.get("HYPNOMIX_HOME")
    if env:
        return Path(env).expanduser()
    from hypnomix.core import paths
    return paths.HOME


def crash_dir():
    return home() / "crashes"


def last_file():
    return home() / "last-run.json"


def app_work():
    """The app's work folder, without making it (a report never creates folders)."""
    return Path(os.environ.get("HYPNOMIX_APP_HOME", "~/Documents/Hypnomix")).expanduser()


def utcnow():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- scrubbing
_HOME_RE = re.compile(r"(?:/Users|/home)/[^/\s\"'<>\\:]+|[A-Za-z]:\\{1,2}Users\\{1,2}[^\\\s\"'<>/:]+")
_NOTSTART = r"(?<![\w:/.~$%\-])"          # a path does not start in the middle of a word, a URL, an option or a version
_START_POSIX = re.compile(_NOTSTART + r"(?:~(?=[/\\])|/(?!(?:api|mcp|audio|wiki)\b)(?=[^\s/]))")
_START_WIN = re.compile(r"(?<![\w])(?:[A-Za-z]:(?=[\\/])|\\\\(?=[\w.$]))")
_REL = re.compile(_NOTSTART + r"(?!hypnomix[/\\])(?!https?)((?:(?:<[^<>\n]{1,40}>|[\w.\-+@#%&=,])+[/\\]{1,2})+(?:<[^<>\n]{1,40}>|[\w.\-+@#%&=,])+)")
_HARD = set("\"'|*?:()\n\r\t")
# Words that end a path written with spaces in it: "wrote /a/b/c and ..." ends at "c". The second group ends it only when
# a lowercase word, a path or the end follows (so "Night Drive" and "Slow Burn" stay whole).
_STOP = frozenset("is was are not as then failed wrote read see but because while when which it this that no has had can cannot "
                  "could should will did does do be so if after before into".split())
_SOFT = frozenset("and or of the a an in to at on for with from by".split())
_EXT = re.compile(r"\.([A-Za-z0-9]{1,5})$")
# File types a person names their work with: a name that ends in one of these is a file name wherever it appears.
_NAME_EXTS = ("wav|wave|aif|aiff|aifc|flac|mp3|m4a|aac|ogg|oga|opus|wma|caf|mp4|mov|m4v|als|alc|rpp|rpp-bak|ardour|mid|midi|"
              "logicx|ptx|ptf|flp|cpr|reapeaks|sfk|zip")
_QUOTED_A = re.compile(r"'([^'\n]{1,160}\.(?:" + _NAME_EXTS + r"))'", re.I)
_QUOTED_B = re.compile(r'"([^"\n]{1,160}\.(?:' + _NAME_EXTS + r'))"', re.I)
_ERRNO = re.compile(r"(?i)((?:no such file or directory|permission denied|is a directory|not a directory|file exists|"
                    r"directory not empty|file name too long|read-only file system)\W{0,3}:\s*)(['\"])([^'\"\n]{1,160})\2")
_BARE_LAST = re.compile(r"(?<![\w<])[^\s'\"|*?:<>]+\.(?:" + _NAME_EXTS + r")(?![\w\-])", re.I)
_DONE = re.compile(r"^(?:~|<[A-Za-z ]{2,12} \d+>(?:\.\w+)?)$")
_PROSE = frozenset(_STOP | {"file", "files", "stem", "stems", "audio", "loading", "opening", "reading", "writing", "saving",
                            "rendering", "processing", "using", "named", "called", "open", "load", "save", "write", "render",
                            "track", "clip", "song", "project", "folder", "directory", "path"})


def _has_ext(x):
    m = _EXT.search(x)
    return bool(m and re.search(r"[A-Za-z]", m.group(1)) and len(x) > len(m.group(0)))

_SECRET_PATTERNS = [
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"\bgsk_[A-Za-z0-9]{16,}"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-~+/=]{12,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]*"),             # a JWT
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),                                            # an AWS key id
    re.compile(r"(?i)\bX-Hypnomix\b[\"']?\s*[=:]\s*\S+"),
    re.compile(r"(?i)\b(?:set-)?cookie\s*:[^\n]+"),                                           # a Cookie / Set-Cookie header, to the end of its line
]
# A query parameter that carries a secret under a short name: ?key=..., &sig=..., &code=...
_QUERY_SECRET = re.compile(r"(?i)([?&](?:key|auth|sig|signature|code|session|sid|pass|pwd|jwt|access)=)[^\s&\"'#]+")
_SECRET_PAIR = re.compile(r"(?i)\b([\w.-]*(?:api[_-]?key|token|secret|passw(?:or)?d|authorization|credential)[\w.-]*[\"']?)"
                          r"(\s*[=:]\s*)(?:(?:basic|bearer|token|digest|negotiate)\s+)?(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s,;&\"']+)")
_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s@:]+(?::[^/\s@]*)?@")     # ssh://user@host, https://user:pw@host
_EMAIL = re.compile(r"(?<![\w.+\-])[A-Za-z0-9][A-Za-z0-9._%+\-]*@[A-Za-z0-9][A-Za-z0-9\-]*(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}(?![\w])")
_LONG_TOKEN = re.compile(r"(?<![\w/.\-])(?=[A-Za-z0-9_\-]*[A-Za-z])(?=[A-Za-z0-9_\-]*\d)[A-Za-z0-9_\-]{28,}(?![\w/\-])")
HIDDEN = "<hidden>"


def _env_secrets():
    out = []
    for k, v in os.environ.items():
        if re.search(r"KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH", k, re.I) and isinstance(v, str) and len(v.strip()) >= 8:
            out.append(v.strip())
    return out


def _saved_keys():
    """The keys saved for the Assistant (the same list the chat hides), when the app's module can be read."""
    try:
        from hypnomix.app import chat
        return list(chat.saved_keys())
    except Exception:
        return []


def _homes():
    out = set()
    for h in (os.path.expanduser("~"), os.environ.get("HYPNOMIX_USER_HOME", "")):
        h = str(h or "").rstrip("/\\")
        if len(h) > 3:
            out.update({h, h.replace("\\", "/"), h.replace("/", "\\")})
    return sorted(out, key=len, reverse=True)


def _username():
    try:
        u = getpass.getuser()
    except Exception:
        return ""
    return u if len(u) >= 3 else ""


class Scrubber:
    """One report's scrubbing: the same file or name is always the same placeholder within it."""

    def __init__(self, keep_names=False, known_paths=(), names=None):
        self.keep_names = bool(keep_names)
        self._files = {}                    # path (home as ~) -> number
        self._folders = {}
        self._names = {}                    # name -> kind
        self._ids = {}                      # (kind, name) -> number
        self._count = Counter()
        self._rx = None
        self._secrets = None
        self._homelist = _homes()
        self._user = _username()
        for p in known_paths:
            self.add_path(p)
        for kind, vals in (names or {}).items():
            self.add_names(kind, vals)

    # -- what it knows
    def add_path(self, p):
        p = str(p or "").strip()
        if len(p) > 3:
            leaf = re.split(r"[\\/]+", p.rstrip("\\/"))[-1]
            if leaf:
                self.add_names("song", [Path(leaf).stem if _EXT.search(leaf) else leaf])

    def add_names(self, kind, vals):
        for v in vals or ():
            v = unicodedata.normalize("NFC", str(v).strip())               # a Mac file name is NFD; the text is matched as NFC
            if len(v) >= 3 and not v.isdigit() and v not in self._names and not re.fullmatch(r"[\W_]+", v):
                self._names[v] = kind
                self._rx = None

    # -- the pieces
    def _hide_secrets(self, s):
        if self._secrets is None:
            self._secrets = sorted({k for k in _saved_keys() + _env_secrets() if len(k) >= 6}, key=len, reverse=True)
        tok = getattr(sys.modules.get("hypnomix.app.server"), "TOKEN", "")      # the running app's own token, when this is the app
        for k in ([tok] if isinstance(tok, str) and len(tok) >= 6 else []) + self._secrets:
            if k in s:
                s = s.replace(k, HIDDEN)
        for rx in _SECRET_PATTERNS:
            s = rx.sub(HIDDEN, s)
        s = _SECRET_PAIR.sub(lambda m: m.group(1) + m.group(2) + HIDDEN, s)
        s = _QUERY_SECRET.sub(lambda m: m.group(1) + HIDDEN, s)
        s = _USERINFO.sub(r"\1", s)
        s = _EMAIL.sub("<email>", s)
        return _LONG_TOKEN.sub(HIDDEN, s)

    def _shorten_home(self, s, generic=True):
        for h in self._homelist:
            s = s.replace(h, "~")
        return _HOME_RE.sub("~", s) if generic else s

    def _reduce(self, raw):
        """One path (as found) -> what the report shows."""
        p = raw.strip()
        key = self._shorten_home(p, False)
        parts = [x for x in re.split(r"[\\/]+", key.rstrip("\\/")) if x]
        if key in ("~", "~/", "~\\") or not parts:
            return "~" if key.startswith("~") or not parts else raw
        leaf = parts[-1]
        if leaf == "~":
            return "~"
        if self.keep_names:
            return leaf
        m = _EXT.search(leaf)
        ext = m.group(0) if m and re.search(r"[A-Za-z]", m.group(1)) and len(leaf) > len(m.group(0)) else ""
        table, word = (self._files, "file") if ext else (self._folders, "folder")
        if key not in table:
            self._count[word] += 1
            table[key] = self._count[word]
        return f"<{word} {table[key]}>{ext}"

    @staticmethod
    def _paren(s, k):
        """Where a bracketed part of a name that starts at s[k] == "(" ends (just after the ")"), or 0 when it is not one:
        a short part with no spaces or quotes breaking it, and a ")" that closes it."""
        c = s.find(")", k)
        return c + 1 if 0 < c - k <= 40 and not re.search(r"[\n\"'<>]", s[k:c]) and (c + 1 >= len(s) or s[c + 1] != "(") else 0

    @staticmethod
    def _paren_name(s, m):
        """True when the words from s[m] ("(...") on end in a file name's extension within a few words."""
        words = s[m:m + 120].split(" ")[:5]
        for n in range(1, len(words) + 1):
            w = " ".join(words[:n])
            if re.search(r"\)[^\s\"']*\.[A-Za-z][A-Za-z0-9]{0,4}$", w) and w.count("(") == w.count(")") and "\n" not in w:
                return True
        return False

    def _path_end(self, s, i, drive):
        """Where the path that starts at s[i] ends. A path may have spaces in it (a folder named for a song); it stops at a
        quote, a bracket or a colon, at the end of a file name that has its extension, and before a word that is plainly
        prose."""
        n, j, extra = len(s), i, 0
        while True:
            k = j
            while k < n and not s[k].isspace() and (s[k] not in _HARD or (drive and k == i + 1 and s[k] == ":")
                                                    or (s[k] == "(" and self._paren(s, k))):
                k = self._paren(s, k) if s[k] == "(" else k + 1
            end = k
            while end > j and s[end - 1] in ",;!?.":
                end -= 1
            if end != k or k >= n or s[k] != " " or extra >= 6:
                return end
            if re.search(r"\.[A-Za-z][A-Za-z0-9]{0,4}$", s[i:end]):
                return end
            m = k + 1
            e = m
            while e < n and not s[e].isspace():
                e += 1
            w = s[m:e]
            if not w or w[0] in "/~\"'<(" or w.startswith(("http", "\\\\")) or re.match(r"[A-Za-z]:[\\/]", w):
                if w[:1] == "(" and self._paren_name(s, m):          # "Slow Burn (mix 2).wav": the bracket is part of the name
                    j, extra = m, extra + 1
                    continue
                return end
            lw = re.sub(r"[^\w]+$", "", w).lower()
            if lw in _STOP:
                return end
            if lw in _SOFT:
                f = s[e + 1:e + 2] if e < n and s[e] == " " else ""
                if e >= n or s[e] != " " or f == "" or f.islower() or f in "/~":
                    return end
            j, extra = m, extra + 1

    def _sub_paths(self, s, start_rx, drive):
        out, pos = [], 0
        for m in start_rx.finditer(s):
            if m.start() < pos:
                continue
            end = self._path_end(s, m.start(), drive)
            if end <= m.end():
                continue
            out.append(s[pos:m.start()])
            out.append(self._reduce(s[m.start():end]))
            pos = end
        out.append(s[pos:])
        return "".join(out)

    def _paths(self, s):
        s = self._shorten_home(s, False)
        s = self._sub_paths(s, _START_WIN, True)
        s = self._sub_paths(s, _START_POSIX, False)
        s = _REL.sub(lambda m: self._reduce(m.group(1)) if (len(re.findall(r"[/\\]+", m.group(1))) >= 2
                                                              or _has_ext(m.group(1))) else m.group(1), s)
        return self._bare(s)

    def _bare(self, s):
        """Names that are not written as a path: 'Song Name.als' in quotes (how Python's own file errors quote them), the
        quoted thing after "No such file or directory:", and a bare 'Lead Vocal.wav' in a log line. With names kept, none."""
        if self.keep_names:
            return s

        def one(m):
            return m.group(0) if _DONE.match(m.group(1)) else m.group(0).replace(m.group(1), self._reduce(m.group(1)), 1)
        s = _QUOTED_A.sub(one, s)
        s = _QUOTED_B.sub(one, s)
        s = _ERRNO.sub(lambda m: m.group(1) + m.group(2) + (m.group(3) if _DONE.match(m.group(3)) else self._reduce(m.group(3)))
                       + m.group(2), s)
        out, pos = [], 0
        for m in _BARE_LAST.finditer(s):
            if m.start() < pos:
                continue
            i, words = m.start(), 0
            while words < 6 and i > pos and s[i - 1] == " ":
                k = i - 1
                while k > pos and not s[k - 1].isspace():
                    k -= 1
                w = s[k:i - 1]
                pm = re.search(r"<folder \d+> $", s[pos:i])
                if pm:                                            # the start of a relative path that was reduced already
                    i = pos + pm.start()
                    continue
                part = bool(re.search(r"[A-Za-z0-9)][/\\]", w)) and not w.startswith(("http", "~"))     # "stems/Lead": a folder of the name
                if (not w or w[0] == "-" or any(c in w for c in "'\"|*?:<>,;") or w.lower().strip("()!.") in _PROSE
                        or w.startswith(("http", "~")) or (not part and w[0].islower() and w.lower() not in _SOFT
                                                           and m.group(0)[:1].isupper())):
                    break
                i, words = k, words + 1
            while i < m.start() and s[i:m.start()].split(" ", 1)[0][:1].islower() and s[i:].split(" ", 1)[0].lower() in _SOFT:
                i += len(s[i:].split(" ", 1)[0]) + 1                  # "from Lead Vocal.wav": the lowercase "from" is prose
            out.append(s[pos:i])
            out.append(self._reduce(re.split(r"[\\/]+", s[i:m.end()])[-1]))      # the same name, the same number
            pos = m.end()
        out.append(s[pos:])
        return "".join(out)

    def _names_in(self, s):
        if self.keep_names or not self._names:
            return s
        s = unicodedata.normalize("NFC", s)
        if self._rx is None:
            alt = "|".join(re.escape(n) for n in sorted(self._names, key=len, reverse=True))
            self._rx = re.compile(r"(?<![\w])(?:" + alt + r")(?![\w])")

        def one(m):
            n = m.group(0)
            kind = self._names[n]
            if (kind, n) not in self._ids:
                self._count[kind] += 1
                self._ids[(kind, n)] = self._count[kind]
            return f"<{kind} {self._ids[(kind, n)]}>"
        return self._rx.sub(one, s)

    def text(self, s, limit=None):
        """`s` with keys, paths, the home folder and (unless names are kept) known names hidden."""
        if s is None:
            return ""
        s = s if isinstance(s, str) else str(s)
        s = self._hide_secrets(s)
        s = self._names_in(self._shorten_home(s, False))
        s = self._paths(s)
        s = self._shorten_home(s)
        if self._user:
            s = re.sub(r"(?<![\w])" + re.escape(self._user) + r"(?![\w])", "<user>", s)
        if limit and len(s) > limit:
            s = s[:limit].rstrip() + "…"
        return s

    def lines(self, lines, limit=300):
        return [self.text(x, limit) for x in lines]


def scrub(text, keep_names=False):
    """A quick one-off scrub (no names known): keys, the home folder and paths."""
    return Scrubber(keep_names=keep_names).text(text)


# ---------------------------------------------------------------- what a report says about this computer
def version():
    try:
        from hypnomix.app import update
        return str(update.current())
    except Exception:
        return "unknown"


def _git_commit(root):
    try:
        head = (root / ".git" / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head.split(None, 1)[1].strip()
            f = root / ".git" / ref
            if f.is_file():
                return f.read_text(encoding="utf-8").strip()[:7]
            for line in (root / ".git" / "packed-refs").read_text(encoding="utf-8").splitlines():
                if line.endswith(" " + ref):
                    return line.split()[0][:7]
            return ""
        return head[:7]
    except (OSError, IndexError):
        return ""


def install_kind():
    """How HypnoMix is installed: the packaged Mac or Windows app, a source checkout, or pip."""
    try:
        from hypnomix import extras
        packaged = extras.bundled()
    except Exception:
        packaged = False
    if packaged:
        what = "the Mac app" if sys.platform == "darwin" else "the Windows app"
        try:
            from hypnomix.app import engine_addon
            v = engine_addon.installed_versions()
            what += f" (HypnoMix DAW {v[0]} added)" if v else ""
        except Exception:
            pass
        return what
    root = Path(__file__).resolve().parents[2]
    if (root / ".git").exists() and (root / "pyproject.toml").exists():
        c = _git_commit(root)
        return "a source checkout" + (f" (commit {c})" if c else "")
    return "pip (an installed package)"


def computer():
    system = platform.system() or sys.platform
    if system == "Darwin":
        return f"macOS {platform.mac_ver()[0] or platform.release()} ({platform.machine()})"
    if system == "Windows":
        return f"Windows {platform.release()} ({platform.version()}, {platform.machine()})"
    return f"{system} {platform.release()} ({platform.machine()})"


def helpers():
    """Which optional programs are present: yes or no, never a path."""
    from hypnomix.core import tools
    return [("ffmpeg", bool(shutil.which("ffmpeg"))), ("the stretch program (Rubber Band)", bool(tools.rubberband_path()))]


def packages():
    out = []
    try:
        from importlib.metadata import version as v
        for n in ("numpy", "scipy", "soundfile"):
            try:
                out.append(f"{n} {v(n)}")
            except Exception:
                out.append(f"{n}: not installed")
    except Exception:
        pass
    return out


DAW_WORDS = {"live": "Ableton Live", "reaper": "REAPER", "ardour": "HypnoMix DAW", "other": "another DAW"}


def setup_daw():
    try:
        from hypnomix.workflow import prefs
        d = prefs.setup_daw()
    except Exception:
        d = ""
    return DAW_WORDS.get(d, d) or "not chosen"


def switches():
    on = [n for n in ENV_NAMES if os.environ.get(n)]
    off = [n for n in ENV_NAMES if n not in on]
    return on, off


# ---------------------------------------------------------------- the open scan
_NAME_KEYS = {"track", "tracks", "clip", "clips", "name", "names", "part", "parts", "lead", "guide", "title", "song", "set_name"}


def newest_scan():
    """The scan folder the app wrote last (findings.json newest), or None."""
    base = app_work() / "scan"
    best, when = None, -1.0
    try:
        for d in base.iterdir():
            f = d / "findings.json"
            try:
                t = f.stat().st_mtime
            except OSError:
                continue
            if t > when:
                best, when = d, t
    except OSError:
        return None
    return best


def _walk_names(o, out, depth=0):
    if depth > 6:
        return
    if isinstance(o, dict):
        for k, v in o.items():
            if str(k) in _NAME_KEYS:
                kind = "track" if k in ("track", "tracks", "lead", "guide", "part", "parts") else "clip" if k in ("clip", "clips") else "song"
                for s in (v if isinstance(v, list) else [v]):
                    if isinstance(s, str):
                        out.setdefault(kind, set()).add(s)
            elif isinstance(v, (dict, list)):
                _walk_names(v, out, depth + 1)
    elif isinstance(o, list):
        for v in o[:5000]:
            _walk_names(v, out, depth + 1)


def scan_info(scan_dir=None):
    """What the open scan tells a report: {dir, counts: {tool: n}, names: {kind: set}, source} or None. Read-only."""
    d = Path(scan_dir) if scan_dir else newest_scan()
    if not d:
        return None
    try:
        data = json.loads((d / "findings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    counts = Counter()
    for f in data.get("findings") or []:
        if isinstance(f, dict):
            t = re.sub(r"[^A-Za-z0-9_-]", "", str(f.get("tool") or "other"))[:30] or "other"
            counts[t] += 1
    names = {}
    _walk_names(data.get("findings") or [], names)
    src = str(data.get("set") or "")
    names.setdefault("song", set())
    if src:
        names["song"].add(Path(src).stem)
    names["song"].add(d.name)
    for extra in ("scan.json", "meta.json"):
        try:
            _walk_names(json.loads((d / extra).read_text(encoding="utf-8")), names)
        except (OSError, ValueError):
            pass
    return dict(dir=d, counts=dict(counts), names=names, source=src)


# ---------------------------------------------------------------- the last thing that ran
def record_last(source, what, status, reason="", exit_code=None, log=(), kind=""):
    """Keep one small private record of the last command (when it ended badly) or job (the app, every one) and how it
    ended. Never raises: a report is a help, not a duty."""
    try:
        from hypnomix.core.paths import write_private
        rec = dict(when=utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), source=source, what=str(what)[:200], kind=str(kind)[:40],
                   status=str(status)[:40], reason=str(reason)[:600], exit=exit_code,
                   log=[str(x)[:400] for x in list(log)[-LOG_LINES:]])
        write_private(last_file(), json.dumps(rec, indent=1))
    except Exception:
        pass


def last_run():
    try:
        d = json.loads(last_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- crash records
_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[a-z0-9_-]+(?:-\d+)?$")
_RECENT = {}                  # signature -> (when, id): the same crash twice in five minutes is one record
_PAGE_TIMES = []
PAGE_PER_MINUTE = 5


def _slug(s):
    return re.sub(r"[^a-z0-9_-]+", "-", str(s or "").lower()).strip("-")[:40] or "unknown"


def _kind_of(v):
    v = str(v)
    if re.fullmatch(r"[-+]?\d+(\.\d+)?([eE][-+]?\d+)?", v):
        return "<number>"
    if "/" in v or "\\" in v or v.startswith("~") or re.search(r"\.[A-Za-z0-9]{1,5}$", v):
        return "<path>"
    try:
        if v and len(v) < 400 and os.path.exists(v):
            return "<path>"
    except (OSError, ValueError):
        pass
    return "<text>"


def option_summary(args):
    """The options a command was given, by NAME, each value replaced by its kind: ['--mix <path>', '--bpm <number>']."""
    out, a, i = [], [str(x) for x in args], 0
    num = re.compile(r"-\d+\.?\d*([eE][-+]?\d+)?$|-\.\d+$")
    while i < len(a):
        x = a[i]
        if x.startswith("-") and len(x) > 1 and not num.match(x):
            name, eq, val = x.partition("=")
            if not re.fullmatch(r"--?[A-Za-z][\w-]{0,40}", name):
                out.append("<text>")
            elif eq:
                out.append(f"{name} {_kind_of(val)}")
            elif i + 1 < len(a) and (not a[i + 1].startswith("-") or num.match(a[i + 1])):
                out.append(f"{name} {_kind_of(a[i + 1])}")
                i += 1
            else:
                out.append(name)
        else:
            out.append(_kind_of(x))
        i += 1
    return out[:40]


def _frames(tb):
    import traceback
    pkg = Path(__file__).resolve().parents[1]
    std = Path(os.__file__).resolve().parent
    out = []
    for fr in traceback.extract_tb(tb):
        f = Path(fr.filename)
        try:
            fr_path = f.resolve()
        except OSError:
            fr_path = f
        if pkg in fr_path.parents:
            name = "hypnomix/" + fr_path.relative_to(pkg).as_posix()
        elif "site-packages" in fr_path.parts:
            name = "<site-packages>/" + "/".join(fr_path.parts[fr_path.parts.index("site-packages") + 1:])
        elif std in fr_path.parents or fr.filename.startswith("<"):
            name = ("<python>/" + fr_path.relative_to(std).as_posix()) if std in fr_path.parents else fr.filename
        else:
            name = "<other file>" + fr_path.suffix[:6]          # code that is not hypnomix's, Python's or a package's
        out.append(dict(file=name[:160], line=fr.lineno, func=re.sub(r"[^\w<>.]", "", str(fr.name))[:60]))
    return out[-FRAMES:]


def _list_ids():
    d = crash_dir()
    try:
        names = [p.stem for p in d.iterdir() if p.suffix == ".json" and _ID_RE.match(p.stem)]
    except OSError:
        return []
    return sorted(names, key=_id_key)


def _id_key(rid):
    """Oldest first: by the second, then the command, then the number after it as a NUMBER ("-10" comes after "-9": as text
    it came before "-2", so with more than nine records in one second the trim deleted the newest ones)."""
    m = re.match(r"^(\d{8}T\d{6}Z)-(.+?)(?:-(\d+))?$", rid)
    return (m.group(1), m.group(2), int(m.group(3) or 1)) if m else (rid, "", 0)


def _state():
    try:
        s = json.loads((crash_dir() / "_state.json").read_text(encoding="utf-8"))
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(s):
    try:
        from hypnomix.core.paths import write_private
        write_private(crash_dir() / "_state.json", json.dumps(s))
    except Exception:
        pass


def write_crash(where, command, exc=None, argv=(), exc_info=None, extra=None):
    """Write one crash record and return {id, path}; None when it was the same crash a moment ago (the earlier one is
    returned) or when it could not be written (`error` says why). The record has the version, platform, the command
    name, its option NAMES with each value replaced by its kind, the exception type, its scrubbed message and the
    scrubbed traceback (file names inside the package, the innermost 30 lines). 20 records are kept."""
    try:
        et, ev, tb = exc_info if exc_info else (type(exc), exc, getattr(exc, "__traceback__", None))
        sc = Scrubber()
        frames = _frames(tb) if tb is not None else []
        sig = (where, et.__name__ if et else "", frames[-1]["file"] if frames else "", frames[-1]["line"] if frames else 0,
               str(ev)[:80] if where == "page" else "")          # a page's errors have no traceback here: the message tells them apart
        now = time.time()
        with _LOCK:
            seen = _RECENT.get(sig)
            if seen and now - seen[0] < 300 and (crash_dir() / (seen[1] + ".json")).exists():
                return dict(id=seen[1], path=str(crash_dir() / (seen[1] + ".json")), repeat=True)
            stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
            base = f"{stamp}-{_slug(command)}"
            cd = crash_dir()
            from hypnomix.core.paths import private_dir
            from hypnomix.core import atomic
            private_dir(cd)
            # the next number after the highest one already used this second for this command (not the first free one: when
            # the trim removes the oldest, a free number is an old one, and the record just written would be the oldest)
            have = [_id_key(i) for i in _list_ids() if i == base or re.fullmatch(re.escape(base) + r"-\d+", i)]
            rid = f"{base}-{max(k[2] for k in have) + 1}" if have else base
            cause = getattr(ev, "__cause__", None) or getattr(ev, "__context__", None)
            rec = dict(format=1, id=rid, when=utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), where=str(where), command=str(command)[:60],
                       version=version(), install=install_kind().split(" (")[0], computer=computer(),
                       python=platform.python_version(), options=option_summary(argv),
                       exception=(et.__name__ if et else "Exception"), message=sc.text(str(ev), 500), traceback=frames)
            if cause is not None:
                rec["cause"] = sc.text(f"{type(cause).__name__}: {cause}", 300)
            if extra:
                rec.update({k: sc.text(v, 300) if isinstance(v, str) else v for k, v in extra.items()})
            path = cd / (rid + ".json")
            atomic.write_text(path, json.dumps(rec, indent=1), backup=False)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            for k in [k for k, v in _RECENT.items() if now - v[0] >= 300]:       # nothing here lives past its five minutes
                del _RECENT[k]
            _RECENT[sig] = (now, rid)
            _trim()
        return dict(id=rid, path=str(path))
    except Exception as e:                      # the one place that must never raise: a bug report about a bug report
        return dict(id="", path="", error=f"{type(e).__name__}: {e}")


def _trim():
    ids = _list_ids()
    for old in ids[:-KEEP] if len(ids) > KEEP else []:
        try:
            (crash_dir() / (old + ".json")).unlink()
        except OSError:
            pass


def crashes():
    """Every crash record, newest first, each with its state: new (never offered), offered or dismissed."""
    st = _state()
    off, dis = set(st.get("offered") or []), set(st.get("dismissed") or [])
    out = []
    for rid in reversed(_list_ids()):
        try:
            rec = json.loads((crash_dir() / (rid + ".json")).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict):
            continue
        rec["id"] = rid
        rec["state"] = "dismissed" if rid in dis else "offered" if rid in off else "new"
        out.append(rec)
    return out


def crash(n=1):
    """The n-th newest crash record (1 = newest), or None."""
    rs = crashes()
    return rs[n - 1] if 1 <= n <= len(rs) else None


def crash_by_id(rid):
    return next((r for r in crashes() if r["id"] == rid), None)


def mark(ids, state="dismissed"):
    """Remember that these records were offered (shown once) or dismissed. The records themselves stay."""
    ids = [i for i in ids if isinstance(i, str) and _ID_RE.match(i)]
    if not ids:
        return
    with _LOCK:
        st = _state()
        for key in (("offered", "dismissed") if state == "dismissed" else ("offered",)):
            cur = list(st.get(key) or [])
            st[key] = (cur + [i for i in ids if i not in cur])[-200:]
        _save_state(st)


def crash_text(rec):
    """One crash record as Markdown (what a report's crash part says)."""
    if not rec:
        return ""
    lines = [f"- When: {rec.get('when', '')} (UTC)", f"- Where: {rec.get('where', '')}, {rec.get('command', '')}",
             f"- HypnoMix {rec.get('version', '')}, {rec.get('install', '')}, {rec.get('computer', '')}, Python {rec.get('python', '')}",
             f"- Options given (values hidden): {' '.join(rec.get('options') or []) or 'none'}",
             f"- Error: {rec.get('exception', '')}: {rec.get('message', '')}"]
    if rec.get("cause"):
        lines.append(f"- Caused by: {rec['cause']}")
    if rec.get("page"):
        lines.append(f"- Page: {rec['page']}")
    tb = rec.get("traceback") or []
    if tb:
        lines += ["", "```text"] + [f"{f.get('file', '')}:{f.get('line', '')} in {f.get('func', '')}" for f in tb] + ["```"]
    return "\n".join(lines)


def crash_sentence(info):
    """The one sentence a command ends with after a crash."""
    p = home_short(info.get("path", ""))
    if info.get("path"):
        return (f"HypnoMix hit a bug and could not finish: a report was saved at {p} and nothing was sent; "
                "`hypnomix report --crash` shows it and how to send it.")
    return ("HypnoMix hit a bug and could not finish; the report could not be saved "
            f"({info.get('error') or 'unknown reason'}) and nothing was sent; `hypnomix report` shows what it can and how to send it.")


def home_short(p):
    for h in _homes():
        if p.startswith(h):
            return "~" + p[len(h):]
    return p


def page_error(message, source="", line=0, stack="", page=""):
    """A script error from the app's page: recorded like a crash, at most PAGE_PER_MINUTE a minute (None when over)."""
    now = time.time()
    with _LOCK:
        _PAGE_TIMES[:] = [t for t in _PAGE_TIMES if now - t < 60]
        if len(_PAGE_TIMES) >= PAGE_PER_MINUTE:
            return None
        _PAGE_TIMES.append(now)
    sc = Scrubber()
    src = re.sub(r"^https?://[^/]+", "", str(source or ""))[:120]
    err = RuntimeError(str(message)[:500])
    info = write_crash("page", "page-script", exc=err,
                       extra=dict(page=sc.text(f"{src}:{int(line or 0)}" + (f" {page}" if page else ""), 200),
                                  stack=sc.text(re.sub(r"https?://[^/\s]+", "", str(stack or ""))[:2000], 2000)))
    return info


def dismiss_all():
    mark([r["id"] for r in crashes()], "dismissed")


def forget_recent():
    """Test helper: the same crash is written again."""
    with _LOCK:
        _RECENT.clear()
        _PAGE_TIMES.clear()


# ---------------------------------------------------------------- the report
def _fence(text):
    n = max([len(m) for m in re.findall(r"`+", text)] + [2]) + 1
    return "`" * n


def _block(lines):
    body = "\n".join(lines)
    f = _fence(body)
    return [f + "text", body, f]


def compose(kind="bug", what_happened="", expected="", include=ALL, names=False, scan_dir=None, job=None,
            crash_id=None, now=None):
    """The report and what could go in it: {text, parts: {log, crash, scan: bool available}, digest}.

    kind        "bug" (something is wrong) or "crash" (the newest crash record, or `crash_id`, comes first)
    include     which optional parts go in: any of "log", "crash", "scan" (each a separate choice)
    names       keep track and file names (default: no, they are replaced by placeholders)
    job         the app's current job as {title, kind, status, reason, dir, log}; else the last record on disk
    Nothing is written, nothing is sent: this is the text the person is shown."""
    include = set(include or ())
    info = scan_info(scan_dir)
    sc = Scrubber(keep_names=names)
    if info:
        sc.add_path(info["source"])
        sc.add_path(str(info["dir"]))
        for k, vals in info["names"].items():
            sc.add_names(k, vals)
    jd = (job or {}).get("dir", "")
    if jd:
        sc.add_path(jd)
    rec = crash_by_id(crash_id) if crash_id else (crashes() or [None])[0]
    last = None
    if job and job.get("status") not in (None, "idle"):
        last = dict(source="app", what=job.get("title", ""), kind=job.get("kind", ""), status=job.get("status", ""),
                    reason=job.get("reason", ""), log=job.get("log") or [])
    elif last_run():
        last = last_run()
    avail = dict(log=bool(last and last.get("log")), crash=bool(rec), scan=bool(info and info["counts"]))
    when = (now or utcnow()).strftime("%Y-%m-%d")
    title = "HypnoMix crash report" if kind == "crash" else "HypnoMix problem report"
    out = [f"# {title}", "",
           f"_Written on this computer on {when} (UTC) by HypnoMix {version()}. Nothing was sent: it is yours to read, "
           f"change and share (or not). Paths, file, track and song names and keys are hidden as far as HypnoMix can tell"
           f"{' (except the names you chose to keep)' if names else ''}: read it before you share it._", ""]
    if kind == "crash" and rec and "crash" in include:
        out += ["## Crash record", "", f"_Numbers in `<file N>`-style placeholders here are the record's own._", "",
                sc.text(crash_text(rec), 6000), ""]
    out += ["## What happened", "", sc.text(what_happened, 4000).strip() or "_(not written yet)_", "",
            "## What I expected", "", sc.text(expected, 4000).strip() or "_(not written yet)_", ""]
    on, off = switches()
    ffm = helpers()
    out += ["## Version and setup", "",
            f"- HypnoMix: {version()}", f"- Installed as: {install_kind()}", f"- Computer: {computer()}",
            f"- Python: {platform.python_version()} ({platform.python_implementation()})",
            f"- DAW chosen in Setup: {setup_daw()}",
            "- Helpers: " + "; ".join(f"{n}: {'present' if ok else 'not found'}" for n, ok in ffm),
            "- Packages: " + (", ".join(packages()) or "unknown"),
            "- Switches: set: " + (", ".join(on) or "none") + "; not set: " + ", ".join(off), ""]
    out += ["## What ran last", ""]
    if last:
        bits = [f"{'job' if last.get('source') == 'app' else 'command'} \"{sc.text(last.get('what', ''), 200)}\"",
                f"ended: {last.get('status', 'unknown')}"]
        if last.get("exit") not in (None, ""):
            bits.append(f"exit code {last.get('exit')}")
        if last.get("when"):
            bits.append(f"at {last['when']}")
        out.append("- " + ", ".join(bits))
        if last.get("reason"):
            out.append(f"- Why: {sc.text(last['reason'], 600)}")
    else:
        out.append("- No failed command or finished job is on record.")
    out.append("")
    if "log" in include and avail["log"]:
        out += [f"## Log (the last {min(len(last['log']), LOG_LINES)} lines of that job)", ""]
        out += _block(sc.lines(last["log"][-LOG_LINES:])) + [""]
    if kind != "crash" and "crash" in include and rec:
        out += ["## Crash record", "", "_The newest one on this computer. Numbers in placeholders here are the record's own._", "",
                sc.text(crash_text(rec), 6000), ""]
    if "scan" in include and avail["scan"]:
        out += ["## Findings in the open scan", "",
                ", ".join(f"{t}: {n}" for t, n in sorted(info["counts"].items())) + f" ({sum(info['counts'].values())} in all)", ""]
    text = "\n".join(out).rstrip() + "\n"
    import hashlib
    return dict(text=text, parts=avail, digest=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
                crash=rec["id"] if rec else "")


def build(kind="bug", what_happened="", expected="", include=ALL, names=False, **kw):
    """The report as text. See compose()."""
    return compose(kind, what_happened, expected, include, names, **kw)["text"]


# ---------------------------------------------------------------- sending it: the person's own action
def copy_text(text):
    """Put `text` on the clipboard with the system's own program. -> (done, how it was done or why it was not)."""
    data = text.encode("utf-8")
    tries = []
    if sys.platform == "darwin":
        tries.append(("pbcopy", ["pbcopy"], data))
    elif os.name == "nt":
        tries.append(("clip", ["clip"], b"\xff\xfe" + text.encode("utf-16-le")))
    else:
        if os.environ.get("WAYLAND_DISPLAY"):
            tries.append(("wl-copy", ["wl-copy"], data))
        tries += [("xclip", ["xclip", "-selection", "clipboard"], data), ("xsel", ["xsel", "--clipboard", "--input"], data),
                  ("wl-copy", ["wl-copy"], data)]
    for name, argv, payload in tries:
        exe = shutil.which(argv[0])
        if not exe:
            continue
        try:
            r = subprocess.run([exe] + argv[1:], input=payload, capture_output=True, timeout=10)
            if r.returncode == 0:
                return True, name
        except (OSError, subprocess.SubprocessError):
            continue
    return False, ("no clipboard program was found (pbcopy, clip, wl-copy or xclip): select the report and copy it yourself, "
                   "or save it with --out FILE")


def open_issue_page(opener=None):
    """Open the project's new-issue page in the browser: the address is fixed in this file and carries the template's
    name only, never a word of the report. -> True when the browser took it."""
    try:
        if opener is None:
            import webbrowser
            opener = webbrowser.open
        return bool(opener(ISSUE_URL))
    except Exception:
        return False


def save_report(text, folder, stem="hypnomix-report"):
    """Write the report as a NEW file in `folder` (never over an earlier one). -> the path."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    p = folder / f"{stem}-{stamp}.md"
    n = 1
    while p.exists():
        n += 1
        p = folder / f"{stem}-{stamp}-{n}.md"
    p.write_text(text, encoding="utf-8")
    return p
