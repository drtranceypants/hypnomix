"""The DAW view's top bar and status bar (hypnomix/app/daw/): two rules from review, pinned.

1. The top bar's loudness field shows the loudness number (short-term LUFS) only, at every width. Momentary loudness,
   true peak and correlation are in the status bar, and no width rule (@media) hides or reshapes the loudness field:
   with the engine's meter stream on, the top bar used to overflow (the whole page scrolled sideways) between about
   1320 and 1590 px. The width checks themselves (1280, 1440, 1441, 1520, 1521, 1600 and 1920 px, stream on and the demo
   song) were made in a real page; these are the static rules that keep them true.
2. The status bar names the engine "HypnoMix engine" and its version, never the name the engine's MCP surface gives
   itself (serverInfo.name): renaming that surface must change nothing on the page."""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from hypnomix.app import daw as DW

ROOT = Path(DW.ROOT)


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def element(html, el_id):
    """The outer HTML of the element with this id (its tag's matching close: the markup here nests plainly)."""
    m = re.search(r'<(\w+)\b[^>]*\bid="%s"[^>]*>' % re.escape(el_id), html)
    if not m:
        return None
    tag, i, depth = m.group(1), m.end(), 1
    pat = re.compile(r"<(/?)%s\b[^>]*>" % tag)
    while depth:
        t = pat.search(html, i)
        if not t:
            return html[m.start():]
        depth += -1 if t.group(1) else 1
        i = t.end()
    return html[m.start():i]


def media_blocks(css):
    """Every @media block's text (its braces matched)."""
    out = []
    for m in re.finditer(r"@media[^{]*\{", css):
        i, depth = m.end(), 1
        while depth and i < len(css):
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append(css[m.start():i])
    return out


class TopBarLoudness(unittest.TestCase):
    def setUp(self):
        self.html = read("index.html")
        self.field = element(self.html, "loudField")
        self.assertIsNotNone(self.field, "the top bar's loudness field is gone")

    def test_the_top_bar_field_holds_only_the_lufs_number(self):
        self.assertIn('class="field loud"', self.field)
        self.assertEqual(re.findall(r'class="num"[^>]*id="(\w+)"', self.field), ["loudS"])
        units = re.findall(r'<span class="unit">([^<]*)</span>', self.field)
        self.assertEqual(units, ["LUFS"])
        for gone in ("loudM", "loudTP", "loudC", ">TP<", "dBTP", ">C<"):
            self.assertNotIn(gone, self.field)

    def test_momentary_true_peak_and_correlation_are_in_the_status_bar(self):
        footer = element(self.html, "loudStatus")
        self.assertIsNotNone(footer, "the status bar's loudness readout is gone")
        status = self.html[self.html.index('<footer class="status">'):self.html.index("</footer>")]
        self.assertIn('id="loudStatus"', status)
        for want in ('id="loudM"', 'id="loudTP"', 'id="loudC"', ">dBTP<"):
            self.assertIn(want, footer)
        self.assertEqual(self.html.count('id="loudTP"'), 1)
        self.assertEqual(self.html.count('id="loudC"'), 1)
        self.assertIn(" hidden ", footer.split(">", 1)[0] + " ")           # shown only while the stream runs

    def test_the_stream_fills_both_and_hides_both_without_it(self):
        js = read("js/live.js")
        body = js[js.index("function showLoudness"):]
        body = body[:body.index("\n  }\n")]
        for want in ("#loudField", "#loudStatus", "#loudS", "#loudM", "#loudTP", "#loudC"):
            self.assertIn(want, body)
        self.assertRegex(body, r"st\.hidden\s*=\s*!x")

    def test_no_width_rule_touches_the_loudness_readouts(self):
        for css_file in sorted((ROOT / "css").glob("*.css")):
            for block in media_blocks(css_file.read_text(encoding="utf-8")):
                self.assertNotRegex(block, r"loud", f"{css_file.name}: a width rule for the loudness readout")

    def test_the_page_never_scrolls_sideways_the_bar_does(self):
        # at every width (no @media needed) what does not fit in the top bar scrolls inside it, never the page: a longer
        # label ("Opening…" while the stream is on) or other fonts must not push the page sideways
        app = read("css/app.css")
        base = re.search(r"^\.topbar \{([^}]*display: flex[^}]*)\}", app, re.M)
        self.assertIsNotNone(base, "the top bar's base rule is gone")
        self.assertIn("overflow-x: auto", base.group(1))
        self.assertIn("overflow-y: hidden", base.group(1))
        self.assertRegex(app, r"\.topbar::-webkit-scrollbar \{ display: none; \}")
        self.assertIn("overflow: hidden", app.split(".brand {", 1)[1].split("}", 1)[0])
        # below the full width the less used readouts give way first, and the name block may shrink to the mark
        narrow = [b for b in media_blocks(read("css/tour.css")) if ".topbar" in b]
        self.assertEqual(len(narrow), 1)
        self.assertIn(".topbar .brand { min-width: 24px; }", narrow[0])
        self.assertIn(".topbar .cpu", narrow[0])


class EngineName(unittest.TestCase):
    def test_no_page_file_reads_the_engines_own_name(self):
        files = list((ROOT / "js").glob("*.js")) + [ROOT / "index.html"]
        for f in files:
            text = f.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"serverInfo\s*(\.\s*name|\[\s*['\"]name)", text), f.name)
            self.assertNotIn("ardour-mcp", text, f.name)

    def test_the_status_bar_says_hypnomix_engine_and_the_version(self):
        js = read("js/app.js")
        self.assertIn("'MCP · ' + HX.engineLabel(HX.mcp.serverInfo)", js)
        m = re.search(r"HX\.engineLabel = (\(info\) => \{.*?\n  \});", js, re.S)
        self.assertIsNotNone(m)
        self.assertIn("'HypnoMix engine'", m.group(1))
        # run it: node when it is on the PATH, else the JavaScript engine macOS ships (osascript -l JavaScript)
        calls = ("JSON.stringify([f({name: 'ardour-mcp-http', version: '0.1.0'}), f({name: 'hypnomix-engine', version: '0.1.0'}),"
                 " f({version: '0.2.0'}), f(null), f({name: 'x'}), f({name: 'x', version: 7})])")
        node, osa = shutil.which("node"), shutil.which("osascript")
        if node:
            argv = [node, "-e", "const f = " + m.group(1) + ";\nconsole.log(" + calls + ");"]
        elif osa:
            argv = [osa, "-l", "JavaScript", "-e", "const f = " + m.group(1) + ";\n" + calls]
        else:
            self.skipTest("no JavaScript engine here (node or osascript): the label was checked statically only")
        out = subprocess.run(argv, capture_output=True, text=True, timeout=30, encoding="utf-8")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), '["HypnoMix engine 0.1.0","HypnoMix engine 0.1.0","HypnoMix engine 0.2.0",'
                                             '"HypnoMix engine","HypnoMix engine","HypnoMix engine"]')


if __name__ == "__main__":
    unittest.main()
