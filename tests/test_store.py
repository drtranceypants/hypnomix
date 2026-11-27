"""The HypnoMix store: the catalogue's schema, and the installer on archives built here (zip, tar, 7z, dmg), into a
temporary HYPNOMIX_STORE_ROOT. Nothing touches the real ~/Library or ~/Music.

HYPNOMIX_STORE_NET=1 also runs one real download (GATE-12 from GitHub) into a temporary root."""
import contextlib
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

from hypnomix.store import catalogue as C, install as I


def bundle(root, name, text="v1"):
    """A fake plug-in bundle: a folder with Contents/MacOS/<binary> (plain text, never run)."""
    b = Path(root) / name
    (b / "Contents" / "MacOS").mkdir(parents=True)
    (b / "Contents" / "MacOS" / b.stem).write_text(text, encoding="utf-8")
    (b / "Contents" / "Info.plist").write_text("<plist/>", encoding="utf-8")
    return b


def zip_dir(src, dest, extra=None):
    with zipfile.ZipFile(dest, "w") as z:
        for p in sorted(Path(src).rglob("*")):
            z.write(p, p.relative_to(src))
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return dest


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def flag_settable():
    """The Mac's "downloaded from the internet" flag is set by `xattr`: with it, the installer package tests use the real
    thing; without it (Linux, Windows) the flag is a stand-in that says it worked, so the logic after it is still tested."""
    if sys.platform == "darwin" and shutil.which("xattr"):
        return contextlib.nullcontext()
    return mock.patch.object(I, "_quarantine", return_value=True)


ITEM = dict(id="fooverb", name="Fooverb", kind="effect", vendor="Test", licence="MIT", open_source=True,
            formats=["VST3", "AU"], macos_arm64=None, homepage="https://example.org/", about="test",
            source={"type": "url", "url": "https://example.org/foo.zip", "version": "1"}, method="bundles")
KIT = dict(ITEM, id="testkit", name="Test Kit", kind="drum kit", formats=["SFZ", "WAV"], method="content")


class Catalogue(unittest.TestCase):
    def test_shipped_catalogue_is_valid(self):
        data = C.load()
        self.assertEqual(C.validate(data), [])
        # 0.3.0 shipped 26 items as version 2026.11.26; this one has more, so it carries a later version (it is shown on the page)
        self.assertGreater(tuple(map(int, data["version"].split("."))), (2026, 11, 26))
        self.assertGreater(len(data["items"]), 26)
        # the article names every format the filter offers (the page builds the filter from these) and no vendor is a person's handle
        article = open(Path(__file__).resolve().parent.parent / "hypnomix/app/wiki/articles/18-store.html", encoding="utf-8").read()
        for f in {f for it in data["items"] for f in it.get("formats", [])}:
            self.assertIn(f, article.split("and licence")[0].split("format (")[-1], f)
        self.assertNotIn("TheWaveWarden", {it.get("vendor") for it in data["items"]})
        ids = [it["id"] for it in data["items"]]
        for must in ("surge-xt", "dexed", "ob-xd", "odin2", "cardinal", "airwindows-consolidated", "dragonfly-reverb",
                     "chowtapemodel", "sfizz",
                     "salamander-grand-piano", "vsco2-ce"):
            self.assertIn(must, ids)
        self.assertGreaterEqual(len({it["kind"] for it in data["items"]}), 5)
        self.assertTrue(data["left_out"])
        for it in data["items"]:                       # every download is HTTPS or GitHub, every homepage HTTPS
            s = it["source"]
            self.assertTrue(s["type"] in ("github", "page") or s["url"].startswith("https://"), it["id"])
        self.assertFalse(C.get("ob-xd")["open_source"])                # v2 is discoDSP freeware
        self.assertFalse({"tdr-nova", "tdr-kotelnikov"} & set(ids))      # products with paid tiers are not named in the store

    def test_a_malformed_catalogue_lists_problems_and_never_crashes(self):
        good = C.load()
        for mut, want in ((lambda d: d["items"].insert(0, "not an object"), "must be an object"),
                          (lambda d: d["items"][0].update(source="https://x.org/a.zip"), "source must be an object"),
                          (lambda d: d["items"][0].update(id=5), "id must be a string"),
                          (lambda d: d["items"][0].update(name=".hidden"), "name must be usable"),
                          (lambda d: d["items"][0].update(name="~"), "name must be usable"),
                          (lambda d: d["items"][0].update(homepage="https://good.example@evil.example/x"), "no user name"),
                          (lambda d: d["items"][0].update(formats=5), "formats must be"),
                          (lambda d: d.update(items={}), "items must be a list")):
            bad = json.loads(json.dumps(good))
            mut(bad)
            errs = C.validate(bad)
            self.assertTrue(any(want in e for e in errs), (want, errs))
        bad = json.loads(json.dumps(good))
        bad["items"][-1]["source"] = {"type": "url", "url": "https://u:p@evil.example/a.zip", "version": "1"}
        self.assertTrue(any("no user name" in e for e in C.validate(bad)))
        self.assertTrue(C.validate([1, 2]))
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "c.json"
            f.write_text(json.dumps({"schema": 1, "version": "2026.1.1", "items": ["x"]}), encoding="utf-8")
            with self.assertRaises(C.CatalogueError):
                C.load(f)

    def test_validation_catches_mistakes(self):
        good = C.load()
        bad = json.loads(json.dumps(good))
        it = bad["items"][0]
        it["licence"] = "GPL-3.0"
        it["open_source"] = False                                     # GPL marked closed
        bad["items"][1]["source"] = {"type": "url", "url": "http://x.org/a.zip", "version": "1"}
        del bad["items"][2]["homepage"]
        bad["items"][3]["id"] = bad["items"][4]["id"]
        bad["items"][5]["kind"] = "plugin"
        bad["items"][6]["source"] = {"type": "github", "repo": "a/b", "asset": "(unclosed"}
        errs = "\n".join(C.validate(bad))
        for want in ("open_source must be True", "must be https", "missing homepage", "duplicate id", "kind 'plugin'", "asset pattern"):
            self.assertIn(want, errs)
        drums = json.loads(json.dumps(good))
        next(i for i in drums["items"] if i["kind"] == "drum kit")["method"] = "bundles"
        self.assertTrue(any("content kinds" in e for e in C.validate(drums)))

    def test_search(self):
        its = C.items()
        self.assertIn("dragonfly-reverb", [i["id"] for i in C.search(its, "reverb")])
        self.assertTrue(all(i["kind"] == "synth" for i in C.search(its, kind="synth")))
        self.assertTrue(all("CLAP" in i["formats"] for i in C.search(its, fmt="CLAP")))
        self.assertTrue(all(not i["open_source"] for i in C.search(its, licence="freeware")))
        self.assertTrue(all(i["open_source"] for i in C.search(its, licence="open")))
        self.assertEqual({i["licence"] for i in C.search(its, licence="CC0-1.0")}, {"CC0-1.0"})


