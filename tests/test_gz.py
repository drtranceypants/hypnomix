"""hypnomix.core.gz.read_gz: the same bytes as gzip.open().read(), and a clear stop past the size cap.

Run from the repo root:  python -m unittest tests.test_gz -v
"""
import gzip, shutil, tempfile, unittest
from unittest import mock
from pathlib import Path

from hypnomix.core import gz
from hypnomix.core.gz import read_gz


class ReadGz(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, True)

    def test_small_file_reads_the_same_as_gzip(self):
        p = self.td / "a.als"
        with gzip.open(p, "wb") as f:
            f.write(b"<Ableton><LiveSet/></Ableton>")
        self.assertEqual(read_gz(p), b"<Ableton><LiveSet/></Ableton>")
        self.assertEqual(read_gz(str(p)), gzip.open(p).read())

    def test_a_file_bigger_than_one_chunk_is_whole(self):
        p = self.td / "b.als"
        data = bytes(range(256)) * 20000                       # about 5 MB, more than one chunk
        with gzip.open(p, "wb") as f:
            f.write(data)
        self.assertEqual(read_gz(p), data)

    def test_a_highly_compressible_file_past_the_cap_is_refused_with_a_clear_message(self):
        p = self.td / "bomb.als"
        with gzip.open(p, "wb") as f:
            f.write(b"\0" * (6 << 20))                         # 6 MB unpacked, a few KB packed
        self.assertLess(p.stat().st_size, 100_000)
        with self.assertRaises(ValueError) as cm:
            read_gz(p, cap=1 << 20)
        self.assertIn("this file unpacks to more than 1 MB", str(cm.exception))
        self.assertIn("not a project HypnoMix will open", str(cm.exception))
        self.assertEqual(len(read_gz(p, cap=8 << 20)), 6 << 20)   # a higher cap lets it through

    def test_a_file_past_the_cap_is_refused_without_holding_it_in_memory(self):
        import tracemalloc
        p = self.td / "big.als"
        with gzip.open(p, "wb") as f:
            for _ in range(40):
                f.write(b"\0" * (1 << 20))                     # 40 MB unpacked, a few KB packed
        with mock.patch.object(gz, "SOFT", 2 << 20):
            tracemalloc.start()
            try:
                with self.assertRaises(ValueError):
                    read_gz(p, cap=20 << 20)
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
            self.assertLess(peak, 8 << 20)                      # not the 20 MB cap
            self.assertEqual(len(read_gz(p, cap=64 << 20)), 40 << 20)   # large but allowed: whole

    def test_the_default_cap_is_one_gigabyte(self):
        self.assertEqual(gz.CAP, 1 << 30)

    def test_a_file_that_is_not_gzip_raises_what_gzip_raises(self):
        p = self.td / "junk.als"
        p.write_bytes(b"not a set")
        with self.assertRaises(OSError):
            read_gz(p)


if __name__ == "__main__":
    unittest.main()
