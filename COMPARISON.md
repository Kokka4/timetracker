# Two different products that both measure time

## This tracker, next to DeskTime

Everything said here about DeskTime comes from their own published page,
[What does DeskTime track][dt], read in November 2026. Where this tracker is
behind, it says so. The interesting part is not the feature count, it is that
the two tools are built for opposite people.

[dt]: https://desktime.com/what-does-desktime-track

---

## The difference that decides everything else

DeskTime is sold to a manager who wants visibility into other people. It has
an admin dashboard, an employee directory, shift scheduling, an absence
calendar, attendance management, per-team productivity settings, optional
screenshots and optional IP logging to show who is in the office. Those are
not accessories. They are the product, and they are why it exists as a
business.

This tracker is built for one person who wants visibility into themselves,
and it is deliberately incapable of reporting upward. There is no account, no
server, no sync, no telemetry and no mechanism to send a figure anywhere. The
HTTP server binds to `127.0.0.1`, which is never routed onto a network. A
colleague on the same wifi who types your address reaches their own machine.

That is not a setting that could be turned on later. It is the shape of the
thing. Everything below follows from it.

---

## Where the measurement is the same

Credit where it is due. On the mechanics of watching a Mac, the two are close
to level, and DeskTime's published limits are honest ones.

Both record which app is frontmost and for how long. Both record which site
is open and for how long. Both read window and document titles, so you can
tell one spreadsheet from another. Both start at unlock and stop at lock or
shutdown. Both pause after three minutes without input, which is the same
default, to the second.

DeskTime's "what we do not track" list is a good list: no GPS, no page
content, no screen video, no webcam, no audio, no keystroke or mouse content,
no remote access. All of that is true here too.

If you want a tool that measures a working day accurately, both do. The
question is what happens to the measurement afterwards.

---

## Five places this one is genuinely better

### 1. Fixing a mistake fixes the past

This is the architectural difference and it is not a small one.

Here, nothing is labelled when it is recorded. A block carries an app, a
title, a domain and a time; what it is *called* is computed from your rules
at the moment you look at it. Rename a category and your entire history
renames itself in the same instant. Add a rule today and the last six months
reclassify.

That turns correction from a chore into compound interest. Two minutes a day
for a week and most of your time classifies itself, because every correction
reaches backwards as well as forwards.

Trackers that stamp a label onto the event at record time cannot do that. A
wrong call stays wrong unless you go and edit every affected row, which
nobody does, which is why so many people's historical data quietly means
nothing.

### 2. You are shown the consequence before you commit

The flip side of read-time classification is that a rule change is instantly
global. A keyword one letter too short reassigns a month and nothing
announces it. So the rule builder answers before it acts. As you type:

> **8h 38m** across 38 blocks this month, 13% of everything recorded.

followed by six real blocks you can recognise, and, if the keyword is wide
enough to take time that already belongs to another client, a line naming
them and the amount. The button stays shut until there is a figure on it.

I have not seen this anywhere else in the category. The usual answer to
misclassification is a better editing screen, which treats the mistake as
inevitable. This treats it as preventable.

### 3. There are no screenshots, and there is no setting

DeskTime offers periodic screenshots. Optional, off by default, with optional
blurring, and genuinely useful to some teams.

This tracker cannot take one. There is no screenshot code in it. That is a
different claim from "we have it switched off", and it is the only version of
the claim that is worth anything to the person being tracked, because a
setting someone else controls is not a guarantee. The same is true of the
camera, the microphone, the screen and your location.

### 4. You can delete your own time

If an hour was personal, you remove it. The panel tells you what is in the
window first (*1h 12m across 9 blocks: youtube.com 48m, Spotify 21m*), takes
two presses, trims blocks that only partly overlap so removing an hour costs
exactly an hour, and snapshots the database first so a wrong window is
recoverable.

A tool sold to managers structurally cannot offer this, because the entire
proposition is that the employee cannot. That is not a criticism of DeskTime;
it is what their customers are buying. It is also why the two products cannot
converge.

### 5. The trust model is different in kind, not degree

DeskTime's security page is a serious answer to a serious question:
encryption in transit and at rest, optional 2FA, GDPR, ISO 27001 and ISO
27701, European servers, retention limits, deletion on request, a 99.95%
uptime claim. For a SaaS holding thousands of people's activity, that is
roughly the right set of commitments.

This tracker has none of them, because it has nothing to commit to. One
SQLite file, on your Mac, that no process sends anywhere. There is no breach
surface, no retention policy to trust, no subprocessor list, no transfer
mechanism and no vendor to outlive. Deletion on request is `rm`.

Certification is how you make an unavoidable risk acceptable. Not taking the
risk is better than certifying it.

---

## Two more, smaller but real

**Everything destructive shows the figure and asks twice.** Deleting time,
deleting a rule, unlabelling a client: each previews what it will affect,
arms on the first press, acts on the second, and the one irreversible action
snapshots the database before it starts.

**It installs in one command with no toolchain.** No pip, no Homebrew, no
Xcode, no Command Line Tools, no account. The whole thing runs on the Python
standard library. That constraint is why the PDF export is a print-ready HTML
page through the browser's own print engine rather than a vendored PDF
library: it is a better PDF, and it costs the install nothing.

---

## Where DeskTime is ahead, and it is a lot

An honest comparison has to include the part where you lose.

**Everything multi-user.** Admin dashboards, access controls, employee
directory, shift scheduling, absence calendar, attendance. This is most of
DeskTime, and this tracker has none of it, on purpose.

**Integrations.** Jira, Asana, Outlook, Google Calendar, GitLab, Trello,
Zapier, and a public API. Against that, this has a CSV export and an HTML
report.

**Offline and manual time.** DeskTime syncs with Outlook and Google Calendar
and lets you add time you spent away from the machine. This tracker only
knows what happened on the Mac, so an in-person meeting is invisible to it.
For anyone whose day includes real rooms, that is a genuine gap.

**Projects.** They have project time tracking. Here the field exists in the
schema and is not yet exposed.

**Productivity scoring.** DeskTime sorts apps and sites into productive,
unproductive and neutral and gives you a percentage. This tracker does not,
and that is a choice rather than a gap. A composite score invents a judgement
the data cannot support: the same hour in the same app is deep work or
avoidance depending on things no sampler can see. This reports and leaves the
conclusion to you.

**Cross-platform.** DeskTime covers Windows, Linux, macOS and mobile. This is
macOS and Chrome only.

**Operational maturity.** Backups, uptime, support, a roadmap, a team. This
is one person's tool with a test suite.

---

## So which one

If you are running a team and you need attendance, shifts, approvals and a
single place to see everyone, buy DeskTime. This tracker will never do that,
and anyone who tells you it could has not understood why it is acceptable to
run.

If you are one person who wants to know where your week went, and you would
like that answer to stay on your machine, the comparison looks different. You
get measurement at parity, correction that works backwards instead of
forwards, a preview before anything rewrites your history, no screenshots at
all, the ability to delete your own time, and a privacy story that needs no
certificate because it has no surface.

There is also a middle case worth naming, because it is the one most teams
actually face. If your people would accept a tracker on the condition that it
genuinely cannot report to you, this is that tracker, and the only way to
make the promise credible is for it to be structurally true. The moment a
tool can send your hours to a manager, every conversation about it becomes a
negotiation about trust. The moment it cannot, there is nothing to negotiate.

That is the whole argument. It is a smaller product, and for one person it is
a better one.

---

*Written against DeskTime's published feature page as of November 2026.
Features change; check theirs before quoting any of it back at anyone.*