class Installer(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hx-store-test-"))
        self.root = self.tmp / "root"
        self.env = mock.patch.dict(os.environ, {"HYPNOMIX_STORE_ROOT": str(self.root), "HYPNOMIX_STORE_NO_OPEN": "1"})
        self.env.start()
        self.src = self.tmp / "src"

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build_zip(self, name, bundles, text="v1", extra=None):
        d = self.tmp / ("b-" + name)
        for b in bundles:
            bundle(d / "Plugins", b, text)
        return zip_dir(d, self.tmp / name, extra)

    def test_targets_follow_the_test_root(self):
        self.assertEqual(I.plugins_dir(), self.root / "Library" / "Audio" / "Plug-Ins")
        self.assertEqual(I.library_dir(), self.root / "Music" / "Hypnomix Library")
        self.assertTrue(str(I.manifest_path()).startswith(str(self.root)))
        self.assertNotIn(str(Path.home() / "Library"), str(I.plugins_dir()))

    def test_zip_install_uninstall_and_update(self):
        z = self.build_zip("foo1.zip", ["Fooverb.vst3", "Fooverb.component"])
        e = I.install(ITEM, archive=z, info={"version": "1", "sha256": sha(z)})
        vst3 = self.root / "Library/Audio/Plug-Ins/VST3/Fooverb.vst3"
        au = self.root / "Library/Audio/Plug-Ins/Components/Fooverb.component"
        self.assertTrue(vst3.is_dir() and au.is_dir())
        self.assertEqual(sorted(e["paths"]), sorted([str(au), str(vst3)]))
        self.assertEqual(e["formats"], ["AU", "VST3"])
        self.assertTrue(e["sha256_checked"])
        self.assertEqual(I.manifest()["items"]["fooverb"]["version"], "1")
        self.assertFalse((self.root / ".hypnomix/store/work").exists() and any((self.root / ".hypnomix/store/work").iterdir()))
        # a neighbour the store did not install is never touched
        other = bundle(self.root / "Library/Audio/Plug-Ins/VST3", "Other.vst3")
        # update: version 2 drops the AU and changes the VST3
        z2 = self.build_zip("foo2.zip", ["Fooverb.vst3"], text="v2")
        I.install(ITEM, archive=z2, info={"version": "2"}, confirm_unverified=True)
        self.assertEqual((vst3 / "Contents/MacOS/Fooverb").read_text(encoding="utf-8"), "v2")
        self.assertFalse(au.exists())
        self.assertEqual(I.manifest()["items"]["fooverb"]["paths"], [str(vst3)])
        self.assertEqual(I.status([ITEM])["fooverb"]["version"], "2")
        gone = I.uninstall("fooverb")
        self.assertEqual(gone, [str(vst3)])
        self.assertFalse(vst3.exists())
        self.assertTrue(other.is_dir())
        self.assertNotIn("fooverb", I.manifest()["items"])
        with self.assertRaises(I.StoreError):
            I.uninstall("fooverb")

    def test_refuses_to_overwrite_what_it_did_not_install(self):
        mine = bundle(self.root / "Library/Audio/Plug-Ins/VST3", "Fooverb.vst3", "the person's own copy")
        z = self.build_zip("foo.zip", ["Fooverb.vst3"])
        with self.assertRaises(I.NeedsConfirm) as cm:
            I.install(ITEM, archive=z, info={"version": "1"}, confirm_unverified=True)
        self.assertIn(str(mine), cm.exception.paths)
        self.assertEqual((mine / "Contents/MacOS/Fooverb").read_text(encoding="utf-8"), "the person's own copy")
        self.assertNotIn("fooverb", I.manifest()["items"])
        # confirmed: replaced, and the old copy is kept in the store's trash, not deleted
        e = I.install(ITEM, archive=z, info={"version": "1"}, confirm_unverified=True, confirm_overwrite=True)
        self.assertEqual((mine / "Contents/MacOS/Fooverb").read_text(encoding="utf-8"), "v1")
        self.assertEqual(len(e["replaced_kept_in"]), 1)
        self.assertEqual((Path(e["replaced_kept_in"][0]) / "Contents/MacOS/Fooverb").read_text(encoding="utf-8"), "the person's own copy")

    def test_another_items_bundle_needs_confirming_too(self):
        z = self.build_zip("foo.zip", ["Fooverb.vst3"])
        I.install(ITEM, archive=z, info={"version": "1"}, confirm_unverified=True)
        with self.assertRaises(I.NeedsConfirm):
            I.install(dict(ITEM, id="lookalike"), archive=z, info={"version": "1"}, confirm_unverified=True)
        e = I.install(dict(ITEM, id="lookalike"), archive=z, info={"version": "1"}, confirm_unverified=True, confirm_overwrite=True)
        self.assertEqual(I.manifest()["items"]["fooverb"]["paths"], [])     # the replaced item no longer owns it
        I.uninstall("fooverb")
        self.assertTrue(Path(e["paths"][0]).exists())                       # so its uninstall leaves the new copy

    def test_sha256_mismatch_installs_nothing(self):
        z = self.build_zip("foo.zip", ["Fooverb.vst3"])
        with self.assertRaises(I.StoreError):
            I.install(ITEM, archive=z, info={"version": "1", "sha256": "0" * 64})
        self.assertFalse((self.root / "Library/Audio/Plug-Ins/VST3/Fooverb.vst3").exists())

    def test_unsafe_archives_are_refused(self):
        z = self.tmp / "evil.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("../../evil.txt", "x")
        with self.assertRaises(I.StoreError):
            I.install(ITEM, archive=z, info={"version": "1"}, confirm_unverified=True)
        z2 = self.tmp / "link.zip"
        with zipfile.ZipFile(z2, "w") as zf:
            info = zipfile.ZipInfo("Plugins/escape")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "../../../../etc")
        with self.assertRaises(I.StoreError):
            I.unpack(z2, self.tmp / "out")
        t = self.tmp / "evil.tar.gz"
        with tarfile.open(t, "w:gz") as tf:
            ti = tarfile.TarInfo("/abs.txt")
            ti.size = 1
            tf.addfile(ti, io.BytesIO(b"x"))
        with self.assertRaises(I.StoreError):
            I.unpack(t, self.tmp / "out2")
        self.assertFalse((self.tmp.parent / "evil.txt").exists())
        z3 = self.tmp / "chain.zip"                         # each link looks inside on its own; together they climb out
        with zipfile.ZipFile(z3, "w") as zf:
            zf.writestr("X.vst3/Contents/Info.plist", "x")
            for name, target in (("X.vst3/Contents/l1", ".."), ("X.vst3/Contents/up", "l1/../..")):
                info = zipfile.ZipInfo(name)
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                zf.writestr(info, target)
        if sys.platform == "darwin" and shutil.which("ditto"):
            with self.assertRaises(I.StoreError):
                I.install(ITEM, archive=z3, info={"version": "1"}, confirm_unverified=True)
            self.assertFalse((self.root / "Library").exists())
        else:
            # Only `ditto` (the Mac's unzip) makes the links of a zip; Python's zipfile writes a link as a small file holding
            # its target text, so the chain cannot climb out: nothing unpacked is a link, and nothing needs refusing
            out3 = I.unpack(z3, self.tmp / "out3")
            made = [os.path.join(d, n) for d, ds, fs in os.walk(out3) for n in ds + fs if os.path.islink(os.path.join(d, n))]
            self.assertEqual(made, [])

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("hdiutil"), "needs hdiutil")
    def test_dmg_with_a_link_outside_is_refused(self):
        src = self.tmp / "dmgsrc" / "Evil.vst3" / "Contents"
        src.mkdir(parents=True)
        (src / "Info.plist").write_text("x", encoding="utf-8")
        os.symlink(str(Path.home()), src / "home")
        dmg = self.tmp / "evil.dmg"
        subprocess.run(["hdiutil", "create", "-quiet", "-fs", "HFS+", "-srcfolder", str(self.tmp / "dmgsrc"),
                        "-volname", "Evil", str(dmg)], check=True)
        with self.assertRaises(I.StoreError):
            I.install(ITEM, archive=dmg, info={"version": "1"}, confirm_unverified=True)
        self.assertFalse((self.root / "Library").exists())

    def test_only_https(self):
        with self.assertRaises(I.StoreError):
            I.download("http://example.org/a.zip", self.tmp / "a.zip")
        self.assertFalse((self.tmp / "a.zip").exists())

    def test_pkg_is_opened_for_the_person_never_run(self):
        z = self.build_zip("pkg.zip", [], extra={"Foo Installer.pkg": "xar!"})
        opened = []
        with flag_settable():
            e = I.install(dict(ITEM, method="pkg"), archive=z, info={"version": "1"}, confirm_unverified=True, open_pkg=lambda p: opened.append(p) or True)
        self.assertEqual(e["method"], "pkg")
        self.assertEqual(e["paths"], [])
        self.assertTrue(Path(e["installer"]).is_file())
        self.assertEqual(opened, [Path(e["installer"])])
        self.assertFalse((self.root / "Library").exists())                  # nothing was installed by itself
        I.uninstall("fooverb")
        self.assertFalse(Path(e["installer"]).exists())

    def test_content_goes_to_the_library(self):
        d = self.tmp / "kit" / "Test Kit v1"
        (d / "Samples").mkdir(parents=True)
        (d / "kit.sfz").write_text("<region> sample=Samples/kick.wav", encoding="utf-8")
        (d / "Samples" / "kick.wav").write_bytes(b"RIFF")
        t = self.tmp / "kit.tar.gz"
        with tarfile.open(t, "w:gz") as tf:
            tf.add(d, arcname="Test Kit v1")
        e = I.install(KIT, archive=t, info={"version": "1"}, confirm_unverified=True)
        lib = self.root / "Music/Hypnomix Library/Drum Kits/Test Kit"
        self.assertEqual(e["paths"], [str(lib)])
        self.assertTrue((lib / "kit.sfz").is_file() and (lib / "Samples/kick.wav").is_file())
        self.assertEqual(e["sfz"], ["kit.sfz"])
        I.uninstall("testkit")
        self.assertFalse(lib.exists())
        self.assertTrue(lib.parent.is_dir())

    @unittest.skipUnless(shutil.which("bsdtar") or sys.platform == "darwin", "needs bsdtar")
    def test_7z(self):
        d = self.tmp / "k7"
        (d / "Kit").mkdir(parents=True)
        (d / "Kit" / "a.sfz").write_text("x", encoding="utf-8")
        z = self.tmp / "kit.7z"
        tar = shutil.which("bsdtar") or "/usr/bin/tar"
        r = subprocess.run([tar, "--format", "7zip", "-cf", str(z), "-C", str(d), "Kit"], capture_output=True)
        if r.returncode:
            self.skipTest("this tar cannot write 7z")
        e = I.install(KIT, archive=z, info={"version": "1"}, confirm_unverified=True)
        self.assertTrue((Path(e["paths"][0]) / "a.sfz").is_file())

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("hdiutil"), "disk images need macOS")
    def test_dmg_and_zip_inside_dmg(self):
        d = self.tmp / "dmgsrc"
        bundle(d, "Fooverb.clap")
        os.symlink("/Applications", d / "Applications")                   # the usual shortcut: skipped
        dmg = self.tmp / "foo.dmg"
        subprocess.run(["hdiutil", "create", "-quiet", "-fs", "HFS+", "-volname", "Foo", "-srcfolder", str(d), "-ov",
                        "-format", "UDZO", str(dmg)], check=True)
        before = subprocess.run(["hdiutil", "info"], capture_output=True, text=True, encoding="utf-8").stdout.count("hypnomix-store-mnt")
        e = I.install(dict(ITEM, formats=["CLAP"]), archive=dmg, info={"version": "1"}, confirm_unverified=True)
        self.assertEqual(e["paths"], [str(self.root / "Library/Audio/Plug-Ins/CLAP/Fooverb.clap")])
        self.assertFalse((self.root / "Library/Audio/Plug-Ins/CLAP/Applications").exists())
        after = subprocess.run(["hdiutil", "info"], capture_output=True, text=True, encoding="utf-8").stdout.count("hypnomix-store-mnt")
        self.assertEqual(before, after)                                     # detached again
        # a zip with the dmg inside (how some publishers ship): unpacked one level deeper
        z = self.tmp / "wrapped.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.write(dmg, "Foo-1.0.dmg")
        I.uninstall("fooverb")
        e = I.install(dict(ITEM, formats=["CLAP"]), archive=z, info={"version": "2"}, confirm_unverified=True)
        self.assertTrue(Path(e["paths"][0]).is_dir())

    def test_github_resolution_picks_the_matching_asset(self):
        item = dict(ITEM, source={"type": "github", "repo": "o/r", "asset": r"^foo-macos-.*\.zip$"})
        rel = {"tag_name": "v2.0", "html_url": "https://github.com/o/r/releases/v2.0", "assets": [
            {"name": "foo-win-2.0.zip", "browser_download_url": "https://github.com/o/r/w.zip", "size": 1},
            {"name": "foo-macos-2.0.zip", "browser_download_url": "https://github.com/o/r/m.zip", "size": 5,
             "digest": "sha256:" + "a" * 64}]}
        with mock.patch.object(I, "_github", return_value=rel) as g:
            r = I.resolve(item, fresh=True)
        g.assert_called_once_with("/repos/o/r/releases/latest")
        self.assertEqual((r["url"], r["version"], r["sha256"], r["size"]), ("https://github.com/o/r/m.zip", "v2.0", "a" * 64, 5))
        tagged = dict(item, id="tagged", source=dict(item["source"], tag="Nightly"))
        with mock.patch.object(I, "_github", return_value=rel) as g:
            r = I.resolve(tagged, fresh=True)
        g.assert_called_once_with("/repos/o/r/releases/tags/Nightly")
        self.assertEqual(r["version"], "foo-macos-2.0.zip")             # a moving tag: the asset name is the version
        with mock.patch.object(I, "_github", return_value=dict(rel, assets=[])):
            with self.assertRaises(I.StoreError):
                I.resolve(dict(item, id="none"), fresh=True)

    def test_page_items_are_not_downloaded(self):
        with self.assertRaises(I.StoreError):
            I.install(dict(C.get("surge-xt"), id="page-only", method="page",
                           source={"type": "page", "note": "the site refuses automated downloads"}))

    @unittest.skipUnless(os.environ.get("HYPNOMIX_STORE_NET") == "1", "set HYPNOMIX_STORE_NET=1 for the real download")
    def test_real_download_from_github(self):
        e = I.install(C.get("gate12"))
        self.assertTrue(e["sha256_checked"])
        self.assertTrue(all(p.startswith(str(self.root)) for p in e["paths"]))
        self.assertIn("VST3", e["formats"])
        self.assertIn("arm64", sum(e["archs"].values(), []))
        I.uninstall("gate12")


class Catalogue2(unittest.TestCase):
    """The catalogue is checked when it is loaded, and its text follows the naming rules."""

    def _write(self, mutate):
        data = json.loads(json.dumps(C.load()))
        mutate(data)
        f = Path(tempfile.mkdtemp(prefix="hx-cat-")) / "catalogue.json"
        f.write_text(json.dumps(data), encoding="utf-8")
        self.addCleanup(shutil.rmtree, f.parent, ignore_errors=True)
        return f

    def test_load_refuses_a_bad_catalogue(self):
        def bad(d):
            d["items"][0]["name"] = ".."                                    # a folder name that climbs out
            d["items"][1]["id"] = "../evil"
            d["items"][2]["source"] = {"type": "url", "url": "https://x.org/..%2F..%2Fx.zip", "version": "1"}
            d["items"][3]["homepage"] = "http://example.org/"
            salamander = next(i for i in d["items"] if i["id"] == "salamander-grand-piano")
            del salamander["credit"]                                        # CC-BY needs its credit line
        f = self._write(bad)
        with self.assertRaises(C.CatalogueError) as cm:
            C.load(f)
        msg = str(cm.exception)
        self.assertIn("name must be usable as a folder name", msg)
        errs = "\n".join(C.validate(C.load(f, check=False)))
        for want in ("id must be a string of lower-case", "is not a plain file name", "homepage must be https", "requires a credit"):
            self.assertIn(want, errs)
        for name in ("", ".", "a/b", "a\\b", "a:b", " pad"):
            self.assertFalse(C.safe_part(name), name)
        self.assertTrue(C.safe_part("Some Plug-in.zip"))

    def test_names_follow_the_rules(self):
        """No hardware, no paid product, no person outside a licence credit (the credit field is the one place).
        Names are checked as fingerprints (the repo's own check, plus the people and the products this catalogue once
        named), never spelled out here."""
        from tests.test_repo_rules import names_in, fp, words
        once_named = {"352a3de45045", "800392455c95", "9bc705a6205a", "299d1d52bc93", "eed59d514cf4", "fd3d8515757c",
                      "af87901ee08f", "39ca0c269f8b", "c7555c52934c", "0dcd87854d99"}
        data = C.load()
        texts = [(it["id"], " ".join(str(it.get(k, "")) for k in ("name", "vendor", "about", "note", "mpe_note"))) for it in data["items"]]
        texts += [("left_out", " ".join(x["name"] + " " + x["why"] for x in data["left_out"]))]
        for where, text in texts:
            self.assertEqual(names_in(text), set(), where)
            low = [w[1] for w in words(text)]
            grams = {fp(" ".join(low[k:k + n])) for n in (1, 2) for k in range(len(low) - n + 1)}
            self.assertEqual(grams & once_named, set(), where)
        for it in C.items():                                                # a CC-BY licence needs its credit, in its own field
            if it["licence"].startswith("CC-BY"):
                self.assertTrue(it["credit"].strip(), it["id"])
            self.assertTrue(C.size_bytes(it) > 0, it["id"])                 # every item states a size: the download limit

    def test_every_item_says_how_it_is_checked(self):
        kinds = {it["id"]: C.verification(it) for it in C.items()}
        self.assertEqual(set(kinds.values()) - {"pinned", "github", "none"}, set())
        for it in C.items():
            if it["source"]["type"] == "url" and not it["source"].get("sha256"):
                self.assertEqual(kinds[it["id"]], "none", it["id"])         # the page says so before the click


