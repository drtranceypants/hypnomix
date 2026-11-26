"""Leftovers: temporary renders are removed when a command ends, found again by Disk care, and the render cache trim
does not list the whole cache every few writes.

Nothing here measures time. Each test counts something (folders left, calls, listings) on a tiny synthetic input.
"""
import ast, contextlib, gzip, io, json, os, re, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

SR = 44100
DAY = 86400
ROOT = Path(__file__).resolve().parents[1]


def limiter_set(td, tracks=2, secs=3):
    """A Live set with `tracks` audio tracks (each with a Limiter) and their source audio, all synthetic."""
    td = Path(td)
    td.mkdir(parents=True, exist_ok=True)
    t = np.arange(SR * secs) / SR

    def clip(i, fn):
        return (f'<AudioClip Id="{i}" Time="0"><Name Value="take"/><CurrentStart Value="0"/><CurrentEnd Value="{secs * 2}"/>'
                f'<Loop><LoopStart Value="0"/><LoopEnd Value="{secs * 2}"/><LoopOn Value="false"/><StartRelative Value="0"/></Loop>'
                f'<IsWarped Value="false"/><WarpMarkers><WarpMarker Id="0" SecTime="0" BeatTime="0"/><WarpMarker Id="1" SecTime="1" BeatTime="2"/></WarpMarkers>'
                f'<SampleVolume Value="1"/><Disabled Value="false"/>'
                f'<Fades><FadeInLength Value="0"/><FadeOutLength Value="0"/><IsDefaultFadeIn Value="true"/><IsDefaultFadeOut Value="true"/></Fades>'
                f'<SampleRef><FileRef><Path Value="{td / fn}"/><RelativePath Value="{fn}"/></FileRef></SampleRef></AudioClip>')

    mixer = lambda base: (f'<Mixer><Volume><Manual Value="1"/><AutomationTarget Id="{base}"/></Volume>'
                          f'<Pan><Manual Value="0"/><AutomationTarget Id="{base + 1}"/></Pan>'
                          f'<Speaker><Manual Value="true"/><AutomationTarget Id="{base + 2}"/></Speaker><Sends/></Mixer>')
    body = ""
    for k in range(tracks):
        fn = f"src{k}.wav"
        sf.write(str(td / fn), (0.5 * np.sin(2 * np.pi * (110 + 55 * k) * t)).astype(np.float32), SR)
        body += (f'<AudioTrack Id="{k + 1}"><Name><EffectiveName Value="Tr{k}"/></Name><AutomationEnvelopes><Envelopes/></AutomationEnvelopes>'
                 f'<DeviceChain>{mixer(10 + 10 * k)}<MainSequencer><Sample><ArrangerAutomation><Events>{clip(k, fn)}</Events>'
                 f'</ArrangerAutomation></Sample></MainSequencer><DeviceChain><Devices><Limiter Id="0"><On><Manual Value="true"/></On>'
                 f'<Gain><Manual Value="12"/></Gain><Ceiling><Manual Value="-0.3"/></Ceiling></Limiter></Devices></DeviceChain>'
                 f'</DeviceChain></AudioTrack>')
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><Ableton MajorVersion="5" MinorVersion="12.0_12049" Creator="Ableton Live 12.0">'
           f'<LiveSet><NextPointeeId Value="1000"/><Tracks>{body}</Tracks><MainTrack><Name><EffectiveName Value="Main"/></Name>'
           f'<AutomationEnvelopes><Envelopes/></AutomationEnvelopes><DeviceChain>{mixer(900)}<Mixer2/><DeviceChain><Devices/>'
           f'</DeviceChain></DeviceChain><Tempo><Manual Value="120"/></Tempo></MainTrack></LiveSet></Ableton>')
    with gzip.open(td / "Song.als", "wb") as f:
        f.write(xml.encode())
    return td / "Song.als"


