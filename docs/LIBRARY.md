# Learn my style: the library scan

`hypnomix taste --library` is the first-run scan of everything you have made in Ableton Live. It studies your
sets and the finished bounces next to them, describes how you mix (**YOUR STYLE**), and lists a few measured,
gentle suggestions (**WHERE YOU COULD IMPROVE**). Other tools read the result so their proposals start from
your habits instead of generic defaults.

```bash
hypnomix taste --library                       # your Ableton folders + every set Spotlight knows about
hypnomix taste --library ~/Music/Projects      # only these folders
hypnomix taste --library --no-bounces          # sets only, no audio measured
hypnomix taste --library --genre "My Song Project=indie folk"     # confirm a genre guess
python -m hypnomix.workflow.library [same arguments]               # the same thing, run as its own module
```

Options: `--jobs N` (parallel readers, default CPUs - 1, at most 8), `--refresh` (ignore the cache),
`--no-spotlight` (walk the folders only), `--max-bounce-seconds S` (read at most this much of each bounce,
default 600), `--out DIR` (where LIBRARY.md goes, default `hypnomix-out/library/`).

## Which sets count

Default folders: `~/Music/Ableton`, `~/Documents`, plus every `.als` Spotlight finds (on a Mac). Given
folders are walked instead, without Spotlight.

Skipped, each with the reason in the report:

- Live's own content: Factory Packs, Core Library, lessons and demo sets
- `Backup` folders (Live's automatic copies)
- templates (`Templates`, `Defaults`, "template" in the name, a set called `Default`)
- downloaded packs and preset projects (a project folder with `Lessons` or `Presets` folders, or names like
  "presets", "drum kit", "demo set")
- test and device-chain sets ("test", "mastering chain" in the name)
- HypnoMix output, the Trash, sets marked `(BROKEN, do not open)`
- **older versions**: each song counts once. Versions are recognised by their name without version words
  (`Song`, `Song v2`, `Song (final review 3)` and `Song v2 Project/Song v2` are one song); the newest file wins,
  wherever it is. An `Untitled` set counts as a version of its project's song.
- after reading: sets with under 30 seconds in the Arrangement (sketches, preset or device sets)

## What it learns

From each set (read as XML; nothing is rendered):

| topic | what is read |
|---|---|
| levels, space, ambience, chains | the same as `hypnomix taste`: faders against the lead vocal, pans, reverb / delay sends, device chains, automation |
| compression | Live's Compressor and Glue Compressor per kind of track: ratio, attack, release, threshold, makeup, knee, sidechain on or off |
| EQ | EQ Eight's active bands: type, frequency, gain, Q. The low cut per kind of track, and the usual boosts and cuts by region (sub, bass, low-mid, mid, presence, air) |
| main chain | Limiter ceiling and gain, Glue / Compressor, Utility on Main |
| saturation, width | Saturator drive and dry/wet; Utility width and bass mono |
| returns | Reverb decay and predelay; Delay / Echo synced or free, free times as a fraction of a beat, feedback |
| plug-ins | third-party plug-ins per kind of track, **by name and count only**. Their settings are an opaque blob in the set: HypnoMix cannot read them and never tries |
| sounds | Live and plug-in instruments, Drum Racks, the samples Simpler / Sampler play, the Live packs the set uses |
| genre | a rough guess from tempo and instruments, saved only as a **question** (see below) |

The kind of track ("role": lead, harmony, drums, bass, keys/guitar/synth, strings/other, group, return, main)
comes from the labels `hypnomix name` / `voices --learn` gave a version of the song when there are any,
otherwise from the track's name, its group's name, its instrument and its samples. A track nothing identifies
is counted as "unknown".

From each song's **bounce** (optional): the newest exported mix found in the project folder, next to it, in the
song's renders folder `~/Desktop/HypnoMix/<song>/` (`hypnomix renders <song>` prints and creates it; export there
so the Desktop stays clear), or at the top of Desktop, Music or Documents, whose name matches the song
or contains mix / master / final / bounce. Names with "before", "test", "stem", "vocals" and similar are test
renders, not mixes; "review" and "unmastered" ones are used only when nothing better exists. Measured:
integrated loudness (pyloudnorm), true peak (4x oversampled), crest, peak-to-loudness ratio (PLR) and the
tonal balance in 8 bands. At most 10 minutes of each file is read, and a file that takes more than 90 s is
reported as timed out. A bounce much shorter than the arrangement is taken for a section and ignored.