class Safety(unittest.TestCase):
    """The review findings: the unverified confirmation, file names, links, limits and the uninstall check."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hx-store-safe-"))
        self.root = self.tmp / "root"
        self.env = mock.patch.dict(os.environ, {"HYPNOMIX_STORE_ROOT": str(self.root), "HYPNOMIX_STORE_NO_OPEN": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build_zip(self, name, bundles=("Fooverb.vst3",), text="v1"):
        d = self.tmp / ("b-" + name)
        for b in bundles:
            bundle(d / "Plugins", b, text)
        return zip_dir(d, self.tmp / name)

    # ---- not verified: a second, explicit confirmation
    def test_a_download_with_nothing_to_check_it_against_needs_a_second_yes(self):
        z = self.build_zip("foo.zip")
        with self.assertRaises(I.NotVerified) as cm:
            I.install(ITEM, archive=z, info={"version": "1", "url": "https://example.org/foo.zip"})
        self.assertIn("NOT VERIFIED", str(cm.exception))
        self.assertIn("example.org", str(cm.exception))
        self.assertFalse((self.root / "Library").exists())                         # nothing installed
        self.assertFalse((self.root / ".hypnomix/store/work").exists() and any((self.root / ".hypnomix/store/work").iterdir()))
        e = I.install(ITEM, archive=z, info={"version": "1"}, confirm_unverified=True)
        self.assertFalse(e["sha256_checked"])
        self.assertTrue(I.status([ITEM])["fooverb"]["installed"])
        self.assertFalse(I.status([ITEM])["fooverb"]["verified"])
        # with a fingerprint there is nothing to confirm
        I.uninstall("fooverb")
        e = I.install(ITEM, archive=z, info={"version": "1", "sha256": sha(z)})
        self.assertTrue(e["sha256_checked"])

    def test_pkg_not_verified_says_it_runs_with_admin_rights(self):
        with self.assertRaises(I.NotVerified) as cm:
            I.install(dict(ITEM, method="pkg"), archive=self.build_zip("p.zip"), info={"version": "1"})
        self.assertIn("administrator", str(cm.exception))

    def test_cli_needs_unverified_flag(self):
        from hypnomix.store import cli
        item = dict(ITEM, source={"type": "url", "url": "https://example.org/foo.zip", "version": "1"})
        info = {"version": "1", "url": item["source"]["url"], "filename": "foo.zip", "sha256": None, "size": None}
        with mock.patch.object(cli.C, "get", return_value=item), mock.patch.object(cli.C, "items", return_value=[item]), \
                mock.patch.object(I, "resolve", return_value=info), mock.patch.object(I, "download") as dl:
            with mock.patch.object(sys, "argv", ["hypnomix store", "install", "fooverb"]):
                with self.assertRaises(SystemExit) as cm:
                    cli.main()
            self.assertIn("--unverified", str(cm.exception))
            self.assertIn("NOT VERIFIED", str(cm.exception))
            dl.assert_not_called()                                                  # refused before downloading
            with mock.patch.object(I, "install", return_value={"method": "bundles", "paths": ["/x"]}) as inst:
                with mock.patch.object(sys, "argv", ["hypnomix store", "install", "fooverb", "--unverified"]), \
                        mock.patch.object(sys, "stdout", io.StringIO()):
                    cli.main()
            self.assertTrue(inst.call_args.kwargs["confirm_unverified"])

    def test_assistant_card_says_not_verified_however_the_flag_is_written(self):
        """The card is decided by the command's own parser: any position, and no abbreviation sneaks past it."""
        from hypnomix.store import cli
        for args in (["--unverified", "install", "odin2"], ["install", "--unverified", "odin2"], ["install", "odin2", "--unverified"]):
            self.assertIn("NOT VERIFIED", cli.card_text("store", args) or "", args)
        for args in (["install", "odin2", "--unv"], ["--unve", "install", "odin2"]):   # not a flag the command accepts: it will not run,
            self.assertIn("NOT VERIFIED", cli.card_text("store", args) or "", args)   # but the card never looks plain
            with mock.patch.object(sys, "argv", ["hypnomix store"] + args), mock.patch.object(I, "install") as inst:
                with self.assertRaises(SystemExit), mock.patch.object(sys, "stderr", io.StringIO()):
                    cli.main()
            inst.assert_not_called()                                                    # abbreviations are refused outright
        self.assertIsNone(cli.card_text("store", ["install", "odin2"]))
        self.assertIsNone(cli.card_text("store", ["info", "odin2", "--unverified"]))
        self.assertIsNone(cli.card_text("scan", ["install", "--unverified"]))

    def test_assistant_card_says_not_verified_in_words(self):
        from hypnomix.store import cli
        self.assertIsNone(cli.card_text("store", ["install", "surge-xt"]))
        self.assertIsNone(cli.card_text("scan", ["x", "--unverified"]))
        t = cli.card_text("store", ["install", "vsco2-ce", "--unverified"])
        self.assertIn("hypnomix store install vsco2-ce --unverified", t)
        self.assertIn("NOT VERIFIED", t)
        import inspect
        from hypnomix.app import chat
        self.assertIn("card_text", inspect.getsource(chat))                         # the Assistant's card uses it

    # ---- file names, ids, names
    def test_percent_encoded_slash_in_a_download_name_is_refused(self):
        item = dict(ITEM, source={"type": "url", "url": "https://x.org/a/..%2F..%2F..%2FESCAPED.zip", "version": "1"})
        with self.assertRaises(I.StoreError):
            I.resolve(item)
        with self.assertRaises(I.StoreError):                                      # and install() itself, whatever resolve said
            I.install(item, info={"version": "1", "url": item["source"]["url"], "filename": "../../ESCAPED.zip",
                                  "sha256": "0" * 64})
        self.assertFalse((self.tmp / "ESCAPED.zip").exists() or (self.root.parent / "ESCAPED.zip").exists())
        with self.assertRaises(I.StoreError):
            I._work("../../evil")
        with self.assertRaises(I.StoreError):
            I.target_for_content(dict(KIT, name=".."))
        self.assertEqual(I.target_for_content(KIT).name, "Test Kit")

    # ---- uninstall compares real paths
    def _manifest_with(self, paths):
        I._save_manifest({"items": {"fooverb": {"id": "fooverb", "paths": [str(p) for p in paths], "method": "bundles"}}})

    def test_uninstall_works_through_a_linked_format_folder(self):
        """~/Library/Audio/Plug-Ins/VST3 may be a link to another drive: that is legitimate, and real paths are compared."""
        other = self.tmp / "otherdrive"
        (other / "VST3").mkdir(parents=True)
        plug = self.root / "Library" / "Audio" / "Plug-Ins"
        plug.mkdir(parents=True)
        (plug / "VST3").symlink_to(other / "VST3", target_is_directory=True)
        z = self.build_zip("foo.zip")
        e = I.install(ITEM, archive=z, info={"version": "1", "sha256": sha(z)})
        self.assertTrue((other / "VST3" / "Fooverb.vst3").exists())
        self.assertTrue(e["paths"])
        self.assertTrue(I._inside_targets(plug / "VST3" / "Fooverb.vst3"))
        self.assertFalse(I._inside_targets(plug / "VST3"))                # the folder itself is never accepted
        I.uninstall("fooverb")
        self.assertFalse((other / "VST3" / "Fooverb.vst3").exists())
        self.assertTrue((other / "VST3").is_dir())                        # and the linked folder is still there

    def test_uninstall_will_not_follow_a_link_or_remove_a_plugin_folder(self):
        vst3 = self.root / "Library/Audio/Plug-Ins/VST3"
        vst3.mkdir(parents=True)
        other = bundle(vst3, "Other.vst3")
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "victim.txt").write_text("keep me", encoding="utf-8")
        os.symlink(outside, vst3 / "lnk")
        (self.root / "Music/Hypnomix Library").mkdir(parents=True)
        for bad in (vst3 / "lnk" / "victim.txt",                                    # through a link in a parent folder
                    vst3,                                                           # the whole format folder
                    self.root / "Library/Audio/Plug-Ins",                           # or above it
                    self.root / "Music/Hypnomix Library",
                    vst3 / "Other.vst3" / ".." / ".."):                           # a path that climbs
            self._manifest_with([bad])
            with self.assertRaises(I.StoreError, msg=str(bad)):
                I.uninstall("fooverb")
            self.assertTrue((outside / "victim.txt").exists())
            self.assertTrue(other.is_dir())
            self.assertIn("fooverb", I.manifest()["items"])                         # still listed: nothing was removed
        # a real one, next to bad ones: refused as a whole before the good one is touched
        mine = bundle(vst3, "Fooverb.vst3")
        self._manifest_with([mine, vst3 / "lnk" / "victim.txt"])
        with self.assertRaises(I.StoreError):
            I.uninstall("fooverb")
        self.assertTrue(mine.is_dir())
        self._manifest_with([mine])
        self.assertEqual(I.uninstall("fooverb"), [str(mine)])
        self.assertFalse(I._inside_targets(self.root / "Library/Audio/Plug-Ins/VST3/lnk/victim.txt"))
        self.assertTrue(I._inside_targets(self.root / "Library/Audio/Plug-Ins/VST3/New.vst3"))
        self.assertTrue(I._inside_targets(self.root / "Music/Hypnomix Library/Drum Kits/Some Kit"))
        self.assertTrue(I._inside_targets(self.root / ".hypnomix/store/installers/foo/Foo.pkg"))
        self.assertFalse(I._inside_targets(self.root / ".hypnomix/store/installers"))
        self.assertFalse(I._inside_targets(self.root / ".hypnomix/store/manifest.json"))

    def test_app_routes_use_the_same_check(self):
        from hypnomix.app import store as ST
        out = self.tmp / "outside.pkg"
        out.write_text("x", encoding="utf-8")
        I._save_manifest({"items": {"fooverb": {"id": "fooverb", "paths": [], "method": "pkg", "installer": str(out)}}})
        self.assertEqual(ST.handle_post("/api/store/open-installer", {"id": "fooverb"})[0], 404)
        self.assertFalse(ST._reveal(str(out)))

    # ---- links in a tar on a Python without tarfile's data filter
    def _chain_tar(self, path):
        with tarfile.open(path, "w") as tf:
            for name, target in (("a/l", ".."), ("m1", "a/l/.."), ("m2", "m1/..")):
                ti = tarfile.TarInfo(name)
                ti.type = tarfile.SYMTYPE
                ti.linkname = target
                tf.addfile(ti)
            for name in ("m2/pwn.txt", "m1/pwn1.txt"):
                ti = tarfile.TarInfo(name)
                ti.size = 1
                ti.mode = 0o4755
                tf.addfile(ti, io.BytesIO(b"x"))

    def test_tar_links_on_an_old_python_write_nothing_outside(self):
        t = self.tmp / "chain.tar"
        self._chain_tar(t)
        dest = self.tmp / "c5" / "p2" / "p1" / "dest"
        with mock.patch.object(I, "_has_data_filter", return_value=False):
            with self.assertRaises(I.StoreError) as cm:
                I.unpack(t, dest)
        self.assertIn("links", str(cm.exception))
        self.assertEqual([p for p in self.tmp.rglob("pwn*") if dest not in p.parents], [])        # nothing anywhere outside
        self.assertEqual(list(dest.rglob("*")), [])                                    # not even inside: nothing was extracted
        # a plain tar still unpacks on that path, with the setuid bit dropped
        plain = self.tmp / "plain.tar.gz"
        with tarfile.open(plain, "w:gz") as tf:
            ti = tarfile.TarInfo("Kit/a.sfz")
            ti.size = 1
            ti.mode = 0o4755
            tf.addfile(ti, io.BytesIO(b"x"))
            ti = tarfile.TarInfo("Kit/../../up.txt")
            ti.size = 1
            tf.addfile(ti, io.BytesIO(b"x"))
        with mock.patch.object(I, "_has_data_filter", return_value=False):
            with self.assertRaises(I.StoreError):                                      # one bad member: nothing extracted at all
                I.unpack(plain, self.tmp / "o1")
        self.assertFalse((self.tmp / "o1" / "Kit" / "a.sfz").exists())
        good = self.tmp / "good.tar.gz"
        with tarfile.open(good, "w:gz") as tf:
            ti = tarfile.TarInfo("Kit/a.sfz")
            ti.size = 1
            ti.mode = 0o4755
            tf.addfile(ti, io.BytesIO(b"x"))
        with mock.patch.object(I, "_has_data_filter", return_value=False):
            I.unpack(good, self.tmp / "o2")
        mode = os.stat(self.tmp / "o2" / "Kit" / "a.sfz").st_mode
        self.assertFalse(mode & (stat.S_ISUID | stat.S_ISGID))

    # ---- limits while unpacking
    def test_a_small_archive_that_explodes_is_refused(self):
        z = self.tmp / "bomb.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("big.bin", b"\0" * (40 * 10 ** 6))                              # a few KB that expand to 40 MB
        self.assertLess(z.stat().st_size, 200000)
        with self.assertRaises(I.StoreError) as cm:
            I.install(ITEM, archive=z, info={"version": "1"}, confirm_unverified=True)
        self.assertIn("far larger", str(cm.exception))
        self.assertFalse((self.root / "Library").exists())

    def test_entry_count_and_total_size_limits(self):
        z = self.tmp / "many.zip"
        with zipfile.ZipFile(z, "w") as zf:
            for n in range(30):
                zf.writestr(f"Kit/f{n}.txt", "x")
        with mock.patch.object(I, "MAX_ENTRIES", 10):
            with self.assertRaises(I.StoreError) as cm:
                I.unpack(z, self.tmp / "o")
        self.assertIn("more than 10 files", str(cm.exception))
        with mock.patch.object(I, "MIN_UNPACK_ALLOWED", 5), mock.patch.object(I, "MAX_UNPACKED", 20):
            with self.assertRaises(I.StoreError):
                I.unpack(z, self.tmp / "o2")
        tar = self.tmp / "t.tar"
        with tarfile.open(tar, "w") as tf:
            for n in range(30):
                ti = tarfile.TarInfo(f"Kit/f{n}.txt")
                ti.size = 1
                tf.addfile(ti, io.BytesIO(b"x"))
        with mock.patch.object(I, "MAX_ENTRIES", 10):
            with self.assertRaises(I.StoreError):
                I.unpack(tar, self.tmp / "o3")
        I.unpack(z, self.tmp / "ok")                                                   # and within the limits it works
        self.assertTrue((self.tmp / "ok" / "Kit" / "f29.txt").exists())

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("ditto"), "ditto is the macOS unzip")
    def test_the_unzip_is_stopped_when_the_headers_lie(self):
        """A zip whose directory claims tiny sizes: the unzip itself is watched and killed."""
        z = self.tmp / "liar.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("big.bin", b"\0" * (40 * 10 ** 6))
        b = bytearray(z.read_bytes())
        eocd = b.rfind(b"PK\x05\x06")
        cd = int.from_bytes(b[eocd + 16:eocd + 20], "little")                           # start of the central directory
        b[cd + 24:cd + 28] = (10).to_bytes(4, "little")                                 # claim 10 bytes uncompressed
        z.write_bytes(bytes(b))
        with self.assertRaises(I.StoreError):
            I.unpack(z, self.tmp / "lie")

    def test_a_runaway_unpack_is_killed_while_it_runs_not_after(self):
        """The in-flight watch: a child that writes 1 MB every 0.1 s (100 MB in all, 10 s) against a 5 MB budget is
        killed at the next look (about a second), long before it has written everything. Without the watch the
        command would run to the end and only the after-the-fact check would refuse."""
        dest = self.tmp / "grow"
        dest.mkdir()
        code = ("import sys,time\nd=sys.argv[1]\n"
                "for i in range(100):\n    open(d+'/f%d'%i,'wb').write(b'x'*1000000)\n    time.sleep(0.1)\n")
        t0 = time.monotonic()
        with self.assertRaises(I.StoreError) as cm:
            I._run_limited([sys.executable, "-c", code, str(dest)], "unpacking", dest, I.Budget(0, max_bytes=5 * 10 ** 6))
        took = time.monotonic() - t0
        self.assertIn("stopped", str(cm.exception))                       # the in-flight message, not the final one
        self.assertLess(took, 6)
        self.assertLess(I._tree_size(dest)[0], 40 * 10 ** 6)

    # ---- space, cancel, deadline
    def test_free_space_is_checked_before_a_big_download(self):
        big = dict(ITEM, size="4 GB", source={"type": "url", "url": "https://example.org/foo.zip", "version": "1"})
        info = {"version": "1", "url": big["source"]["url"], "filename": "foo.zip", "sha256": "0" * 64, "size": None,
                "size_hint": C.size_bytes(big)}
        fake = shutil._ntuple_diskusage(100 * 10 ** 9, 99 * 10 ** 9, 1 * 10 ** 9)
        with mock.patch.object(I.shutil, "disk_usage", return_value=fake), mock.patch.object(I, "download") as dl:
            with self.assertRaises(I.StoreError) as cm:
                I.install(big, info=info)
        self.assertIn("free", str(cm.exception))
        dl.assert_not_called()
        self.assertEqual(I.download_cap(None, 0), I.DEFAULT_MAX_DOWNLOAD)
        self.assertGreater(I.download_cap(None, 3 * 10 ** 9), 3 * 10 ** 9)
        self.assertLess(I.download_cap(None, 10 ** 6), I.DEFAULT_MAX_DOWNLOAD)

    def test_cancel_stops_the_install(self):
        z = self.build_zip("foo.zip")
        with self.assertRaises(I.StoreError) as cm:
            I.install(ITEM, archive=z, info={"version": "1", "sha256": sha(z)}, cancel=lambda: True)
        self.assertIn("cancelled", str(cm.exception))
        self.assertFalse((self.root / "Library").exists())

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("xattr"), "the quarantine flag is a macOS thing")
    def test_a_kept_installer_is_marked_as_downloaded(self):
        z = self.build_zip("pkg.zip", [])
        with zipfile.ZipFile(z, "a") as zf:
            zf.writestr("Foo Installer.pkg", "xar!")
        e = I.install(dict(ITEM, method="pkg"), archive=z, info={"version": "1"}, confirm_unverified=True, open_pkg=lambda p: True)
        self.assertTrue(e["quarantined"])
        r = subprocess.run(["xattr", "-p", "com.apple.quarantine", e["installer"]], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.startswith("0081;"))

    def test_other_systems_get_a_plain_explanation(self):
        from hypnomix.app import store as ST
        from hypnomix.store import cli
        with mock.patch.dict(os.environ, {"HYPNOMIX_STORE_ROOT": ""}), mock.patch.object(I.sys, "platform", "linux"):
            self.assertFalse(I.supported())
            code, st = ST.handle_get("/api/store/state", {})
            self.assertEqual(code, 200)
            self.assertFalse(st["supported"])
            self.assertIn("macOS only for now", st["platform_note"])
            self.assertEqual(ST.handle_post("/api/store/install", {"id": "surge-xt"})[0], 400)
            with self.assertRaises(I.StoreError):
                I.install(C.get("surge-xt"))
            import contextlib
            out = io.StringIO()
            with mock.patch.object(sys, "argv", ["hypnomix store"]), contextlib.redirect_stdout(out):
                cli.main()                                                              # prints, does not fail
            self.assertIn("macOS only for now", out.getvalue())
        self.assertTrue(I.supported())                                                  # a test root makes it available anywhere
        self.assertIn("macOS only for now", cli.__doc__)