class Scratch(unittest.TestCase):
    """HYPNOMIX_HOME and the system temp folder both inside a folder of ours, so what is left behind can be counted."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.r = Path(self.td.name).resolve()
        self.home, self.systmp = self.r / "home", self.r / "systmp"
        self.systmp.mkdir()
        self.env = mock.patch.dict(os.environ, HYPNOMIX_HOME=str(self.home), HYPNOMIX_USER_HOME=str(self.r))
        self.env.start()
        self._tempdir = tempfile.tempdir
        tempfile.tempdir = str(self.systmp)

    def tearDown(self):
        tempfile.tempdir = self._tempdir
        self.env.stop()
        self.td.cleanup()

    def left(self):
        """Every hypnomix scratch folder still there (cache/tmp and the system temp folder)."""
        out = []
        for d in (self.home / "cache" / "tmp", self.systmp):
            if d.is_dir():
                out += [p for p in d.iterdir()]
        return sorted(out)


class WorkDir(Scratch):
    def test_name_place_marker_and_removal(self):
        from hypnomix.core import tmp as TMP
        with TMP.workdir("render") as p:
            self.assertTrue(p.name.startswith("hypnomix-render-"))
            self.assertEqual(p.parent, self.home / "cache" / "tmp")          # big: under the hypnomix home
            self.assertTrue((p / TMP.MARKER).is_file())
            self.assertTrue(TMP.OWN.match(p.name))
            (p / "x.wav").write_bytes(b"0" * 100)
        self.assertFalse(p.exists())
        with TMP.workdir("work", big=False) as q:
            self.assertEqual(q.parent, self.systmp)                           # small: the system temp folder
        self.assertFalse(q.exists())

    def test_removed_on_an_error_ctrl_c_and_exit(self):
        from hypnomix.core import tmp as TMP
        for exc in (RuntimeError("boom"), KeyboardInterrupt(), SystemExit(2)):
            seen = []
            with self.assertRaises(type(exc)):
                with TMP.workdir("render") as p:
                    seen.append(p)
                    (p / "a.wav").write_bytes(b"1")
                    raise exc
            self.assertFalse(seen[0].exists(), type(exc).__name__)
        self.assertEqual(self.left(), [])

    def test_a_scope_removes_what_scratch_made_even_on_sys_exit(self):
        from hypnomix.core import tmp as TMP
        seen = []

        def long_function():
            p = TMP.scratch("alignset")
            seen.append(p)
            (p / "g.wav").write_bytes(b"1")
            raise SystemExit("this set has tempo automation")

        with self.assertRaises(SystemExit):
            with TMP.scope():
                long_function()
        self.assertTrue(seen[0].name.startswith("hypnomix-alignset-"))
        self.assertFalse(seen[0].exists())

    def test_sigterm_ends_the_program_the_ordinary_way_while_a_folder_exists_and_is_given_back(self):
        import signal
        from hypnomix.core import tmp as TMP
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        before = signal.getsignal(signal.SIGTERM)
        with TMP.workdir("render"):
            self.assertNotEqual(signal.getsignal(signal.SIGTERM), signal.SIG_DFL)   # "kill" now ends it the ordinary way
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)
        # a handler somebody else set is left alone
        mine = lambda s, f: None
        signal.signal(signal.SIGTERM, mine)
        try:
            with TMP.workdir("render"):
                self.assertIs(signal.getsignal(signal.SIGTERM), mine)
        finally:
            signal.signal(signal.SIGTERM, before)

    def test_over_a_gigabyte_it_says_so_in_one_plain_line(self):
        from hypnomix.core import tmp as TMP
        err = io.StringIO()
        with contextlib.redirect_stderr(err), TMP.workdir("render", expect_bytes=3.2e9) as p:
            pass
        line = err.getvalue().strip()
        self.assertEqual(len(line.splitlines()), 1)
        self.assertIn("3.2 GB", line)
        self.assertIn(str(p), line)
        self.assertIn("removed when this command ends", line)
        quiet = io.StringIO()
        with contextlib.redirect_stderr(quiet), TMP.workdir("render", expect_bytes=0.9e9):
            pass
        self.assertEqual(quiet.getvalue(), "")

    def test_render_bytes_is_what_render_writes(self):
        from hypnomix.core import tmp as TMP
        import xml.etree.ElementTree as ET
        als = limiter_set(self.r / "set", tracks=3, secs=3)
        root = ET.fromstring(gzip.open(als).read())
        n = TMP.render_bytes(root, 3)
        self.assertEqual(n, int(3 * (6 + 8) * 0.5 * SR * 4))                    # 3 tracks, song end 6 beats + 8 beats


class CommandsLeaveNothing(Scratch):
    """Each command that renders the set into a scratch folder: the folder is there while it works, gone after."""

    def fake_render(self, seen):
        def hx(*args):
            args = [str(a) for a in args]
            if args[0] == "render":
                out = Path(args[args.index("--out") + 1])
                seen.append(out)
                for n in args[args.index("--tracks") + 1:args.index("--out")]:
                    t = np.arange(SR * 2) / SR
                    sf.write(str(out / f"{n}.wav"), (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), SR)
                return 0, ""
            if args[0] == "name":
                out = Path(args[args.index("--out") + 1])
                seen.append(out)
                rows = [dict(old="Tr0", kind="Audio", on=True, confidence=1.0, label="Lead Vocal", final="Lead Vocal"),
                        dict(old="Tr1", kind="Audio", on=True, confidence=1.0, label="Harmony 1", final="Harmony 1"),
                        dict(old="Tr2", kind="Audio", on=True, confidence=1.0, label="Harmony 2", final="Harmony 2")]
                (out / "names.json").write_text(json.dumps({"tracks": rows}), encoding="utf-8")
                return 0, ""
            return 1, "?"
        return hx

    def test_devices_removes_its_renders(self):
        from hypnomix.engineer import devices as D
        als = limiter_set(self.r / "set", tracks=2)
        seen = []
        with mock.patch.object(D, "hx", self.fake_render(seen)):
            items, notes, root, tempo = D.propose(als)
        self.assertEqual(len(items), 2)                                         # it did judge the (stub) renders
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].name.startswith("hypnomix-render-"))
        self.assertFalse(seen[0].exists())
        self.assertEqual(self.left(), [])

    def test_devices_removes_its_renders_when_it_fails_half_way(self):
        from hypnomix.engineer import devices as D
        als = limiter_set(self.r / "set", tracks=2)
        seen = []
        with mock.patch.object(D, "hx", self.fake_render(seen)), \
                mock.patch.object(D, "review_track", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                D.propose(als)
        self.assertFalse(seen[0].exists())

    def test_devices_announces_a_big_render_before_it_starts(self):
        from hypnomix.engineer import devices as D
        from hypnomix.core import tmp as TMP
        als = limiter_set(self.r / "set", tracks=2)
        err = io.StringIO()
        with mock.patch.object(D, "hx", self.fake_render([])), mock.patch.object(TMP, "render_bytes", return_value=int(4.1e9)), \
                contextlib.redirect_stderr(err):
            D.propose(als)
        self.assertIn("about 4.1 GB of temporary audio will be written to", err.getvalue())

    def test_duck_removes_its_names_folder(self):
        from hypnomix.engineer import duck as K
        als = limiter_set(self.r / "set", tracks=3)
        seen = []
        with mock.patch.object(K, "hx", self.fake_render(seen)):
            K.propose(als)                                                       # no names.json given: `name` runs
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].name.startswith("hypnomix-work-"))
        self.assertFalse(seen[0].exists())
        self.assertEqual(self.left(), [])

    def test_duck_removes_the_vocal_renders_it_made(self):
        from hypnomix.engineer import duck as K
        import xml.etree.ElementTree as ET
        als = limiter_set(self.r / "set", tracks=2)
        root = ET.fromstring(gzip.open(als).read())
        seen = []
        with mock.patch.object(K, "hx", self.fake_render(seen)):
            mix = K.trigger_audio(als, root, ["Tr0", "Tr1"], None, None)
        self.assertIsNotNone(mix)                                                # the summed vocals came back
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].name.startswith("hypnomix-render-"))
        self.assertFalse(seen[0].exists())
        self.assertEqual(self.left(), [])

    def test_duck_leaves_renders_that_were_given(self):
        from hypnomix.engineer import duck as K
        import xml.etree.ElementTree as ET
        als = limiter_set(self.r / "set", tracks=2)
        root = ET.fromstring(gzip.open(als).read())
        mine = self.r / "mine"
        mine.mkdir()
        seen = []
        with mock.patch.object(K, "hx", self.fake_render(seen)):
            K.trigger_audio(als, root, ["Tr0"], str(mine), None)
        self.assertTrue((mine / "Tr0.wav").exists())                             # the caller's folder is theirs: kept
        self.assertEqual(self.left(), [])

    def test_cliplevel_removes_its_renders_and_its_names_folder(self):
        from hypnomix.session import cliplevel as CL
        als = limiter_set(self.r / "set", tracks=3)
        seen = []
        with mock.patch.object(CL, "hx", self.fake_render(seen)), \
                mock.patch("hypnomix.core.pitch.track", return_value=(None, np.array([220.0, 220.0]), None)):
            CL.propose(als)
        self.assertEqual(len(seen), 2)                                           # `name`, then `render`
        for p in seen:
            self.assertFalse(p.exists(), p)
        self.assertEqual(self.left(), [])

    def test_tidy_makes_its_folder_late_deletes_each_render_and_removes_it(self):
        from hypnomix.session import tidy as TD
        import xml.etree.ElementTree as ET
        als = limiter_set(self.r / "set", tracks=2)
        root = ET.fromstring(gzip.open(als).read())
        tr = [t for t in root.find(".//Tracks")]
        made = []

        def fake_run(cmd, **kw):
            out = Path(cmd[cmd.index("--out") + 1])
            made.append(out)
            nm = cmd[cmd.index("--tracks") + 1]
            sf.write(str(out / f"{nm}.wav"), np.zeros(SR, dtype=np.float32), SR)
            return mock.Mock(returncode=0, stdout="", stderr="")

        probe = TD.silence_probe(als, 120.0)
        self.assertEqual(self.left(), [])                                        # nothing is made until a track is heard
        with mock.patch("subprocess.run", fake_run):
            self.assertTrue(probe(tr[0], 0, 4))
            self.assertEqual(list(made[0].glob("*.wav")), [])                    # read once, and gone: one render at a time
            self.assertTrue(probe(tr[1], 0, 4))
            self.assertTrue(probe(tr[0], 0, 4))                                  # heard before: not rendered again
        self.assertEqual(len(made), 2)
        self.assertTrue(made[0].exists())
        probe.close()
        self.assertFalse(made[0].exists())
        probe.close()                                                            # twice is harmless
        self.assertTrue(made[0].name.startswith("hypnomix-tidy-"))

    def test_tidy_with_nothing_to_hear_makes_no_folder_at_all(self):
        from hypnomix.session import tidy as TD
        probe = TD.silence_probe("nowhere.als", 120.0)
        probe.close()
        self.assertEqual(self.left(), [])


class Audit(unittest.TestCase):
    """Every temporary folder the package makes carries a recognisable name, or is on this short list."""

    ALLOWED = {
        "hypnomix/core/tmp.py": "the helper itself",
        "hypnomix/store/install.py": "hypnomix-store-mnt-: a disk image's mount point, removed in a finally; never swept",
        "hypnomix/workflow/fix.py": ".new-: a folder INSIDE the scan folder's fixed/ that the same block removes",
    }

    def test_every_mkdtemp_and_temporarydirectory_has_a_hypnomix_prefix(self):
        bad = []
        for py in sorted((ROOT / "hypnomix").rglob("*.py")):
            rel = py.relative_to(ROOT).as_posix()
            if rel in self.ALLOWED or "/remote_script/" in rel:
                continue
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if not isinstance(n, ast.Call):
                    continue
                f = n.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if name not in ("mkdtemp", "TemporaryDirectory", "NamedTemporaryFile"):
                    continue
                pre = next((k.value for k in n.keywords if k.arg == "prefix"), None)
                ok = isinstance(pre, ast.Constant) and isinstance(pre.value, str) and pre.value.startswith("hypnomix-")
                if not ok:
                    bad.append(f"{rel}:{n.lineno} {name}")
        self.assertEqual(bad, [], "a temporary folder without a hypnomix- prefix: Disk care could not tell whose it is")

    def test_the_names_the_code_uses_are_names_disk_care_knows(self):
        from hypnomix.core import tmp as TMP
        for kind in TMP.KINDS:
            self.assertTrue(TMP.OWN.match(f"hypnomix-{kind}-abcd1234"), kind)
        for prefix in ("hypnomix-work-", "hypnomix-ab-", "hypnomix-alignset-"):
            self.assertTrue(TMP.OWN.match(prefix + "ab_d1234"), prefix)
        self.assertFalse(TMP.OWN.match("hypnomix-store-mnt-abcd1234"))             # a mount point is never ours to remove
        self.assertFalse(TMP.OWN.match("hypnomix-tests-abcd1234"))


class RenderCache(Scratch):
    def setUp(self):
        super().setUp()
        from hypnomix.session import render as R
        self.R = R
        self.root = self.r / "cache"
        self._env = mock.patch.dict(os.environ, HYPNOMIX_RENDER_CACHE=str(self.root))
        self._env.start()
        R._INDEX[0] = None
        R.CACHE_STATS.update(scans=0, writes=0)

    def tearDown(self):
        self.R._INDEX[0] = None
        self._env.stop()
        super().tearDown()

    def key(self, i):
        import hashlib
        return hashlib.sha256(str(i).encode()).hexdigest()

    def test_a_write_does_not_list_the_cache_again(self):
        seg = np.zeros(100, dtype=np.float32)
        scans = []
        real = self.R.CacheIndex.scan

        def counting(ix):
            scans.append(1)
            return real(ix)

        with mock.patch.object(self.R.CacheIndex, "scan", counting):
            for i in range(160):                                                 # the old code listed it at writes 1, 51, 101, 151
                self.R.cache_put(self.key(i), seg)
        self.assertEqual(len(scans), 1)
        self.assertEqual(len(list(self.root.glob("*/*.npy"))), 160)
        self.assertEqual(self.R._INDEX[0].total, sum(p.stat().st_size for p in self.root.glob("*/*.npy")))   # the running total is the real one

    def test_it_looks_again_after_the_rescan_age_for_what_other_programs_did(self):
        seg = np.zeros(100, dtype=np.float32)
        self.R.cache_put(self.key(0), seg)
        self.assertEqual(self.R.CACHE_STATS["scans"], 1)
        (self.root / self.key(0)[:2] / f"{self.key(0)}.npy").unlink()            # another program removes it
        self.R._INDEX[0].seen -= self.R.RESCAN_S + 1
        self.R.cache_put(self.key(1), seg)
        self.assertEqual(self.R.CACHE_STATS["scans"], 2)
        self.assertEqual(len(self.R._INDEX[0].files), 1)

    def test_over_the_cap_the_oldest_go_first_and_the_cap_holds(self):
        seg = np.zeros(1000, dtype=np.float32)                                   # about 4 KB each
        cap_mb = 0.02                                                            # 20 KB: about five entries
        with mock.patch.dict(os.environ, HYPNOMIX_RENDER_CACHE_MB=str(cap_mb)):
            for i in range(30):
                self.R.cache_put(self.key(i), seg)
                os.utime(self.root / self.key(i)[:2] / f"{self.key(i)}.npy", (1.7e9 + i, 1.7e9 + i))
        files = list(self.root.glob("*/*.npy"))
        self.assertLessEqual(sum(p.stat().st_size for p in files), cap_mb * 1e6 + 5000)   # within one entry of the cap
        left = {p.stem for p in files}
        self.assertIn(self.key(29), left)                                        # the newest stays

    def test_trim_picks_exactly_what_a_full_listing_would(self):
        import random
        rng = random.Random(3)
        sizes = {}
        for i in range(200):
            k = self.key(i)
            d = self.root / k[:2]
            d.mkdir(parents=True, exist_ok=True)
            np.save(d / f"{k}.npy", np.zeros(rng.randint(50, 2000), dtype=np.float32))
            t = 1.7e9 + rng.random() * 1e5                                       # distinct times
            os.utime(d / f"{k}.npy", (t, t))
            st = (d / f"{k}.npy").stat()
            sizes[k] = (st.st_mtime, st.st_size)
        cap = 0.15e6
        expected, total = set(sizes), sum(s for _, s in sizes.values())          # the old rule: oldest first until under the cap
        for k in sorted(sizes, key=lambda k: sizes[k]):
            if total <= cap:
                break
            expected.discard(k)
            total -= sizes[k][1]
        removed = self.R.cache_trim(cap_mb=cap / 1e6)
        self.assertEqual({p.stem for p in self.root.glob("*/*.npy")}, expected)
        self.assertEqual(removed, sum(s for k, (_, s) in sizes.items() if k not in expected))

    def test_a_clip_used_since_the_last_look_is_kept_and_one_removed_elsewhere_is_forgotten(self):
        seg = np.zeros(1000, dtype=np.float32)
        for i in range(6):
            self.R.cache_put(self.key(i), seg)
            os.utime(self.root / self.key(i)[:2] / f"{self.key(i)}.npy", (1.7e9 + i, 1.7e9 + i))
        self.R._INDEX[0].scan()                                                  # the index now knows the times above
        oldest = self.root / self.key(0)[:2] / f"{self.key(0)}.npy"
        os.utime(oldest, (1.8e9, 1.8e9))                                         # used just now (cache_get does this)
        (self.root / self.key(1)[:2] / f"{self.key(1)}.npy").unlink()            # another program removed one
        size = oldest.stat().st_size
        self.R._INDEX[0].trim(2 * size + 1)                                      # room for two
        left = {p.stem for p in self.root.glob("*/*.npy")}
        self.assertIn(self.key(0), left)                                         # newer than it looked: it waits
        self.assertEqual(len(left), 2)
        self.assertEqual(self.R._INDEX[0].total, sum(p.stat().st_size for p in self.root.glob("*/*.npy")))


def touch(p, n=1000, when=None):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * n)
    when = time.time() - 3 * DAY if when is None else when
    os.utime(p, (when, when))
    return p


class DiskCare(Scratch):
    def setUp(self):
        super().setUp()
        self._env2 = mock.patch.dict(os.environ, HYPNOMIX_APP_HOME=str(self.r / "Documents" / "Hypnomix"))
        self._env2.start()
        from hypnomix.app import diskcare as DC
        self.DC = DC
        self._space = DC.space
        DC.space = lambda: (500 * DC.GB, 1000 * DC.GB)

    def tearDown(self):
        self.DC.space = self._space
        self._env2.stop()
        super().tearDown()

    def old(self, folder, name="a.wav", days=3):
        when = time.time() - days * DAY
        p = touch(Path(folder) / name, when=when)
        os.utime(Path(folder), (when, when))
        return p

    def planned(self):
        return {str(i[2]) for i in self.DC.plan("ok")[0] if i[0] == "temp"}

    def test_our_own_old_folders_are_swept_in_both_places_and_nothing_else(self):
        mine_a = self.home / "cache" / "tmp" / "hypnomix-render-abcd1234"
        mine_b = self.systmp / "hypnomix-work-ab_d1234"
        recent = self.systmp / "hypnomix-render-newnew12"
        self.old(mine_a), self.old(mine_b)
        touch(recent / "a.wav", when=time.time())                                # a command running right now
        stranger = self.systmp / "hypnomix-backup"                               # somebody's own folder: not our name
        mount = self.systmp / "hypnomix-store-mnt-abcd1234"                      # a disk image: never
        unprefixed = self.systmp / "tmpwack_btj"
        for d in (stranger, mount, unprefixed):
            self.old(d)
        got = self.planned()
        self.assertEqual(got, {str(mine_a), str(mine_b)})

    def test_a_link_with_one_of_our_names_is_not_followed(self):
        target = self.r / "precious"
        self.old(target)
        link = self.systmp / "hypnomix-render-linkedxx"
        link.symlink_to(target, target_is_directory=True)
        self.assertEqual(self.planned(), set())
        self.DC.run("by hand")
        self.assertTrue((target / "a.wav").exists())

    def test_run_deletes_our_old_folders_and_reports_them_under_temp(self):
        mine = self.systmp / "hypnomix-render-abcd1234"
        self.old(mine, "k.wav")
        self.DC.run("by hand")
        self.assertFalse(mine.exists())
        rules = {r["rule"] for r in self.DC.load()["last"]["rules"]}
        self.assertIn("temp", rules)

    def test_old_unprefixed_folders_are_offered_never_swept(self):
        a = self.systmp / "tmpwack_btj"
        self.old(a, "Keys.wav")
        touch(a / "Bass.wav", 5000, when=time.time() - 3 * DAY)
        b = self.systmp / "tidy-kw3hm93b"
        self.old(b, "Vox.wav")
        recent = self.systmp / "tmprecent12"
        touch(recent / "x.wav", when=time.time())
        mixed = self.systmp / "tmpmixed123"                                      # holds something that is not a WAV: not offered
        self.old(mixed, "notes.txt")
        touch(mixed / "x.wav", when=time.time() - 3 * DAY)
        deep = self.systmp / "tmpdeepdir1"                                       # has a subfolder: not offered
        self.old(deep / "sub", "x.wav")
        other = self.systmp / "not-a-temp-name"
        self.old(other, "x.wav")
        names_only = self.systmp / "tmpnames123"                                 # duck/cliplevel without --names left only this
        self.old(names_only, "names.json")
        names_txt = self.systmp / "tmpnamestxt"                                  # names.json beside something else: not offered
        self.old(names_txt, "names.json")
        touch(names_txt / "notes.txt", when=time.time() - 3 * DAY)
        names_big = self.systmp / "tmpnamesbig"                                  # a names.json that is not small: not offered
        self.old(names_big, "names.json")
        with open(names_big / "names.json", "ab") as f:
            f.truncate(2_000_000)
        os.utime(names_big, (time.time() - 3 * DAY,) * 2)
        offered = {d["path"] for d in self.DC.old_leftovers()}
        self.assertEqual(offered, {str(a), str(b), str(names_only)})
        v = self.DC.view()["leftovers"]
        self.assertEqual(v["count"], 3)
        self.assertEqual(v["bytes"], 1000 + 5000 + 1000 + 1000)
        row = [d for d in self.DC.old_leftovers() if d["path"] == str(names_only)][0]
        self.assertEqual((row["wavs"], row["sample"]), (0, []))
        self.assertEqual(sorted(v["paths"]), sorted(offered))
        self.assertEqual(self.DC.old_leftovers()[0]["sample"], ["Bass.wav", "Keys.wav"])
        self.assertEqual(self.planned(), set())                                  # the plan never lists them
        self.DC.run("by hand")                                                   # a full clean leaves them where they are
        self.assertTrue(a.exists() and b.exists() and names_only.exists())

    def test_clear_old_removes_only_what_is_offered_and_ignores_everything_else(self):
        a = self.systmp / "tmpwack_btj"
        self.old(a, "Keys.wav")
        keep = self.systmp / "tmpkeepme12"
        self.old(keep, "k.wav")
        outside = self.r / "Documents" / "Hypnomix" / "scan"                     # a path of the real data: refused
        self.old(outside, "findings.json")
        notoffered = self.systmp / "tmpmixed123"
        self.old(notoffered, "notes.txt")
        r = self.DC.clear_old([str(a), str(outside), str(notoffered), "/", str(self.r)])
        self.assertEqual(r["cleared"], dict(count=1, bytes=1000))
        self.assertFalse(a.exists())
        self.assertTrue(keep.exists())                                           # offered, but not asked for
        self.assertTrue((outside / "findings.json").exists())
        self.assertTrue((notoffered / "notes.txt").exists())
        self.assertEqual(self.DC.view()["leftovers"]["count"], 1)

    def test_clear_old_checks_again_just_before_and_waits_for_a_running_job(self):
        a = self.systmp / "tmpwack_btj"
        self.old(a, "Keys.wav")
        r = self.DC.clear_old([str(a)], job_running=lambda: True)
        self.assertTrue(r["cleared"]["busy"])
        self.assertTrue(a.exists())
        touch(a / "late.txt", when=time.time() - 3 * DAY)                        # no longer only WAV files
        r = self.DC.clear_old([str(a)])
        self.assertEqual(r["cleared"]["count"], 0)
        self.assertTrue(a.exists())

    def test_the_route(self):
        a = self.systmp / "tmpwack_btj"
        self.old(a, "Keys.wav")
        code, body = self.DC.handle_post("/api/diskcare/clear-old", {"paths": [str(a)]})
        self.assertEqual((code, body["cleared"]["count"]), (200, 1))
        again = self.systmp / "tmpagain123"
        self.old(again, "b.wav")
        other = self.systmp / "tmpagain456"
        self.old(other, "c.wav")
        for bad in ({"paths": "x"}, {"paths": None}, {"paths": 5}, {}, None):    # not a list of folders: nothing is cleared
            code, body = self.DC.handle_post("/api/diskcare/clear-old", bad)
            self.assertEqual((code, body["cleared"]["count"]), (200, 0), bad)
            self.assertTrue(again.exists() and other.exists(), bad)
        self.assertEqual(self.DC.clear_old()["cleared"]["count"], 0)             # the function too: no list, no clearing
        self.assertEqual(self.DC.clear_old("x")["cleared"]["count"], 0)
        self.assertTrue(again.exists() and other.exists())

    def run_cli(self, *argv, tty=False, answer=""):
        import io
        from unittest import mock
        out = io.StringIO()
        fake_in = io.StringIO(answer + "\n")
        fake_in.isatty = lambda: tty
        with mock.patch.object(sys, "argv", ["diskcare", *argv]), mock.patch.object(sys, "stdin", fake_in), \
                mock.patch.object(sys, "stdout", out):
            self.DC.main()
        return out.getvalue()

    def test_cli_clear_old_asks_first_and_never_removes_without_an_answer(self):
        a = self.systmp / "tmpcli00001"
        self.old(a, "k.wav")
        n = self.systmp / "tmpcli00002"
        self.old(n, "names.json")
        text = self.run_cli("--clear-old", tty=False)                            # no terminal, no --yes: lists, removes nothing
        self.assertIn(str(a), text)
        self.assertIn("only a names.json", text)
        self.assertIn("--yes", text)
        self.assertTrue(a.exists() and n.exists())
        self.run_cli("--clear-old", tty=True, answer="n")                        # a terminal, the answer is no
        self.run_cli("--clear-old", tty=True, answer="")
        self.assertTrue(a.exists() and n.exists())
        text = self.run_cli("--clear-old", tty=True, answer="y")                 # a terminal, the answer is yes
        self.assertIn("cleared 2 old temp folder(s)", text)
        self.assertFalse(a.exists() or n.exists())
        b = self.systmp / "tmpcli00003"
        self.old(b, "k.wav")
        self.run_cli("--clear-old", "--yes")                                     # --yes answers for a script
        self.assertFalse(b.exists())
        self.assertIn("no old temp folders", self.run_cli("--clear-old", "--yes"))


if __name__ == "__main__":
    unittest.main()
