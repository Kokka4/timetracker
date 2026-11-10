# Local time tracker

Two streams, one clock.

- **The desktop watcher** samples which app is frontmost, how long ago you last
  touched the keyboard, and whether the screen is locked. It is the only thing
  that claims time.
- **The Chrome extension** says which tab was in front at a given moment. It
  never claims time of its own; it only labels time the watcher already
  recorded.

They are joined on timestamps. A desktop interval where Chrome was frontmost is
cut into the pieces covered by tab intervals, and whatever is left over stays as
plain Chrome time with no tab attached. The totals add up to the desktop total
whether or not the extension was running, which is the whole point of splitting
it this way: the browser half can fail without corrupting the numbers.

Everything is local. The HTTP server binds to `127.0.0.1`, the database is a
SQLite file in `data/`, the dashboard loads no fonts or scripts from anywhere,
and nothing in the code makes an outbound request.

---

## Install

```bash
cd ~/Desktop/ActivityWatch
chmod +x install.sh uninstall.sh doctor.sh
./install.sh
```

That finds a usable Python, writes a launch agent, starts it, and prints a
diagnostic. The agent has `RunAtLoad` and `KeepAlive`, so it starts at every
login and restarts if it ever dies.

Then open **http://127.0.0.1:8734**.

Re-running `./install.sh` is safe; it replaces the agent and restarts.

### Two optional extras

**Window titles.** App-level tracking needs no permissions at all. Capturing
*which* document, repo or window needs Accessibility, and macOS grants that per
binary:

```
System Settings → Privacy & Security → Accessibility → +
⌘⇧G, then paste the path ./doctor.sh prints
launchctl kickstart -k gui/$(id -u)/ai.leadprinter.timetracker
```

Chrome tabs do **not** need this — they come from the extension.

**Chrome tab detail.** `chrome://extensions` → Developer mode on → Load
unpacked → pick the `extension/` folder. Chrome will warn that it can read data
on all sites; that is what reading tab URLs and titles means. Incognito windows
are never reported.

---

## How to actually use it

The dashboard is not the product. A general "here's your time" view gets looked
at for two weeks and then never again, because it doesn't force a decision. The
thing worth your attention is the **Needs a label** panel.

Each row is a chunk of unattributed time. Type a client, press Label, and a rule
is written. The rule applies to your whole history, not just from now on, so
every correction compounds backwards as well as forwards. Two minutes a day for
a week and most of your time classifies itself.

The **around it** column is the trick that makes the ambiguous blocks tractable.
Twelve minutes in Claude means nothing on its own. Twelve minutes in Claude with
one client's campaign work either side of it almost certainly belongs to that
client, and the column shows you that without you having to remember.

Rules compose rather than compete: the starter rules say what *kind* of work a
site is, your rules say *whose* it is, and both apply to the same block.

Once a few weeks are labelled, the number that changes decisions is hours per
client against what that client pays you. Export it with the CSV link.

---

## What the numbers mean

Worth knowing, because most trackers quietly get these wrong:

- **Idle is back-dated.** macOS reports how long ago your last input was, so
  when you cross the idle threshold the tracker knows you stopped three minutes
  ago, not now. The activity already recorded in that window is deleted rather
  than left as phantom work.
- **Sleep is not counted.** `time.monotonic()` stops while a Mac is suspended
  and the wall clock does not, so the difference between them is the sleep
  duration. Close the lid for an hour and that hour is recorded as a gap, not
  credited to whatever was frontmost.
- **A locked screen is away time**, back-dated the same way.
- **Resolution is one sample interval.** A switch between apps lands within 5
  seconds of when it happened. Totals have no gaps and no overlaps.
- **Browser intervals are clipped to desktop intervals**, so a tab left open
  while you were in another app counts for nothing.
- **Classification is computed at read time**, never stored, which is why
  editing a rule rewrites history.

---

## Privacy

- Nothing leaves the machine. There is no telemetry and no sync.
- `excluded_apps` in `config.json` records that an app was in front but never
  its window title. 1Password and similar are excluded out of the box.
- `excluded_title_patterns` drops any title matching a regex.
- `excluded_domains` drops sites entirely.
- Query strings are stripped from URLs by default (`strip_query_strings`), since
  they carry tokens and search terms.
- The content script counts keystrokes. It never reads what you typed — four
  integers and a boolean are all that leave the page.
- The ingest endpoint rejects any request with an `http(s)` origin, so a web
  page you have open cannot post into your database.

This is built for one person tracking themselves. Putting it on someone else's
machine makes it employee monitoring, with the consent and proportionality
obligations that come with that under GDPR.

---

## Configuration

`config.json`, then:

```bash
launchctl kickstart -k gui/$(id -u)/ai.leadprinter.timetracker
```

