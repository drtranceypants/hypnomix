"""The package pins OpenBLAS to one thread before numpy loads (a fork from a worker thread could hang
OpenBLAS's fork handler: a scan froze in the vocals step), and leaves an explicit setting alone."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = "import hypnomix, os; print(os.environ.get('OPENBLAS_NUM_THREADS'))"


def probe(env_extra):
    env = {k: v for k, v in os.environ.items() if k != "OPENBLAS_NUM_THREADS"}
    env.update(env_extra, PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, "-c", PROBE], env=env, capture_output=True, text=True,
                          check=True).stdout.strip()


class BlasGuard(unittest.TestCase):
    def test_default_one_thread(self):
        self.assertEqual(probe({}), "1")

    def test_explicit_setting_wins(self):
        self.assertEqual(probe({"OPENBLAS_NUM_THREADS": "4"}), "4")


if __name__ == "__main__":
    unittest.main()
