"""Classification: turn a raw block into (client, project, category).

Classification is computed at query time, never stored on the event. Editing a
rule therefore reclassifies the whole history, which is what makes the review
loop worth doing: every correction you make compounds backwards as well as
forwards.

A rule matches when *every* pattern it sets matches its field (AND). Rules are
tried in ascending `priority`, then ascending `id`, and all patterns are
case-insensitive.

Matching rules *compose*, field by field: the first rule to set a client wins
the client, the first to set a category wins the category, and they need not be
the same rule. This matters more than it sounds. The starter rules say what
kind of work a site is ("instantly.ai is outreach ops"); the rules you add from
the review panel say whose work it is ("instantly.ai is Hanval"). Under
first-match-wins the starter rule would swallow the match and your label would
silently do nothing, which is the one failure that would make you stop trusting
the review loop.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

FIELDS = ("app", "title", "domain", "url")

# `match_any` is checked against all four and matches if any one of them
# does. The four named fields AND together, which is exactly right for "this
# app, showing this title" and useless for "anything mentioning Hanval",
# because a client's name turns up in a window title on Monday, in a URL on
# Tuesday and in a filename on Wednesday.
ANY_FIELD = "any"


def as_pattern(raw: str, mode: str) -> str:
    """What actually gets compiled.

    A phrase is escaped. Without this, `C++`, `(draft)` and `a.b` are either
    invalid patterns, which disable the rule, or valid ones that match the
    wrong thing — and both failures are silent, because a rule that matches
    nothing looks exactly like a rule nobody has reached yet.
    """
    return re.escape(raw) if mode == "text" else raw

# Starter rules, inserted once into an empty database. These label *categories*
# only. Client labels are yours to add, and the dashboard's review panel writes
# them for you one click at a time.
SEED_RULES: list[dict[str, Any]] = [
    # Breaks first, so they beat anything else that might claim the same time.
    {
        "priority": 40,
        "match_domain": r"(^|\.)(youtube\.com|netflix\.com|twitch\.tv|reddit\.com|"
        r"x\.com|twitter\.com|instagram\.com|tiktok\.com|hbomax\.com)$",
        "category": "Break",
    },
    {"priority": 60, "match_domain": r"(^|\.)instantly\.ai$", "category": "Outreach ops"},
    {
        "priority": 60,
        "match_domain": r"(^|\.)(clay\.com|apollo\.io|prospeo\.io|phantombuster\.com|"
        r"aimfox\.com|lemlist\.com|smartlead\.ai)$",
        "category": "List building",
    },
    {
        "priority": 60,
        "match_domain": r"(^|\.)(mail\.google\.com|outlook\.office\.com|outlook\.live\.com)$",
        "category": "Email",
    },
    {"priority": 60, "match_domain": r"(^|\.)calendar\.google\.com$", "category": "Admin"},
    {
        "priority": 60,
        "match_domain": r"(^|\.)(docs\.google\.com|drive\.google\.com)$",
        "category": "Docs",
    },
    {"priority": 60, "match_domain": r"(^|\.)linkedin\.com$", "category": "LinkedIn"},
    {
        "priority": 60,
        "match_domain": r"(^|\.)(claude\.ai|chatgpt\.com|openai\.com|perplexity\.ai|"
        r"gemini\.google\.com)$",
        "category": "AI work",
    },
    {"priority": 60, "match_domain": r"(^|\.)slack\.com$", "category": "Comms"},
    {
        "priority": 60,
        "match_domain": r"(^|\.)(github\.com|vercel\.com|supabase\.com|render\.com|"
        r"railway\.app|cloudflare\.com)$",
        "category": "Building",
    },
    {
        "priority": 70,
        "match_app": r"^(Slack|Discord|Zoom|zoom\.us|Microsoft Teams|Telegram|WhatsApp)$",
        "category": "Comms",
    },
    {
        "priority": 70,
        "match_app": r"^(Cursor|Code|Visual Studio Code|Xcode|iTerm2?|Terminal|Warp|"
        r"Ghostty|Hyper|RevCode|Zed|Sublime Text|Docker|TablePlus|Postico)$",
        "category": "Building",
    },
    {"priority": 70, "match_app": r"^(Claude|ChatGPT|Ollama|LM Studio)$", "category": "AI work"},
    {"priority": 70, "match_app": r"^(Mail|Spark|Superhuman|Outlook)$", "category": "Email"},
    {
        "priority": 70,
        "match_app": r"^(Notion|Obsidian|Notes|Numbers|Pages|Keynote|Preview|"
        r"Microsoft Word|Microsoft Excel|Microsoft PowerPoint)$",
        "category": "Docs",
    },
    {"priority": 70, "match_app": r"^(Spotify|Music|Photos|VLC|IINA|TV)$", "category": "Break"},
    {
        "priority": 90,
        "match_app": r"^(Finder|System Settings|System Preferences|Activity Monitor|"
        r"Raycast|Alfred|Rectangle|CleanShot X|Screenshot)$",
        "category": "Admin",
    },
]

UNCLASSIFIED = "Unlabelled"


class Rule:
    """A compiled rule. Invalid patterns disable the rule rather than crash."""

    __slots__ = (
        "id",
        "priority",
        "patterns",
        "anywhere",
        "mode",
        "client",
        "project",
        "category",
        "error",
    )

    def __init__(self, row: dict[str, Any]):
        self.id = int(row.get("id") or 0)
        self.priority = int(row.get("priority") or 100)
        self.client = row.get("client") or None
        self.project = row.get("project") or None
        self.category = row.get("category") or None
        self.error: str | None = None
        self.patterns: dict[str, re.Pattern[str]] = {}
        self.anywhere: re.Pattern[str] | None = None
        self.mode = "text" if str(row.get("match_mode") or "regex") == "text" else "regex"

        for field in FIELDS + (ANY_FIELD,):
            raw = row.get(f"match_{field}")
            if not raw:
                continue
            try:
                compiled = re.compile(as_pattern(str(raw), self.mode), re.IGNORECASE)
            except re.error as exc:
                self.error = f"{field}: {exc}"
                self.patterns = {}
                self.anywhere = None
                break
            if field == ANY_FIELD:
                self.anywhere = compiled
            else:
                self.patterns[field] = compiled

    @property
    def usable(self) -> bool:
        return self.error is None and (bool(self.patterns) or self.anywhere) and bool(
            self.client or self.project or self.category
        )

    def matches(self, signature: dict[str, Any]) -> bool:
        # The named fields AND: every one the rule sets has to match.
        for field, pattern in self.patterns.items():
            value = signature.get(field)
            if not value or not pattern.search(str(value)):
                return False
        # `any` ORs: one hit anywhere is enough. A rule may set both, in
        # which case the keyword narrows an already specific rule rather
        # than widening it.
        if self.anywhere is not None:
            for field in FIELDS:
                value = signature.get(field)
                if value and self.anywhere.search(str(value)):
                    return True
            return False
        return True


def compile_rules(rows: Iterable[dict[str, Any]]) -> list[Rule]:
    rules = [Rule(row) for row in rows]
    rules.sort(key=lambda r: (r.priority, r.id))
    return [r for r in rules if r.usable]


def classify(rules: list[Rule], signature: dict[str, Any]) -> dict[str, Any]:
    """Fill client, project and category from the matching rules, in order.

    Each field is claimed by the first matching rule that sets it, so a narrow
    client rule and a broad category rule can both apply to the same block.
    """
    client: str | None = None
    project: str | None = None
    category: str | None = None
    contributors: list[int] = []

    for rule in rules:
        if client and project and category:
            break
        if not rule.matches(signature):
            continue
        used = False
        if client is None and rule.client:
            client, used = rule.client, True
        if project is None and rule.project:
            project, used = rule.project, True
        if category is None and rule.category:
            category, used = rule.category, True
        if used:
            contributors.append(rule.id)

    return {
        "client": client,
        "project": project,
        "category": category or UNCLASSIFIED,
        "rule_ids": contributors,
    }


def rule_from_signature(
    signature: dict[str, Any],
    client: str | None = None,
    project: str | None = None,
    category: str | None = None,
    scope: str = "auto",
    priority: int = 20,
) -> dict[str, Any]:
    """Build an exact-match rule from a block the user just labelled.

    `scope` picks which field anchors the rule:
      domain -> every page on that host
      app    -> every window of that app
      title  -> that app plus that exact window title
      url    -> that one page
      auto   -> domain if there is one, else app
    """
    domain = signature.get("domain")
    app = signature.get("app")
    url = signature.get("url")
    title = signature.get("title")

    if scope == "auto":
        scope = "domain" if domain else "app"

    rule: dict[str, Any] = {
        "priority": priority,
        "client": client,
        "project": project,
        "category": category,
    }

    if scope == "domain" and domain:
        rule["match_domain"] = f"^{re.escape(str(domain))}$"
    elif scope == "url" and url:
        rule["match_url"] = f"^{re.escape(str(url))}$"
    elif scope == "title" and app and title:
        rule["match_app"] = f"^{re.escape(str(app))}$"
        rule["match_title"] = re.escape(str(title))
    elif app:
        rule["match_app"] = f"^{re.escape(str(app))}$"
    elif domain:
        rule["match_domain"] = f"^{re.escape(str(domain))}$"
    else:
        raise ValueError("nothing in this block to match on")

    return rule