| key | default | what it does |
|---|---|---|
| `port` | 8734 | dashboard and ingest port |
| `sample_interval_seconds` | 5 | how often the watcher looks |
| `idle_threshold_seconds` | 180 | silence before you count as away |
| `capture_window_titles` | true | set false to never read titles |
| `excluded_apps` | 1Password etc. | timed, but no title recorded |
| `excluded_title_patterns` | password, secret | regexes; matching titles are dropped |
| `excluded_domains` | [] | sites not recorded at all |
| `strip_query_strings` | true | drop `?...` from stored URLs |
| `browsers` | Chrome, Brave, Arc… | bundle ids treated as browsers |

---

## Giving it to someone else

Each install is an island: its own machine, its own database, no account and
no server. Nothing reports anywhere.

**See `SETUP.md`** for the step-by-step sheet — commands, permissions, exact
clicks, verification and troubleshooting. Budget 10 minutes per Mac.

```bash
curl -fsSL https://raw.githubusercontent.com/kokka4/timetracker/main/bootstrap.sh | bash
```

Offline instead of a repo:

```bash
./make-release.sh      # a clean zip on your Desktop, with none of your data
```

The release is built from an allow-list, not an ignore-list, and refuses to
build if a database or log file would end up inside it. `bootstrap.sh` deletes
any `tracker.db` that arrives with a download, so nobody inherits anyone
else's history.

Updating a machine later:

```bash
cd ~/timetracker && ./update.sh
```

## Commands

```bash
./doctor.sh                  # what works, what is missing, and why
./doctor.sh probe 20         # watch all three probes live while you switch apps
./doctor.sh status           # the running tracker's state as JSON
./doctor.sh stats            # row counts and database size
./reset.sh                   # delete all history and start from zero
./uninstall.sh               # stop and remove the agent; data is kept

tail -f logs/tracker.err.log
launchctl kickstart -k gui/$(id -u)/ai.leadprinter.timetracker   # restart
./.python -m tracker purge 365                                   # drop old data
```

---

## Troubleshooting

**Dashboard won't load.** `./doctor.sh`. If it says nothing is listening, check
`logs/tracker.err.log`. Two usual causes: the port is taken (change `port` in
`config.json` and re-run `./install.sh`), or macOS is refusing the agent access
to the folder.

**`logs/tracker.err.log` says "No module named tracker".** The agent could not
read the project directory. If the project sits under `~/Desktop`,
`~/Documents` or `~/Downloads`, that is why: macOS protects those folders and a
background agent is denied with no prompt, unlike your Terminal which you
approved once. Move it somewhere unprotected and reinstall:

```bash
mv ~/Desktop/ActivityWatch ~/timetracker && cd ~/timetracker && ./install.sh
```

Granting Full Disk Access to the Python binary that `./doctor.sh` prints works
too, but it is a much broader permission than this needs.

**All my time is credited to one app**, and **"By site" stays empty even though
the extension is loaded.** These are one fault, not two. Browser intervals are
clipped to desktop intervals where a browser was frontmost, so if the watcher
never reports Chrome, every tab interval is discarded at join time. Run:

```bash
./doctor.sh probe 20
```

and switch apps while it runs. It prints all three frontmost-app sources side
by side and names which ones follow your focus. The tracker prefers
`osascript` for exactly this reason: `NSWorkspace.frontmostApplication()` via
pyobjc answers from a cache refreshed by notifications that only arrive when a
Cocoa run loop is pumping, and a background script has no run loop — so it can
return the app that was frontmost at startup indefinitely, without ever
erroring. It is kept in the probe as a diagnostic and is never used as a
source.

**Everything says "Unlabelled".** Expected on day one. Use the review panel.

**Chrome time appears but no sites.** The extension is not loaded or not
reporting. Click its toolbar icon; the popup says whether it can reach the
tracker. It posts to `http://127.0.0.1:8734/api/ingest/chrome` — if you changed
the port, change it there too.

**Titles are empty.** Accessibility is not granted, or granted to a different
Python than the agent runs. `./doctor.sh` prints the exact path to add.

**Numbers look too high after a break.** They shouldn't — that is what the
back-dating is for. If they do, `idle_threshold_seconds` may be very large.

**Nothing recorded after a macOS update.** Permission grants sometimes reset.
Re-run `./doctor.sh` and re-grant.

---

## Layout

```
config.json          your settings
install.sh           launch agent setup
doctor.sh            diagnostics
tracker/
  watcher.py         the sampling loop: idle, lock, sleep, back-dating
  macos.py           the probes, with three fallback layers
  ingest.py          browser heartbeats to intervals
  analytics.py       the desktop × browser join, and the rollups
  rules.py           classification
  server.py          loopback HTTP: dashboard, API, ingest
  db.py              SQLite schema and writes
web/                 the dashboard (one page, no dependencies)
extension/           the Chrome extension
data/tracker.db      everything you have recorded
logs/                stdout and stderr from the agent
```
