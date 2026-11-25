# The app and the Live device

Two ways to do the whole first pass by clicking, without an AI: a web app on your own computer (which you
can optionally build into a Mac app), and a device inside Ableton Live. Both drive the same commands the rest of this guide describes, and the same
rules hold: the scan changes nothing, you decide each item, approved fixes go into a new set.

## The web app

```bash
hypnomix app            # opens http://127.0.0.1:8791 in your browser
```

That is all it takes: the app is a page served from your own computer. Leave the terminal window open while
you use it; Ctrl-C stops it.

| screen | what you do there |
|---|---|
| Songs | choose a Live set, or a folder of recordings from any DAW; optionally a bounce of the mix, a song you love, the key. "Start the first pass" runs `scan`, then `ab` |
| Activity | the log of each command as it runs, with a Stop button |
| Review | every finding with its A / B players; Approve, Skip or Change with a note. Saved as you click |
| Apply | writes only what you approved into one new set next to the original (`fix --approved`), then shows the log: what was applied, what changed, what is no longer measured |
| Preferences | the questions asked once: targets, protected tracks, what is deliberate |
| Tools | every other command with its help and a form: tempo, variations, mastering, and the rest |

It is a web server on this computer only. It refuses requests from other sites, only reads and writes scans
inside its own folder (`~/Documents/Hypnomix`; change with `--home`), and never overwrites a set.

## Optional: your own Mac app

If you would rather have an icon in the Dock than a browser tab, build `Hypnomix.app`: a small window around
the same web app that starts it when you open the app and stops it when you quit.

```bash
xcode-select --install      # once: Apple's command line tools (the Swift compiler)
macapp/build.sh             # from the hypnomix folder; about a minute
open macapp/dist/Hypnomix.app
```

Drag `macapp/dist/Hypnomix.app` into Applications if you want to keep it. Things to know:

- You build it yourself, so it is made for your Mac and macOS trusts it. A copy sent to someone else will be
  blocked by macOS unless it is signed and notarised with an Apple developer account: tell them to build
  their own with the three lines above.
- The app remembers where hypnomix is installed. If you move or reinstall that folder, build again (or the
  app asks you to point at the folder).
- It is the same page as `hypnomix app`. Nothing is lost by using the browser instead, and on Windows or
  Linux the browser is the way.
- To remove it, delete the app. Your songs' scans stay in `~/Documents/Hypnomix`.

## The Live device (Max for Live)

```bash
hypnomix device         # writes Hypnomix.amxd + hypnomix_device.js into your Live User Library
```

Drag **Hypnomix** from Live's browser (User Library → Presets → Audio Effects → Max Audio Effect → Hypnomix)
onto any track. Audio passes through it untouched. With the app running and a review open:

- the device shows the finding you are on: track, bar, the problem and the proposed fix
- **Prev / Next / Next open** step through the findings, and Live jumps to each: the track is selected, the
  playhead moves to the spot, the loop brace is put around it (looping is not switched on) and the clip opens
- **Approve / Skip** record your decision, exactly like a click in the app. Nothing is applied from Live
- **Show in Live** buttons in the app do the same jump through the device
- **Brace off** leaves your loop brace where it is

Applying still happens in the app, into a new set, with the original closed. The device never edits the set
it sits in.

It needs Max for Live (Live Suite, or the add-on). It is built from the blank Max Audio Effect inside your
own copy of Live plus one script file; keep the two files in the same folder.

## For an AI agent

- If the person prefers clicking to chatting, start `hypnomix app` for them (as a background process, not a
  blocking shell) and say what each screen does. Their decisions land in the same `decisions.json` you read.
- The app is not a way round the rules: it runs `fix --approved`, with the same gates.
- Say plainly that the Live device is new: its script has been tested against a simulated Live set. Until the
  person has loaded it in Live, present it as untested there.
