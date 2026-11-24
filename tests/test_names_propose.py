"""hypnomix name's proposals (pure part): copies, lead, group names, the person's own names."""
import unittest
from hypnomix.session.names import propose


def tr(old, label, conf, on=True, vowel=0.0, active=0.0, f0=None, kind="Audio", group=None):
    return dict(old=old, kind=kind, group=group, on=on, label=label, confidence=conf, reason="test",
                features=dict(vowel_move=vowel, active_s=active, f0=f0) if kind == "Audio" else None)


def vocal_set():
    # three takes switched off, each with a playing copy named "<take> CLEAN"; one copy's own sound is unclear
    rows = {
        "1": tr("12-Audio", "Vocal", 0.9, on=False, vowel=15.0, active=70, f0=196),
        "2": tr("12-Audio CLEAN", "Keys", 0.4, on=True, vowel=14.8, active=45, f0=196),
        "3": tr("13-Audio", "Vocal", 0.9, on=False, vowel=14.4, active=62, f0=220),
        "4": tr("13-Audio CLEAN", "Vocal", 0.9, on=True, vowel=15.8, active=35, f0=220),
        "5": tr("14-Audio", "Vocal", 0.9, on=False, vowel=14.1, active=53, f0=247),
        "6": tr("14-Audio CLEAN", "Vocal", 0.9, on=True, vowel=15.2, active=32, f0=247),
    }
    return rows, {k: "-1" for k in rows}


class Names(unittest.TestCase):
    def test_playing_copy_gets_the_part_and_its_partner_mirrors_it(self):
        rows, parent = vocal_set()
        new = {r["old"]: r["new"] for r in propose(rows, parent).values()}
        self.assertEqual(new["12-Audio CLEAN"], "Lead Vocal CLEAN")
        self.assertEqual(new["12-Audio"], "Lead Vocal")
        self.assertEqual(new["13-Audio CLEAN"], "Harmony 1 CLEAN")
        self.assertEqual(new["13-Audio"], "Harmony 1")
        self.assertEqual(new["14-Audio"], "Harmony 2")

    def test_playing_original_gets_the_part_when_the_copy_is_off(self):
        rows, parent = vocal_set()
        for k in rows:
            rows[k]["on"] = not rows[k]["on"]
        new = {r["old"]: r["new"] for r in propose(rows, parent).values()}
        self.assertEqual(new["12-Audio"], "Lead Vocal")
        self.assertEqual(new["12-Audio CLEAN"], "Lead Vocal CLEAN")

    def test_given_name_is_not_suffixed_again(self):
        rows, parent = vocal_set()
        new = {r["old"]: r["new"] for r in propose(rows, parent, {"12-Audio CLEAN": "Lead Vocal CLEAN"}).values()}
        self.assertEqual(new["12-Audio CLEAN"], "Lead Vocal CLEAN")

    def test_guesses_do_not_name_a_group(self):
        rows = {"g": tr("8-Group", None, 0, kind="Group")}
        for k in range(8):
            rows[f"k{k}"] = tr(f"{20 + k}-Audio", "Keys", 0.4, group="8-Group")
        rows["v1"] = tr("30-Audio", "Vocal", 0.9, group="8-Group", vowel=15, active=60)
        rows["v2"] = tr("31-Audio", "Vocal", 0.9, group="8-Group", vowel=14, active=30)
        rows["gt"] = tr("32-Audio", "Guitar", 0.75, group="8-Group")
        parent = {k: ("g" if k != "g" else "-1") for k in rows}
        out = propose(rows, parent)
        self.assertNotIn("Keys", out["g"]["new"])
        self.assertLess(out["g"]["confidence"], 0.5)      # mixed group: asked about, not renamed blind


if __name__ == "__main__":
    unittest.main()
