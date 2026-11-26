"""REAPER project files (.rpp): read them, and write them back byte-for-byte unless something was changed.

An .rpp is plain text: nested chunks that open with `<NAME args...` and close with `>`, holding lines of
whitespace-separated tokens. Tokens with spaces are quoted with ", ' or ` (REAPER picks a quote character the
token does not contain). Some chunks (plug-in state) hold raw base64 lines: those are kept exactly as they are.

    root = rpp.load("Song.rpp")
    for tr in root.chunks("TRACK"):
        print(tr.get("NAME"))
    rpp.save(root, "Song (fixed).rpp")      # refuses to overwrite the file it was read from

Unchanged lines are written back from their original text, so a load + save of an untouched project is identical.
"""
from pathlib import Path

QUOTES = "\"'`"


def split(text):
    """One RPP line -> tokens (quotes removed)."""
    out, i, n = [], 0, len(text)
    while i < n:
        while i < n and text[i] in " \t":
            i += 1
        if i >= n:
            break
        q = text[i]
        if q in QUOTES:
            j = text.find(q, i + 1)
            while j != -1 and j + 1 < n and text[j + 1] not in " \t":   # a quote inside a token, not its end
                j = text.find(q, j + 1)
            if j == -1:
                j = n
            out.append(text[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in " \t":
                j += 1
            out.append(text[i:j])
            i = j
    return out


def quote(tok):
    tok = str(tok)
    if tok and not any(c in tok for c in " \t" + QUOTES):
        return tok
    for q in QUOTES:
        if q not in tok:
            return f"{q}{tok}{q}"
    return '"' + tok.replace('"', "'") + '"'


def fmt(x):
    """A number the way REAPER writes it (up to 10 decimals, no trailing zeros)."""
    if isinstance(x, bool):
        return "1" if x else "0"
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        s = f"{x:.10f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    return quote(x)


class Line:
    __slots__ = ("tokens", "raw", "indent")

    def __init__(self, tokens, raw=None, indent=""):
        self.tokens, self.raw, self.indent = list(tokens), raw, indent

    @property
    def key(self):
        return self.tokens[0] if self.tokens else ""

    def set(self, *values):
        """Replace the values after the key; the line is re-written on save."""
        self.tokens = [self.tokens[0], *values]
        self.raw = None

    def text(self):
        if self.raw is not None:
            return self.raw
        return self.indent + " ".join([self.tokens[0]] + [fmt(t) for t in self.tokens[1:]])


class Chunk:
    """A `<NAME ...>` block: header tokens, then Lines and Chunks in order."""

    def __init__(self, tokens, raw=None, indent="", children=None):
        self.tokens, self.raw, self.indent = list(tokens), raw, indent
        self.children = children if children is not None else []
        self.close_raw = None
        self.parent = None

    @property
    def name(self):
        return self.tokens[0] if self.tokens else ""

    def lines(self, key=None):
        return [c for c in self.children if isinstance(c, Line) and (key is None or c.key == key)]

    def line(self, key):
        return next((c for c in self.children if isinstance(c, Line) and c.key == key), None)

    def chunks(self, name=None):
        return [c for c in self.children if isinstance(c, Chunk) and (name is None or c.name == name)]

    def chunk(self, name):
        return next((c for c in self.children if isinstance(c, Chunk) and c.name == name), None)

    def get(self, key, i=1, cast=str, default=None):
        ln = self.line(key)
        if ln is None or len(ln.tokens) <= i:
            return default
        try:
            return cast(ln.tokens[i])
        except ValueError:
            return default

    def set(self, key, *values, after=None):
        """Set (or add) a line `KEY values...`. New lines go after the line named `after`, else after the last line."""
        ln = self.line(key)
        if ln is not None:
            ln.set(*values)
            return ln
        ln = Line([key, *values], indent=self._child_indent())
        at = len(self.children)
        if after is not None and self.line(after) is not None:
            at = self.children.index(self.line(after)) + 1
        else:
            for k in range(len(self.children) - 1, -1, -1):
                if isinstance(self.children[k], Line):
                    at = k + 1
                    break
        self.children.insert(at, ln)
        return ln

    def add(self, child, at=None):
        if isinstance(child, Chunk):
            child.parent = self
        if isinstance(child, (Line, Chunk)) and not child.indent:
            child.indent = self._child_indent()
        self.children.insert(len(self.children) if at is None else at, child)
        return child

    def _child_indent(self):
        for c in self.children:
            if getattr(c, "indent", None):
                return c.indent
        return self.indent + "  "

    def walk(self, name=None):
        for c in self.children:
            if isinstance(c, Chunk):
                if name is None or c.name == name:
                    yield c
                yield from c.walk(name)

    def text_lines(self):
        yield self.raw if self.raw is not None else \
            self.indent + "<" + " ".join([self.tokens[0]] + [fmt(t) for t in self.tokens[1:]])
        for c in self.children:
            if isinstance(c, Chunk):
                yield from c.text_lines()
            else:
                yield c.text()
        yield self.close_raw if self.close_raw is not None else self.indent + ">"


def parse(text):
    """Text of a whole .rpp -> its root Chunk (REAPER_PROJECT)."""
    stack, root = [], None
    newline = "\r\n" if "\r\n" in text else "\n"
    for raw in text.split(newline):
        s = raw.strip()
        indent = raw[: len(raw) - len(raw.lstrip())]
        if s.startswith("<"):
            ch = Chunk(split(s[1:]), raw=raw, indent=indent)
            if stack:
                ch.parent = stack[-1]
                stack[-1].children.append(ch)
            elif root is None:
                root = ch
            stack.append(ch)
        elif s == ">" and stack:
            stack.pop().close_raw = raw
        elif stack:
            stack[-1].children.append(Line(split(s), raw=raw, indent=indent))
    if root is None:
        raise ValueError("not a REAPER project (no <REAPER_PROJECT chunk)")
    root.newline = newline
    root.trailing = text.endswith(newline)
    return root


def load(path):
    # bytes, not read_text: text reading turns REAPER's CRLF line ends into LF, and the file would change everywhere
    root = parse(Path(path).read_bytes().decode("utf-8", errors="surrogateescape"))
    root.path = Path(path)
    return root


def dumps(root):
    nl = getattr(root, "newline", "\n")
    return nl.join(root.text_lines()) + (nl if getattr(root, "trailing", True) else "")


def save(root, out):
    out = Path(out)
    src = getattr(root, "path", None)
    if src is not None and out.resolve() == Path(src).resolve():
        raise SystemExit("refusing to overwrite the original project: give a new file name")
    out.write_bytes(dumps(root).encode("utf-8", errors="surrogateescape"))
    return out
