#!/usr/bin/env python3
"""The review as one page: every finding with its before / after players and approve / skip / change.

  hypnomix review SCAN_DIR                 write SCAN_DIR/REVIEW.html and print its path (open it in a browser)
  hypnomix review SCAN_DIR --serve         same page on http://127.0.0.1:8790: every click is saved straight
                                           into SCAN_DIR/decisions.json (Ctrl-C to stop)
  hypnomix review SCAN_DIR --import FILE   take in a decisions.json downloaded from the page

Run `hypnomix ab SCAN_DIR` first to get the play buttons. The page is one file with no network access: opened
directly, it keeps your choices in the browser and "Download decisions" saves them as a file to import;
with --serve they are written as you click. Either way nothing is applied until you run
`hypnomix fix SCAN_DIR --approved --out ...`.

High-severity and protected items are marked: decide those one at a time. "Approve all low" only touches
low-severity items that are not protected.
"""
import argparse, html, json, sys, time
from pathlib import Path

DECISIONS = ("approve", "skip", "change")

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Review: __TITLE__</title>
<style>
:root{--bg:#f6f4ef;--card:#fff;--ink:#1d1b18;--mute:#6b665e;--line:#e2ddd2;--hi:#b3261e;--med:#a8640a;--low:#3d6b4f;
--info:#5a6472;--ok:#2f6f4f;--skip:#7a756c;--chg:#8a5a00;--accent:#3b4cca}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--card:#201f1c;--ink:#ece8df;--mute:#a09a8e;--line:#34322d;
--hi:#ff8a80;--med:#f0b455;--low:#8fc7a4;--info:#9aa6b6;--ok:#7fd0a4;--skip:#a09a8e;--chg:#f0b455;--accent:#9aa7ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 120px}h1{font-size:1.5rem;margin:0 0 4px}
.sub{color:var(--mute);margin:0 0 16px}.prefs{border-left:3px solid var(--accent);padding:4px 12px;margin:0 0 16px;color:var(--mute)}
.warn{border-left:3px solid var(--hi);padding:4px 12px;margin:0 0 16px}
.bar{position:sticky;top:0;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line);display:flex;gap:8px;
flex-wrap:wrap;align-items:center;z-index:2}.bar .count{margin-right:auto;font-variant-numeric:tabular-nums}
button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;padding:6px 12px;cursor:pointer}
button:hover{border-color:var(--mute)}button.on.approve{background:var(--ok);color:#fff;border-color:var(--ok)}
button.on.skip{background:var(--skip);color:#fff;border-color:var(--skip)}button.on.change{background:var(--chg);color:#fff;border-color:var(--chg)}
.item{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:14px 0}
.item.done{opacity:.72}.head{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.sev{font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.sev.high{color:var(--hi)}.sev.medium{color:var(--med)}.sev.low{color:var(--low)}.sev.info{color:var(--info)}
.tag{font-size:.75rem;border:1px solid var(--line);border-radius:99px;padding:1px 8px;color:var(--mute)}
.tag.prot{border-color:var(--hi);color:var(--hi)}.where{color:var(--mute);font-variant-numeric:tabular-nums}
.title{font-weight:600}.fix{color:var(--mute);margin:6px 0 0;white-space:pre-wrap;overflow-wrap:anywhere}
pre.fix{font:13px/1.45 ui-monospace,monospace;max-height:220px;overflow:auto;background:var(--bg);padding:8px;border-radius:8px}
.ab{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0 0}.ab label{font-size:.8rem;color:var(--mute);display:block}
.ab audio{width:100%}.note{font-size:.85rem;color:var(--mute);margin:8px 0 0}
.act{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 0}.act input{flex:1;min-width:180px;font:inherit;padding:6px 10px;
border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}
code{font:13px ui-monospace,monospace;background:var(--bg);padding:1px 5px;border-radius:5px}
@media (max-width:560px){.ab{grid-template-columns:1fr}}
</style></head><body><main>
<h1>Review: __TITLE__</h1>
<p class="sub">Nothing has been changed. Listen, decide each item, then apply only what you approved.</p>
<div id="top"></div>
<div class="bar"><span class="count" id="count"></span>
<button id="alllow" title="Low-severity items that are not protected">Approve all low</button>
<button id="dl">Download decisions</button></div>
<div id="list"></div>
<p class="sub" id="apply"></p>
</main>
<script>
const DATA = __DATA__;
const served = location.protocol.startsWith('http');
const KEY = 'hypnomix-review:' + DATA.set;
let dec = Object.assign({}, DATA.decisions);
if (!served) { try { Object.assign(dec, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (e) {} }
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function persist(id) {
  if (served) {
    fetch('/decide', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({id, decision: dec[id].decision, note: dec[id].note || ''})})
      .catch(() => alert('Could not save: is `hypnomix review --serve` still running?'));
  } else { try { localStorage.setItem(KEY, JSON.stringify(dec)); } catch (e) {} }
}
function setDecision(id, d, note) {
  dec[id] = {decision: d, note: note || (dec[id] && dec[id].note) || '', at: new Date().toISOString().slice(0,16).replace('T',' ')};
  persist(id); render();
}
function render() {
  const actionable = DATA.findings.filter(f => f.applies !== 'info');
  const n = {approve:0, skip:0, change:0};
  actionable.forEach(f => { const d = dec[f.id] && dec[f.id].decision; if (d) n[d]++; });
  const left = actionable.length - n.approve - n.skip - n.change;
  document.getElementById('count').textContent =
    `${n.approve} approved · ${n.skip} skipped · ${n.change} to change · ${left} undecided`;
  const top = [];
  if (DATA.broken.length) top.push('<div class="warn"><b>Checks that did NOT run</b> (no findings there means nothing):<br>' + DATA.broken.map(esc).join('<br>') + '</div>');
  if (DATA.prefs.length) top.push('<div class="prefs">' + DATA.prefs.map(esc).join('<br>') + '</div>');
  document.getElementById('top').innerHTML = top.join('');
  document.getElementById('list').innerHTML = DATA.findings.map(f => {
    const d = dec[f.id] && dec[f.id].decision, ab = DATA.ab[f.id] || {};
    const fix = String(f.fix || '');
    const players = ab.a ? `<div class="ab"><div><label>A · now</label><audio controls preload="none" src="ab/${encodeURIComponent(ab.a)}"></audio></div>
      <div><label>B · with the fix${ab.matched_db ? ' (level-matched ' + (ab.matched_db > 0 ? '+' : '') + ab.matched_db + ' dB)' : ''}</label><audio controls preload="none" src="ab/${encodeURIComponent(ab.b)}"></audio></div></div>` : '';
    const note = ab.note ? `<p class="note">${esc(ab.note)}</p>` : ((f.applies === 'set' || f.applies === 'audio') && !ab.a ? '<p class="note">No preview yet: run <code>hypnomix ab</code>.</p>' : '');
    const act = f.applies === 'info' ? '' : `<div class="act">
      ${['approve','skip','change'].map(x => `<button class="${x}${d === x ? ' on' : ''}" data-id="${esc(f.id)}" data-d="${x}">${x[0].toUpperCase() + x.slice(1)}</button>`).join('')}
      <input placeholder="note (what to change, or why)" data-note="${esc(f.id)}" value="${esc(dec[f.id] && dec[f.id].note)}"></div>`;
    return `<div class="item${d ? ' done' : ''}"><div class="head"><span class="sev ${esc(f.severity)}">${esc(f.severity)}</span>
      <span class="title">${esc(f.track || f.tool)}</span><span class="where">${esc(f.where || '')}</span>
      <span class="tag">${esc(f.tool)} · ${esc(f.applies)}</span><span class="tag">${esc(f.id)}</span>
      ${f.protected ? '<span class="tag prot">protected: ask again</span>' : ''}</div>
      <div>${esc(f.problem)}</div>
      ${fix.includes('\n') ? `<pre class="fix">${esc(fix)}</pre>` : `<p class="fix">Proposed: ${esc(fix)}</p>`}
      ${f.history ? `<p class="note">${esc(f.history)}</p>` : ''}${players}${note}${act}</div>`;
  }).join('');
  document.getElementById('apply').innerHTML = served
    ? 'Saved as you click. When you are done: <code>hypnomix fix "' + esc(DATA.dir) + '" --approved --out "&lt;Song&gt; (fixed).als"</code>'
    : 'When you are done: Download decisions, then <code>hypnomix review "' + esc(DATA.dir) + '" --import ~/Downloads/decisions.json</code> and <code>hypnomix fix "' + esc(DATA.dir) + '" --approved --out "&lt;Song&gt; (fixed).als"</code>';
}
document.addEventListener('click', e => {
  const b = e.target.closest('button[data-id]');
  if (b) { const note = document.querySelector(`input[data-note="${CSS.escape(b.dataset.id)}"]`); setDecision(b.dataset.id, b.dataset.d, note ? note.value : ''); }
});
document.addEventListener('change', e => {
  const i = e.target.closest('input[data-note]');
  if (i && dec[i.dataset.note]) { dec[i.dataset.note].note = i.value; persist(i.dataset.note); }
});
document.addEventListener('play', e => {  // one player at a time, so A and B are compared, not mixed
  document.querySelectorAll('audio').forEach(a => { if (a !== e.target) a.pause(); });
}, true);
document.getElementById('alllow').onclick = () => {
  const ids = DATA.findings.filter(f => f.severity === 'low' && !f.protected && f.applies !== 'info' && !dec[f.id]).map(f => f.id);
  if (ids.length && confirm(`Approve ${ids.length} low-severity item(s) without listening to each?`)) ids.forEach(id => setDecision(id, 'approve', 'batch: all low'));
};
document.getElementById('dl').onclick = () => {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(dec, null, 1)], {type:'application/json'}));
  a.download = 'decisions.json'; a.click();
};
render();
</script></body></html>
"""


def load(sd):
    data = json.loads((sd / "findings.json").read_text())
    dec = json.loads((sd / "decisions.json").read_text()) if (sd / "decisions.json").exists() else {}
    ab = json.loads((sd / "ab" / "ab.json").read_text()) if (sd / "ab" / "ab.json").exists() else {}
    return data, dec, ab


def build(sd):
    from hypnomix.workflow import prefs as P
    data, dec, ab = load(sd)
    notes = data.get("notes", [])
    payload = dict(set=data.get("set", ""), dir=str(sd), findings=data["findings"], decisions=dec, ab=ab,
                   prefs=P.summary(P.load()), broken=[n for n in notes if "failed" in n or n.startswith("WARNING")])
    blob = json.dumps(payload, default=str).replace("</", "<\\/")
    title = html.escape(Path(data.get("set") or sd.name).stem)
    page = PAGE.replace("__TITLE__", title).replace("__DATA__", blob)
    out = sd / "REVIEW.html"
    out.write_text(page)
    return out


def record(sd, fid, decision, note=""):
    data, dec, _ = load(sd)
    ids = {f["id"] for f in data["findings"]}
    if fid not in ids:
        raise ValueError(f"unknown id: {fid}")
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    dec[fid] = {"decision": decision, "note": str(note)[:500], "at": time.strftime("%Y-%m-%d %H:%M")}
    (sd / "decisions.json").write_text(json.dumps(dec, indent=1))


def import_file(sd, path):
    incoming = json.loads(Path(path).expanduser().read_text())
    n, bad = 0, []
    for fid, d in incoming.items():
        what = d.get("decision") if isinstance(d, dict) else d
        try:
            record(sd, fid, what, d.get("note", "") if isinstance(d, dict) else "")
            n += 1
        except ValueError as e:
            bad.append(str(e))
    print(f"imported {n} decision(s) into {sd / 'decisions.json'}")
    for b in bad[:10]:
        print(f"  ignored: {b}")


def serve(sd, port):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import unquote
    root = sd.resolve()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = unquote(self.path.split("?")[0])
            if path in ("/", "/REVIEW.html"):
                return self.send(200, build(sd).read_bytes(), "text/html; charset=utf-8")
            if path.startswith("/ab/"):
                f = (root / "ab" / Path(path[4:]).name)
                if f.is_file() and f.suffix == ".wav":
                    return self.send(200, f.read_bytes(), "audio/wav")
            self.send(404, b"not found", "text/plain")

        def do_POST(self):
            if self.path != "/decide" or self.headers.get("Origin", f"http://127.0.0.1:{port}") not in (
                    f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
                return self.send(403, b"no", "text/plain")
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 20000)))
                record(sd, body["id"], body["decision"], body.get("note", ""))
                print(f"  {body['id']}: {body['decision']}" + (f"  ({body['note']})" if body.get("note") else ""))
                self.send(200, b"{}", "application/json")
            except Exception as e:
                self.send(400, str(e).encode(), "text/plain")

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"review page: http://127.0.0.1:{port}/   (this computer only; Ctrl-C to stop)\n"
          f"decisions are saved to {sd / 'decisions.json'} as they are made")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


def main():
    ap = argparse.ArgumentParser(prog="hypnomix review", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scan_dir")
    ap.add_argument("--serve", action="store_true", help="serve the page locally and save decisions as they are made")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--import", dest="imp", metavar="FILE", help="take in a decisions.json downloaded from the page")
    a = ap.parse_args()
    sd = Path(a.scan_dir)
    if not (sd / "findings.json").exists():
        sys.exit(f"no findings.json in {sd}: run `hypnomix scan` first")
    if a.imp:
        return import_file(sd, a.imp)
    out = build(sd)
    if a.serve:
        return serve(sd, a.port)
    _, _, ab = load(sd)
    print(out)
    if not ab:
        print(f'no before/after clips yet: hypnomix ab "{sd}"')
    print("open it in a browser; or `--serve` to save decisions as you click")


if __name__ == "__main__":
    main()
