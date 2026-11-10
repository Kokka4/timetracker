"""What the categories are, as opposed to how they are matched.

The first version of this tracker shipped one person's job as its defaults:
instantly.ai meant "Outreach ops", clay.com meant "List building". That is
correct for a cold-email agency and wrong for everybody else, and worse, it was
invisible: a new user could not tell which categories were theirs to change and
which were the tool's opinion.

So the catalogue is split in two.

**Starter** is what every install gets, and it matches only on things that are
on more or less every Mac: Mail, Slack, a calendar, a browser, a video call,
Spotify. Nothing in it names an industry.

**Packs** are opt-in bundles for a kind of work. Applying one adds its
categories and rules on top; removing one takes back exactly what it added and
nothing else, which is why every rule carries a `source`. A pack never replaces
or edits anything, so a pack you try and dislike costs you nothing.

Both are starting points. Anything here can be renamed, recoloured or deleted,
and a rule you write from the review panel outranks everything in this file.

Colours are palette slots (`s1`..`s8`), not hex. The dashboard defines each
slot once for light and once for dark, so a stored slot stays legible in both
themes and a stored hex would not.
"""

from __future__ import annotations

from typing import Any

SLOTS = ("s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8")

# Priorities. Lower wins, and each field is claimed independently, so a pack
# rule can set the category of a block whose client came from one of yours.
#   20  rules you write from the review panel
#   40  breaks, which beat everything else claiming the same minutes
#   50  pack rules on a domain
#   65  pack rules on an app
#   60  starter rules on a domain
#   70  starter rules on an app
#   90  the catch-all for system apps
P_BREAK, P_PACK_DOMAIN, P_SITE, P_PACK_APP, P_APP, P_SYSTEM = 40, 50, 60, 65, 70, 90

STARTER_CATEGORIES: list[dict[str, Any]] = [
    {"name": "Email", "color": "s1", "sort_order": 10},
    {"name": "Meetings", "color": "s7", "sort_order": 20},
    {"name": "Comms", "color": "s5", "sort_order": 30},
    {"name": "Docs", "color": "s3", "sort_order": 40},
    {"name": "AI & research", "color": "s4", "sort_order": 50},
    {"name": "Admin", "color": "s6", "sort_order": 60},
    {"name": "Break", "color": "s2", "sort_order": 70},
]

STARTER_RULES: list[dict[str, Any]] = [
    {
        "priority": P_BREAK,
        "match_domain": r"(^|\.)(youtube\.com|netflix\.com|twitch\.tv|reddit\.com|"
        r"x\.com|twitter\.com|instagram\.com|tiktok\.com|hbomax\.com|facebook\.com)$",
        "category": "Break",
    },
    {
        "priority": P_SITE,
        "match_domain": r"(^|\.)(mail\.google\.com|outlook\.office\.com|"
        r"outlook\.live\.com|mail\.yahoo\.com|mail\.proton\.me|fastmail\.com)$",
        "category": "Email",
    },
    {
        "priority": P_SITE,
        "match_domain": r"(^|\.)(meet\.google\.com|zoom\.us|teams\.microsoft\.com|"
        r"whereby\.com|around\.co)$",
        "category": "Meetings",
    },
    {
        "priority": P_SITE,
        "match_domain": r"(^|\.)(slack\.com|discord\.com|web\.whatsapp\.com|"
        r"web\.telegram\.org)$",
        "category": "Comms",
    },
    {
        "priority": P_SITE,
        "match_domain": r"(^|\.)(docs\.google\.com|drive\.google\.com|"
        r"sheets\.google\.com|slides\.google\.com|notion\.so|dropbox\.com)$",
        "category": "Docs",
    },
    {
        "priority": P_SITE,
        "match_domain": r"(^|\.)(claude\.ai|chatgpt\.com|openai\.com|perplexity\.ai|"
        r"gemini\.google\.com|wikipedia\.org)$",
        "category": "AI & research",
    },
    {
        "priority": P_SITE,
        "match_domain": r"(^|\.)(calendar\.google\.com|outlook\.office\.com/calendar)$",
        "category": "Admin",
    },
    {
        "priority": P_APP,
        "match_app": r"^(Mail|Spark|Superhuman|Outlook|Airmail|Mimestream|Canary Mail)$",
        "category": "Email",
    },
    {
        "priority": P_APP,
        "match_app": r"^(zoom\.us|Zoom|Microsoft Teams|Google Meet|Webex|Around|"
        r"FaceTime)$",
        "category": "Meetings",
    },
    {
        "priority": P_APP,
        "match_app": r"^(Slack|Discord|Telegram|WhatsApp|Messages|Signal)$",
        "category": "Comms",
    },
    {
        "priority": P_APP,
        "match_app": r"^(Notion|Obsidian|Notes|Numbers|Pages|Keynote|Preview|"
        r"Microsoft Word|Microsoft Excel|Microsoft PowerPoint|Craft|Bear)$",
        "category": "Docs",
    },
    {
        "priority": P_APP,
        "match_app": r"^(Claude|ChatGPT|Ollama|LM Studio|Perplexity)$",
        "category": "AI & research",
    },
    {
        "priority": P_APP,
        "match_app": r"^(Spotify|Music|Photos|VLC|IINA|TV|Books)$",
        "category": "Break",
    },
    {
        "priority": P_SYSTEM,
        "match_app": r"^(Finder|System Settings|System Preferences|Activity Monitor|"
        r"Raycast|Alfred|Rectangle|CleanShot X|Screenshot|1Password)$",
        "category": "Admin",
    },
]


