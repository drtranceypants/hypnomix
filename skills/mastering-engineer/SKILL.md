---
name: mastering-engineer
description: Master a stereo mix for release with hypnomix (loudness target, reference matching, codec-safe peaks, QC), and explain the chain. Use when someone wants a song mastered, louder, "ready for Spotify", compared to a reference, or checked before release.
---

# Mastering engineer

Read `hypnomix prefs` first: the loudness and true-peak targets and the delivery format are there (ask the
first-run questions if not). The master is a new file; the mix is never changed. Start with `hypnomix master mix.wav --plan`: each stage of
the chain (clean-up, tone match, glue, mono low end, limiter, top and tail) becomes a finding to approve, and
`hypnomix fix DIR --approved` runs only those. `hypnomix match mix.wav reference.wav` lists how the mix differs
from a song they love before any processing. After mastering, give a
level-matched A/B against the mix and ask what they hear before any second attempt.

1. **Measure the mix first:** `hypnomix measure mix.wav`. If true peak is near 0 or the mix is already squashed (crest under ~8 dB), say so: mastering can't undo it.
2. **Pick the target with them.** -14 LUFS suits Spotify, YouTube and Tidal (they turn louder songs down). -16 for Apple-first or very dynamic music. -9 to -11 only for loud genres, and say that the platforms will turn it down anyway.
3. **Master:** `hypnomix master mix.wav --target -14 [--reference ref.wav --match 0.6] [--warmth 0.3] [--cd]`.
   - The chain: subsonic HPF → (reference tone match) → glue compression → mono low end → (saturation) → true-peak limiter → codec-safe ceiling → top and tail.
   - It encodes AAC and MP3 test copies and lowers the ceiling itself if they clip. Mention this when it happens.
4. **Read the notes:** limiter "avg dB when it does" over ~3 dB means the mix is too quiet or too peaky going in. Suggest fixing the loudest elements in the mix rather than pushing harder.
5. **Check:** `hypnomix translate master.wav --render` (they can listen to the phone and mono versions) and `hypnomix qc master.wav [--for cd|vinyl]`. Don't deliver anything with a FAIL.

When comparing with a reference, level-match first (the louder one always sounds better) and compare the same section. To compare two bounces of the same song, `hypnomix compare old.wav new.wav` says in plain words what changed, with level-matched A/B clips of the biggest differences.

For delivery: `hypnomix release master.wav --title … --artist … --check` first (read-only), then without `--check`: a new folder with the 24-bit WAV, a dithered 16-bit WAV, MP3 and AAC with tags and cover, and a report that measures every file. For a whole EP or album, `hypnomix album song1.wav song2.wav …` reports which songs sit apart in level or tone before anything is changed. `hypnomix versions --stems DIR --vocals "Lead*,Harm*" --check` shows the plan first (read-only, writes nothing). Without `--check` it writes the instrumental and a cappella, plus a TV mix (with `--tv`) and a radio edit (with `--cut`), into a new folder from the person's own stems.

## Mastering inside Live (stock devices, no paid plug-ins)
When they want a chain they can tweak in Live, or don't own a mastering suite: export the full mix from bar 1, then run `hypnomix chain master bounce.wav --target -14 [--reference ref.wav] --dry-run` and show the plan. On their OK, drop `--dry-run` and add `--existing bypass` (switch off current master plug-ins) or `--existing keep`, plus `--verify` if BlackHole is set up. It never deletes devices and saves a mixer snapshot first. Parameters the Live version doesn't have are listed to set by hand.
