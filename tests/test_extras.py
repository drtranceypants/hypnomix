"""The optional extras (hypnomix/extras.py) and the skills the desktop-AI setup copies (hypnomix/app/setup.py)."""
import tempfile, unittest
from pathlib import Path
from unittest import mock

from hypnomix import extras as X
from hypnomix.app import setup as SU


class Extras(unittest.TestCase):
    def test_requirements_follow_pyproject(self):
        with mock.patch.object(X.metadata, "requires", return_value=[
                'numpy>=1.24', 'matchering>=2.0; extra == "reference"', 'pedalboard>=0.9 ; extra == "plugins"']):
            self.assertEqual(X.requirements("reference"), ["matchering>=2.0"])
            self.assertEqual(X.requirements("plugins"), ["pedalboard>=0.9"])
            self.assertEqual(X.requirements("ml"), [])

    def test_bundled_install_goes_to_user_dir_with_pins(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(X, "bundled", return_value=True), \
                mock.patch.object(X, "base_dir", return_value=Path(d)), \
                mock.patch.object(X, "requirements", return_value=["x"]):
            cmds, env = X.commands("ml")
            self.assertEqual(len(cmds), 2)                       # basic-pitch goes in on its own, without TensorFlow
            self.assertIn("--no-deps", cmds[1])
            for c in cmds:
                self.assertIn("--user", c)
                self.assertIn("--constraint", c)
            self.assertEqual(env["PYTHONUSERBASE"], d)
            self.assertNotIn("PYTHONNOUSERSITE", env)
            self.assertTrue((Path(d) / "app-packages.txt").exists())

    def test_included_extras_are_not_installable(self):
        with self.assertRaises(ValueError):
            X.install("assistant")

    def test_status_lists_every_extra(self):
        ids = {e["id"] for e in X.status()["extras"]}
        self.assertEqual(ids, {"reference", "plugins", "ml", "assistant", "critique"})


class Skills(unittest.TestCase):
    def test_copy_skills_into_claude_folder(self):
        here = Path(SU.__file__).resolve()
        with tempfile.TemporaryDirectory() as d:
            skills, agents = SU.copy_skills(Path(d), here)
            self.assertIn("first-pass", skills)
            self.assertTrue((Path(d) / ".claude/skills/first-pass/SKILL.md").exists())
            self.assertIn("hypnomix-scanner", agents)
            self.assertTrue((Path(d) / ".claude/agents/hypnomix-scanner.md").exists())
            SU.copy_skills(Path(d), here)                       # again: replaces, doesn't fail


if __name__ == "__main__":
    unittest.main()