def _pack(key, name, blurb, categories, rules):
    return {
        "id": key,
        "name": name,
        "blurb": blurb,
        "categories": categories,
        "rules": rules,
    }


PACKS: list[dict[str, Any]] = [
    _pack(
        "sales",
        "Sales & outreach",
        "Sequencers, list building and CRMs. The original defaults of this tool.",
        [
            {"name": "Outreach ops", "color": "s2", "sort_order": 110},
            {"name": "List building", "color": "s4", "sort_order": 120},
            {"name": "CRM", "color": "s8", "sort_order": 130},
            {"name": "LinkedIn", "color": "s1", "sort_order": 140},
        ],
        [
            {
                "priority": P_PACK_DOMAIN,
                "match_domain": r"(^|\.)(instantly\.ai|lemlist\.com|smartlead\.ai|"
                r"woodpecker\.co|reply\.io)$",
                "category": "Outreach ops",
            },
            {
                "priority": P_PACK_DOMAIN,
                "match_domain": r"(^|\.)(clay\.com|apollo\.io|prospeo\.io|"
                r"phantombuster\.com|aimfox\.com|hunter\.io|zoominfo\.com)$",
                "category": "List building",
            },
            {
                "priority": P_PACK_DOMAIN,
                "match_domain": r"(^|\.)(salesforce\.com|hubspot\.com|pipedrive\.com|"
                r"close\.com|attio\.com|folk\.app)$",
                "category": "CRM",
            },
            {
                "priority": P_PACK_DOMAIN,
                "match_domain": r"(^|\.)linkedin\.com$",
                "category": "LinkedIn",
            },
        ],
    ),
    _pack(
        "software",
        "Software & engineering",
        "Editors and terminals, code review, and the hosting consoles.",
        [
            {"name": "Building", "color": "s6", "sort_order": 210},
            {"name": "Code review", "color": "s3", "sort_order": 220},
            {"name": "Infra", "color": "s7", "sort_order": 230},
        ],
        [
            {
                "priority": P_PACK_DOMAIN,
                "match_domain": r"(^|\.)(github\.com|gitlab\.com|bitbucket\.org)$",
                "category": "Code review",
            },
            {
                "priority": P_PACK_DOMAIN,
                "match_domain": r"(^|\.)(vercel\.com|supabase\.com|render\.com|"
                r"railway\.app|cloudflare\.com|console\.aws\.amazon\.com|"
                r"console\.cloud\.google\.com|fly\.io)$",
                "category": "Infra",
            },
            {
                "priority": P_PACK_APP,
                "match_app": r"^(Cursor|Code|Visual Studio Code|Xcode|iTerm2?|Terminal|"
                r"Warp|Ghostty|Hyper|Zed|Sublime Text|Nova|Docker|TablePlus|Postico|"
                r"IntelliJ IDEA|PyCharm|WebStorm|Android Studio)$",
                "category": "Building",
            },
        ],
    ),
    _pack(
        "design",
        "Design & creative",
        "Design tools, prototyping and the places assets come from.",
        [
            {"name": "Design", "color": "s5", "sort_order": 310},
            {"name": "Assets", "color": "s4", "sort_order": 320},
        ],
        [
            {
                "priority": P_PACK_DOMAIN,
                "match_domain": r"(^|\.)(figma\.com|framer\.com|penpot\.app)$",
                "category": "Design",
            },
            {
                "priority": P_PACK_DOMAIN,
                "match_domain": r"(^|\.)(dribbble\.com|behance\.net|unsplash\.com|"
                r"fonts\.google\.com|pexels\.com|iconfinder\.com)$",
                "category": "Assets",
            },
            {
                "priority": P_PACK_APP,
                "match_app": r"^(Figma|Sketch|Adobe Photoshop|Adobe Illustrator|"
                r"Adobe InDesign|Adobe After Effects|Adobe Premiere Pro|Affinity Photo|"
                r"Affinity Designer|Blender|Procreate|Pixelmator Pro)$",
                "category": "Design",
            },
        ],
    ),
    _pack(
        "marketing",
        "Marketing & content",
        "Ad managers, analytics, and the places content gets published.",
        [
            {"name": "Ads", "color": "s2", "sort_order": 410},
            {"name": "Analytics", "color": "s7", "sort_order": 420},
            {"name": "Content", "color": "s3", "sort_order": 430},
        ],
        [
            {
                "priority": P_PACK_DOMAIN,
                "match_domain": r"(^|\.)(ads\.google\.com|business\.facebook\.com|"
                r"ads\.tiktok\.com|ads\.linkedin\.com)$",
                "category": "Ads",
            },
            {
                "priority": P_PACK_DOMAIN,
                "match_domain": r"(^|\.)(analytics\.google\.com|posthog\.com|"
                r"mixpanel\.com|plausible\.io|search\.google\.com|ahrefs\.com|"
                r"semrush\.com)$",
                "category": "Analytics",
            },
            {
                "priority": P_PACK_DOMAIN,
                "match_domain": r"(^|\.)(wordpress\.com|webflow\.com|ghost\.org|"
                r"buffer\.com|hootsuite\.com|mailchimp\.com)$",
                "category": "Content",
            },
        ],
    ),
    _pack(
        "finance",
        "Finance & accounting",
        "Ledgers, payments and the reporting tools on top of them.",
        [
            {"name": "Bookkeeping", "color": "s6", "sort_order": 510},
            {"name": "Reporting", "color": "s8", "sort_order": 520},
        ],
        [
            {
                "priority": P_PACK_DOMAIN,
                "match_domain": r"(^|\.)(xero\.com|quickbooks\.intuit\.com|"
                r"netsuite\.com|stripe\.com|brex\.com|ramp\.com|wise\.com|"
                r"merit\.ee|e-arveldaja\.rik\.ee)$",
                "category": "Bookkeeping",
            },
            {
                "priority": P_PACK_DOMAIN,
                "match_domain": r"(^|\.)(looker\.com|tableau\.com|powerbi\.microsoft\.com|"
                r"metabase\.com|sigmacomputing\.com)$",
                "category": "Reporting",
            },
        ],
    ),
    _pack(
        "legal",
        "Legal",
        "Case research, drafting and signature.",
        [
            {"name": "Legal research", "color": "s7", "sort_order": 610},
            {"name": "Contracts", "color": "s1", "sort_order": 620},
        ],
        [
            {
                "priority": P_PACK_DOMAIN,
                "match_domain": r"(^|\.)(westlaw\.com|lexisnexis\.com|casetext\.com|"
                r"riigiteataja\.ee|eur-lex\.europa\.eu)$",
                "category": "Legal research",
            },
            {
                "priority": P_PACK_DOMAIN,
                "match_domain": r"(^|\.)(docusign\.net|docusign\.com|pandadoc\.com|"
                r"ironcladapp\.com|dokobit\.ee)$",
                "category": "Contracts",
            },
        ],
    ),
]

