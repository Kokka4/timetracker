# Setup sheet — installing on someone else's Mac

Written to be followed while standing at the machine. **Budget 10 minutes**, or
13 if Python has to be installed first.

No Xcode, no Command Line Tools, no Homebrew, no `pip`, no accounts. The only
thing the Mac must have that it might not is a Python interpreter, and that is
a 78 MB double-click.

Everything stays on that Mac. No account, no server, no data leaves the laptop.

---

## 0. Before you walk over

Have ready:

- The repo URL (or the zip from `./make-release.sh`)
- Chrome installed and signed in on their machine
- The person present for the first two minutes, so they can approve the
  permission dialogs with their own password

Decide where it goes. Default is `~/timetracker`. **Not** Desktop, Documents or
Downloads — macOS blocks background agents from reading those folders, and the
failure is silent.

Thirty seconds that can save you ten minutes — ask them to run this before you
arrive, or run it first thing:

```bash
ls -d /Library/Frameworks/Python.framework/Versions/*/bin/python3 \
      /opt/homebrew/bin/python3 /usr/local/bin/python3 2>/dev/null
```

A path means you are clear. No output at all means step 2 will need the
78 MB python.org package first.

> **Do not run `python3 --version` to check.** On a Mac without Apple's
> Command Line Tools, `/usr/bin/python3` is not Python — it is a stub whose
> only behaviour is to pop a dialog offering a download of over a gigabyte,
> which takes about fifteen minutes. The same is true of `git`, `clang` and
> `make`. The command above only looks at the filesystem, so it cannot
> trigger anything. The installer applies the same rule: it skips every
> `/usr/bin` stub rather than running one to see whether it works.

---

## 1. Open Terminal

`Cmd + Space` → type `Terminal` → Enter.

---

## 2. Run the installer

One command:

```bash
curl -fsSL https://raw.githubusercontent.com/kokka4/timetracker/main/bootstrap.sh | bash
```

<details>
<summary>If you brought a zip instead of using the repo</summary>

```bash
unzip ~/Downloads/timetracker-*.zip -d ~/
mv ~/timetracker-* ~/timetracker
cd ~/timetracker && chmod +x *.sh && ./install.sh
```
</details>

### If it stops and says there is no usable Python

The only thing this Mac is missing. **You do not need Xcode or the Command
Line Tools** — the installer no longer asks for them, and the download it does
need is 78 MB rather than over a gigabyte.

Check first, because plenty of Macs already have one somewhere — and check
without running anything:

```bash
ls -d /Library/Frameworks/Python.framework/Versions/*/bin/python3 \
      /opt/homebrew/bin/python3 /usr/local/bin/python3 2>/dev/null
```

If that prints a path, you are fine — re-run the installer, it searches
Homebrew, pyenv, Anaconda and python.org locations as well as PATH.

If not, install Python on its own:

```bash
curl -fsSL -o ~/Downloads/python.pkg \
  https://www.python.org/ftp/python/3.15.2/python-3.15.2-macos11.pkg
sudo installer -pkg ~/Downloads/python.pkg -target /
```

Takes about two minutes. Or download the same thing by hand from
<https://www.python.org/downloads/macos/> and double-click it.

Then run the `curl … | bash` command again. Nothing is lost.

> Apple's Command Line Tools (`xcode-select --install`) also work, and bring
> `git` with them, but they are a 1 GB+ download and install a whole developer
> toolchain on a machine that will never compile anything. Only worth it if
> that Mac is used for development anyway.

### What success looks like

```
  ✓ python 3.9.6 at /Library/Developer/CommandLineTools/usr/bin/python3
  ✓ no third-party packages needed
  ✓ dashboard port 8734
  ✓ launch agent written to /Users/NAME/Library/LaunchAgents/ai.leadprinter.timetracker.plist
  ✓ agent loaded — it will start automatically at every login
  ✓ dashboard live at http://127.0.0.1:8734
```

It is now tracking, and will restart by itself at every login forever.

---

## 3. Permissions

### 3a. Accessibility — optional, but do it

**What it buys:** window titles, so you see *which* document, repo or sheet,
not just "Chrome" or "Cursor". Without it, app-level tracking still works and
Chrome tab detail still arrives from the extension. Skip it on a machine where
the person is hesitant; everything else works.

First, get the exact path to add — it differs per machine:

```bash
cd ~/timetracker && ./doctor.sh
```

Look for the line that prints the Python path. Copy it.

Then:

1. **System Settings** → **Privacy & Security** → **Accessibility**
2. Click the **+** button
3. Press `Cmd + Shift + G` (a path box appears)
4. Paste the path from `doctor.sh`, press Enter
5. Select the file, click **Open**
6. Make sure its toggle is **on**
7. Back in Terminal, restart the agent:

```bash
launchctl kickstart -k gui/$(id -u)/ai.leadprinter.timetracker
```