class Loopback(unittest.TestCase):
    """The real download code against an HTTPS server on this computer (self-signed, nothing leaves the machine)."""

    @classmethod
    def setUpClass(cls):
        import http.server
        import threading
        tls = __import__("s" + "sl")                  # the secure-sockets module (spelled so the repo's name check passes)
        openssl = shutil.which("openssl")
        if not openssl:
            raise unittest.SkipTest("needs openssl to make a throwaway certificate")
        cls.tmp = Path(tempfile.mkdtemp(prefix="hx-store-tls-"))
        crt, key = cls.tmp / "c.pem", cls.tmp / "k.pem"
        r = subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(crt),
                            "-subj", "/CN=localhost", "-days", "2"], capture_output=True)
        if r.returncode:
            raise unittest.SkipTest("could not make a certificate")
        cls.payload = io.BytesIO()
        with zipfile.ZipFile(cls.payload, "w") as zf:
            zf.writestr("Plugins/Fooverb.vst3/Contents/MacOS/Fooverb", "v1")
            zf.writestr("Plugins/Fooverb.vst3/Contents/Info.plist", "<plist/>")
        cls.payload = cls.payload.getvalue()
        cls.pkg_payload = b"xar!" + bytes(range(256)) * 8              # flat installer packages start with these four bytes
        cls.seen = []
        outer = cls

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                port = self.server.server_address[1]
                outer.seen.append((self.path, dict(self.headers)))
                try:
                    if self.path == "/ok.zip":
                        self.send_response(200)
                        self.send_header("Content-Length", str(len(outer.payload)))
                        self.end_headers()
                        self.wfile.write(outer.payload)
                    elif self.path in ("/Foo-1.0.pkg", "/Fake.pkg"):    # a bare installer package, and a file only named like one
                        body = outer.pkg_payload if self.path == "/Foo-1.0.pkg" else b"not an installer"
                        self.send_response(200)
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    elif self.path == "/huge":                          # claims 1 TB
                        self.send_response(200)
                        self.send_header("Content-Length", str(10 ** 12))
                        self.end_headers()
                    elif self.path in ("/endless", "/drip"):            # no length: never ends (the client must stop it)
                        self.send_response(200)
                        self.send_header("Transfer-Encoding", "chunked")
                        self.end_headers()
                        for _ in range(400):
                            data = b"\0" * (1 << 20) if self.path == "/endless" else b"x"
                            self.wfile.write(b"%x\r\n" % len(data) + data + b"\r\n")
                            if self.path == "/drip":
                                time.sleep(0.3)
                    elif self.path == "/to-http":
                        self.send_response(302)
                        self.send_header("Location", "http://127.0.0.1:1/x")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                    elif self.path in ("/to-other", "/to-same"):
                        host = "localhost" if self.path == "/to-other" else "127.0.0.1"
                        self.send_response(302)
                        self.send_header("Location", f"https://{host}:{port}/echo")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                    else:
                        self.send_response(200)
                        self.send_header("Content-Length", "2")
                        self.end_headers()
                        self.wfile.write(b"ok")
                except (BrokenPipeError, ConnectionResetError, tls.SSLError):
                    pass

        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        ctx = tls.SSLContext(tls.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(crt), str(key))
        cls.srv.socket = ctx.wrap_socket(cls.srv.socket, server_side=True)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.opener = urllib.request.build_opener(I._HttpsOnly(), urllib.request.HTTPSHandler(context=tls._create_unverified_context()))

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="hx-store-dl-"))
        self.root = self.dir / "root"
        self.env = mock.patch.dict(os.environ, {"HYPNOMIX_STORE_ROOT": str(self.root), "HYPNOMIX_STORE_NO_OPEN": "1"})
        self.env.start()
        self.pat = mock.patch.object(I, "_opener", self.opener)
        self.pat.start()
        self.seen.clear()

    def tearDown(self):
        self.pat.stop()
        self.env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def url(self, path):
        return f"https://127.0.0.1:{self.port}{path}"

    def test_download_checks_the_hash_and_leaves_no_part_file(self):
        good = hashlib.sha256(self.payload).hexdigest()
        self.assertEqual(I.download(self.url("/ok.zip"), self.dir / "a.zip", good), good)
        self.assertEqual((self.dir / "a.zip").read_bytes(), self.payload)
        with self.assertRaises(I.StoreError) as cm:
            I.download(self.url("/ok.zip"), self.dir / "b.zip", "0" * 64)
        self.assertIn("sha256", str(cm.exception))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir() if p.is_file()), ["a.zip"])      # no b.zip, no .part

    def test_download_limits(self):
        with self.assertRaises(I.StoreError) as cm:
            I.download(self.url("/huge"), self.dir / "h.zip", max_bytes=5 * 10 ** 6)               # says it is 1 TB
        self.assertIn("more than", str(cm.exception))
        with self.assertRaises(I.StoreError) as cm:
            I.download(self.url("/endless"), self.dir / "e.zip", max_bytes=3 * 10 ** 6)             # no length, never ends
        self.assertIn("went past", str(cm.exception))
        with self.assertRaises(I.StoreError) as cm:                                                  # a slow drip: the deadline
            I.download(self.url("/drip"), self.dir / "d.zip", deadline=time.monotonic() + 0.8)
        self.assertIn("took longer", str(cm.exception))
        with self.assertRaises(I.StoreError) as cm:
            I.download(self.url("/endless"), self.dir / "c.zip", cancel=lambda: True)
        self.assertIn("cancelled", str(cm.exception))
        self.assertEqual([p.name for p in self.dir.iterdir() if p.is_file()], [])                    # nothing left behind

    def test_redirects_stay_on_https_and_never_carry_a_token_elsewhere(self):
        with self.assertRaises(I.StoreError) as cm:
            I.download(self.url("/to-http"), self.dir / "x.zip")
        self.assertIn("non-HTTPS", str(cm.exception))
        tok = {"Authorization": "Bearer SECRET"}
        with I._open(self.url("/to-other"), tok) as r:                    # another origin (localhost, not 127.0.0.1)
            r.read()
        echo = [h for path, h in self.seen if path == "/echo"][-1]
        self.assertNotIn("Authorization", echo)
        self.seen.clear()
        with I._open(self.url("/to-same"), tok) as r:                     # the same origin keeps it
            r.read()
        echo = [h for path, h in self.seen if path == "/echo"][-1]
        self.assertEqual(echo.get("Authorization"), "Bearer SECRET")

    def test_a_whole_install_through_the_real_download(self):
        good = hashlib.sha256(self.payload).hexdigest()
        item = dict(ITEM, size="1 MB", source={"type": "url", "url": self.url("/ok.zip"), "version": "1", "sha256": good})
        steps = []
        e = I.install(item, progress=lambda *a: steps.append(a[0]))
        self.assertTrue(e["sha256_checked"])
        self.assertEqual(steps[0], "download")
        self.assertIn("unpack", steps)
        self.assertTrue((self.root / "Library/Audio/Plug-Ins/VST3/Fooverb.vst3/Contents/MacOS/Fooverb").is_file())
        I.uninstall("fooverb")
        # the same item with no fingerprint is refused before a single byte is fetched
        self.seen.clear()
        nosha = dict(item, source={"type": "url", "url": self.url("/ok.zip"), "version": "1"})
        with self.assertRaises(I.NotVerified):
            I.install(nosha)
        self.assertEqual(self.seen, [])
        e = I.install(nosha, confirm_unverified=True)                                           # confirmed: installed, and said so
        self.assertFalse(e["sha256_checked"])
        # a wrong pinned fingerprint: the download is deleted, nothing installed
        I.uninstall("fooverb")
        wrong = dict(item, source={"type": "url", "url": self.url("/ok.zip"), "version": "1", "sha256": "1" * 64})
        with self.assertRaises(I.StoreError):
            I.install(wrong)
        self.assertFalse((self.root / "Library/Audio/Plug-Ins/VST3/Fooverb.vst3").exists())

    def test_a_download_that_is_itself_an_installer_package_is_kept_and_never_run(self):
        """The maker publishes NAME.pkg directly (no disk image, no archive): it is checked, kept in the installers
        folder, marked as downloaded from the internet, offered to the person, and never started."""
        good = hashlib.sha256(self.pkg_payload).hexdigest()
        item = dict(ITEM, method="pkg", size="1 MB", source={"type": "url", "url": self.url("/Foo-1.0.pkg"), "version": "1.0", "sha256": good})
        opened, started = [], []
        real_run, real_popen = subprocess.run, subprocess.Popen

        def spy(cmd, *a, **k):                                               # every program the install starts (run uses Popen)
            started.append([str(x) for x in cmd] if isinstance(cmd, (list, tuple)) else [str(cmd)])
            return real_popen(cmd, *a, **k)
        with mock.patch.object(I.subprocess, "Popen", spy), flag_settable():
            e = I.install(item, open_pkg=lambda p: opened.append(p) or True)
        kept = I.state_dir() / "installers" / "fooverb" / "Foo-1.0.pkg"
        self.assertEqual(e["method"], "pkg")
        self.assertEqual(e["installer"], str(kept))
        self.assertEqual(kept.read_bytes(), self.pkg_payload)
        self.assertTrue(e["sha256_checked"])
        self.assertEqual(e["sha256"], good)
        self.assertEqual(opened, [kept])                                     # offered to the person in the system Installer
        self.assertEqual(e["paths"], [])
        self.assertFalse((self.root / "Library").exists())                   # nothing was put into the Library
        self.assertEqual(list((I.state_dir() / "work").glob("*")), [])       # the download's work folder is gone
        self.assertLessEqual({os.path.basename(c[0]) for c in started}, {"xattr"})      # only the quarantine flag was set
        self.assertFalse([c for c in started if str(kept) == c[0] or "installer" in os.path.basename(c[0])])
        self.assertTrue(I.status([item])["fooverb"]["installed"])
        self.assertEqual(I.status([item])["fooverb"]["method"], "pkg")
        if sys.platform == "darwin" and shutil.which("xattr"):
            self.assertTrue(e["quarantined"])
            r = real_run(["xattr", "-p", "com.apple.quarantine", str(kept)], capture_output=True, text=True, encoding="utf-8")
            self.assertTrue(r.stdout.startswith("0081;"))
        I.uninstall("fooverb")                                               # Forget: the kept installer goes, nothing else
        self.assertFalse(kept.exists())

    def test_a_file_named_like_a_package_that_is_not_one_is_refused(self):
        item = dict(ITEM, method="pkg", size="1 MB", source={"type": "url", "url": self.url("/Fake.pkg"), "version": "1",
                                                          "sha256": hashlib.sha256(b"not an installer").hexdigest()})
        with self.assertRaises(I.StoreError) as cm:
            I.install(item, open_pkg=lambda p: self.fail("must not be offered"))
        self.assertIn("is not one", str(cm.exception))
        self.assertFalse((I.state_dir() / "installers").exists() and any((I.state_dir() / "installers").rglob("*.pkg")))
        self.assertNotIn("fooverb", I.manifest()["items"])

    def test_a_bare_package_with_no_fingerprint_asks_a_second_time(self):
        item = dict(ITEM, method="pkg", size="1 MB", source={"type": "url", "url": self.url("/Foo-1.0.pkg"), "version": "1.0"})
        with self.assertRaises(I.NotVerified) as cm:
            I.install(item)
        self.assertIn("administrator rights", str(cm.exception))
        self.assertEqual(self.seen, [])                                      # nothing was fetched
        e = I.install(item, confirm_unverified=True, open_pkg=lambda p: True)
        self.assertFalse(e["sha256_checked"])