PACKS_BY_ID = {pack["id"]: pack for pack in PACKS}


def pack_source(pack_id: str) -> str:
    return f"pack:{pack_id}"


# The defaults this tool shipped before the catalogue was split. Recognised on
# upgrade so they can be swapped for the starter set and the two packs that
# cover the same ground, instead of sitting alongside them as duplicates.
# Matched on (match_app, match_domain, category) so a rule the user edited by
# hand is no longer recognised, and is therefore left alone.
LEGACY_SEED_KEYS: set[tuple[str, str, str]] = {
    ("", r"(^|\.)(youtube\.com|netflix\.com|twitch\.tv|reddit\.com|x\.com|"
         r"twitter\.com|instagram\.com|tiktok\.com|hbomax\.com)$", "Break"),
    ("", r"(^|\.)instantly\.ai$", "Outreach ops"),
    ("", r"(^|\.)(clay\.com|apollo\.io|prospeo\.io|phantombuster\.com|"
         r"aimfox\.com|lemlist\.com|smartlead\.ai)$", "List building"),
    ("", r"(^|\.)(mail\.google\.com|outlook\.office\.com|outlook\.live\.com)$", "Email"),
    ("", r"(^|\.)calendar\.google\.com$", "Admin"),
    ("", r"(^|\.)(docs\.google\.com|drive\.google\.com)$", "Docs"),
    ("", r"(^|\.)linkedin\.com$", "LinkedIn"),
    ("", r"(^|\.)(claude\.ai|chatgpt\.com|openai\.com|perplexity\.ai|"
         r"gemini\.google\.com)$", "AI work"),
    ("", r"(^|\.)slack\.com$", "Comms"),
    ("", r"(^|\.)(github\.com|vercel\.com|supabase\.com|render\.com|"
         r"railway\.app|cloudflare\.com)$", "Building"),
    (r"^(Slack|Discord|Zoom|zoom\.us|Microsoft Teams|Telegram|WhatsApp)$", "", "Comms"),
    (r"^(Cursor|Code|Visual Studio Code|Xcode|iTerm2?|Terminal|Warp|Ghostty|Hyper|"
     r"RevCode|Zed|Sublime Text|Docker|TablePlus|Postico)$", "", "Building"),
    (r"^(Claude|ChatGPT|Ollama|LM Studio)$", "", "AI work"),
    (r"^(Mail|Spark|Superhuman|Outlook)$", "", "Email"),
    (r"^(Notion|Obsidian|Notes|Numbers|Pages|Keynote|Preview|Microsoft Word|"
     r"Microsoft Excel|Microsoft PowerPoint)$", "", "Docs"),
    (r"^(Spotify|Music|Photos|VLC|IINA|TV)$", "", "Break"),
    (r"^(Finder|System Settings|System Preferences|Activity Monitor|Raycast|Alfred|"
     r"Rectangle|CleanShot X|Screenshot)$", "", "Admin"),
}

