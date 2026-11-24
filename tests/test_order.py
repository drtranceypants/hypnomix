"""Track order and vocal-stack assignment (pure parts of hypnomix order)."""
import unittest
from hypnomix.session.order import propose_order, assign_stack, category


def t(i, kind="Audio", parent=None, cat=5, pitch=None):
    return dict(id=i, kind=kind, parent=parent, cat=cat, pitch=pitch)


class Order(unittest.TestCase):
    def test_categories_then_low_to_high(self):
        tracks = [t("vox_hi", cat=3, pitch=330), t("bass", cat=1, pitch=60), t("vox_lo", cat=3, pitch=196),
                  t("gtr", cat=2, pitch=200), t("kick", cat=0, pitch=5), t("hats", cat=0, pitch=900),
                  t("cello", cat=4, pitch=110), t("rev", kind="Return")]
        self.assertEqual(propose_order(tracks), ["kick", "hats", "bass", "gtr", "vox_lo", "vox_hi", "cello", "rev"])

    def test_groups_move_as_blocks_and_sort_inside(self):
        tracks = [t("g", kind="Group"), t("h2", parent="g", cat=3, pitch=330), t("h1", parent="g", cat=3, pitch=220),
                  t("drum", cat=0, pitch=10)]
        self.assertEqual(propose_order(tracks), ["drum", "g", "h1", "h2"])

    def test_unclear_tracks_keep_their_order_and_go_last(self):
        tracks = [t("x1", pitch=900), t("x2", pitch=100), t("b", cat=1, pitch=50)]
        self.assertEqual(propose_order(tracks), ["b", "x1", "x2"])

    def test_guess_labels_are_unclear(self):
        self.assertEqual(category("Keys", 0.4), 5)
        self.assertEqual(category("Harmony 2", 0.9), 3)
        self.assertEqual(category("Kick", 0.8), 0)


class Stack(unittest.TestCase):
    def test_low_harmony_recorded_on_a_later_track_moves_down(self):
        clips = [dict(key="a", track="T1", start=0, end=8, hz=330),   # high part on the low track
                 dict(key="b", track="T2", start=0, end=8, hz=196),   # low part on the high track
                 dict(key="c", track="T1", start=16, end=20, hz=200)]  # sung alone: stays put
        self.assertEqual(assign_stack(clips, ["T1", "T2"]), {"a": "T2", "b": "T1"})

    def test_already_in_place(self):
        clips = [dict(key="a", track="T1", start=0, end=8, hz=196), dict(key="b", track="T2", start=0, end=8, hz=330)]
        self.assertEqual(assign_stack(clips, ["T1", "T2"]), {})


if __name__ == "__main__":
    unittest.main()