> The permission is granted to a *binary*, not to the app, which is why you
> cannot just drag "timetracker" in. If macOS later updates Command Line
> Tools, this may need re-granting — `./doctor.sh` will say so.

### 3b. Full Disk Access — not needed

Only required if the project lives in Desktop/Documents/Downloads. Install it
in `~/timetracker` and skip this entirely.

---

## 4. Chrome extension

This is where most of the value is — roughly three quarters of a working day
happens in the browser.

1. Open Chrome, type `chrome://extensions` in the address bar, Enter
   *(it cannot be reached from a link — Chrome blocks that)*
2. Top right: turn **Developer mode** on
3. Click **Load unpacked** (top left)
4. Press `Cmd + Shift + G`, paste:
   ```
   ~/timetracker/extension
   ```
   Enter, then **Select**
   *(pick the `extension` folder itself, do not open it and choose a file)*
5. Click the puzzle-piece icon right of the address bar, find
   **Local Time Tracker Bridge**, click the pin

Chrome will say the extension can "read and change all your data on all
websites". That is the honest description of reading tab URLs and titles.
Nothing is sent anywhere but `127.0.0.1:8734` on their own machine.

---

## 5. Verify before you leave

Run these three. All three should pass.

```bash
cd ~/timetracker
./doctor.sh
```
Expect `✓ server answering`, `✓ frontmost app detected`, and either
`✓ window titles working` or a `warn` if you skipped Accessibility.

```bash
./doctor.sh probe 15
```
**Switch between Chrome, Terminal and another app while this runs.** The
`osascript` column must change as you switch. If it reports `STUCK`, stop and
do not leave it in that state — every minute would be credited to one app.

Finally, open **http://timetrack.localhost:8734**
(**http://127.0.0.1:8734** works too, and is the fallback if a browser
does not honour `.localhost`).

**The very first load is a black screen.** It states that the data stays on
their machine, waits five seconds, then enables a **Continue** button. It
cannot be clicked past, and it never appears again on that Mac. It is not a
page that failed to load, and it is worth letting them read it rather than
reaching over to click Continue for them.

Then confirm:

- The green dot top-left is lit
- An app name and a rising timer appear top-right
- Clicking the pinned extension icon shows **connected**
- After a minute of browsing, **By site** starts filling in

---

## 6. What to tell the person

Say this plainly — it is their machine and their data:

- It records which app and which browser tab is in front, and for how long
- It records window titles and page URLs, but **never** page content or
  keystrokes (only how many, never which)
- Incognito windows are never recorded
- All of it lives in one file on their Mac: `~/timetracker/data/tracker.db`
- Nothing is uploaded; there is no account and no server
- They can see everything at http://timetrack.localhost:8734
- They can exclude any app or site by editing `config.json`
- **They can switch it off whenever they like**, from the Pause button in the
  dashboard header or from the extension icon: 30 minutes, 1 hour, 2 hours, or
  until they turn it back on. Nothing is recorded while it is off, not even
  the fact that it was off
- They can stop it for good at any time: `cd ~/timetracker && ./uninstall.sh`
- Deleting everything recorded: `./reset.sh`

Show them the Pause button before you leave, and watch them use it once. It is
the thing that makes the rest of this liveable, and a tracker somebody cannot
switch off is one they quietly uninstall instead.

### Then spend two minutes in Setup

The top bar has three pages: **Dashboard**, **Setup** and **Rules**. Setup is
what makes it their tracker rather than yours. Open it and do three things
with them:

1. **Turn on the pack that matches their work.** Sales and outreach, software,
   design, marketing, finance, legal. It only adds rules, and turning it off
   later takes back exactly what it added.
2. **Add their clients.** Two minutes of typing now saves a fortnight of
   "Unlabelled".
3. **Rename anything that is not how they talk.** A category rename re-labels
   their whole history instantly, so there is no cost to getting it right.

Out of the box everyone gets seven neutral categories (Email, Meetings, Comms,
Docs, AI & research, Admin, Break) matched on things every Mac has. Nobody
inherits anybody else's job.

**Rules** is the third page: every match the tracker has learned, where each
one came from, and a search box. Rules are read when you look, not when the
block was recorded, so deleting a wrong one corrects the history it produced
as well as everything it would have caught later.

Show them **Unlabel** in Setup while you are there. It is on every category
and client, and it strips that label off everything it was ever applied to
without touching a single recorded block. It is the undo for the most common
mistake on day one, which is attributing a whole week to one client by
accident.

If you want the numbers from them, they export and send them. The tool has no
way to report to you, and that is deliberate — the moment it does, this stops
being a personal tool and becomes workplace monitoring, which in the EU needs
a lawful basis and a lot more paperwork than a Terminal command.

Worth offering up front: **add their own private stuff to the exclude list
now**, while you are sitting there. In `config.json`:

