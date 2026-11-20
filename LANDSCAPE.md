# This tracker against ten commercial ones

As of 2026-11-11. Companion to `COMPARISON.md`, which takes DeskTime alone in
more depth. Feature claims are the vendors' own unless marked otherwise, and
prices move, so check before quoting any of them.

Seven of the ten are not competitors: they are payroll and shift-workforce
products that happen to record hours. Of the three that are in the same
business, this tracker beats all of them on classification, on honesty about
offline time, and on the fact that it cannot be turned into surveillance. It
loses on money: none of the time it records can be turned into an invoice,
which is the one gap worth closing.

---

## Most of the list is not the competition

The list mixes two industries. One group sells the answer to "how do I pay
forty hourly staff correctly and stay on the right side of the labour
inspectorate." The other sells the answer to "where did my week go." Only the
second group is in the same business, and there are three of them.

| Tool | What it actually sells | Competes? |
| --- | --- | --- |
| Paycom | Payroll. Punches, badges, biometrics, geofenced mobile clock-ins, overtime rules that update with federal and state law | No |
| Connecteam | Deskless field teams. GPS breadcrumbs, kiosk and NFC clock-in, shift scheduling, free to 10 users | No |
| Factorial | European HR suite. Clock-in for legal record keeping, absence and PTO, payroll, onboarding, performance reviews | No |
| Homebase | Hourly shift work. Rotas, shift trades, labour-to-sales forecasting, US payroll at $39/month plus $6 per head | No |
| QuickBooks Time | Getting hours into Intuit payroll and invoices. Kiosk, GPS, job costing, $8 to $10 per worker per month | No |
| Monitask | Surveillance with a timesheet attached. Screenshots on an interval, keystroke and click counts, IP and VPN location, mouse-jiggler detection, "insider threat" flagging | No, and not to imitate |
| Insightful | Surveillance at the analytics end. Up to 30 screenshots an hour, productivity scores, stealth mode on every tier | No, and not to imitate |
| **DeskTime** | Automatic desktop tracking with productivity scores, calendar sync, an AI daily summary | **Yes** |
| **Toggl Track** | Automatic background recording you promote into billable entries | **Yes** |
| **Clockify** | The same, cheaper, with a large free tier | **Yes** |

Comparing feature counts with the seven is meaningless. Paycom does not lose
on classification; it was never trying to classify anything.

One thing the seven do say: every one of them is sold per employee per month,
and four of the ten exist mainly to answer a regulator. A tracker for one
person who wants to know where their own week went is not a product anybody
on this list is building.

---

## Where this one is stronger

**Classification is retroactive, and nobody else's is.** This is the real
difference and none of the ten have it. Toggl lets you map a keyword in a
window title to a project, and what that buys is a notification asking
whether to start a timer. Ignore it and that time is unclassified forever
unless you hand-edit entries later. Clockify is the same shape: review the
day, promote activity into entries by hand. Here nothing is stored
classified, so a rule written today relabels every matching minute since
install. A fortnight of unlabelled work is one keyword away from being
labelled, not a fortnight of timesheet repair. For anyone who tracks first
and sorts later, which is everyone, that is the difference between a tracker
you keep and one you abandon in week three.

**Added time cannot inflate the day.** DeskTime, Toggl, Clockify and Monitask
all let you log offline time, and all store it as a row beside what was
recorded. Claim an hour for a call, have twenty minutes of it recorded
because you joined from your desk, and the day reads eighty minutes. Here an
entry is a claim over a window that fills only the parts with nothing in
them, so the day grows by forty and says it left twenty alone.

**Short switches stay in the arithmetic.** Clockify's own page says its
timeline hides anything under ten minutes, so a day of flicking between apps
leaves visible holes. Toggl ignores anything under ten seconds. This records
down to the configured minimum and folds the noise visually while keeping
every second in the total.

**There is no capacity for surveillance.** Insightful ships stealth mode on
all four tiers, the cheapest included, with up to thirty screenshots an hour.
Monitask counts keystrokes, logs IP and VPN, watches for mouse jigglers and
flags "activity that deviates from normal patterns." DeskTime takes
screenshots for when "integrity is in question." This has no screenshot code,
no keystroke capture, no manager role and no second account. That is not a
setting to flip; the capability is absent, and the source is there to prove
it.

**No productivity score.** DeskTime and Insightful both sort activity into
productive, unproductive and neutral and show a percentage. Nothing on a
screen tells you whether the thinking was any good.

**Removing time is first class.** Preview, clipping, splitting, a snapshot
before the delete. In the monitoring tools, not being able to remove time is
the product.

### Two places the claim is weaker than it looks

Be careful with "only this one is local." Both Toggl and Clockify keep the
raw auto-tracked stream on your own machine and upload only what you promote
into an entry, and both say so on their own pages. Clockify's words are that
tracked activity is "saved locally on your computer and only you can see
them," admins included. That is a good design and closer to this one than the
surveillance tools are.

What is still true: they require an account, the entries you promote do live
on their servers, syncing is on by default in Toggl, and the boundary is a
vendor policy that can move in a release. This has no account, no sync, no
vendor and nowhere else for the data to go. Say it that way rather than "they
upload everything," because on this point they are not the villains.

