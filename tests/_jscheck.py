"""One way to check that every script a page of the app loads still parses.

`scripts()` finds them: every .js file in hypnomix/app and hypnomix/app/daw/js, the main page's own inline script and the
DAW page's inline scripts. `parse(scripts)` returns the problems found, or raises Missing, which names what is not here:
Node.js (`node --check`), else macOS's JavaScript engine through osascript, else nothing can parse, and a test that
needs it SKIPS with that sentence (a skip, never a silent pass). The osascript way proves it works before it is trusted:
it must report a script that is broken on purpose, so an engine that ran but checked nothing is an error, not a pass.

The tests that RUN a script (a page script against stand-ins for the page, a Max device script against a simulated Live)
use `runner()`: Node.js when it is there (with `print` defined for it, as the Mac's engine has it), else macOS's
JavaScriptCore (jsc), else None, and the test calls `need_runner(self)`, which skips with a sentence naming what is missing.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "hypnomix" / "app"

MISSING = ("SKIPPED: nothing here can parse JavaScript, so the page scripts were NOT checked: "
           "install Node.js (the `node` program), or run on a Mac (osascript)")

NO_RUNNER = ("SKIPPED: no JavaScript engine here to run the script, so it was NOT run: "
             "install Node.js (the `node` program), or run on a Mac (JavaScriptCore)")

PRINT_SHIM = Path(__file__).with_name("_print.js")       # `print` for Node.js: the Mac's engine has it, and the scripts use it
JSC_PATHS = ("/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc",
             "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc")

CHECKER = r"""ObjC.import('Foundation');
function run(argv) { var out = [], n = 0;
  for (var i = 0; i < argv.length; i++) {
    var s = $.NSString.stringWithContentsOfFileEncodingError(argv[i], $.NSUTF8StringEncoding, null);
    if (s.isNil()) { out.push(argv[i] + ': cannot be read'); continue; }
    try { new Function(ObjC.unwrap(s)); n++; } catch (e) { out.push(argv[i] + ': ' + e); } }
  return 'CHECKED ' + n + (out.length ? '\n' + out.join('\n') : ''); }
"""


class Missing(Exception):
    """No way to parse JavaScript here (the message says what to install)."""


def engine():
    """('node', path), ('osascript', path) or None."""
    node = shutil.which("node")
    if node:
        return "node", node
    osa = shutil.which("osascript") if sys.platform == "darwin" else None
    return ("osascript", osa) if osa else None


def runner():
    """The words that start a JavaScript engine on a script file with `print` defined: Node.js, else JavaScriptCore; or None."""
    node = shutil.which("node")
    if node:
        return [node, "--require", str(PRINT_SHIM)]
    for p in JSC_PATHS:
        if os.path.exists(p):
            return [p]
    return None


def need_runner(case):
    """From a unittest test: the engine's words, or a visible skip that names what is missing."""
    r = runner()
    if r is None:
        case.skipTest(NO_RUNNER)
    return r


def scripts(tmp):
    """{name: path} of every page script; the inline ones are written into the folder `tmp`."""
    from hypnomix.app import daw as DW, ui
    found = {}
    for p in sorted(ROOT.glob("*.js")):
        found[p.name] = p
    for p in sorted((ROOT / "daw" / "js").glob("*.js")):
        found["daw/js/" + p.name] = p
    tmp = Path(tmp)
    main = re.search(r"<script>(.*?)</script>", ui.PAGE, re.S)
    if main:
        q = tmp / "page-inline.js"
        q.write_text(main.group(1).replace("__TOKEN__", "x"), encoding="utf-8")
        found["the page's own script"] = q
    html = (Path(DW.ROOT) / "index.html").read_text(encoding="utf-8")
    for i, m in enumerate(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)):
        q = tmp / f"daw-inline-{i}.js"
        q.write_text(m, encoding="utf-8")
        found[f"daw/index.html inline script {i + 1}"] = q
    return found


def parse(found):
    """[problem, ...] for the scripts {name: path}, [] when all parse. Raises Missing when nothing can parse."""
    eng = engine()
    if eng is None:
        raise Missing(MISSING)
    kind, exe = eng
    names = {str(p): n for n, p in found.items()}
    problems = []
    if kind == "node":
        for name, path in found.items():
            r = subprocess.run([exe, "--check", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode:
                problems.append(f"{name}: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'does not parse'}")
        return problems
    with tempfile.TemporaryDirectory() as td:
        chk = Path(td) / "check.js"
        chk.write_text(CHECKER, encoding="utf-8")
        bad = Path(td) / "broken.js"
        bad.write_text("function (", encoding="utf-8")
        files = [str(p) for p in found.values()]
        r = subprocess.run([exe, "-l", "JavaScript", str(chk), str(bad)] + files, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        out = (r.stdout + r.stderr).strip()
        if r.returncode or not out.startswith("CHECKED") or str(bad) not in out:
            raise RuntimeError("osascript did not check the scripts (it did not even report the broken one): " + out[:300])
        for line in out.splitlines()[1:]:
            if line.startswith(str(bad)):
                continue
            path = line.split(": ", 1)[0]
            problems.append(f"{names.get(path, path)}: {line.split(': ', 1)[1] if ': ' in line else line}")
    return problems


def check(case):
    """Run from a unittest test: parse everything, fail on a problem, skip (visibly) when nothing can parse."""
    with tempfile.TemporaryDirectory() as td:
        found = scripts(td)
        for want in ("review.js", "chat.js", "daw/js/app.js", "daw/js/assistant.js", "the page's own script"):
            case.assertIn(want, found, "the list of page scripts lost a script")
        case.assertGreaterEqual(len(found), 24)
        try:
            problems = parse(found)
        except Missing as e:
            case.skipTest(str(e))
        case.assertEqual(problems, [], "a page script does not parse")
        return len(found)
