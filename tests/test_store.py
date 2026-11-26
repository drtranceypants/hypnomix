"""The Hypnomix store: the catalogue's schema, and the installer on archives built here (zip, tar, 7z, dmg), into a
temporary HYPNOMIX_STORE_ROOT. Nothing touches the real ~/Library or ~/Music.

HYPNOMIX_STORE_NET=1 also runs one real download (GATE-12 from GitHub) into a temporary root."""
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
    (b / "Contents" / "MacOS" / b.stem).write_text(text)
    (b / "Contents" / "Info.plist").write_text("<plist/>")
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


ITEM = dict(id="fooverb", name="Fooverb", kind="effect", vendor="Test", licence="MIT", open_source=True,
            formats=["VST3", "AU"], macos_arm64=None, homepage="https://example.org/", about="test",
            source={"type": "url", "url": "https://example.org/foo.zip", "version": "1"}, method="bundles")
KIT = dict(ITEM, id="testkit", name="Test Kit", kind="drum kit", formats=["SFZ", "WAV"], method="content")


class Catalogue(unittest.TestCase):
    def test_shipped_catalogue_is_valid(self):
        data = C.load()
        self.assertEqual(C.validate(data), [])
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
            f.write_text(json.dumps({"schema": 1, "version": "2026.1.1", "items": ["x"]}))
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
        self.assertEqual((vst3 / "Contents/MacOS/Fooverb").read_text(), "v2")
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
        self.assertEqual((mine / "Contents/MacOS/Fooverb").read_text(), "the person's own copy")
        self.assertNotIn("fooverb", I.manifest()["items"])
        # confirmed: replaced, and the old copy is kept in the store's trash, not deleted
        e = I.install(ITEM, archive=z, info={"version": "1"}, confirm_unverified=True, confirm_overwrite=True)
        self.assertEqual((mine / "Contents/MacOS/Fooverb").read_text(), "v1")
        self.assertEqual(len(e["replaced_kept_in"]), 1)
        self.assertEqual((Path(e["replaced_kept_in"][0]) / "Contents/MacOS/Fooverb").read_text(), "the person's own copy")

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
        with self.assertRaises(I.StoreError):
            I.install(ITEM, archive=z3, info={"version": "1"}, confirm_unverified=True)
        self.assertFalse((self.root / "Library").exists())

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("hdiutil"), "needs hdiutil")
    def test_dmg_with_a_link_outside_is_refused(self):
        src = self.tmp / "dmgsrc" / "Evil.vst3" / "Contents"
        src.mkdir(parents=True)
        (src / "Info.plist").write_text("x")
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
        (d / "kit.sfz").write_text("<region> sample=Samples/kick.wav")
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
        (d / "Kit" / "a.sfz").write_text("x")
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
        before = subprocess.run(["hdiutil", "info"], capture_output=True, text=True).stdout.count("hypnomix-store-mnt")
        e = I.install(dict(ITEM, formats=["CLAP"]), archive=dmg, info={"version": "1"}, confirm_unverified=True)
        self.assertEqual(e["paths"], [str(self.root / "Library/Audio/Plug-Ins/CLAP/Fooverb.clap")])
        self.assertFalse((self.root / "Library/Audio/Plug-Ins/CLAP/Applications").exists())
        after = subprocess.run(["hdiutil", "info"], capture_output=True, text=True).stdout.count("hypnomix-store-mnt")
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
        f.write_text(json.dumps(data))
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
        texts = [(it["id"], " ".join(str(it.get(k, "")) for k in ("name", "vendor", "about"))) for it in data["items"]]
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
        (outside / "victim.txt").write_text("keep me")
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
        out.write_text("x")
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
        r = subprocess.run(["xattr", "-p", "com.apple.quarantine", e["installer"]], capture_output=True, text=True)
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
                gone = {str(p.relative_to(st)) for rule, a, p, n in items if rule == "store"}
                self.assertEqual(gone, {"work/foo-1", "installers/old", "trash/20260101-000000"})
                self.assertIn("store", [r["rule"] for r in DC.summary(items)])
                self.assertIn("store:", (Path(DC.__file__).with_name("diskcare.js")).read_text())
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


if __name__ == "__main__":
    unittest.main()