## YOUR STYLE

Each number is the median set (each set counts once) with the middle half and the full range. The rule is the
same as `taste`: a narrow middle half is a **standard** (you do it the same way every time: tools keep to it);
a wide one is a **taste call** (tools ask each time). Fewer than three sets is "too few sets to tell".

## WHERE YOU COULD IMPROVE

Advice only, never applied. Each suggestion names the sets and the numbers behind it:

- **bounces above the true-peak target** (your `targets.true_peak`, default -1 dBTP): lossy encodes add about
  0.5-1 dB, so the upload may clip. Shows the Live Limiter's ceiling when there is one, or says the Main chain
  ends in a plug-in whose ceiling can't be read.
- **compressor release faster than two cycles of the lowest bass note** on bass, groups with bass in them and
  Main (the lowest note comes from the bass's MIDI; 41 Hz, low E, is assumed for audio bass). Sidechained
  compressors are ducking and are left out.
- **low cut missing** on a kind of part that you cut in most of your other sets (60% or more of at least 3).
- **loudness spread**: bounces more than 3 LU apart.
- **heavy limiting on Main**: PLR under 8 dB, with a rough estimate of the gain reduction (unlimited mixes
  usually sit at 11-14 dB).
- **tonal outliers**: a song 4 dB or more away from the median of your own songs in a band.

## Genres

The guess (from tempo, drums, synth instruments, vocal tracks) is never stored as a fact. The report lists one
question per project; confirm or correct it with `--genre "PROJECT=genre"` (saved under `library.genres` in
`~/.hypnomix/preferences.json`). Once genres are confirmed, the report adds a per-genre breakdown (tempo,
bounce loudness and PLR, bass compressor release, lead compressor ratio, Main ceiling).

## How long it takes

On a library of about 340 `.als` files (most of them backups, Factory Packs and older versions, so a few
dozen are actually read) the first full run took about 15-35 seconds on a recent Mac with 8 readers,
bounces included. A re-run reads only the sets and bounces that changed (cache by path, size and time in
`~/.hypnomix/cache/library/`) and takes a second or two. Large sets with many tracks take longest to parse.

## Privacy

Everything stays on the computer. The scan only reads: it never opens Live, never writes to a set, a
sample or a bounce, and sends nothing anywhere. It writes three things: `LIBRARY.md` (in `hypnomix-out/library/`
or `--out`), `~/.hypnomix/library.json` and its cache in `~/.hypnomix/cache/library/` (set `HYPNOMIX_HOME`
to put them elsewhere). These files contain your set names, track names, paths and plug-in names: don't
commit or share them unless you mean to.

## How other tools use library.json

`~/.hypnomix/library.json` is the machine-readable version:

- `scan`: counts and timing (found, sets, skipped, read, cache hits, seconds)
- `style`: per topic, `{median, low, high, p25, p75, sets}` summaries (`compression["lead|compressor"]`,
  `eq[role]`, `main`, `saturation`, `utility`, `returns`, `plugins`, `sounds`, `bounces`, `taste` (the same
  shape as `taste.json`'s profile), `genres`)
- `improve`: a list of `{topic, rule, title, advice, evidence[]}`
- `questions`: the unconfirmed genre guesses, `{project, set, guess, why, key}`
- `sets`, `skipped` (with reasons), `failed`

A tool that proposes a setting can start from the person's median for that role (for example a compressor's
release on the lead) and treat a "standard" as the default to keep, while a "taste call" is a question to
ask. Like every preference, it shapes proposals; it never replaces asking.
