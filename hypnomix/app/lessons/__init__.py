"""The lessons of teacher mode (hypnomix/app/teacher.py): one module per chapter, each exporting CHAPTER.

A chapter is a dict: id, title, sub, levels (which courses it belongs to: "tour", "101", "az") and steps. A step may carry
its own `levels`; without one it follows its chapter. The three courses:

  tour  hypnomix in your DAW (for people who already record and mix)
  101   the crash course: the words, a first recording, one effect at a time, mastering, then the tour
  az    the complete course, A to Z: every chapter and step (101 is a subset of it)

Chapters are listed in teaching order below. Step ids must never change once published (progress files key on them).
"""
from importlib import import_module

_ORDER = ["ch01_sound", "ch02_digital", "ch03_gear", "ch04_words", "ch05_song", "ch06_record", "ch07_editing",
          "ch08_mix", "ch09_master", "ch10_release", "ch11_trouble", "ch12_cheats", "ch13_hypnomix"]


def _load():
    out = []
    for name in _ORDER:
        out.append(import_module(f"{__name__}.{name}").CHAPTER)
    return out


CHAPTERS = _load()
from hypnomix.app.lessons.glossary import GLOSSARY  # noqa: E402  (extra words that no step defines)