# Which packs an install carrying the old defaults should come up with, so the
# upgrade is a reorganisation rather than a loss of classification.
LEGACY_EQUIVALENT_PACKS = ("sales", "software")


def legacy_key(rule: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(rule.get("match_app") or ""),
        str(rule.get("match_domain") or ""),
        str(rule.get("category") or ""),
    )


# ---------------------------------------------------------------------------
# Setting a database up, and moving an old one over
# ---------------------------------------------------------------------------

SETUP_KEY = "taxonomy_version"
SETUP_VERSION = "2"


def slot_for(name: str) -> str:
    """A stable colour for a category we are discovering rather than defining.

    Derived from the name so the same category gets the same colour on every
    machine, and so re-running setup never shuffles the charts.
    """
    total = 0
    for char in name.casefold():
        total = (total * 31 + ord(char)) & 0xFFFFFFFF
    return SLOTS[total % len(SLOTS)]


def installed_packs(store) -> set[str]:
    prefix = "pack:"
    return {
        source[len(prefix):]
        for source in store.rule_sources()
        if source.startswith(prefix)
    }


def pack_list(store) -> list[dict[str, Any]]:
    counts = store.rule_sources()
    installed = installed_packs(store)
    out = []
    for pack in PACKS:
        out.append({
            "id": pack["id"],
            "name": pack["name"],
            "blurb": pack["blurb"],
            "categories": [c["name"] for c in pack["categories"]],
            "rule_count": len(pack["rules"]),
            "installed": pack["id"] in installed,
            "installed_rules": counts.get(pack_source(pack["id"]), 0),
        })
    return out


def apply_pack(store, pack_id: str) -> dict[str, Any]:
    pack = PACKS_BY_ID.get(pack_id)
    if pack is None:
        raise ValueError(f"no such pack: {pack_id}")
    source = pack_source(pack_id)
    if store.rule_sources().get(source):
        return {"ok": True, "already": True, "id": pack_id}

    for category in pack["categories"]:
        store.add_category(
            category["name"],
            color=category.get("color"),
            sort_order=category.get("sort_order", 100),
            source=source,
        )
    for rule in pack["rules"]:
        store.add_rule({**rule, "source": source})
    return {
        "ok": True,
        "id": pack_id,
        "rules_added": len(pack["rules"]),
        "categories_added": len(pack["categories"]),
    }