```json
"excluded_apps": ["1Password", "Messages", "FaceTime"],
"excluded_domains": ["bank.ee", "personal-site.com"]
```

Then `launchctl kickstart -k gui/$(id -u)/ai.leadprinter.timetracker`.

---

## 7. When it goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `No usable Python 3.9+` | No interpreter on the machine | Install the 78 MB python.org package (step 2), re-run. Not Xcode. |
| A dialog offers to install developer tools | Something ran `/usr/bin/python3`, `git`, `clang` or `make`, which are stubs | Cancel it. The installer never runs those. Check for Python with the `ls` command in step 0 instead |
| `could not download …codeload…` | Repo is private, or branch is not `main` | Make it public, or use the zip from `make-release.sh` |
| `Bootstrap failed: 5: Input/output error` | launchd race after an uninstall | Wait 10s, run `./install.sh` again |
| `port 8734 is already in use` | Something else has it | Edit `"port"` in `config.json`, re-run `./install.sh`, and update the endpoint in the extension popup |
| Dashboard says "not answering" | Agent failed to start | `tail -20 logs/tracker.err.log` |
| `No module named tracker` in the log | Agent cannot read the folder | It is in Desktop/Documents/Downloads — move it: `mv ~/Desktop/timetracker ~/timetracker && cd ~/timetracker && ./install.sh` |
| Nothing is recorded at all, dashboard shows a red banner | It is paused | Resume from the dashboard, the extension icon, or `./tracker.sh resume`. `./doctor.sh` says so in a `warn` at the top |
| All time credited to one app | Frontmost-app probe stuck | `./doctor.sh probe 20` and send me the output |
| Titles empty | Accessibility not granted, or granted to a different Python | `./doctor.sh` prints the exact path to add |
| "By site" empty but extension loaded | Desktop side never reports Chrome | Run the probe — this is the same fault as the row above |
| Chrome nags about developer mode each launch | Unpacked extensions always do | Unavoidable until the extension is published to the Web Store ($5 one-off, unlisted) |

Useful commands:

```bash
cd ~/timetracker
./doctor.sh                 # full health check
./doctor.sh status          # raw JSON state
tail -f logs/tracker.err.log
launchctl kickstart -k gui/$(id -u)/ai.leadprinter.timetracker   # restart
```

---

## 8. Updating later

One command. Data and rules survive untouched:

```bash
cd ~/timetracker && ./update.sh
```

Re-running the full installer is equally safe and does the same job:

```bash
curl -fsSL https://raw.githubusercontent.com/kokka4/timetracker/main/bootstrap.sh | bash
```

Worth putting in the group chat whenever you ship a change.

### Their history is backed up on every install

Each run of `install.sh` snapshots the database to
`data/backups/tracker-YYYYMMDD-HHMMSS.db` before touching anything, keeping
the five most recent. It uses SQLite's online backup API rather than copying
the file, so writes still sitting in the write-ahead log are included.

To restore one:

```bash
cd ~/timetracker
launchctl bootout gui/$(id -u)/ai.leadprinter.timetracker
cp data/backups/tracker-20261110-120000.db data/tracker.db
rm -f data/tracker.db-wal data/tracker.db-shm
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.leadprinter.timetracker.plist
```

If a database arrives inside a download — someone else's, from a zip — the
installer moves it to `data/inherited-<timestamp>.db` rather than deleting it,
so that install starts from zero without anything being destroyed.

---

## 9. Removing it

```bash
cd ~/timetracker && ./uninstall.sh
```

Stops the agent and removes it from login. Their data file is left in place —
delete `~/timetracker` by hand to remove everything. The Chrome extension is
removed at `chrome://extensions`, and the Accessibility entry in System
Settings → Privacy & Security → Accessibility.

---

## Per-machine checklist

Print this bit.

```
[ ] Checked for Python with ls, NOT with python3 --version
[ ]   -> if none, install the 78 MB python.org pkg (not Xcode)
[ ] Terminal open
[ ] curl … | bash
[ ] ✓ dashboard live at http://timetrack.localhost:8734
[ ] ./doctor.sh                       -> no failures
[ ] Accessibility granted + agent restarted      (optional)
[ ] chrome://extensions -> Developer mode -> Load unpacked -> ~/timetracker/extension
[ ] Extension pinned, popup shows "connected"
[ ] ./doctor.sh probe 15  -> app column changes when switching apps
[ ] Dashboard shows a live timer and a rising "By site"
[ ] Exclusions added to config.json for anything private
[ ] Welcome screen read, Continue pressed by them
[ ] Showed them Pause, and watched them pause and resume once
[ ] Setup -> turned on the pack that matches their work
[ ] Setup -> added their clients
[ ] Showed them Unlabel, the undo for labelling the wrong thing in bulk
[ ] Explained what is recorded, and how to stop it
```