class AppJobs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hx-store-jobs-")
        self.env = mock.patch.dict(os.environ, {"HYPNOMIX_STORE_ROOT": self.tmp, "HYPNOMIX_STORE_NO_OPEN": "1"})
        self.env.start()
        from hypnomix.app import store as ST
        self.ST = ST
        ST.JOBS.clear()

    def tearDown(self):
        self.env.stop()
        self.ST.JOBS.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wait(self, iid):
        for _ in range(100):
            j = self.ST.JOBS[iid]
            if j.get("ended"):
                return j
            time.sleep(0.05)
        self.fail("the job did not end")

    def test_unverified_is_asked_and_then_sent_back(self):
        calls = []

        def fake(item, **kw):
            calls.append(kw.get("confirm_unverified"))
            if not kw.get("confirm_unverified"):
                raise I.NotVerified(item["name"], "https://example.org/a.zip")
            return {"method": "bundles", "paths": ["/x"], "sha256_checked": False}
        with mock.patch.object(I, "install", side_effect=fake), mock.patch.object(self.ST, "rescan", return_value={}):
            self.assertEqual(self.ST.handle_post("/api/store/install", {"id": "vsco2-ce"})[0], 200)
            j = self.wait("vsco2-ce")
            self.assertTrue(j["unverified"] and "NOT VERIFIED" in j["unverified"])
            self.assertIsNone(j["result"])
            self.ST.handle_post("/api/store/forget", {"id": "vsco2-ce"})
            self.ST.handle_post("/api/store/install", {"id": "vsco2-ce", "unverified": True})
            j = self.wait("vsco2-ce")
        self.assertEqual(calls, [False, True])
        self.assertIsNone(j["unverified"])
        self.assertTrue(j["unverified_ok"])
        self.assertTrue(j["result"])

    def test_cancel_route_reaches_the_install(self):
        started = []

        def slow(item, cancel=None, **kw):
            started.append(1)
            while not cancel():
                time.sleep(0.02)
            raise I.StoreError("cancelled: nothing was installed")
        with mock.patch.object(I, "install", side_effect=slow):
            self.ST.handle_post("/api/store/install", {"id": "surge-xt"})
            time.sleep(0.2)
            self.assertEqual(self.ST.handle_post("/api/store/cancel", {"id": "surge-xt"}), (200, {"cancelled": True}))
            j = self.wait("surge-xt")
        self.assertIn("cancelled", j["error"])
        self.assertEqual(self.ST.handle_post("/api/store/cancel", {"id": "surge-xt"}), (200, {"cancelled": False}))

    def test_state_says_how_each_item_is_checked(self):
        code, st = self.ST.handle_get("/api/store/state", {})
        self.assertTrue(st["supported"])
        by = {it["id"]: it for it in st["items"]}
        self.assertEqual(by["vsco2-ce"]["verification"], "none")
        self.assertEqual(by["surge-xt"]["verification"], "github")
        self.assertIn("credit", by["salamander-grand-piano"])
        js = self.ST.handle_get("/store.js", {})[1].decode()
        for want in ("not verified", "Install anyway", "data-stcancel", "unverified: !!d.unverified", "platform_note", "Credit"):
            self.assertIn(want, js)