def remove_pack(store, pack_id: str) -> dict[str, Any]:
    pack = PACKS_BY_ID.get(pack_id)
    if pack is None:
        raise ValueError(f"no such pack: {pack_id}")
    source = pack_source(pack_id)
    removed = store.delete_rules_by_source(source)

    # A category the pack brought but which something else now uses, or which
    # has been renamed or recoloured since, is no longer the pack's to take
    # back. Only the untouched leftovers go.
    in_use = store.categories_in_use()
    dropped = 0
    for row in store.categories():
        if row.get("source") != source:
            continue
        if str(row["name"]).casefold() in in_use:
            continue
        store.delete_category(int(row["id"]))
        dropped += 1
    return {"ok": True, "id": pack_id, "rules_removed": removed,
            "categories_removed": dropped}


def _register_names_from_rules(store) -> dict[str, int]:
    """Make sure every name the rules mention exists as a record."""
    categories = clients = 0
    seen_categories = {c["name"].casefold() for c in store.categories()}
    seen_clients = {c["name"].casefold() for c in store.clients()}
    order = 1000
    for rule in store.rules(enabled_only=False):
        name = (rule.get("category") or "").strip()
        if name and name.casefold() not in seen_categories:
            store.add_category(name, color=slot_for(name), sort_order=order)
            seen_categories.add(name.casefold())
            categories += 1
            order += 10
        name = (rule.get("client") or "").strip()
        if name and name.casefold() not in seen_clients:
            store.add_client(name)
            seen_clients.add(name.casefold())
            clients += 1
    return {"categories": categories, "clients": clients}


def install_starter(store) -> None:
    for category in STARTER_CATEGORIES:
        store.add_category(
            category["name"],
            color=category["color"],
            sort_order=category["sort_order"],
            source="starter",
        )
    for rule in STARTER_RULES:
        store.add_rule({**rule, "source": "starter"})


def ensure(store, backup_dir=None) -> dict[str, Any]:
    """Bring a database up to the split catalogue. Runs once.

    Three cases, and the difference between them is the whole point:

    * **Fresh.** No rules at all, so install the starter set and stop. A new
      person gets categories that describe a working day, not an industry.
    * **The old defaults.** Rules that still exactly match what this tool used
      to ship. Those are swapped for the starter set plus the two packs that
      cover the same tools, so nothing stops being classified and nothing ends
      up duplicated. A rule that has been edited by hand no longer matches and
      is therefore left alone.
    * **Anything else.** Rules we did not write. Nothing is added or removed;
      the names already in use are simply registered so they can be managed.

    No recorded event is read or written by any of this.
    """
    if store.get_meta(SETUP_KEY) == SETUP_VERSION:
        return {"ran": False}

    existing = store.rules(enabled_only=False)
    summary: dict[str, Any] = {"ran": True, "backup": None}

    if existing and backup_dir is not None:
        # Taken before anything changes, and only when there is something to
        # lose. Rules are cheap to rebuild; the fact that someone might not
        # agree with how this went is what the file is for.
        import time as _time
        from pathlib import Path as _Path

        stamp = _time.strftime("%Y%m%d-%H%M%S")
        target = _Path(backup_dir) / f"pre-taxonomy-{stamp}.db"
        try:
            store.backup_to(target)
            summary["backup"] = str(target)
        except Exception as exc:  # a backup that fails must not block startup
            summary["backup_error"] = f"{type(exc).__name__}: {exc}"

    if not existing:
        install_starter(store)
        summary["case"] = "fresh"
    else:
        legacy = [r for r in existing if legacy_key(r) in LEGACY_SEED_KEYS]
        # Most of the old set still intact means these are defaults rather
        # than a coincidence. The threshold is deliberately high.
        if len(legacy) >= 12:
            for rule in legacy:
                store.delete_rule(int(rule["id"]))
            install_starter(store)
            for pack_id in LEGACY_EQUIVALENT_PACKS:
                apply_pack(store, pack_id)
            summary["case"] = "upgraded-from-defaults"
            summary["legacy_rules_replaced"] = len(legacy)
            summary["packs_applied"] = list(LEGACY_EQUIVALENT_PACKS)
        else:
            summary["case"] = "left-alone"

    summary["registered"] = _register_names_from_rules(store)
    store.set_meta(SETUP_KEY, SETUP_VERSION)
    return summary
