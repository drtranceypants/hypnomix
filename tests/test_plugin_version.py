"""The plug-in manifest and the package say the same version.

Run from the repo root:  python -m unittest tests.test_plugin_version -v
"""
import json, re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pyproject_version():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = re.search(r"^\[project\]\s*$(.*?)(?=^\[|\Z)", text, re.S | re.M)
    m = re.search(r'^version\s*=\s*"([^"]+)"', project.group(1) if project else text, re.M)
    return m.group(1) if m else None


class PluginVersion(unittest.TestCase):
    def test_plugin_json_version_equals_pyproject(self):
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertTrue(pyproject_version(), "pyproject.toml has no version")
        self.assertEqual(plugin["version"], pyproject_version(),
                         ".claude-plugin/plugin.json and pyproject.toml must carry the same version")


if __name__ == "__main__":
    unittest.main()