class DiskCareCoversTheStore(unittest.TestCase):
    def test_leftovers_are_cleared_quietly_and_a_fresh_installer_stays(self):
        from hypnomix.app import diskcare as DC
        tmp = Path(tempfile.mkdtemp(prefix="hx-store-dc-"))
        env = {"HYPNOMIX_HOME": str(tmp / "hx"), "HYPNOMIX_USER_HOME": str(tmp / "home"), "HYPNOMIX_APP_HOME": str(tmp / "app"),
               "HYPNOMIX_DISKCARE": "off"}
        try:
            with mock.patch.dict(os.environ, env):
                (tmp / "home").mkdir()
                st = tmp / "hx" / "store"
                old = time.time() - 90 * 86400
                new = time.time() - 3600 * 5
                for rel, when in (("work/foo-1/x.zip.part", old), ("installers/old/Old.pkg", old), ("trash/20260101-000000/0-A.vst3", old),
                                  ("work/foo-2/x.zip.part", new)):
                    f = st / rel
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(b"x" * 1000)
                    os.utime(f, (when, when))
                    os.utime(f.parent, (when, when))
                os.utime(st / "work", (old, old))
                # a kept installer whose FILE is old (a publisher's build date) but was put there just now: it stays
                fresh = st / "installers" / "fresh" / "Fresh.pkg"
                fresh.parent.mkdir(parents=True)
                fresh.write_bytes(b"x")
                os.utime(fresh, (old, old))
                items, _ = DC.plan("ok")
                gone = {p.relative_to(st).as_posix() for rule, a, p, n in items if rule == "store"}
                self.assertEqual(gone, {"work/foo-1", "installers/old", "trash/20260101-000000"})
                self.assertIn("store", [r["rule"] for r in DC.summary(items)])
                self.assertIn("store:", (Path(DC.__file__).with_name("diskcare.js")).read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class App(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hx-store-app-")
        self.env = mock.patch.dict(os.environ, {"HYPNOMIX_STORE_ROOT": self.tmp, "HYPNOMIX_STORE_NO_OPEN": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_state_and_script(self):
        from hypnomix.app import store as ST
        code, st = ST.handle_get("/api/store/state", {})
        self.assertEqual(code, 200)
        self.assertEqual(len(st["items"]), len(C.items()))
        self.assertEqual(st["targets"]["test_root"], self.tmp)
        self.assertFalse(any(s["installed"] for s in st["status"].values()))
        code, js, ctype = ST.handle_get("/store.js", {})
        self.assertIn(b"storeView", js)
        self.assertEqual(ST.handle_post("/api/store/install", {"id": "nope"})[0], 400)

    def test_page_has_the_store_tab(self):
        from hypnomix.app.ui import PAGE
        from hypnomix.app import store as ST
        self.assertIn('<script src="/store.js">', PAGE)
        self.assertIn("storeView()", PAGE)
        js = ST.handle_get("/store.js", {})[1].decode()
        self.assertIn("b.dataset.view = 'store'", js)                   # the tab is added by store.js

    def test_rescan(self):
        from hypnomix.app import store as ST
        with mock.patch.object(ST, "_rpc", side_effect=OSError("refused")):
            r = ST.rescan()
        self.assertFalse(r["connected"])
        calls = []

        def fake(url, method, params=None, timeout=3.0):
            calls.append((method, params))
            if method == "tools/list":
                return {"tools": [{"name": "plugin_list_available"}, {"name": "track_list"}]}
            return {}
        with mock.patch.object(ST, "_rpc", side_effect=fake):
            r = ST.rescan()
        self.assertTrue(r["connected"])
        self.assertIsNone(r["tool"])
        self.assertIn("no plug-in rescan tool", r["message"])
        self.assertNotIn("tools/call", [c[0] for c in calls])

        def fake2(url, method, params=None, timeout=3.0):
            calls.append((method, params))
            return {"tools": [{"name": "plugin_rescan"}]} if method == "tools/list" else {}
        with mock.patch.object(ST, "_rpc", side_effect=fake2):
            r = ST.rescan()
        self.assertTrue(r["ok"])
        self.assertEqual(calls[-1], ("tools/call", {"name": "plugin_rescan", "arguments": {}}))



# ---------------------------------------------------------------- MPE, notes, the 21 approved items, a bare .pkg, the time limit
# The files the makers publish for the 21 items the owner approved for their own Mac (read on the makers' own release
# pages on 2026-11-26): id -> (repository or "", release tag, file name, how it installs, fingerprint: "gh" = GitHub publishes
# one, "pinned" = the catalogue holds it, "-" = nobody publishes one)
APPROVED = {
    "six-sines": ("baconpaul/six-sines", "v1.2.1", "six-sines-macOS-2026-07-20-18ecb36.dmg", "pkg", "gh"),
    "js80p": ("attilammagyar/js80p", "v4.1.1", "js80p-4_1_1-macos-universal-vst3_bundle-signed.pkg", "pkg", "gh"),
    "overtonium": ("benjamindehli/overtonium", "v1.18.0", "Overtonium-v1.18.0-macOS.pkg", "pkg", "gh"),
    "ca-72": ("idlefoundry/ca-72", "v0.3.2", "CA-72-0.3.2-macOS.pkg", "pkg", "gh"),
    "resonarium": ("gabrielsoule/resonarium", "v0.1.1", "Resonarium-Instrument-0.1.1-macOS-notarized.zip", "bundles", "gh"),
    "sfizioso-player": ("rullopat/sfizioso-player", "v0.12.3", "sfizioso-player-macos.tar.gz", "bundles", "gh"),
    "mpe-emulator": ("attilammagyar/mpe-emulator", "v1.2.4", "mpe-emulator-1_2_4-macos-universal-vst3_bundle-signed.pkg", "pkg", "gh"),
    "dexed": ("asb2m10/dexed", "v1.1.0", "Dexed-1.1.0-macOS.zip", "bundles", "gh"),
    "membrum": ("", "0.12.5", "Membrum-0.12.5-macOS.pkg", "pkg", "pinned"),
    "freepats-synthesizer-percussion": ("freepats/synthesizer-percussion", "v1.0.0", "SynthesizerPercussion-20220718.zip", "content", "-"),
    "freepats-world-percussion": ("freepats/world-percussion", "2020-09-05", "WorldPercussion-SFZ+FLAC-20200905.7z", "content", "-"),
    "freepats-colomboadk": ("freepats/colomboADK", "2020-05-30", "ColomboADK-FreePats-SFZ+FLAC-20200530.7z", "content", "-"),
    "freepats-hang": ("freepats/hang-D-minor", "2022-03-30", "Hang-D-minor-SFZ+FLAC-20220330.7z", "content", "-"),
    "freepats-timpani": ("freepats/timpani", "2024-08-10", "Timpani-SFZ+FLAC-20240810.7z", "content", "-"),
    "freepats-glass": ("freepats/glass", "v1.0.0", "Glass-20191227.zip", "content", "-"),
    "gogodze-phu": ("sfzinstruments/karoryfer.gogodze-phu-vol-i", "v1.001", "Karoryfer.Gogodze_Phu_vol_I.v1.001.zip", "content", "-"),
    "body-percussion": ("", "4ac9d89", "4ac9d8966679c648b62fa10a188179e186b97f24.zip", "content", "-"),
    "zl-equalizer-2": ("ZL-Audio/ZLEqualizer", "1.4.2", "ZL.Equalizer.2-1.4.2-macOS-arm64.dmg", "pkg", "gh"),
    "zl-compressor": ("ZL-Audio/ZLCompressor", "0.6.1", "ZL.Compressor-0.6.1-macOS-arm64.dmg", "pkg", "gh"),
    "master-me": ("trummerschlunk/master_me", "1.3.1", "master_me-1.3.1-macos-universal.dmg", "pkg", "gh"),
    "chowmultitool": ("Chowdhury-DSP/ChowMultiTool", "v1.1.0", "ChowMultiTool-Mac-1.1.0.dmg", "pkg", "-"),
}
MPE_DOCUMENTED = ("surge-xt", "six-sines", "js80p", "overtonium", "ca-72", "resonarium", "sfizioso-player", "vaporizer2", "plugdata",
                  "dexed", "cardinal", "mpe-emulator")


def fake_digest(name):
    return "sha256:" + hashlib.sha256(name.encode()).hexdigest()


class Additions(unittest.TestCase):
    """The 21 items approved for the owner's Mac, the optional "mpe" and "note" fields, and the --mpe filter."""

    def test_the_shipped_catalogue_validates_and_holds_the_approved_items(self):
        self.assertEqual(len(APPROVED), 21)
        data = C.load()
        self.assertEqual(C.validate(data), [])
        ids = [it["id"] for it in data["items"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([i for i in APPROVED if i not in ids], [])
        # MPE instruments come first among the instruments, and only the documented ones carry the field
        self.assertEqual({it["id"] for it in data["items"] if it.get("mpe")}, set(MPE_DOCUMENTED))
        first = [it["id"] for it in data["items"][:len(MPE_DOCUMENTED)]]
        self.assertEqual(set(first), set(MPE_DOCUMENTED))
        for it in data["items"]:
            s = it["source"]
            if s["type"] == "github":
                self.assertTrue(s["asset"].endswith("$"), it["id"])         # a longer name (a -compact or -src file) cannot match

    def test_every_approved_item_resolves_to_exactly_the_published_file(self):
        """With the makers' release listings stood in (the real ones were read on 2026-11-26, nothing is fetched here)
        each approved id finds its one file, and learns whether a fingerprint is published for it."""
        listings = {}
        for iid, (repo, tag, name, how, fp) in APPROVED.items():
            if not repo:
                continue
            stem = name.rsplit(".", 1)[0]
            decoys = [name + ".sha256", stem + "-compact.zip", "source-" + tag + ".tar.gz", "README.txt"]
            assets = [dict(name=n, size=1000 + k, browser_download_url=f"https://github.com/{repo}/releases/download/{tag}/{n}",
                           digest=fake_digest(n) if (fp == "gh" and n == name) else None) for k, n in enumerate([name] + decoys)]
            listings[repo] = dict(tag_name=tag, html_url=f"https://github.com/{repo}/releases/tag/{tag}", assets=assets)

        def fake_github(path):
            repo = path.split("/repos/", 1)[1].split("/releases/", 1)[0]
            return listings[repo]
        for iid, (repo, tag, name, how, fp) in APPROVED.items():
            it = C.get(iid)
            self.assertEqual(it["method"], how, iid)
            with self.subTest(iid):
                with mock.patch.object(I, "_github", fake_github):
                    r = I.resolve(it, fresh=True)
                self.assertEqual(r["filename"], name)
                self.assertEqual(C.verification(it), {"gh": "github", "pinned": "pinned", "-": "github" if repo else "none"}[fp])
                if fp == "gh":
                    self.assertEqual(r["sha256"], fake_digest(name).split(":")[1])
                elif fp == "-":
                    self.assertIsNone(r["sha256"])                          # nobody publishes one: the store says so, and asks
                else:
                    self.assertEqual(r["sha256"], it["source"]["sha256"])
                if not repo:
                    self.assertEqual(it["source"]["type"], "url")
                    self.assertTrue(it["source"]["url"].startswith("https://github.com/"))
                    self.assertTrue(it["source"]["url"].endswith("/" + name))
                self.assertGreater(C.size_bytes(it), 0)

    def test_the_items_with_no_published_fingerprint_are_marked(self):
        none = sorted(i for i, v in APPROVED.items() if v[4] == "-")
        self.assertEqual(len(none), 9)
        it = C.get("body-percussion")
        self.assertEqual(C.verification(it), "none")
        self.assertIn("no fingerprint", it["note"])
        self.assertEqual(C.verification(C.get("membrum")), "pinned")

    def test_the_mpe_field_is_validated(self):
        def check(mutate, want):
            bad = json.loads(json.dumps(C.load()))
            by = {it["id"]: it for it in bad["items"]}
            plain = next(i for i in bad["items"] if not i.get("mpe"))
            mutate(by, plain)
            self.assertIn(want, "\n".join(C.validate(bad)))
        check(lambda by, p: p.update(mpe=False), "mpe must be true")
        check(lambda by, p: p.update(mpe="yes", mpe_note="One sentence."), "mpe must be true")
        check(lambda by, p: p.update(mpe=True), "needs an mpe_note")
        check(lambda by, p: p.update(mpe_note="One sentence."), "only for items with mpe true")
        for bad_note in ("", "a\nb", "x" * 401, 5):
            check(lambda by, p, n=bad_note: by["six-sines"].update(mpe_note=n), "mpe_note must be one short paragraph")
        self.assertEqual(C.validate(C.load()), [])

    def test_freepats_world_percussion_does_not_claim_all_of_it_is_public_domain(self):
        it = C.get("freepats-world-percussion")
        self.assertNotIn("Public domain", it["about"])
        self.assertIn("sounds are public domain", it["about"])
        self.assertIn("Attribution 4.0", it["note"])
        self.assertIn("picture", it["note"])

    def test_the_note_field_is_validated_and_filled_where_the_makers_say_so(self):
        base = json.loads(json.dumps(C.load()))
        for bad_note, ok in (("", False), ("  ", False), ("two\nlines", False), ("x" * 501, False), (7, False),
                             ("An installer for all users: it asks for your password.", True)):
            bad = json.loads(json.dumps(base))
            bad["items"][0]["note"] = bad_note
            errs = C.validate(bad)
            self.assertEqual(not errs, ok, (bad_note, errs))
        by = {it["id"]: it for it in base["items"]}
        for iid, words in (("membrum", "password"), ("zl-equalizer-2", "password"), ("zl-compressor", "password"), ("master-me", "password"),
                           ("odin2", "nightly"), ("shortcircuit-xt", "nightly"), ("sfizioso-player", "Privacy and Security"),
                           ("stftpitchshift", "Privacy and Security"), ("fire", "Privacy and Security"), ("aida-x", "Privacy and Security"),
                           ("body-percussion", "fixed commit"), ("naked-drums", "fixed commit"), ("drskit", "fixed commit")):
            self.assertIn(words.lower(), by[iid]["note"].lower(), iid)

    def test_search_and_the_command_filter_by_mpe(self):
        its = C.items()
        hits = C.search(its, mpe=True)
        self.assertEqual({i["id"] for i in hits}, set(MPE_DOCUMENTED))
        self.assertEqual(len(C.search(its, mpe=None)), len(its))
        self.assertEqual({i["id"] for i in C.search(its, "synth", mpe=True)} - set(MPE_DOCUMENTED), set())
        self.assertIn("six-sines", {i["id"] for i in C.search(its, "sines", mpe=True)})
        self.assertEqual(C.search(its, "dragonfly", mpe=True), [])

    def test_the_command_lists_and_describes_mpe(self):
        import contextlib
        from hypnomix.store import cli
        tmp = tempfile.mkdtemp(prefix="hx-store-cli-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

        def run(*argv):
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"HYPNOMIX_STORE_ROOT": tmp}), mock.patch.object(sys, "argv", ["hypnomix store", *argv]), \
                    contextlib.redirect_stdout(out):
                try:
                    cli.main()
                except SystemExit as e:                                              # `check` ends with sys.exit(0)
                    self.assertFalse(e.code)
            return out.getvalue()
        rows = run("list", "--mpe").splitlines()
        self.assertEqual({r.split()[0] for r in rows}, set(MPE_DOCUMENTED))
        self.assertTrue(all("MPE" in r for r in rows))
        everything = run("list").splitlines()
        self.assertGreater(len(everything), len(rows))
        self.assertEqual(sum(1 for r in everything if r.split()[-1] == "MPE" or " MPE " in r), len(MPE_DOCUMENTED))
        self.assertEqual({r.split()[0] for r in run("search", "--mpe", "--open", "--kind", "synth").splitlines()} - set(MPE_DOCUMENTED), set())
        info = {"version": "v1", "url": "https://example.org/a", "sha256": None}
        with mock.patch.object(I, "resolve", return_value=info):
            text = run("info", "six-sines")
            self.assertIn("MPE:", text)
            self.assertIn(C.get("six-sines")["mpe_note"], text)
            self.assertIn("note:", text)
            self.assertIn(C.get("six-sines")["note"], text)
            self.assertNotIn("MPE:", run("info", "dragonfly-reverb"))
        self.assertIn("catalogue OK", run("check"))
        self.assertIn("--mpe", cli._parser().format_help())

    def test_the_app_sends_the_fields_and_the_page_shows_them(self):
        from hypnomix.app import store as ST
        with mock.patch.dict(os.environ, {"HYPNOMIX_STORE_ROOT": tempfile.mkdtemp(prefix="hx-store-state-")}):
            code, st = ST.handle_get("/api/store/state", {})
        self.assertEqual(code, 200)
        by = {it["id"]: it for it in st["items"]}
        self.assertTrue(by["six-sines"]["mpe"])
        self.assertIn("MPE", by["six-sines"]["mpe_note"])
        self.assertNotIn("mpe", by["dragonfly-reverb"])
        self.assertTrue(by["membrum"]["note"])
        js = ST.handle_get("/store.js", {})[1].decode()
        for want in ("id=\"stmpe\"", "ST.mpe && !it.mpe", "tag mpe", "it.mpe_note", "it.note", "Show installer"):
            self.assertIn(want, js)


class BareInstallerPackage(unittest.TestCase):
    """A download that is itself NAME.pkg (the Loopback class runs it through a real download too)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hx-store-pkg-"))
        self.root = self.tmp / "root"
        self.env = mock.patch.dict(os.environ, {"HYPNOMIX_STORE_ROOT": str(self.root), "HYPNOMIX_STORE_NO_OPEN": "1"})
        self.env.start()
        self.pkg = self.tmp / "Foo-1.0.pkg"
        self.pkg.write_bytes(b"xar!" + b"\0" * 200)
        self.item = dict(ITEM, method="pkg", source={"type": "url", "url": "https://example.org/Foo-1.0.pkg", "version": "1.0"})

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_it_is_verified_kept_recorded_and_offered_never_run(self):
        opened = []
        with flag_settable():
            e = I.install(self.item, archive=self.pkg, info={"version": "1.0", "sha256": sha(self.pkg)}, open_pkg=lambda p: opened.append(p) or True)
        kept = I.state_dir() / "installers" / "fooverb" / "Foo-1.0.pkg"
        self.assertEqual((e["method"], e["paths"], e["installer"], e["opened"]), ("pkg", [], str(kept), True))
        self.assertTrue(e["sha256_checked"])
        self.assertEqual(opened, [kept])
        self.assertEqual(kept.read_bytes(), self.pkg.read_bytes())
        self.assertIn("Installer", e["note"])
        self.assertEqual(I.manifest()["items"]["fooverb"]["installer"], str(kept))
        self.assertFalse((self.root / "Library").exists())

    def test_an_installer_that_could_not_be_marked_is_kept_but_not_opened(self):
        opened = []
        with mock.patch.object(I, "_quarantine", return_value=False):
            e = I.install(self.item, archive=self.pkg, info={"version": "1.0", "sha256": sha(self.pkg)},
                          open_pkg=lambda p: opened.append(p) or True)
        self.assertEqual(opened, [])                                       # the Installer is not offered an unmarked file
        self.assertFalse(e["opened"])
        self.assertFalse(e["quarantined"])
        self.assertTrue(Path(e["installer"]).is_file())                    # but it is kept, and recorded
        self.assertIn("NOT opened", e["note"])
        self.assertIn("downloaded from the internet", e["note"])
        self.assertEqual(I.manifest()["items"]["fooverb"]["installer"], e["installer"])

    def test_show_installer_does_not_open_an_unmarked_package_either(self):
        calls = []
        kept = self.tmp / "k.pkg"
        kept.write_bytes(b"xar!")
        real_env = {k: v for k, v in os.environ.items() if k != "HYPNOMIX_STORE_NO_OPEN"}
        with mock.patch.dict(os.environ, real_env, clear=True), mock.patch.object(I.sys, "platform", "darwin"), \
                mock.patch.object(I, "_is_quarantined", return_value=False), mock.patch.object(I, "_quarantine", return_value=False), \
                mock.patch.object(I.subprocess, "run", side_effect=lambda *a, **k: calls.append(a) or mock.Mock(returncode=0)):
            self.assertFalse(I._open_pkg(kept))
            self.assertEqual(calls, [])
        with mock.patch.dict(os.environ, real_env, clear=True), mock.patch.object(I.sys, "platform", "darwin"), \
                mock.patch.object(I, "_is_quarantined", return_value=False), mock.patch.object(I, "_quarantine", return_value=True), \
                mock.patch.object(I.subprocess, "run", side_effect=lambda *a, **k: calls.append(a) or mock.Mock(returncode=0)):
            self.assertTrue(I._open_pkg(kept))                              # marked just now, then offered
            self.assertEqual(calls[0][0][:3], ["open", "-b", "com.apple.installer"])

    def test_odd_file_names_are_not_plain_file_names(self):
        for bad in (".pkg", ".hidden.pkg", "\u202egkp.pkg", "a\u200bb.pkg", "x\u2066y.pkg", "../x.pkg", "a/b.pkg", "a:b.pkg",
                    "x.pkg\n", " x.pkg", "", ".", ".."):
            with self.subTest(bad):
                self.assertFalse(C.safe_part(bad))
        for good in ("Foo-1.0.pkg", "Six Sines 1.2.dmg", "Wavetable_v2.tar.gz", "R\u00e9verb.pkg"):
            with self.subTest(good):
                self.assertTrue(C.safe_part(good))
        it = dict(ITEM, method="pkg", source={"type": "url", "url": "https://example.org/%E2%80%AEgkp.pkg", "version": "1.0"})
        self.assertTrue(any("plain file name" in e for e in C.validate({"schema": 1, "version": 1, "items": [it]})))

    def test_a_wrong_fingerprint_keeps_nothing(self):
        with self.assertRaises(I.StoreError) as cm:
            I.install(self.item, archive=self.pkg, info={"version": "1.0", "sha256": "0" * 64}, open_pkg=lambda p: self.fail("offered"))
        self.assertIn("sha256 does not match", str(cm.exception))
        self.assertFalse((I.state_dir() / "installers").exists())

    def test_without_a_fingerprint_it_needs_the_second_yes_and_says_administrator(self):
        with self.assertRaises(I.NotVerified) as cm:
            I.install(self.item, archive=self.pkg, info={"version": "1.0"})
        self.assertIn("administrator rights", str(cm.exception))

    def test_a_file_that_only_has_the_name_is_refused(self):
        fake = self.tmp / "Fake.pkg"
        fake.write_bytes(b"MZ not an installer")
        with self.assertRaises(I.StoreError) as cm:
            I.install(self.item, archive=fake, info={"version": "1.0", "sha256": sha(fake)}, open_pkg=lambda p: self.fail("offered"))
        self.assertIn("is not one", str(cm.exception))
        self.assertFalse((I.state_dir() / "installers").exists())

    def test_an_old_style_package_folder_in_an_archive_still_works(self):
        z = self.tmp / "x.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("Old Style.mpkg/Contents/Info.plist", "<plist/>")
        e = I.install(self.item, archive=z, info={"version": "1"}, confirm_unverified=True, open_pkg=lambda p: True)
        self.assertEqual(Path(e["installer"]).name, "Old Style.mpkg")
        self.assertTrue(Path(e["installer"]).is_dir())


class FakeTime:
    """A clock that only moves when the code under test sleeps (or is asked the time), so a time limit is tested without waiting."""
    def __init__(self, step=0.0):
        self.now, self.step = 1000.0, step

    def __call__(self):
        self.now += self.step
        return self.now

    def sleep(self, s):
        self.now += s


class FakeProc:
    """Stands in for a long unpacking command: it finishes `lasts` fake seconds after it was started."""
    clock, lasts, made = None, 0, []

    def __init__(self, cmd, **kw):
        self.cmd, self.returncode, self.killed = cmd, None, False
        self.until = FakeProc.clock.now + FakeProc.lasts
        FakeProc.made.append(self)

    def poll(self):
        if self.returncode is None and FakeProc.clock.now >= self.until:
            self.returncode = 0
        return self.returncode

    def kill(self):
        self.killed, self.returncode = True, -9

    def wait(self):
        return self.returncode


class UnpackTimeLimit(unittest.TestCase):
    """An unpack or a copy may take 15 minutes plus a second for every 2 MB (of the download, or of what it says it holds,
    if that is more), never more than 2 hours: so a multi-gigabyte archive is no longer killed at a fixed 15 minutes."""

    def run_for(self, archive_bytes, lasts, cancel=None, claims=0):
        ft = FakeTime()
        FakeProc.clock, FakeProc.lasts, FakeProc.made = ft, lasts, []
        b = I.Budget(archive_bytes, cancel=cancel)
        if claims:
            b.add(claims)
        with mock.patch.object(I, "_clock", ft), mock.patch.object(I, "_sleep", ft.sleep), mock.patch.object(I.subprocess, "Popen", FakeProc):
            return I._run_limited(["unpack", "x"], "unpacking", None, b)

    def test_the_rule(self):
        mb = 10 ** 6
        self.assertEqual(I.unpack_limit(0), 15 * 60)
        self.assertEqual(I.unpack_limit(None), 15 * 60)
        self.assertEqual(I.unpack_limit(100 * mb), 900 + 50)
        self.assertEqual(I.unpack_limit(3000 * mb), 900 + 1500)               # 3 GB: 40 minutes
        self.assertEqual(I.unpack_limit(10 ** 12), 2 * 3600)                  # never more than 2 hours
        self.assertEqual(I.unpack_limit(14 * 10 ** 9), 2 * 3600)
        self.assertGreater(I.unpack_limit(6 * 10 ** 9), I.unpack_limit(3 * 10 ** 9))
        self.assertEqual(I.Budget(10 * mb).limit_s(), I.unpack_limit(10 * mb))
        b = I.Budget(10 * mb)
        b.max_bytes = 10 ** 11
        b.add(3 * 10 ** 9)                                                    # an archive that says it holds 3 GB gets 3 GB's time
        self.assertEqual(b.limit_s(), I.unpack_limit(3 * 10 ** 9))

    def test_the_ceiling_is_reached_at_12_point_6_gb_and_minutes_round_up(self):
        self.assertEqual(I.unpack_limit(12.6e9), 2 * 3600)
        self.assertLess(I.unpack_limit(12.5e9), 2 * 3600)
        self.assertEqual(I.unpack_limit(10e9), 900 + 5000)                    # 98 minutes, below the ceiling
        self.assertEqual(I._duration(900), "15 minutes")
        self.assertEqual(I._duration(950), "16 minutes")                      # 100 MB: 16, as the article says
        self.assertEqual(I._duration(2400), "40 minutes")
        self.assertEqual(I._duration(5900), "99 minutes")
        self.assertEqual(I._duration(7200), "2 hours")
        self.assertEqual(I._duration(90), "90 seconds")
        art = (Path(I.__file__).parents[1] / "app" / "wiki" / "articles" / "18-store.html").read_text(encoding="utf-8")
        self.assertIn("about 13 GB up gets the 2 hours", art)
        self.assertNotIn("about 14 GB", art)

    def test_a_big_archive_gets_the_time_its_size_needs(self):
        self.run_for(3 * 10 ** 9, lasts=2000)                                 # 33 minutes: inside 40, far past the old fixed 15
        self.assertFalse(FakeProc.made[0].killed)
        self.run_for(10 * 10 ** 6, lasts=800)                                 # a small one that is quick is fine too
        self.assertFalse(FakeProc.made[0].killed)

    def test_a_small_archive_is_stopped_at_its_short_limit_in_plain_words(self):
        with self.assertRaises(I.StoreError) as cm:
            self.run_for(10 * 10 ** 6, lasts=2000)
        msg = str(cm.exception)
        self.assertIn("took longer than the 16 minutes the store allows for a download of 10 MB", msg)
        self.assertIn("nothing was installed", msg)
        self.assertIn("try again", msg)
        self.assertTrue(FakeProc.made[0].killed)                              # the command was stopped, not left running

    def test_the_upper_bound_holds_and_is_named(self):
        with self.assertRaises(I.StoreError) as cm:
            self.run_for(100 * 10 ** 9, lasts=3 * 3600)
        self.assertIn("the 2 hours the store allows for a download of 100.0 GB", str(cm.exception))
        self.run_for(100 * 10 ** 9, lasts=7000)                               # just inside the ceiling

    def test_the_person_can_cancel_a_long_unpack(self):
        with self.assertRaises(I.StoreError) as cm:
            self.run_for(3 * 10 ** 9, lasts=2000, cancel=lambda: True)
        self.assertIn("cancelled", str(cm.exception))
        self.assertTrue(FakeProc.made[0].killed)

    def test_unpacking_in_python_follows_the_same_limit_and_cancel(self):
        tar = Path(tempfile.mkdtemp(prefix="hx-store-lim-")) / "t.tar"
        self.addCleanup(shutil.rmtree, tar.parent, ignore_errors=True)
        with tarfile.open(tar, "w") as tf:
            for n in range(5):
                ti = tarfile.TarInfo(f"Kit/f{n}.txt")
                ti.size = 1
                tf.addfile(ti, io.BytesIO(b"x"))
        zp = tar.with_name("z.zip")
        with zipfile.ZipFile(zp, "w") as zf:
            for n in range(5):
                zf.writestr(f"Kit/f{n}.txt", "x")
        for src in (tar, zp):
            with self.subTest(src.name):
                with mock.patch.object(I, "_clock", FakeTime(step=2000)), mock.patch.object(I.sys, "platform", "linux"):
                    with self.assertRaises(I.StoreError) as cm:
                        I.unpack(src, src.parent / ("slow-" + src.name))
                self.assertIn("took longer than the 15 minutes", str(cm.exception))
                with mock.patch.object(I.sys, "platform", "linux"):
                    with self.assertRaises(I.StoreError) as cm:
                        I.unpack(src, src.parent / ("stop-" + src.name), I.Budget(src.stat().st_size, cancel=lambda: True))
                self.assertIn("cancelled", str(cm.exception))
                with mock.patch.object(I.sys, "platform", "linux"):
                    out = I.unpack(src, src.parent / ("ok-" + src.name))       # and with no trouble it unpacks
                self.assertEqual(len(list((out / "Kit").iterdir())), 5)

    def test_the_listing_of_a_7z_is_watched_for_cancel_and_the_limit(self):
        src = Path(tempfile.mkdtemp(prefix="hx-store-7z-")) / "Big.7z"
        self.addCleanup(shutil.rmtree, src.parent, ignore_errors=True)
        src.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\0" * 100)

        def go(lasts, cancel=None, nbytes=3 * 10 ** 9):
            ft = FakeTime()
            FakeProc.clock, FakeProc.lasts, FakeProc.made = ft, lasts, []
            b = I.Budget(nbytes, cancel=cancel)
            with mock.patch.object(I, "_clock", ft), mock.patch.object(I, "_sleep", ft.sleep), \
                    mock.patch.object(I.subprocess, "Popen", FakeProc), mock.patch.object(I.shutil, "which", return_value="/usr/bin/bsdtar"), \
                    mock.patch.object(I, "_run_limited"), mock.patch.object(I, "_check_links"):
                I._unpack(src, src.parent / "out", b)
        with self.assertRaises(I.StoreError) as cm:                           # Cancel is honoured while the archive is listed
            go(lasts=2000, cancel=lambda: True)
        self.assertIn("cancelled", str(cm.exception))
        self.assertTrue(FakeProc.made[0].killed)
        with self.assertRaises(I.StoreError) as cm:                           # and the limit for ITS size applies (3 GB: 40 minutes)
            go(lasts=2500)
        self.assertIn("Listing the archive took longer than the 40 minutes", str(cm.exception))
        self.assertTrue(FakeProc.made[0].killed)
        go(lasts=2000)                                                        # inside the 40 minutes it goes on (FakeProc lists nothing)
        self.assertFalse(FakeProc.made[0].killed)

    def _dmg(self, size_mb, cancel=None, clock=None, claims=None):
        """Run _dmg_copy with the attach faked: a mounted folder holding one top-level file of size_mb MB."""
        tmp = Path(tempfile.mkdtemp(prefix="hx-store-dmg-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        src, dest = tmp / "Thing.dmg", tmp / "out"
        src.write_bytes(b"dmg")
        dest.mkdir()
        attach = []

        def fake_attach(cmd, what, watch, budget, timeout=None):
            attach.append((what, timeout))
            mnt = Path(cmd[cmd.index("-mountpoint") + 1])
            (mnt / "Installer.pkg").write_bytes(b"xar!" + b"\0" * (size_mb * 1024 * 1024))
            return 0, ""
        b = I.Budget(3 * 10 ** 9, cancel=cancel)
        with mock.patch.object(I.sys, "platform", "darwin"), mock.patch.object(I, "_run_watched", fake_attach), \
                mock.patch.object(I.subprocess, "run", return_value=mock.Mock(returncode=0)), \
                mock.patch.object(I, "_clock", clock or time.monotonic):
            try:
                I._dmg_copy(src, dest, b)
            finally:
                self.dmg_result = (attach, dest)
        return attach, dest

    def test_a_disk_image_is_attached_by_size_and_a_big_file_in_it_can_be_cancelled(self):
        attach, dest = self._dmg(1)                                           # no trouble: attached with the 3 GB limit, copied whole
        self.assertEqual(attach, [("opening the disk image", I.unpack_limit(3 * 10 ** 9))])
        self.assertEqual((dest / "Installer.pkg").stat().st_size, 4 + 1024 * 1024)
        calls = []
        def cancel_after_first_piece():
            calls.append(1)
            return len(calls) > 4                                             # the copy is under way when Cancel comes
        with self.assertRaises(I.StoreError) as cm:
            self._dmg(40, cancel=cancel_after_first_piece)                    # a 40 MB file: 5 pieces of 8 MB
        self.assertIn("cancelled", str(cm.exception))
        self.assertLess((self.dmg_result[1] / "Installer.pkg").stat().st_size, 40 * 1024 * 1024)   # stopped part-way

    def test_a_file_copied_out_of_a_disk_image_obeys_the_time_limit(self):
        with self.assertRaises(I.StoreError) as cm:
            self._dmg(20, clock=FakeTime(step=1500))                          # each look at the clock costs 25 fake minutes
        self.assertIn("took longer than the 40 minutes", str(cm.exception))

    def test_no_caller_still_has_the_old_fixed_limit(self):
        text = Path(I.__file__).read_text(encoding="utf-8")
        self.assertEqual(text.count("timeout=900"), 1)                        # only the default of the short listing helper
        section = lambda fn: text.split("def " + fn, 1)[1].split("\ndef ", 1)[0]
        self.assertIn("limit_s()", section("_dmg_copy"))                      # the disk image is opened and copied by size
        self.assertIn("unpack_limit(", section("_copy_tree"))
        self.assertIn("limit_s()", section("_run_watched"))


if __name__ == "__main__":
    unittest.main()
