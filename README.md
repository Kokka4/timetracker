# Local time tracker

A time tracker for one person, on one Mac, that cannot report to anybody.

Everything it records stays in a single SQLite file on the machine that
recorded it. There is no account, no server, no sync and no telemetry. The
HTTP server binds to `127.0.0.1`, the dashboard loads no fonts or scripts
from anywhere, and nothing in the code makes an outbound request. That is not
a privacy policy, it is the architecture: there is nowhere for the data to go.

---

## Contents

- [How it measures time](#how-it-measures-time)
- [Install](#install)
- [A nicer address than an IP](#a-nicer-address-than-an-ip)
- [The first run](#the-first-run)
- [The loop that makes it worth having](#the-loop-that-makes-it-worth-having)
- [Two ways to put a name on time](#two-ways-to-put-a-name-on-time)
- [Writing a rule](#writing-a-rule)
- [The Day page](#the-day-page)
- [Removing time that was not work](#removing-time-that-was-not-work)
- [Export](#export)
- [Making the vocabulary yours](#making-the-vocabulary-yours)
- [The off switch](#the-off-switch)
- [What the numbers mean](#what-the-numbers-mean)
- [Privacy](#privacy)
- [Configuration](#configuration)
- [Giving it to someone else](#giving-it-to-someone-else)
- [Commands](#commands)
- [Troubleshooting](#troubleshooting)
- [Why it is built this way](#why-it-is-built-this-way)
- [Layout](#layout)

---

## How it measures time

Two streams, one clock.

- **The desktop watcher** samples which app is frontmost, how long ago you
  last touched the keyboard, and whether the screen is locked. It is the only
  thing that claims time.
- **The Chrome extension** says which tab was in front at a given moment. It
  never claims time of its own; it only labels time the watcher already
  recorded.

They are joined on timestamps. A desktop interval where Chrome was frontmost
is cut into the pieces covered by tab intervals, and whatever is left over
stays as plain Chrome time with no tab attached.

The totals add up to the desktop total whether or not the extension was
running. That is the whole point of splitting it this way: the browser half
can fail, be uninstalled, or be switched off for an afternoon without
corrupting a single figure. You lose detail, never accuracy.

Two independent reasons a colleague on the same wifi cannot reach your
tracker: `127.0.0.1` means "the machine making the request" and is never
routed onto a network, and the server is not listening on any other
interface, so your LAN address answers nothing either.

---

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/kokka4/timetracker/main/bootstrap.sh | bash
```

Or, from a copy you already have:

```bash
cd ~/timetracker && chmod +x *.sh && ./install.sh
```

That finds a usable Python, writes a launch agent, starts it, and prints a
diagnostic. The agent has `RunAtLoad` and `KeepAlive`, so it starts at every
login and restarts if it ever dies. Re-running `./install.sh` is safe: it
replaces the agent, restarts it, and snapshots your database first.

**No Xcode, no Command Line Tools, no Homebrew, no pip, no accounts.** The
only thing the Mac must have that it might not is a Python interpreter, and
that is a 78 MB double-click from python.org.

> The installer never runs `/usr/bin/python3`, `/usr/bin/git` or any other
> Apple shim to find out whether it works. Those files exist on every Mac
> whether or not the tools behind them do, and running one pops Apple's
> installer and starts a download of over a gigabyte. It asks
> `xcode-select -p` instead, which reports whether a developer directory
> exists and never offers to make one. To check for Python yourself before
> installing, list the paths rather than running the binary:
>
> ```bash
> ls -d /Library/Frameworks/Python.framework/Versions/*/bin/python3 \
>       /opt/homebrew/bin/python3 /usr/local/bin/python3 2>/dev/null
> ```
>
> `python3 --version` is the one command that causes the problem it is
> being used to check for.

### Two optional extras

**Window titles.** App-level tracking needs no permissions at all. Capturing
*which* document, repo or window needs Accessibility, and macOS grants that
per binary:

```
System Settings → Privacy & Security → Accessibility → +
⌘⇧G, then paste the path ./doctor.sh prints
launchctl kickstart -k gui/$(id -u)/ai.leadprinter.timetracker
```

Chrome tabs do **not** need this; they come from the extension.

**Chrome tab detail.** `chrome://extensions` → Developer mode on → Load
unpacked → pick the `extension/` folder. Chrome warns that it can read data
on all sites; that is what reading tab URLs and titles means. Incognito
windows are never reported.

---

## A nicer address than an IP

Any hostname ending in `.localhost` is reserved by [RFC 6761][rfc] and
resolved to the loopback address by the browser itself. No hosts file, no
admin rights, no DNS:

```
http://timetrack.localhost:8734
```

Pick whatever name you like. It can still only ever reach the machine it was
typed on, so it is exactly as private as the IP. Chrome and Firefox honour
it; Safari is unreliable, so keep `127.0.0.1:8734` as the fallback. Change
`"port"` in `config.json` if 8734 is taken.

[rfc]: https://www.rfc-editor.org/rfc/rfc6761#section-6.3

---

## The first run

The first time the dashboard is opened on a machine it shows a black screen
stating that the data stays on that computer, waits five seconds, and then
enables a **Continue** button. It cannot be clicked past and it never appears
again.

That is deliberate, and it is the only moment in the product that takes time
from you without giving anything back. A tracker is a thing people are right
to be suspicious of, and the one claim that matters is the one nobody reads
in a README. Five seconds is long enough to be read and short enough not to
be resented.

---

## The loop that makes it worth having

The dashboard is not the product. A general "here is your time" view gets
looked at for two weeks and then never again, because it does not force a
decision. The thing worth your attention is the **Needs a label** panel.

Each row is a chunk of unattributed time. Type a client, press Label, and a
rule is written. The rule applies to your whole history, not just from now
on, so every correction compounds backwards as well as forwards. Two minutes
a day for a week and most of your time classifies itself.

The **around it** column is the trick that makes ambiguous blocks tractable.
Twelve minutes in Claude means nothing on its own. Twelve minutes in Claude
with one client's campaign work either side of it almost certainly belongs to
that client, and the column shows you that without you having to remember.

Once a few weeks are labelled, the number that changes decisions is hours per
client against what that client pays you. [Export](#export) it.

---

## Two ways to put a name on time

There are two, and they answer different questions. Confusing them is the
most common way to end up with numbers you do not trust.

A **rule** is a pattern. *Anything on `app.instantly.ai` is outreach ops.*
Write one and it classifies the past and the future together, because
classification is computed when you look rather than stored on the event.

An **assignment** is a stretch of the clock. *That hour was Hanval.* It
claims nothing about any other hour.

Assignments are read after rules and win **field by field**, so assigning a
client to an afternoon keeps whatever categories the rules already worked out
for it. That is what makes assigning a client a small act rather than a
destructive one.

A block an assignment only partly covers is **cut at the boundary**, not
attributed whole. The alternative is crediting minutes nobody pointed at, and
that error is invisible afterwards because the day still adds up.

### Where each one comes from

| Where | What it writes |
|---|---|
| Review queue on the dashboard | a rule, from the block's domain or app |
| **Rules** page builder | a rule, from a keyword or a single field |
| **Day** page, per row | an assignment, for that block only |
| Chrome extension | an assignment for the visit, then **offers** a rule |

The extension's two-step is worth explaining. Type a category and a client,
press **Assign this time**, and the visit so far is labelled. Then it asks:

> Next time you are on **app.instantly.ai/campaigns**, call it **Outreach
> ops** for **Hanval Metall** automatically?

Say yes and it writes the rule. Say *Just this once* and nothing else
changes. Assigning used to write the rule silently, which meant labelling one
afternoon quietly changed how every future afternoon was read.

---

## Writing a rule

**Rules** on the top bar has a sentence you fill in:

> When **anything** contains **keyword** call it **category** for **client**

"Anything" means the app, the window or file name, the site and the web
address, and it matches if any one of them does. That is the common case: a
client's name turns up in a window title on Monday, in a URL on Tuesday and
in a filename on Wednesday, and one rule should cover all three. Narrow it to
a single field from the dropdown when you need to be exact.

What you type is a **phrase**, not a pattern. `C++ Consulting`, `report
(draft)` and `a.b` all mean themselves. Tick the box under the sentence to
write a regular expression instead, for alternation and anchors.

That distinction exists because both failure modes are silent. `C++
Consulting` as a regex is invalid and disables the rule; `report (draft)` is
perfectly valid and quietly means something else. Either way a rule that
matches nothing looks exactly like a rule nothing has reached yet.

### The preview is the safety

A rule rewrites your whole history the moment you save it. That is the best
thing about this design and the most alarming: a keyword one letter too short
reassigns a month of work and nothing announces it.

So the form answers before it commits. As you type it measures the rule
against what is actually recorded:

> **8h 38m** across 38 blocks this month, 13% of everything recorded.

followed by six real blocks you can recognise. If the keyword is wide enough
to take time that already belongs to someone, it names them and the amount
first. The button stays shut until there is a figure on it.

### How rules compose

Rules are tried in ascending priority, then ascending id, and **every field
is claimed by the first rule that sets it**. They are not first-match-wins.

That matters more than it sounds. The starter rules say what *kind* of work a
site is; the rules you write say *whose* it is. Under first-match-wins the
starter rule would swallow the match and your label would silently do
nothing, which is the one failure that would stop you trusting the review
loop.

It also has a consequence worth planning around. Rules you write sit at
priority 20 and the starter category rules sit at 40 and 60, so a rule of
yours that sets a **category** outranks them for every block it matches. If
you write *anything containing Hanval is category "Client work"*, every
Hanval block becomes "Client work" and you lose the ability to see that
Hanval is 60% meetings and 10% email. Let the keyword set the **client** and
leave the category to the rules that already know what kind of work it was.

### Rules that match nothing

A rule with no pattern is dropped before classification, so it does nothing
at all while looking exactly like a rule nothing has reached yet. The store
refuses to create one, and the Rules page counts any that already exist,
flags each row in amber, and offers to remove them together.

---

## The Day page

The strip on the dashboard draws one rectangle per block, and a real day is
hundreds of them, most a pixel wide. **Day** is the same day as a list: when,
how long, what it was, what it is called, and a box to call it something
else. Each row assigns that block alone, without writing a rule.

A day is mostly four-second switches to Slack and back. A run of those folds
into one line that says how many and how long, and opens if you want to look.
The time stays in the totals either way; folding is a reading aid, never an
arithmetic one. **Unlabelled** narrows the list to what still needs a name.

---

## Removing time that was not work

The tracker records everything in front of you, which means it records the
hour you spent booking a holiday as readily as the hour you spent working.
**Through the day** on the dashboard is where you take that back.

Click any block on the strip and the panel opens filled with that block's own
span. Or press **Remove time** and type a window yourself. Either way it
tells you what is in that window before it will do anything:

> **1h 12m** across 9 blocks: youtube.com 48m, Spotify 21m, Messages 3m

The button stays dead until there is a figure on it, and the first press only
arms it.

What it does, exactly:

- Blocks inside the window are removed. Blocks that only overlap it are
  trimmed, so removing an hour out of the middle of an afternoon costs that
  hour and nothing else. A block that straddles the whole window survives as
  two, with the middle gone.
- Away time inside the window goes with it, so the day does not end up with
  idle periods belonging to work that no longer exists.
- Assignments over the window go too. One left hovering over an empty stretch
  would reattach itself to whatever got recorded there next.
- Interaction counts on a trimmed block are reduced by the same share, so a
  half-deleted visit does not keep a whole visit's keystrokes.
- Every total, chart, label and export is recomputed from what is left.

**It cannot be undone from the dashboard**, so the database is snapshotted
first to `data/backups/before-delete-<timestamp>.db`. A run of corrections
shares one snapshot, the state before you started rather than before your
last click, and the five most recent are kept.

Two things this is not. Not a way to hide time from someone else: it is your
machine and your database, and there is nobody to hide it from. And not how
you stop recording something in the first place: for an app or site that is
never work, put it in `excluded_apps` or `excluded_domains` and it is never
recorded again. Deleting is for what has already happened.

---

## Export

The **Export** panel on the dashboard takes a range, or two dates, and gives
you three things.

**CSV** is every block as a row: start, end, seconds, app, domain, title,
client, project, category and the interaction counts. This is the one to open
in a spreadsheet or turn into an invoice.

**Report** is one self-contained HTML file. No scripts, no stylesheet, no
images, nothing to fetch. It opens correctly in a year, on a machine that
never had this tracker, with no network. It carries the headline figures,
time across the period, and breakdowns by client, category, app and site,
using the same colours as the dashboard. Tick **Include every block** to
append the full detail table.

**PDF** is that same report through the browser's print dialogue: Cmd+P, Save
as PDF.

> That last one is a deliberate non-feature. Nothing in this project needs
> pip, which is what makes installing it on somebody else's Mac one command
> and no toolchain. No PDF library ships with macOS, so a real PDF writer
> would mean vendoring one or asking every install to grow a package manager.
> Browsers already contain an excellent PDF writer, and a page built for
> print goes through it at better typographic quality than a few hundred
> lines of stdlib would manage. The report carries a print stylesheet that
> drops it to black on white, sets page margins and keeps tables off page
> breaks.

Dates imply a custom range, so `?from=2026-11-04&to=2026-11-06` works on
every endpoint that takes a window, without also having to say
`range=custom`.

---

## Making the vocabulary yours

Open **Setup** on the top bar. Nothing in the taxonomy is fixed.

**Categories** are what kind of work a block is. Add, rename, recolour or
delete them. Renaming one re-labels your entire history in the same instant,
because classification is worked out when you look at it rather than stored
on the event, so a category you named badly in week one is a typing
correction rather than a migration.

**Clients** are whose work it is. Add them up front, or create one as you go
by labelling a block. Archive the ones you have finished with and they leave
the picker without taking their history with them.

**Undoing a label** is the one you will want soonest. Labelling in bulk is
one click, and so is getting it wrong. Every row says how many rules use it,
and offers two ways out:

- **Unlabel** takes the name off every rule *and every assignment* that uses
  it. The client or category itself stays, ready to be used properly. A rule
  that existed only to set that name goes; one that also set the other half
  keeps it.
- **Delete** does the same and removes the record too.

Neither touches a single recorded event.

**Starter packs** are optional bundles of rules for a kind of work: sales and
outreach, software, design, marketing, finance, legal. Turning one on only
adds. Turning it off takes back exactly the rules it added, and leaves behind
any of its categories you have since started using yourself.

What everybody gets without choosing anything is seven neutral categories
(Email, Meetings, Comms, Docs, AI & research, Admin, Break) matched only on
things that are on more or less every Mac. No version of this tool should
arrive on your machine already describing somebody else's job.

> Colours are eight palette slots rather than free hex, because each slot is
> defined once for light and once for dark. A hex that looked right in one
> would be unreadable in the other.

---

## The off switch

A pause stops **both** halves. The watcher does not probe, the extension does
not read which tab is in front, and the ingest endpoint refuses heartbeats
from an extension that has not caught up yet. Three ways in, all driving the
same state:

- **Dashboard** — the Pause button in the header: 30 minutes, 1 hour, 2
  hours, or until you turn it back on.
- **Chrome** — the same four choices in the extension popup. The toolbar icon
  carries an `off` badge for as long as it lasts.
- **Terminal** — works whether or not the agent is running:

```bash
./tracker.sh pause 30     # minutes
./tracker.sh pause off    # until resumed
./tracker.sh resume
./tracker.sh pause        # just report the current state
```

**Nothing at all is recorded, including the fact of the pause.** No event, no
away row, no marker. That is deliberate, and it has a price worth knowing: a
paused stretch is indistinguishable from the Mac having been shut, and turns
up as unaccounted time inside the day's span rather than as anything
explained. The daily reconciliation of active + away against the span does
not hold across one.

Because the data will never tell you a pause happened, the live indicators
are the only warning: a red banner across the dashboard, `paused` in the
header, the badge in Chrome, and a `warn` line at the top of `./doctor.sh`. A
pause survives a restart and a reboot on purpose, so an indefinite one really
does mean indefinite.

Pause is for the ad-hoc case. For things that should never be recorded at
all, `excluded_apps` and `excluded_domains` are better, because they need no
remembering.

---

## What the numbers mean

Worth knowing, because most trackers quietly get these wrong.

- **Idle is back-dated.** macOS reports how long ago your last input was, so
  when you cross the idle threshold the tracker knows you stopped three
  minutes ago, not now. The activity already recorded in that window is
  deleted rather than left as phantom work.
- **Sleep is not counted.** `time.monotonic()` stops while a Mac is suspended
  and the wall clock does not, so the difference between them is the sleep
  duration. Close the lid for an hour and that hour is recorded as a gap, not
  credited to whatever was frontmost.
- **A locked screen is away time**, back-dated the same way.
- **Resolution is one sample interval.** A switch between apps lands within 5
  seconds of when it happened. Totals have no gaps and no overlaps.
- **Browser intervals are clipped to desktop intervals**, so a tab left open
  while you were in another app counts for nothing.
- **Desktop and browser rows are never added together.** A browser event
  lives *inside* the desktop event for whichever browser was frontmost, so
  summing the two tables counts every minute in a tab twice. Everything you
  see is computed from blocks, which are the join, never from the raw rows.
- **Classification is computed at read time**, never stored, which is why
  editing a rule rewrites history.
- **Interaction counts are apportioned.** A tab's keystrokes are known for
  the whole visit, not per second, so when a visit is split across blocks the
  counts are divided by the share of time each piece keeps. The total is
  conserved and nothing is invented.
- **Only the browser reports interaction at all.** Desktop events carry no
  keystroke or click counts, so any metric weighted by them would
  systematically rate browser work as more engaged than work in an editor.

---

## Privacy

- Nothing leaves the machine. There is no telemetry and no sync.
- `excluded_apps` records that an app was in front but never its window
  title. 1Password and similar are excluded out of the box.
- `excluded_title_patterns` drops any title matching a regex.
- `excluded_domains` drops sites entirely.
- Query strings are stripped from URLs by default, since they carry tokens
  and search terms.
- The content script counts keystrokes. It never reads what you typed: four
  integers and a boolean are all that leave the page.
- Incognito windows are never reported.
- Every write endpoint checks the request origin, so a web page you happen to
  have open cannot create rules, delete categories or erase your week. It
  could never read anything, but a cross-origin `text/plain` POST skips the
  preflight most people assume protects them.
- The ingest endpoint rejects any request with an `http(s)` origin, so the
  same page cannot post fabricated activity into your database.

This is built for one person tracking themselves. Putting it on someone
else's machine makes it employee monitoring, with the consent and
proportionality obligations that come with that under GDPR.

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
| `min_event_seconds` | 2 | shorter switches are not kept as their own block |
| `review_min_seconds` | 60 | the floor for the review queue; shorter groups are still recorded, they just stop asking to be labelled |
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

**See `SETUP.md`** for the step-by-step sheet: commands, permissions, exact
dialogue paths, what to say to the person, and a printable checklist. Budget
10 minutes per Mac.

```bash
curl -fsSL https://raw.githubusercontent.com/kokka4/timetracker/main/bootstrap.sh | bash
```

Offline instead of a repo:

```bash
./make-release.sh      # a clean zip on your Desktop, with none of your data
```

The release is built from an allow-list, not an ignore-list, and refuses to
build if a database or log file would end up inside it. `bootstrap.sh` moves
aside any `tracker.db` that arrives with a download, so nobody inherits
anyone else's history and nothing is destroyed to achieve that.

Updating a machine later:

```bash
cd ~/timetracker && ./update.sh
```

The tool has no way to report to you, and that is deliberate. The moment it
does, this stops being a personal tool and becomes workplace monitoring,
which in the EU needs a lawful basis and a great deal more paperwork than a
Terminal command.

---

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

./tracker.sh pause 30    # stop recording for 30 minutes
./tracker.sh pause off   # stop until you resume
./tracker.sh resume
./tracker.sh purge 365   # drop old data
```

> `tracker.sh` exists so none of these has to be typed as
> `$(cat .python) -m tracker …`. `.python` holds the path to the interpreter
> this install uses, because the agent, the Accessibility grant and the
> command line all have to mean the same binary. But that substitution
> expands to nothing when the file is missing or you are in another
> directory, and the shell then complains about `-m`, which was never the
> problem. The wrapper finds the interpreter, falls back to `python3`, and
> says so plainly if there is none.

---

## Troubleshooting

**Dashboard will not load.** `./doctor.sh`. If nothing is listening, check
`logs/tracker.err.log`. Two usual causes: the port is taken (change `port` in
`config.json` and re-run `./install.sh`), or macOS is refusing the agent
access to the folder.

**`No module named tracker` in the log.** The agent could not read the
project directory. If the project sits under `~/Desktop`, `~/Documents` or
`~/Downloads`, that is why: macOS protects those folders and a background
agent is denied with no prompt, unlike your Terminal which you approved once.

```bash
mv ~/Desktop/timetracker ~/timetracker && cd ~/timetracker && ./install.sh
```

**All my time is credited to one app**, and **"By site" stays empty even
though the extension is loaded.** These are one fault, not two. Browser
intervals are clipped to desktop intervals where a browser was frontmost, so
if the watcher never reports Chrome, every tab interval is discarded at join
time. Run `./doctor.sh probe 20` and switch apps while it runs. It prints all
three frontmost-app sources side by side and names which ones follow your
focus.

The tracker prefers `osascript` for exactly this reason:
`NSWorkspace.frontmostApplication()` via pyobjc answers from a cache
refreshed by notifications that only arrive when a Cocoa run loop is pumping,
and a background script has no run loop, so it can return the app that was
frontmost at startup indefinitely without ever erroring. It is kept in the
probe as a diagnostic and is never used as a source.

**A dialog offers to install developer tools.** Something ran
`/usr/bin/python3`, `git`, `clang` or `make`. Cancel it. The installer never
runs those; check for Python with the `ls` command under [Install](#install).

**zsh: command not found.** The message names the missing thing after the
colon. `python3` means there is no interpreter: install the 78 MB python.org
package, not Xcode. `install.sh` or `doctor.sh` means the `./` was dropped;
zsh does not search the current directory. If `./install.sh` says *permission
denied* instead, run `chmod +x ~/timetracker/*.sh`.

**Everything says "Unlabelled".** Expected on day one. Use the review panel,
or write one keyword rule on the Rules page and watch the queue shrink.

**A rule I added does nothing.** Check the Rules page for an amber row saying
*no pattern, matches nothing*. If the rule has a pattern, check whether a
lower-priority rule is already claiming that field: rules compose field by
field, and the first to set a field wins it.

**Chrome time appears but no sites.** The extension is not loaded or not
reporting. Click its toolbar icon; the popup says whether it can reach the
tracker. It posts to `http://127.0.0.1:8734/api/ingest/chrome`; if you
changed the port, change it there too.

**The extension popup says it needs reloading.** Chrome reads popup HTML
fresh on every open but only re-evaluates the service worker when the
extension is reloaded, so after an update the new popup can be talking to an
old worker. Reload it at `chrome://extensions`.

**Titles are empty.** Accessibility is not granted, or granted to a different
Python than the agent runs. `./doctor.sh` prints the exact path to add.

**Numbers look too high after a break.** They should not; that is what the
back-dating is for. If they do, `idle_threshold_seconds` may be very large.

**Nothing recorded after a macOS update.** Permission grants sometimes reset.
Re-run `./doctor.sh` and re-grant.

---

## Why it is built this way

The decisions everything else follows from.

**Classification is computed when you look, never stored.** This is the
central one. A block carries an app, a title, a domain and a time; what it is
*called* is worked out from the rules at the moment you ask. Fix a rule today
and six months of history corrects itself. Most trackers label as they
record, so a wrong call stays wrong unless you go and edit every affected
row. This is why the review loop is worth doing: every correction compounds
backwards as well as forwards.

The cost is that a rule change is instantly global, which is exactly why the
rule builder shows you what a rule would claim before it exists.

**The desktop stream is the only thing that claims time.** The browser stream
labels time that already exists. This makes the browser half optional and
fallible without any risk to the totals, and it is why a tab left open in the
background counts for nothing.

**No dependencies, ever.** The tracker runs on the Python standard library
alone. That is what makes installing it on somebody else's Mac one command
with no toolchain, and it is the constraint that produced the HTML-report
approach to PDF, a hand-written dashboard with no framework, and an installer
that refuses to touch Apple's shims.

**Destructive things show you the figure first, then ask twice.** Deleting
time, deleting a rule, unlabelling a client. Each one previews what it will
affect, arms on the first press and acts on the second, and the only
irreversible one snapshots the database before it starts.

**Invariants live in the store, not in the callers.** A rule with no pattern
is refused by `add_rule` itself, not only by the HTTP layer, because an
invariant enforced by every caller separately is one a new caller will
forget, and this particular failure is silent by construction.

**Nothing can report upward.** There is no account, no server and no
mechanism to send a figure anywhere. That is not an omission to be filled in
later; it is the reason the thing is acceptable to run at all.

---

## Layout

```
config.json          your settings
bootstrap.sh         one-command install from a clean machine
install.sh           launch agent setup
tracker.sh           the command line: pause, resume, purge, status
doctor.sh            diagnostics
update.sh            refresh the code, keep the data
make-release.sh      a clean zip with none of your data in it
tracker/
  watcher.py         the sampling loop: idle, lock, sleep, back-dating
  macos.py           the probes, with three fallback layers
  ingest.py          browser heartbeats to intervals
  analytics.py       the desktop × browser join, and the rollups
  rules.py           classification: how a block is matched
  taxonomy.py        the catalogue: starter categories, packs, the upgrade
  report.py          the standalone HTML report
  pause.py           the off switch
  server.py          loopback HTTP: dashboard, API, ingest
  db.py              SQLite schema and writes
web/                 the dashboard (one page, no dependencies)
extension/           the Chrome extension
data/tracker.db      everything you have recorded
data/backups/        snapshots taken before installs and before deletions
logs/                stdout and stderr from the agent
```