Second: the cost argument only holds for one person. Toggl Premium at $18 a
user, Insightful at $12, DeskTime and Clockify in between. Ten people on a
commercial tracker is real money a year, and this avoids all of it, except
that it cannot run ten people at all.

---

## What is missing

Three kinds of absence, and only one is a problem.

**Missing on purpose, and right to be.** Screenshots, keystroke counting,
stealth mode, productivity percentages, IP and VPN logging, mouse-jiggler
detection, insider-threat flagging, an admin who can see your screen. Every
one exists in at least one tool on the list.

**Missing because it is a different product.** GPS and geofencing, kiosks,
badges and biometrics, shift rotas and trades, PTO balances, payroll runs,
tax filing, labour-law compliance alerts, annual contracted-hours tracking.
Building any of them would be building a worse Homebase.

**Missing and it would actually bite**, in order:

1. **Money.** The tracker knows which client every minute belongs to and has
   no idea what any of it is worth. Toggl, Clockify, Monitask and QuickBooks
   all turn hours into an invoice.
2. **Projects in the interface.** They exist in the schema and nowhere else,
   so one client is one bucket whether it was the build or the reporting.
3. **Calendar.** DeskTime and Toggl read Outlook and Google Calendar and fill
   in time away from the desk. Manual time exists because that time was
   invisible; the calendar already knows most of it.
4. **A second device.** All ten have phone apps. This is one Mac.
5. **Anyone else.** No team rollup, no second account, no Windows, no Linux.
   Fine for a personal tool, a hard ceiling otherwise, and crossing that line
   is a rewrite rather than a feature.

Two smaller ones: there is no prompt when you come back from being away, so
idle time gets sorted out later rather than while you remember what it was;
and there are no outbound integrations, though the localhost API means
anything local can read it.

---

## Worth stealing

Ranked by value to a small agency, not by cleverness. Effort assumes the
patterns already in this codebase.

| # | Idea | From | Why | Effort |
| --- | --- | --- | --- | --- |
| 1 | A rate per client, and a tile saying what the week was worth | Toggl, Clockify, QuickBooks | Minutes are already attributed to clients; multiplying is the whole build. Turns the tracker into something that answers whether a retainer is profitable | Small |
| 2 | Retainer budgets with a burn-down | Homebase's scheduled-versus-actual, Toggl's project budgets | "This client is 8h a month and you have spent 11h" is the question an agency actually has | Small once rates exist |
| 3 | Calendar as a source of offline time | DeskTime, Toggl | Every meeting typed in by hand is already in the calendar. Offer each event as a pre-filled entry beside the gaps the Day page finds | Medium |
| 4 | A prompt when you come back | Toggl's idle flow | "You were away 42m from 14:10. Away, or was that the client call?" Catches it while you remember, and feeds the manual-time machinery | Small |
| 5 | Projects, surfaced | All ten | Already in the schema. Makes rates and budgets work per engagement | Small |
| 6 | An MCP over the database | DeskTime's AI summary, done properly | Theirs writes a paragraph. This would let Claude query the real data and answer whatever you ask | Medium |
| 7 | A grace period for flicks | Clockify's 20-second rule | Glance away and back inside 20 seconds and it is not a new activity. Cuts noise at the source | Small, but changes what gets stored |
| 8 | Software spend against actual use | Insightful | Time in each SaaS tool is already recorded. Cross it with subscription cost for cost per hour used | Medium |

If you do one, do the first. If you do two, do the first and second: together
they answer which clients are worth it, which this tracker is uniquely placed
to answer and currently cannot.

One caution on number three. Fetching a calendar would be the first outbound
network call this tracker has ever made, and the whole design rests on there
not being one. Reading the Mac's own calendar store locally keeps the property
intact; pulling a private `.ics` URL does not.

---

## What not to build

**Mobile.** All ten have an app. A phone app means a server to sync through,
which means an account, which means the data leaves the Mac, which is the one
property the whole thing is built on.

**A productivity score.** It would be the first number in the product that is
confidently wrong.

**Anything from the seven.** No rotas, no GPS, no PTO, no payroll. If those
are ever needed they will be bought, and bought from one of these companies.

**A team version**, unless it is a different product built on purpose.
Multi-user is a server, accounts, permissions, and the surveillance question
that can currently be answered by saying the capability does not exist.

---

## Sources

- [Toggl Track automated time tracker](https://toggl.com/track/automated-time-tracker/)
- [Clockify auto tracker](https://clockify.me/automatic-time-tracker)
- [DeskTime time tracking](https://desktime.com/features/time-tracking)
- [Insightful](https://www.insightful.io/discover/crozdesk), with [pricing as summarised by Jibble](https://www.jibble.io/reviews/insightful/insightful-pricing) (dated 2023, indicative only)
- [Monitask](https://www.monitask.com/)
- [Paycom Time and Attendance](https://www.paycom.com/software/time-and-attendance/)
- [Connecteam employee time tracking](https://connecteam.com/employee-time-tracking-app/)
- [Factorial, via Softguide](https://www.softguide.com/program/factorial-human-resources-software)
- [Homebase, via Fit Small Business](https://fitsmallbusiness.com/homebase-review/)
- [QuickBooks Time](https://quickbooks.intuit.com/time-tracking/)
- [Toggl and Clockify pricing, via Costbench](https://www.costbench.com/compare/toggl-track-vs-clockify/)
