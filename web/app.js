/* Dashboard. No external requests: every byte here is served from your own
   machine, and the charts are hand-drawn SVG rather than a CDN library. */

"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";

/* Categorical slots are used in this order and no other: the palette's
   colourblind separation was validated on *adjacent* slot pairs, so skipping
   or cycling them quietly breaks that guarantee. */
const SLOT_NAMES = ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8"];
const SLOTS = SLOT_NAMES.map((name) => `var(--${name})`);

const LIVE_RANGES = new Set(["today", "week", "this_month", "month"]);

const state = {
  range: "today",
  summary: null,
  status: null,
  labels: { clients: [], categories: [], projects: [], colors: {} },
  taxonomy: null,
  rules: [],
  ruleSearch: "",
  ruleSource: "all",
  view: "dashboard",
  day: { date: null, blocks: [], filter: "all" },
};

/* -- small helpers ------------------------------------------------------ */

const $ = (id) => document.getElementById(id);

function h(tag, props = {}, kids = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "style") Object.assign(node.style, value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const kid of [].concat(kids)) {
    if (kid) node.appendChild(typeof kid === "string" ? document.createTextNode(kid) : kid);
  }
  return node;
}

function s(tag, props = {}, kids = []) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined) continue;
    if (key === "style") Object.assign(node.style, value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const kid of [].concat(kids)) if (kid) node.appendChild(kid);
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

function dur(seconds) {
  const total = Math.max(0, Math.round(seconds || 0));
  if (total < 60) return `${total}s`;
  let hours = Math.floor(total / 3600);
  let minutes = Math.round((total % 3600) / 60);
  if (minutes === 60) { hours += 1; minutes = 0; }
  if (hours && minutes) return `${hours}h ${minutes}m`;
  if (hours) return `${hours}h`;
  return `${minutes}m`;
}

function durShort(seconds) {
  const total = Math.max(0, Math.round(seconds || 0));
  if (total === 0) return "0";
  if (total < 3600) return `${Math.round(total / 60)}m`;
  const hours = total / 3600;
  return `${hours % 1 === 0 ? hours : hours.toFixed(1)}h`;
}

function pct(share) {
  return `${Math.round((share || 0) * 100)}%`;
}

function clock(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function hashString(text) {
  let value = 0;
  for (let i = 0; i < text.length; i += 1) value = (value * 31 + text.charCodeAt(i)) | 0;
  return Math.abs(value);
}

/* Colour follows the key, never its size, so a quiet day does not repaint
   yesterday's chart.

   A category that has been given a colour in Settings keeps it everywhere and
   always, which is the point of letting people choose one. Everything else —
   apps, sites, clients, and categories nobody has picked for — is handed the
   remaining slots in order, because the palette's colourblind separation was
   validated on adjacent pairs and hashing into it would break that. Ordering
   is by a hash of the name rather than by size, so the assignment is the same
   on Monday as on Friday. */
function assignSlots(keys) {
  const colors = (state.labels && state.labels.colors) || {};
  const map = new Map();
  const taken = new Set();

  /* A stored colour is honoured unless something already drawn in this chart
     has it. Past eight categories the palette has to repeat somewhere, and a
     chart with two identical greens in it is unreadable however correct the
     swatches in Settings are, so the series that asks second is moved. */
  for (const key of keys) {
    const at = SLOT_NAMES.indexOf(colors[key]);
    if (at >= 0 && !taken.has(at)) {
      map.set(key, SLOTS[at]);
      taken.add(at);
    }
  }

  const rest = keys
    .filter((key) => !map.has(key))
    .sort((a, b) => (hashString(a) % 9973) - (hashString(b) % 9973) || a.localeCompare(b));
  let pool = SLOTS.map((_, i) => i).filter((i) => !taken.has(i));
  if (!pool.length) pool = SLOTS.map((_, i) => i);
  rest.forEach((key, i) => map.set(key, SLOTS[pool[Math.min(i, pool.length - 1)]]));
  return map;
}

/* -- tooltip ------------------------------------------------------------ */

const tip = $("tip");

function showTip(event, lines) {
  clear(tip);
  for (const line of lines) {
    if (!line) continue;
    const row = h("div");
    if (Array.isArray(line)) {
      row.appendChild(h("span", { class: "r", text: `${line[0]} ` }));
      row.appendChild(h("span", { class: "v", text: line[1] }));
    } else {
      row.appendChild(h("b", { text: line }));
    }
    tip.appendChild(row);
  }
  tip.hidden = false;
  moveTip(event);
}

function moveTip(event) {
  const pad = 14;
  const box = tip.getBoundingClientRect();
  let x = event.clientX + pad;
  let y = event.clientY + pad;
  if (x + box.width > window.innerWidth - 8) x = event.clientX - box.width - pad;
  if (y + box.height > window.innerHeight - 8) y = event.clientY - box.height - pad;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}

function hideTip() { tip.hidden = true; }

function hoverable(node, lines) {
  node.addEventListener("mouseenter", (e) => showTip(e, lines));
  node.addEventListener("mousemove", moveTip);
  node.addEventListener("mouseleave", hideTip);
}

/* -- axis --------------------------------------------------------------- */

const TICK_STEPS = [60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 14400, 21600, 43200, 86400];

function axisTicks(max) {
  const step = TICK_STEPS.find((candidate) => max / candidate <= 5) || 86400;
  const top = Math.max(step, Math.ceil(max / step) * step);
  const ticks = [];
  for (let value = 0; value <= top + 1e-6; value += step) ticks.push(value);
  return { top, ticks };
}

/* -- stacked column chart ----------------------------------------------- */

function trimEmptyEnds(buckets, data, minimum = 6) {
  /* An hourly chart that starts at midnight spends half its width on hours
     nobody was awake for. Empty *days* in a week view are information, so this
     only ever runs on the hourly view. */
  const totals = buckets.map((_, b) => data.reduce((sum, row) => sum + (row[b] || 0), 0));
  let first = totals.findIndex((v) => v > 0);
  let last = totals.length - 1 - [...totals].reverse().findIndex((v) => v > 0);
  if (first < 0) return { buckets, data };

  while (last - first + 1 < minimum) {
    if (last < buckets.length - 1) last += 1;
    else if (first > 0) first -= 1;
    else break;
  }
  return {
    buckets: buckets.slice(first, last + 1),
    data: data.map((row) => row.slice(first, last + 1)),
  };
}

function columnChart(host, series, granularity) {
  clear(host);
  let buckets = series.buckets || [];
  const keys = series.keys || [];
  let data = series.data || [];

  if (!buckets.length || !keys.length) {
    host.appendChild(h("div", { class: "empty", text: "Nothing recorded in this range yet." }));
    return;
  }

  if (granularity === "hour") {
    ({ buckets, data } = trimEmptyEnds(buckets, data));
  }

  const slots = assignSlots(keys);
  /* Stack in palette order, so adjacent segments of a column are adjacent
     slots: that is the pairing the palette's colourblind separation was
     actually validated on. Derived from the assigned colours rather than from
     a list of category names, which is what made the old ordering a fixed
     opinion about whose job this tool was for. */
  const slotRank = (key) => {
    const at = SLOTS.indexOf(slots.get(key));
    return at < 0 ? SLOTS.length : at;
  };
  const order = keys.slice().sort(
    (a, b) => slotRank(a) - slotRank(b) || a.localeCompare(b)
  );

  const totals = buckets.map((_, b) => keys.reduce((sum, _k, k) => sum + (data[k][b] || 0), 0));
  const grand = totals.reduce((a, b) => a + b, 0);
  if (grand <= 0) {
    host.appendChild(h("div", { class: "empty", text: "Nothing recorded in this range yet." }));
    return;
  }

  const width = Math.max(320, host.clientWidth || 880);
  const height = 236;
  const pad = { top: 18, right: 6, bottom: 28, left: 48 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;

  // A little headroom, so the tallest bar never touches the top gridline and
  // its total label always has somewhere to sit.
  const { top, ticks } = axisTicks(Math.max(...totals) * 1.08);
  const scale = (value) => (value / top) * innerH;
  const band = innerW / buckets.length;
  const barW = Math.max(3, Math.min(48, band * 0.55));
  const baseY = pad.top + innerH;
  const GAP = 2;

  const svg = s("svg", {
    width, height, viewBox: `0 0 ${width} ${height}`,
    role: "img", "aria-label": "Time per bucket, stacked by category",
  });

  // Recessive grid, drawn first so marks sit on top of it.
  for (const value of ticks) {
    const y = baseY - scale(value);
    svg.appendChild(s("line", {
      x1: pad.left, x2: width - pad.right, y1: y, y2: y,
      style: { stroke: value === 0 ? "var(--axis)" : "var(--grid)", strokeWidth: "1" },
    }));
    svg.appendChild(s("text", {
      x: pad.left - 8, y: y + 4, "text-anchor": "end",
      style: { fill: "var(--ink-muted)", fontSize: "11px", fontVariantNumeric: "tabular-nums" },
    }, [document.createTextNode(durShort(value))]));
  }

  const labelEvery = Math.ceil(buckets.length / 12);

  buckets.forEach((bucket, b) => {
    const x = pad.left + band * b + (band - barW) / 2;
    let stacked = 0;

    const drawn = order
      .map((key) => ({ key, value: data[keys.indexOf(key)][b] || 0 }))
      .filter((entry) => entry.value > 0);

    drawn.forEach((entry, index) => {
      const isTop = index === drawn.length - 1;
      const full = scale(entry.value);
      const y = baseY - stacked - full;
      // A 2px surface gap separates segments; the data-end keeps its height
      // and gets the 4px rounding.
      const drawH = isTop ? full : Math.max(1, full - GAP);
      const radius = isTop ? Math.min(4, drawH / 2, barW / 2) : 0;

      const rect = s("rect", {
        class: "seg",
        x, y, width: barW, height: Math.max(1, drawH),
        rx: radius, ry: radius,
        style: { fill: slots.get(entry.key) },
      });
      hoverable(rect, [
        bucket.weekday && buckets.length > 12 ? `${bucket.weekday} ${bucket.label}` : bucket.label,
        [entry.key, dur(entry.value)],
        ["share of bucket", pct(entry.value / (totals[b] || 1))],
      ]);
      svg.appendChild(rect);
      stacked += full;
    });

    if (totals[b] > 0 && buckets.length <= 12) {
      svg.appendChild(s("text", {
        x: x + barW / 2, y: baseY - stacked - 7, "text-anchor": "middle",
        style: { fill: "var(--ink-2)", fontSize: "11px", fontWeight: "600", fontVariantNumeric: "tabular-nums" },
      }, [document.createTextNode(durShort(totals[b]))]));
    }

    if (b % labelEvery === 0) {
      const short = bucket.label.length === 10
        ? `${bucket.weekday} ${Number(bucket.label.slice(8, 10))}`
        : bucket.label.slice(0, 5);
      svg.appendChild(s("text", {
        x: x + barW / 2, y: height - 9, "text-anchor": "middle",
        style: { fill: "var(--ink-muted)", fontSize: "11px", fontVariantNumeric: "tabular-nums" },
      }, [document.createTextNode(short)]));
    }
  });

  host.appendChild(svg);
  renderLegend(order, slots);
}

function renderLegend(keys, slots) {
  const host = clear($("legend"));
  if (keys.length < 2) return;
  for (const key of keys) {
    host.appendChild(h("span", {}, [
      h("i", { style: { background: slots.get(key) } }),
      document.createTextNode(key),
    ]));
  }
}

/* -- day strip ---------------------------------------------------------- */

function dayStrip(host, timeline, window_, categoryKeys) {
  clear(host);
  if (!timeline.length) {
    host.appendChild(h("div", { class: "empty", text: "No activity recorded for this day." }));
    return;
  }

  const slots = assignSlots(categoryKeys);
  const dayStart = window_.start_ts;
  const firstHour = Math.floor((Math.min(...timeline.map((t) => t.start)) - dayStart) / 3600);
  const lastHour = Math.ceil((Math.max(...timeline.map((t) => t.end)) - dayStart) / 3600);
  const from = dayStart + Math.max(0, firstHour) * 3600;
  const to = dayStart + Math.min(24, Math.max(lastHour, firstHour + 1)) * 3600;
  const span = Math.max(1, to - from);

  const width = Math.max(320, host.clientWidth || 880);
  const height = 78;
  const pad = { left: 4, right: 4 };
  const innerW = width - pad.left - pad.right;
  const rowY = 14;
  const rowH = 36;
  const scale = (ts) => pad.left + ((ts - from) / span) * innerW;

  const clipId = `strip-clip-${Math.random().toString(36).slice(2)}`;
  const svg = s("svg", {
    width, height, viewBox: `0 0 ${width} ${height}`,
    role: "img", "aria-label": "Activity through the day",
  });

  const defs = s("defs");
  defs.appendChild(s("clipPath", { id: clipId }, [
    s("rect", { x: pad.left, y: rowY, width: innerW, height: rowH, rx: 5, ry: 5 }),
  ]));
  svg.appendChild(defs);

  svg.appendChild(s("rect", {
    x: pad.left, y: rowY, width: innerW, height: rowH, rx: 5, ry: 5,
    style: { fill: "var(--wash)" },
  }));

  const group = s("g", { "clip-path": `url(#${clipId})` });
  for (const item of timeline) {
    const x = scale(Math.max(item.start, from));
    const x2 = scale(Math.min(item.end, to));
    if (x2 <= x) continue;
    const rect = s("rect", {
      class: "seg",
      x, y: rowY, width: Math.max(1, x2 - x), height: rowH,
      style: { fill: slots.get(item.category) || SLOTS[0] },
    });
    hoverable(rect, [
      `${clock(item.start)} – ${clock(item.end)}`,
      [item.app, dur(item.seconds)],
      item.label !== item.app ? ["", item.label] : null,
      item.title ? ["", item.title.slice(0, 90)] : null,
      item.client ? ["client", item.client] : ["category", item.category],
      ["", "click to remove this time"],
    ]);
    rect.classList.add("pickable");
    rect.addEventListener("click", () => openRemove(item.start, item.end));
    group.appendChild(rect);
  }
  svg.appendChild(group);

  const hours = Math.round(span / 3600);
  const every = hours > 14 ? 2 : 1;
  for (let i = 0; i <= hours; i += every) {
    const ts = from + i * 3600;
    const x = scale(ts);
    svg.appendChild(s("line", {
      x1: x, x2: x, y1: rowY + rowH + 2, y2: rowY + rowH + 6,
      style: { stroke: "var(--axis)", strokeWidth: "1" },
    }));
    svg.appendChild(s("text", {
      x, y: height - 4,
      "text-anchor": i === 0 ? "start" : i + every > hours ? "end" : "middle",
      style: { fill: "var(--ink-muted)", fontSize: "11px", fontVariantNumeric: "tabular-nums" },
    }, [document.createTextNode(clock(ts))]));
  }

  host.appendChild(svg);
}

/* -- bar tables --------------------------------------------------------- */

function barTable(host, rows, options = {}) {
  clear(host);
  if (!rows || !rows.length) {
    host.appendChild(h("div", { class: "empty", text: options.empty || "Nothing here yet." }));
    return;
  }
  const max = Math.max(...rows.map((row) => row.seconds), 1);
  const slots = options.slots;
  // A category below the chart's series cap is folded into "Other" there, so
  // it gets a neutral swatch rather than borrowing slot 1's blue — otherwise
  // several different categories would all read as the same colour.
  const colourFor = (key) => (slots && slots.get(key)) || "var(--axis)";

  const table = h("table", { class: "bars" });
  table.appendChild(h("thead", {}, [
    h("tr", {}, [
      h("th", { text: options.heading || "Name" }),
      h("th", { text: "" }),
      h("th", { text: "Time" }),
      h("th", { text: "Share" }),
    ]),
  ]));

  const body = h("tbody");
  for (const row of rows) {
    const charted = Boolean(slots && slots.get(row.key));
    const fill = slots ? colourFor(row.key) : "var(--s1)";
    const name = h("div", { class: "k" }, [
      slots
        ? h("span", {
            class: `swatch${charted ? "" : " folded"}`,
            style: { background: fill },
            title: charted ? row.key : `${row.key} — shown inside "Other" in the chart`,
          })
        : null,
      h("b", { text: row.key, title: row.key }),
    ]);
    const track = h("div", { class: "track" }, [
      h("i", { style: { width: `${Math.max(2, (row.seconds / max) * 100)}%`, background: fill } }),
    ]);
    body.appendChild(h("tr", {}, [
      h("td", {}, [name]),
      h("td", {}, [track]),
      h("td", { class: "t", text: dur(row.seconds) }),
      h("td", { class: "pct", text: pct(row.share) }),
    ]));
  }
  table.appendChild(body);
  host.appendChild(table);
}

/* -- tiles -------------------------------------------------------------- */

function renderTiles(summary) {
  const host = clear($("tiles"));
  const window_ = summary.window;
  const days = Math.max(1, window_.days);
  const topClient = (summary.by_client || []).find(
    (row) => row.key !== "(unlabelled)" && row.key !== "Other"
  );
  const away = summary.away || {};

  const tiles = [
    {
      label: window_.days === 1 ? "Active time" : `Active time, last ${days} days`,
      value: dur(summary.total_seconds),
      sub: window_.days === 1
        ? window_.start_date
        : `${dur(summary.total_seconds / days)} a day on average`,
    },
    {
      label: "Attributed to a client",
      value: pct(summary.client_share),
      sub: `${dur(summary.client_seconds)} of ${dur(summary.total_seconds)}`,
    },
    {
      label: "Biggest client",
      value: topClient ? topClient.key : "—",
      sub: topClient
        ? `${dur(topClient.seconds)}, ${pct(topClient.share)} of tracked time`
        : "Label something below to populate this",
    },
    {
      // Counted only between the first and last thing you did each day, so
      // it means "breaks", not "hours the Mac spent switched off overnight".
      label: window_.days === 1 ? "Away during the day" : "Away during work hours",
      value: dur(away.total),
      sub: summary.span && summary.span.seconds
        ? `of ${dur(summary.span.seconds)} from first to last`
        : "Nothing recorded",
      detail: [
        away.idle ? `${dur(away.idle)} idle` : null,
        away.locked ? `${dur(away.locked)} locked` : null,
        away.gap ? `${dur(away.gap)} asleep` : null,
      ].filter(Boolean).join(", "),
    },
  ];

  for (const tile of tiles) {
    const cell = h("div", { class: "tile" }, [
      h("div", { class: "label", text: tile.label }),
      h("div", { class: "value", text: tile.value, title: tile.value }),
      h("div", { class: "sub", text: tile.sub }),
    ]);
    if (tile.detail) {
      cell.appendChild(h("div", { class: "detail", text: tile.detail }));
    }
    host.appendChild(cell);
  }
}

/* -- review queue ------------------------------------------------------- */

/* When a group happened, which is how you actually remember whose work it
   was. One day gets a clock range; several get the span of days, because
   "Mon to Wed" is the useful fact and the hours within each are not. */
function whenText(group) {
  if (!group.first_ts) return "";
  const from = new Date(group.first_ts * 1000);
  const to = new Date(group.last_ts * 1000);
  const hhmm = (d) => d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const dayName = (d) => d.toLocaleDateString([], { weekday: "short", day: "numeric" });

  if ((group.day_count || 1) <= 1) {
    const today = new Date().toDateString() === from.toDateString();
    const label = today ? "" : `${dayName(from)} `;
    return `${label}${hhmm(from)}–${hhmm(to)}`;
  }
  /* No day count on the end: the span already says it recurred, and the
     block count beside it says how often. The column is narrow and the
     clock times across a week are not the thing you are remembering. */
  return `${dayName(from)} – ${dayName(to)}`;
}

function renderReview(summary) {
  const host = clear($("review"));
  const groups = summary.unlabelled || [];
  const floor = summary.review_min_seconds || 0;

  if (!groups.length) {
    // "Everything is attributed" is only good news when there was something
    // to attribute. On an empty day it reads as a false all-clear.
    host.appendChild(h("div", {
      class: "empty",
      text: summary.block_count
        ? `Nothing left worth labelling in this range${
            floor ? ` (anything under ${dur(floor)} is left out)` : ""
          }.`
        : "No activity recorded in this range.",
    }));
    return;
  }

  /* The one thing stopping this tool answering the question it exists for is
     having no clients, and the place to add them was buried two sections
     down behind a Show button. Say so here, where the empty boxes are. */
  if (!(state.labels.clients || []).length) {
    const prompt = h("div", { class: "review-hint" }, [
      h("b", { text: "No clients yet. " }),
      document.createTextNode(
        "Type one into any client box below and press Label: it is created as "
        + "you go. Or add them all at once in "
      ),
    ]);
    const link = h("button", { class: "linkish", text: "Setup" });
    link.addEventListener("click", async () => {
      await showView("setup");
      setTimeout(() => $("client-new").focus(), 120);
    });
    prompt.appendChild(link);
    prompt.appendChild(document.createTextNode("."));
    host.appendChild(prompt);
  }

  for (const group of groups) {
    const what = h("div", { class: "what" }, [
      h("b", {
        text: group.domain || group.title || group.app,
        title: group.url || group.title || group.app,
      }),
      h("small", { text: `${group.app}, ${group.category}` }),
    ]);

    const context = h("div", { class: "ctx" });
    if (group.context && group.context.length) {
      context.appendChild(h("em", { text: "around it: " }));
      context.appendChild(document.createTextNode(
        group.context.map((entry) => `${entry.client} ${dur(entry.seconds)}`).join(", ")
      ));
    } else {
      context.appendChild(h("em", { text: "no labelled work nearby" }));
    }

    const clientInput = h("input", {
      type: "text", list: "known-clients", placeholder: "client (type to add)",
      "aria-label": `Client for ${group.domain || group.app}`,
    });
    const categoryInput = h("input", {
      type: "text", list: "known-categories", placeholder: "category",
      "aria-label": `Category for ${group.domain || group.app}`,
    });

    /* How far the rule reaches, spelled out with the actual names. "this
       app" leaves you guessing whether you are teaching the tracker about
       every Claude window or only this one, and that is the difference
       between labelling once and labelling ninety times. */
    const short = (text, max) => {
      const value = String(text || "");
      return value.length > max ? `${value.slice(0, max - 1)}…` : value;
    };
    const scope = h("select", {
      "aria-label": "How far this rule should reach",
      title: "How far this rule reaches: everything under that name, or only this one window or page",
    });
    if (group.domain) {
      scope.appendChild(h("option", {
        value: "domain", text: `all of ${short(group.domain, 20)}`,
      }));
    }
    scope.appendChild(h("option", {
      value: "app", text: `all of ${short(group.app, 20)}`,
    }));
    if (group.title) {
      scope.appendChild(h("option", { value: "title", text: "only this window" }));
    }
    if (group.url) {
      scope.appendChild(h("option", { value: "url", text: "only this page" }));
    }

    const button = h("button", { class: "primary", text: "Label" });
    const submit = async () => {
      const client = clientInput.value.trim();
      const category = categoryInput.value.trim();
      if (!client && !category) {
        clientInput.focus();
        return;
      }
      button.disabled = true;
      button.textContent = "…";
      try {
        await api("/api/label", {
          signature: {
            app: group.app, domain: group.domain,
            title: group.title, url: group.url,
          },
          client: client || null,
          category: category || null,
          scope: scope.value,
        });
        await refresh();
      } catch (error) {
        button.disabled = false;
        button.textContent = "Label";
        note(`Could not save that rule: ${error.message}`);
      }
    };
    button.addEventListener("click", submit);
    for (const input of [clientInput, categoryInput]) {
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") submit();
      });
    }

    host.appendChild(h("div", { class: "review-row" }, [
      what,
      h("div", { class: "t" }, [
        h("b", { text: dur(group.seconds) }),
        h("small", { text: whenText(group) }),
      ]),
      h("div", { class: "pct" }, [
        document.createTextNode(`${group.blocks} block${group.blocks === 1 ? "" : "s"}`),
        group.blocks > 1 && group.longest
          ? h("small", { text: `longest ${dur(group.longest)}` })
          : null,
      ].filter(Boolean)),
      context,
      clientInput,
      categoryInput,
      h("div", { style: { display: "flex", gap: "6px" } }, [scope, button]),
    ]));
  }
}

/* -- rules -------------------------------------------------------------- */

/* What a rule looks for, in the fewest words that are still exact.
   A keyword rule reads as a sentence; a pattern rule shows the pattern,
   because that is the thing you would need to edit. */
const MATCH_LABELS = {
  app: "app", title: "window", domain: "site", url: "address",
};

function describe(rule) {
  if (rule.match_any) {
    return rule.match_mode === "text"
      ? `anything containing “${rule.match_any}”`
      : `anything matching ${rule.match_any}`;
  }
  const parts = ["app", "title", "domain", "url"]
    .filter((field) => rule[`match_${field}`])
    .map((field) => `${MATCH_LABELS[field]} ~ ${rule[`match_${field}`]}`);
  return parts.join("  &  ");
}

function isDead(rule) {
  return !["app", "title", "domain", "url", "any"]
    .some((field) => rule[`match_${field}`]);
}

function ruleOrigin(rule) {
  const source = rule.source || "user";
  if (source === "starter") return "starter";
  if (source.startsWith("pack:")) return "pack";
  return "user";
}

const RULE_GROUPS = [
  ["user", "Yours", "Written by labelling a block. These outrank everything else."],
  ["pack", "From starter packs", "Turn a pack off in Setup to remove its rules together."],
  ["starter", "Starter", "The universal defaults every install begins with."],
];

async function renderRules() {
  clear($("rules"));
  const payload = await api("/api/rules", null, "GET");
  state.rules = payload.rules || [];
  paintDeadRules(payload.dead || 0);
  paintRules();
}

/* A rule with no pattern is dropped before classification, so it does
   nothing at all while looking exactly like a rule nothing has reached yet.
   Saying so once, with a way to clear them, beats eleven blank rows. */
function paintDeadRules(count) {
  const host = clear($("dead-rules"));
  host.hidden = !count;
  if (!count) return;

  host.appendChild(h("b", { text:
    `${count} rule${count === 1 ? "" : "s"} here ${count === 1 ? "has" : "have"} no pattern.` }));
  host.appendChild(document.createTextNode(
    ` ${count === 1 ? "It matches" : "They match"} nothing and ` +
    `${count === 1 ? "has" : "have"} never labelled anything.`
  ));
  const sweep = armedButton("Remove them", "Remove them?", "danger", async () => {
    const result = await api("/api/rules/dead", {});
    note(`Removed ${result.removed} rule${result.removed === 1 ? "" : "s"} that matched nothing.`);
    await renderRules();
    await refresh();
  }, "Delete every rule that carries no pattern");
  host.appendChild(sweep);
}

function paintRules() {
  const host = clear($("rules"));
  const all = state.rules || [];
  const needle = (state.ruleSearch || "").trim().toLowerCase();
  const wanted = state.ruleSource || "all";

  const rules = all.filter((rule) => {
    if (wanted !== "all" && ruleOrigin(rule) !== wanted) return false;
    if (!needle) return true;
    // The raw fields as well as the description: the row now says "site"
    // where the column is called domain, and someone who thinks in the
    // older vocabulary should still find their rule.
    return [
      describe(rule), rule.client, rule.category, rule.project,
      rule.match_app, rule.match_title, rule.match_domain, rule.match_url,
      rule.match_any,
      rule.match_domain ? "domain" : null,
      rule.match_url ? "url" : null,
      rule.match_title ? "title" : null,
    ].filter(Boolean).join(" ").toLowerCase().includes(needle);
  });

  $("rule-count").textContent = rules.length === all.length
    ? `${all.length}`
    : `${rules.length} of ${all.length}`;

  if (!all.length) {
    host.appendChild(h("div", { class: "empty", text: "No rules yet." }));
    return;
  }
  if (!rules.length) {
    host.appendChild(h("div", { class: "empty", text: "Nothing matches that filter." }));
    return;
  }

  /* Grouped by where a rule came from, because that is the question you are
     asking when you open this page: which of these did I write, and which
     arrived with the tool? */
  for (const [key, title, blurb] of RULE_GROUPS) {
    const mine = rules.filter((rule) => ruleOrigin(rule) === key);
    if (!mine.length) continue;
    if (wanted === "all") {
      host.appendChild(h("div", { class: "rule-group-head" }, [
        document.createTextNode(title),
        h("small", { text: `${mine.length}, ${blurb}` }),
      ]));
    }
    for (const rule of mine) host.appendChild(ruleRow(rule));
  }
}

function ruleRow(rule) {
  {
    const toggle = h("input", {
      type: "checkbox", "aria-label": "Rule enabled",
      ...(rule.enabled ? { checked: "checked" } : {}),
    });
    toggle.addEventListener("change", async () => {
      await api(`/api/rules/${rule.id}/toggle`, { enabled: toggle.checked });
      await renderRules();
      await refresh();
    });

    // Deleting a rule relabels every block it was classifying, right then.
    // That is worth one confirming press.
    const remove = armedButton("Delete", "Delete?", "danger", async () => {
      await api(`/api/rules/${rule.id}`, null, "DELETE");
      await renderRules();
      await refresh();
    }, "Delete this rule and relabel whatever it was claiming");

    // Client and category were the same grey pill, so a row read as two
    // interchangeable words when it is actually "whose" and "what kind".
    const labels = h("div", { class: "rule-labels" }, [
      rule.client ? h("span", { class: "pill who", text: rule.client }) : null,
      rule.project ? h("span", { class: "pill what", text: rule.project }) : null,
      rule.category ? h("span", { class: "pill what", text: rule.category }) : null,
    ]);

    const dead = isDead(rule);
    const what = dead
      ? h("span", { class: "rule-dead", text: "no pattern, matches nothing" })
      : h("code", { text: describe(rule), title: describe(rule) });

    const row = h("div", {
      class: `rule-row${rule.enabled ? "" : " off"}${dead ? " dead" : ""}`,
      // Priority decides who wins a disagreement, which is worth knowing and
      // not worth a column of "p20" on every row.
      title: `Priority ${rule.priority}. Lower numbers are consulted first.`,
    }, [what, labels, toggle, remove]);
    return row;
  }
}

/* -- notices ------------------------------------------------------------ */

function renderNotices(status) {
  const host = clear($("notices"));
  if (!status) {
    host.appendChild(h("div", { class: "banner" }, [
      h("b", { text: "The tracker is not answering. " }),
      document.createTextNode("Start it with ./install.sh, or check logs/tracker.err.log."),
    ]));
    return;
  }

  const watcher = status.watcher || {};
  const browser = status.browser || {};

  /* While paused, every warning below is both true and useless: of course the
     extension is not reporting. Stacking them under the pause banner would
     only teach you to stop reading banners. */
  if ((status.pause || {}).paused) return;

  if (watcher.titles_allowed === false) {
    host.appendChild(h("div", { class: "banner" }, [
      h("b", { text: "Window titles are off. " }),
      document.createTextNode(
        "App-level time is being recorded, but not which document, repo or window. " +
        "Grant Accessibility to your Python binary, then restart the tracker — "
      ),
      h("code", { text: "python3 -m tracker doctor" }),
      document.createTextNode(" prints the exact path to add."),
    ]));
  }

  if (!browser.connected) {
    host.appendChild(h("div", { class: "banner" }, [
      h("b", { text: "The Chrome extension is not reporting. " }),
      document.createTextNode(
        "Browser time is still counted, it just has no tab detail. Load the "
      ),
      h("code", { text: "extension/" }),
      document.createTextNode(" folder at chrome://extensions with Developer mode on."),
    ]));
  }

  if (watcher.last_error) {
    host.appendChild(h("div", { class: "banner" }, [
      h("b", { text: "Last watcher error: " }),
      document.createTextNode(String(watcher.last_error)),
    ]));
  }
}

/* Something to tell the person once, then forget. It goes in #flash, not
   #notices: the status poll rebuilds #notices every fifteen seconds and
   after every refresh, so a message put there is gone before it is read —
   which is how "Removed 2h 14m, the snapshot is in …" was vanishing on the
   refresh that followed it. */
function note(message) {
  const host = $("flash");
  const banner = h("div", { class: "banner" }, [h("b", { text: message })]);
  host.insertBefore(banner, host.firstChild);
  setTimeout(() => banner.remove(), 8000);
}

/* -- your setup --------------------------------------------------------- */

function sourceLabel(source) {
  if (!source || source === "user") return "yours";
  if (source === "starter") return "starter";
  if (source.startsWith("pack:")) {
    /* "Sales & outreach" in a 13-character column is "sales & outreac…",
       which tells you less than the first word on its own. */
    const pack = (state.taxonomy ? state.taxonomy.packs : []).find(
      (p) => p.id === source.slice(5)
    );
    return pack ? pack.name.split(" & ")[0].toLowerCase() : "pack";
  }
  return source;
}

function closeSwatchMenus() {
  for (const node of document.querySelectorAll(".swatch-menu")) node.remove();
}

function swatchButton(row, onPick) {
  const button = h("button", {
    class: "swatch",
    title: "Change colour",
    "aria-label": `Colour for ${row.name}`,
  });
  button.style.background = row.color ? `var(--${row.color})` : "var(--axis)";
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    const open = button.parentNode.querySelector(".swatch-menu");
    closeSwatchMenus();
    if (open) return;
    const menu = h("div", { class: "swatch-menu" });
    for (const name of SLOT_NAMES) {
      const chip = h("button", {
        title: name,
        "aria-label": name,
        "aria-pressed": String(row.color === name),
      });
      chip.style.background = `var(--${name})`;
      chip.addEventListener("click", (pick) => {
        pick.stopPropagation();
        closeSwatchMenus();
        onPick(name);
      });
      menu.appendChild(chip);
    }
    button.parentNode.appendChild(menu);
  });
  return button;
}

/* Deleting can take rules with it, so it asks. Inline rather than through
   confirm(), which blocks the page and cannot be styled or tested. */
function armedButton(label, armedLabel, className, onConfirm, title) {
  const button = h("button", { class: `act ${className}`, text: label });
  if (title) button.title = title;
  let armed = false;
  let timer = null;
  button.addEventListener("click", () => {
    if (armed) {
      clearTimeout(timer);
      onConfirm();
      return;
    }
    armed = true;
    button.textContent = armedLabel;
    button.classList.add("armed");
    timer = setTimeout(() => {
      armed = false;
      button.textContent = label;
      button.classList.remove("armed");
    }, 4000);
  });
  return button;
}

/* "category" does not pluralise by adding an s, and the endpoint is
   /api/categories. One map rather than two near-misses. */
const TAXON_PATH = { category: "categories", client: "clients" };

async function taxonCall(kind, id, body) {
  try {
    await api(`/api/${TAXON_PATH[kind]}/${id}`, body);
    await renderSetup();
    if (state.view === "rules") await renderRules();
    await refresh();
  } catch (error) {
    note(error.message);
    await renderSetup();
  }
}

function taxonRow(row, kind) {
  const node = h("div", { class: "taxon-row" });

  if (kind === "category") {
    node.appendChild(swatchButton(row, (color) => taxonCall(kind, row.id, { color })));
  }

  const name = h("input", { class: "name", value: row.name, maxlength: "60" });
  if (row.archived) name.classList.add("archived");
  name.addEventListener("change", () => {
    const next = name.value.trim();
    if (!next || next === row.name) {
      name.value = row.name;
      return;
    }
    taxonCall(kind, row.id, { name: next });
  });
  node.appendChild(name);

  const used = row.rule_count || 0;
  const plural = used === 1 ? "rule" : "rules";
  const bits = [];
  if (kind === "client") {
    if (row.archived) bits.push("archived");
  } else {
    bits.push(sourceLabel(row.source));
  }
  bits.push(`${used} ${plural}`);
  node.appendChild(h("span", { class: "tag", text: bits.join(", ") }));

  /* The undo for labelling the wrong thing in bulk, which is one careless
     click away in the review panel and used to need a hunt through the
     rules list. Called Unlabel because the button that caused it says
     Label. */
  if (used) {
    node.appendChild(armedButton(
      "Unlabel", `Clear ${used}?`, "warn",
      () => taxonCall(kind, row.id, { unassign: true }),
      `Take this ${kind} off the ${used} ${plural} that assign it. `
      + `The ${kind} itself stays, and nothing recorded is deleted.`,
    ));
  }

  if (kind === "client") {
    const toggle = h("button", {
      class: "act",
      text: row.archived ? "Restore" : "Archive",
      title: row.archived
        ? "Put this client back in the pickers."
        : "Hide from the pickers without losing any history.",
    });
    toggle.addEventListener("click", () =>
      taxonCall(kind, row.id, { archived: !row.archived }));
    node.appendChild(toggle);
  }

  node.appendChild(armedButton(
    "Delete", "Delete?", "danger",
    () => taxonCall(kind, row.id, { delete: true }),
    used
      ? `Remove the ${kind} and take it off ${used} ${plural}. `
        + "Nothing recorded is deleted."
      : `Remove the ${kind}. It is not used by any rule.`,
  ));

  return node;
}

function renderTaxonList(host, rows, kind) {
  clear(host);
  if (!rows.length) {
    host.appendChild(h("div", {
      class: "setup-note",
      text: kind === "client"
        ? "No clients yet. Add one here, or label a block above."
        : "No categories yet.",
    }));
    return;
  }
  for (const row of rows) host.appendChild(taxonRow(row, kind));
}

function renderPacks(host, packs) {
  clear(host);
  for (const pack of packs) {
    const node = h("div", { class: `pack${pack.installed ? " on" : ""}` });
    const main = h("div", { class: "pack-main" }, [
      h("div", { class: "pack-name", text: pack.name }),
      h("div", { class: "pack-blurb", text: pack.blurb }),
    ]);
    const cats = h("div", { class: "pack-cats" });
    for (const name of pack.categories) cats.appendChild(h("span", { text: name }));
    main.appendChild(cats);
    node.appendChild(main);

    const button = h("button", {
      text: pack.installed ? "Turn off" : "Turn on",
      "data-pack": pack.id,
    });
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await api(`/api/packs/${pack.id}`, { apply: !pack.installed });
        await renderSetup();
        await refresh();
      } catch (error) {
        note(error.message);
        button.disabled = false;
      }
    });
    node.appendChild(button);
    host.appendChild(node);
  }
}

async function renderSetup() {
  let data;
  try {
    data = await api("/api/taxonomy");
  } catch (error) {
    note(`Could not load your setup: ${error.message}`);
    return;
  }
  state.taxonomy = data;
  renderTaxonList($("category-list"), data.categories, "category");
  renderTaxonList($("client-list"), data.clients, "client");
  renderPacks($("pack-list"), data.packs);
  $("category-count").textContent = String(data.categories.length);
  $("client-count").textContent = String(data.clients.length);
}

async function addTaxon(kind, input) {
  const name = input.value.trim();
  if (!name) return;
  try {
    await api(`/api/${TAXON_PATH[kind]}`, { name });
    input.value = "";
    await renderSetup();
    await refresh();
  } catch (error) {
    note(error.message);
  }
}

/* -- the off switch ----------------------------------------------------- */

let pauseTicker = null;

function pauseDetail(pause) {
  if (pause.indefinite) {
    return "It stays off until you turn it back on, including after a restart.";
  }
  /* `dur` rather than `durShort`: whole minutes for most of a pause, and
     exact seconds only inside the last one, which is the only point at which
     seconds are worth reading. */
  const left = Math.max(0, Math.round(pause.seconds_left || 0));
  const at = pause.until ? clock(pause.until) : null;
  return `Recording comes back in ${dur(left)}${at ? ` (at ${at})` : ""}.`;
}

function closePauseMenu() {
  $("pause-menu").hidden = true;
  $("pause-open").setAttribute("aria-expanded", "false");
}

function renderPause(status) {
  const pause = (status && status.pause) || null;
  const on = Boolean(pause && pause.paused);

  $("pause-banner").hidden = !on;
  $("pause-open").hidden = on;
  $("pause-resume").hidden = !on;
  if (on) $("pause-banner-detail").textContent = pauseDetail(pause);
  else closePauseMenu();

  /* A countdown that runs only while there is something to count. The status
     poll is too coarse for a number somebody is watching in order to decide
     whether to wait it out or resume now. */
  if (pauseTicker) {
    clearInterval(pauseTicker);
    pauseTicker = null;
  }
  if (on && !pause.indefinite) {
    let left = pause.seconds_left || 0;
    pauseTicker = setInterval(() => {
      left -= 1;
      if (left <= 0) {
        clearInterval(pauseTicker);
        pauseTicker = null;
        pollStatus();
        return;
      }
      /* Ticks every second but writes only when the words change, so a long
         pause repaints once a minute and the last minute repaints properly. */
      const next = pauseDetail({ ...pause, seconds_left: left });
      const node = $("pause-banner-detail");
      if (node.textContent !== next) node.textContent = next;
    }, 1000);
  }
}

async function setPaused(body) {
  try {
    const payload = body
      ? await api("/api/pause", body)
      : await api("/api/resume", {});
    if (state.status) state.status.pause = payload.pause;
    renderPause(state.status || { pause: payload.pause });
    /* Reload rather than wait for the next poll: the totals change the
       instant recording stops or starts. */
    await refresh();
  } catch (error) {
    note(`Could not change the tracker state: ${error.message}`);
  }
}

/* -- status line -------------------------------------------------------- */

function renderStatus(status) {
  const dot = $("live-dot");
  const line = $("now-line");
  const database = $("db-line");

  if (!status) {
    dot.className = "dot down";
    dot.title = "not running";
    line.textContent = "not running";
    return;
  }

  const watcher = status.watcher || {};
  const current = watcher.current;
  const away = watcher.away;
  const pause = status.pause || {};

  if (pause.paused) {
    dot.className = "dot down";
    dot.title = "paused: nothing is being recorded";
    line.textContent = pause.indefinite
      ? "paused"
      : `paused, back in ${durShort(pause.seconds_left || 0)}`;
  } else if (!watcher.running) {
    dot.className = "dot down";
    dot.title = "watcher stopped";
    line.textContent = `today ${dur(status.today_seconds)}`;
  } else if (away) {
    dot.className = "dot stale";
    dot.title = `away (${away.kind})`;
    line.textContent = `away ${dur(away.seconds)} · today ${dur(status.today_seconds)}`;
  } else {
    dot.className = "dot live";
    dot.title = "tracking";
    line.textContent = current
      ? `${current.app} ${dur(current.seconds)} · today ${dur(status.today_seconds)}`
      : `today ${dur(status.today_seconds)}`;
  }

  const db = status.database || {};
  const browser = status.browser || {};
  database.textContent = [
    `${(db.db_bytes / 1048576).toFixed(1)} MB`,
    `${db.desktop_events} desktop intervals`,
    `${db.browser_events} tab intervals`,
    browser.connected ? "extension connected" : "extension offline",
  ].join(" · ");
}

/* -- data --------------------------------------------------------------- */

/* -- export -------------------------------------------------------------
 *
 * Three formats were asked for. CSV is the raw blocks, for a spreadsheet.
 * The report is one self-contained HTML file with no scripts and nothing to
 * fetch, so it still opens in a year or on a machine that has never heard of
 * this tracker. PDF is that same file through the browser's print dialogue,
 * which is a better PDF writer than anything that would fit in here and does
 * not cost the install a dependency.
 */

function exportQuery(extra = {}) {
  const range = $("export-range").value;
  const params = new URLSearchParams();
  if (range === "custom") {
    const from = $("export-from").value;
    const to = $("export-to").value;
    if (!from || !to) return null;
    params.set("from", from);
    params.set("to", to);
  } else {
    params.set("range", range);
  }
  if ($("export-detail").checked) params.set("detail", "1");
  for (const [key, value] of Object.entries(extra)) params.set(key, value);
  return params.toString();
}

function exportTell(message) {
  $("export-note").textContent = message;
  if (message) setTimeout(() => { $("export-note").textContent = ""; }, 6000);
}

function wireExport() {
  if (!$("export-range")) return;

  const syncCustom = () => {
    const custom = $("export-range").value === "custom";
    $("export-from-wrap").hidden = !custom;
    $("export-to-wrap").hidden = !custom;
    if (custom && !$("export-from").value) {
      const today = new Date();
      const week = new Date(today.getTime() - 6 * 86400000);
      $("export-from").value = toDayValue(week.getTime() / 1000);
      $("export-to").value = toDayValue(today.getTime() / 1000);
    }
  };
  $("export-range").addEventListener("change", () => {
    // Once it has been chosen deliberately, stop following the dashboard.
    $("export-range").dataset.touched = "1";
    syncCustom();
  });
  syncCustom();

  $("export-report").addEventListener("click", () => {
    const query = exportQuery();
    if (!query) return exportTell("Pick both dates first.");
    window.open(`/api/report.html?${query}`, "_blank", "noopener");
  });

  // Opened in a tab and told to print, rather than downloaded: the browser's
  // print dialogue is where "Save as PDF" lives, and a downloaded file would
  // make the person find and open it first.
  $("export-print").addEventListener("click", () => {
    const query = exportQuery();
    if (!query) return exportTell("Pick both dates first.");
    const tab = window.open(`/api/report.html?${query}`, "_blank", "noopener");
    exportTell(tab
      ? "Opened in a new tab. Press Cmd+P there and choose Save as PDF."
      : "Allow pop-ups for this page, or use Open report and print it.");
  });

  $("export-csv").addEventListener("click", () => {
    const query = exportQuery();
    if (!query) return exportTell("Pick both dates first.");
    // A real navigation rather than fetch(): the browser handles the
    // Content-Disposition and the file lands in Downloads with its name.
    const link = document.createElement("a");
    link.href = `/api/export.csv?${query}`;
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
    exportTell("Downloaded.");
  });
}

/* -- the rule builder ---------------------------------------------------
 *
 * Saving a rule rewrites the whole history, because classification is
 * computed when you look rather than stored. That is the best thing about
 * the design and the most alarming: a keyword one letter too short quietly
 * reassigns a month of work to the wrong client, and nothing announces it.
 *
 * So the form answers the question before it is committed to. Every
 * keystroke asks the tracker what this rule would claim out of what is
 * actually recorded, and says so in hours, as a share of the month, and as
 * six real blocks you can recognise.
 */

let rbTimer = null;
let rbReady = null;

function rbDraft() {
  const text = $("rb-text").value.trim();
  const category = $("rb-category").value.trim();
  const client = $("rb-client").value.trim();
  if (!text || (!category && !client)) return null;
  return {
    field: $("rb-field").value,
    text,
    category: category || null,
    client: client || null,
    mode: $("rb-regex").checked ? "regex" : "text",
  };
}

function scheduleRulePreview() {
  clearTimeout(rbTimer);
  rbTimer = setTimeout(previewRule, 280);
}

async function previewRule() {
  const draft = rbDraft();
  const out = clear($("rb-preview"));
  const add = $("rb-add");
  rbReady = null;
  add.disabled = true;

  if (!draft) {
    out.appendChild(h("span", { class: "muted", text:
      "Type what to look for, and at least a category or a client." }));
    return;
  }

  const query = new URLSearchParams({
    [`match_${draft.field}`]: draft.text,
    mode: draft.mode,
    range: "month",
  });
  if (draft.client) query.set("client", draft.client);
  if (draft.category) query.set("category", draft.category);

  let found;
  try {
    found = await api(`/api/rule-preview?${query.toString()}`);
  } catch (error) {
    out.appendChild(h("span", { class: "warn-text", text:
      `Could not check that: ${error.message}` }));
    return;
  }

  if (found.ok === false) {
    out.appendChild(h("span", { class: "warn-text", text:
      `That is not a valid pattern: ${found.error}. Untick the box below to ` +
      "treat it as plain text." }));
    return;
  }

  rbReady = draft;
  add.disabled = false;

  if (!found.blocks) {
    out.appendChild(h("span", { class: "muted", text:
      "Nothing in the last month matches this. It will still apply to " +
      "anything that does from now on." }));
    return;
  }

  const head = h("div", { class: "rb-headline" });
  head.appendChild(h("b", { text: dur(found.seconds) }));
  head.appendChild(document.createTextNode(
    ` across ${found.blocks} block${found.blocks === 1 ? "" : "s"}` +
    ` this month, ${pct(found.share)} of everything recorded.`
  ));
  out.appendChild(head);

  // The mistake worth seeing: a keyword wide enough to take time that
  // already belongs to somebody else.
  if ((found.taken_from || []).length) {
    const warn = h("div", { class: "rb-warn" });
    warn.appendChild(document.createTextNode("This would take "));
    warn.appendChild(h("b", { text: found.taken_from
      .map((row) => `${dur(row.seconds)} from ${row.client}`).join(", ") }));
    warn.appendChild(document.createTextNode("."));
    out.appendChild(warn);
  }

  const list = h("ul", { class: "rb-examples" });
  for (const example of found.examples) {
    const item = h("li");
    item.appendChild(h("span", { class: "rb-when num", text:
      `${new Date(example.when * 1000).toLocaleDateString([], {
        month: "short", day: "numeric" })} ${clock(example.when)}` }));
    item.appendChild(h("b", { text: example.what }));
    if (example.title) item.appendChild(h("small", { text: example.title }));
    item.appendChild(h("span", { class: "rb-dur num", text: dur(example.seconds) }));
    list.appendChild(item);
  }
  out.appendChild(list);
}

async function addBuiltRule() {
  if (!rbReady) return;
  const payload = {
    priority: 20,
    match_mode: rbReady.mode,
    client: rbReady.client,
    category: rbReady.category,
  };
  payload[`match_${rbReady.field}`] = rbReady.text;

  $("rb-add").disabled = true;
  $("rb-note").textContent = "Adding…";
  try {
    await api("/api/rules", payload);
    $("rb-text").value = "";
    $("rb-category").value = "";
    $("rb-client").value = "";
    $("rb-note").textContent = "";
    clear($("rb-preview"));
    rbReady = null;
    note("Rule added. Your whole history has been relabelled to match.");
    await renderRules();
    await refresh();
    previewRule();
  } catch (error) {
    $("rb-note").textContent = `Could not add it: ${error.message}`;
    $("rb-add").disabled = false;
  }
}

function wireRuleBuilder() {
  if (!$("rb-text")) return;
  for (const id of ["rb-text", "rb-category", "rb-client"]) {
    $(id).addEventListener("input", scheduleRulePreview);
  }
  for (const id of ["rb-field", "rb-regex"]) {
    $(id).addEventListener("change", previewRule);
  }
  $("rb-add").addEventListener("click", addBuiltRule);
  $("rb-text").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && rbReady) addBuiltRule();
  });
}

/* -- one day, block by block --------------------------------------------
 *
 * The strip on the dashboard draws one rectangle per block, and a real day
 * holds hundreds — most of them a pixel wide and none of them readable or
 * clickable. This is the same day as a list.
 *
 * The short blocks are the point. Switching to Slack for four seconds and
 * back is not a thing anybody wants a row for, but it is also not nothing:
 * forty of them is three minutes that has to still be in the total. So a run
 * of them folds into one row that says how many and how long, and opens if
 * you want to look.
 */

const DAY_FOLD_SECONDS = 60;

function dayKey(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function shiftDay(value, days) {
  const [y, m, d] = value.split("-").map(Number);
  const date = new Date(y, m - 1, d + days);
  return dayKey(date);
}

async function renderDay() {
  if (!state.day.date) state.day.date = dayKey(new Date());
  $("day-date").value = state.day.date;
  const host = clear($("day-list"));
  $("day-summary").textContent = "Loading…";

  let payload;
  try {
    payload = await api(
      `/api/blocks?from=${state.day.date}&to=${state.day.date}`
    );
  } catch (error) {
    $("day-summary").textContent = `Could not load that day: ${error.message}`;
    return;
  }
  state.day.blocks = payload.blocks || [];
  paintDay();
}

function paintDay() {
  const host = clear($("day-list"));
  const all = state.day.blocks;
  const wanted = state.day.filter === "unassigned"
    ? all.filter((b) => !b.client && !b.category)
    : all;

  const total = all.reduce((n, b) => n + b.seconds, 0);
  const labelled = all.filter((b) => b.client || b.category)
    .reduce((n, b) => n + b.seconds, 0);
  $("day-summary").textContent = all.length
    ? `${dur(total)} recorded across ${all.length} blocks. ` +
      `${dur(labelled)} of it is labelled.`
    : "Nothing was recorded on this day.";

  if (!wanted.length) {
    host.appendChild(h("div", { class: "empty", text: all.length
      ? "Everything on this day is labelled."
      : "Nothing was recorded on this day." }));
    return;
  }

  for (const group of foldDay(wanted)) {
    host.appendChild(group.folded ? foldedRow(group) : dayRow(group.blocks[0]));
  }
}

/* Consecutive blocks shorter than the fold threshold become one row. A long
   block is always its own row, even between two short ones. */
function foldDay(blocks) {
  const out = [];
  let run = [];
  const flush = () => {
    if (!run.length) return;
    // Folding one or two away hides more than it saves: the row that
    // replaces them is as long as they were.
    if (run.length > 2) out.push({ folded: true, blocks: run });
    else for (const b of run) out.push({ folded: false, blocks: [b] });
    run = [];
  };
  for (const block of blocks) {
    if (block.seconds < DAY_FOLD_SECONDS) {
      run.push(block);
      continue;
    }
    flush();
    out.push({ folded: false, blocks: [block] });
  }
  flush();
  return out;
}

function foldedRow(group) {
  const seconds = group.blocks.reduce((n, b) => n + b.seconds, 0);
  const row = h("div", { class: "day-row folded" });
  const open = h("button", { class: "fold-open" }, [
    document.createTextNode(
      `${group.blocks.length} short switches, ${dur(seconds)} in total`
    ),
  ]);
  row.appendChild(h("div", { class: "day-when num", text:
    `${clock(group.blocks[0].start)} – ${clock(group.blocks[group.blocks.length - 1].end)}` }));
  row.appendChild(open);
  let shown = false;
  open.addEventListener("click", () => {
    shown = !shown;
    open.textContent = shown
      ? "Fold these back up"
      : `${group.blocks.length} short switches, ${dur(seconds)} in total`;
    if (shown) {
      let after = row;
      for (const block of group.blocks) {
        const node = dayRow(block);
        node.classList.add("unfolded");
        after.after(node);
        after = node;
      }
    } else {
      let next = row.nextSibling;
      while (next && next.classList && next.classList.contains("unfolded")) {
        const doomed = next;
        next = next.nextSibling;
        doomed.remove();
      }
    }
  });
  return row;
}

function dayRow(block) {
  const row = h("div", { class: "day-row" });
  if (block.client || block.category) row.classList.add("has-label");

  row.appendChild(h("div", { class: "day-when num", text:
    `${clock(block.start)} – ${clock(block.end)}` }));
  row.appendChild(h("div", { class: "day-span num", text: dur(block.seconds) }));

  const what = h("div", { class: "day-what" });
  what.appendChild(h("b", { text: block.domain || block.app }));
  const detail = block.title || (block.domain ? block.app : null);
  if (detail) what.appendChild(h("small", { text: detail }));
  what.title = block.url || block.title || block.app;
  row.appendChild(what);

  const now = h("div", { class: "day-now" });
  if (block.category) {
    now.appendChild(h("span", { class: "chip", text: block.category }));
  }
  if (block.client) {
    now.appendChild(h("span", { class: "chip client", text: block.client }));
  }
  if (block.assigned) {
    now.appendChild(h("span", { class: "chip faint", text: "assigned" }));
  }
  row.appendChild(now);

  const category = h("input", {
    class: "day-input", list: "known-categories", placeholder: "category",
    autocomplete: "off",
  });
  const client = h("input", {
    class: "day-input", list: "known-clients", placeholder: "client",
    autocomplete: "off",
  });
  const apply = h("button", { class: "act", text: "Assign" });
  apply.addEventListener("click", async () => {
    const payload = {
      start: block.start,
      end: block.end,
      category: category.value.trim() || null,
      client: client.value.trim() || null,
    };
    if (!payload.category && !payload.client) {
      category.focus();
      return;
    }
    apply.disabled = true;
    try {
      await api("/api/assign", payload);
      await renderDay();
      await refresh();
    } catch (error) {
      note(`Could not assign that: ${error.message}`);
      apply.disabled = false;
    }
  });

  const clearIt = h("button", { class: "act", text: "Clear",
    title: "Put this block back to whatever the rules make of it" });
  clearIt.addEventListener("click", async () => {
    clearIt.disabled = true;
    try {
      await api("/api/unassign", { start: block.start, end: block.end });
      await renderDay();
      await refresh();
    } catch (error) {
      note(`Could not clear that: ${error.message}`);
      clearIt.disabled = false;
    }
  });

  const actions = h("div", { class: "day-actions" }, [category, client, apply]);
  if (block.assigned) actions.appendChild(clearIt);
  row.appendChild(actions);
  return row;
}

function wireDay() {
  if (!$("day-date")) return;
  $("day-date").addEventListener("change", () => {
    state.day.date = $("day-date").value;
    renderDay();
  });
  $("day-prev").addEventListener("click", () => {
    state.day.date = shiftDay(state.day.date || dayKey(new Date()), -1);
    renderDay();
  });
  $("day-next").addEventListener("click", () => {
    state.day.date = shiftDay(state.day.date || dayKey(new Date()), 1);
    renderDay();
  });
  $("day-today").addEventListener("click", () => {
    state.day.date = dayKey(new Date());
    renderDay();
  });
  $("day-filter").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-filter]");
    if (!button) return;
    state.day.filter = button.dataset.filter;
    for (const other of $("day-filter").querySelectorAll("button")) {
      other.setAttribute("aria-selected", String(other === button));
    }
    paintDay();
  });
}

/* -- removing time ------------------------------------------------------
 *
 * The one irreversible thing in the product, so it is also the only one that
 * refuses to act on a number you have not been shown. The form previews what
 * it would take on every keystroke, the button arms before it fires, and the
 * database is snapshotted before the first delete of a session.
 */

const pad2 = (n) => String(n).padStart(2, "0");

function toDayValue(ts) {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function toTimeValue(ts) {
  const d = new Date(ts * 1000);
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

/* The inputs are local wall-clock, which is what the person is reading off
   the strip. Date handles the offset, including the day a clock changes. */
function removeWindow() {
  const day = $("remove-day").value;
  const from = $("remove-from").value;
  const to = $("remove-to").value;
  if (!day || !from || !to) return null;
  const start = new Date(`${day}T${from}`).getTime() / 1000;
  let end = new Date(`${day}T${to}`).getTime() / 1000;
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  // "22:30 to 00:30" is a night that crosses midnight, not a negative span.
  if (end <= start) end += 86400;
  return { start, end };
}

function openRemove(startTs, endTs) {
  const panel = $("remove-panel");
  const now = Date.now() / 1000;
  const start = startTs ?? now - 3600;
  const end = endTs ?? now;
  $("remove-day").value = toDayValue(start);
  $("remove-from").value = toTimeValue(start);
  $("remove-to").value = toTimeValue(end);
  panel.hidden = false;
  $("remove-note").textContent = "";
  previewRemove();
  $("remove-from").focus();
}

function closeRemove() {
  $("remove-panel").hidden = true;
  $("remove-preview").textContent = "";
  $("remove-go").disabled = true;
  disarmRemove();
}

let removePreviewTimer = null;

function schedulePreview() {
  clearTimeout(removePreviewTimer);
  removePreviewTimer = setTimeout(previewRemove, 250);
}

async function previewRemove() {
  disarmRemove();
  const window_ = removeWindow();
  const out = $("remove-preview");
  const go = $("remove-go");
  if (!window_) {
    out.textContent = "Pick a day and a time range.";
    go.disabled = true;
    return;
  }
  try {
    const found = await api(
      `/api/removable?start=${window_.start}&end=${window_.end}`
    );
    if (!found.seconds) {
      out.textContent = "Nothing was recorded in that window.";
      go.disabled = true;
      return;
    }
    const parts = (found.top || [])
      .slice(0, 4)
      .map((row) => `${row.label} ${dur(row.seconds)}`);
    clear(out);
    out.appendChild(h("b", { text: dur(found.seconds) }));
    out.appendChild(document.createTextNode(
      ` across ${found.blocks} block${found.blocks === 1 ? "" : "s"}` +
      (parts.length ? `: ${parts.join(", ")}` : "") +
      (found.top && found.top.length > 4 ? ", and more" : "")
    ));
    go.disabled = false;
    go.textContent = `Delete ${dur(found.seconds)}`;
  } catch (error) {
    out.textContent = `Could not check that window: ${error.message}`;
    go.disabled = true;
  }
}

let removeArmed = false;
let removeArmTimer = null;

function disarmRemove() {
  removeArmed = false;
  clearTimeout(removeArmTimer);
  const go = $("remove-go");
  if (go) go.classList.remove("armed");
}

async function submitRemove(event) {
  event.preventDefault();
  const window_ = removeWindow();
  if (!window_) return;

  // Deleting is not undoable from in here, so it takes two deliberate
  // presses. The second one says what it is about to do.
  if (!removeArmed) {
    removeArmed = true;
    const go = $("remove-go");
    go.classList.add("armed");
    const was = go.textContent;
    go.textContent = `${was.replace("Delete", "Really delete")}?`;
    removeArmTimer = setTimeout(() => {
      removeArmed = false;
      go.classList.remove("armed");
      go.textContent = was;
    }, 5000);
    return;
  }

  disarmRemove();
  $("remove-go").disabled = true;
  $("remove-note").textContent = "Removing…";
  try {
    const result = await api("/api/delete", window_);
    closeRemove();
    const where = result.backup ? result.backup.split("/").slice(-2).join("/") : null;
    note(
      `Removed ${dur(result.seconds)}.` +
      (where ? ` Everything as it was before is in ${where}.` : "")
    );
    await refresh();
  } catch (error) {
    $("remove-note").textContent = `Could not remove it: ${error.message}`;
    $("remove-go").disabled = false;
  }
}

function wireRemove() {
  const open = $("remove-open");
  if (!open) return;
  open.addEventListener("click", () => {
    if ($("remove-panel").hidden) openRemove();
    else closeRemove();
  });
  $("remove-cancel").addEventListener("click", closeRemove);
  $("remove-panel").addEventListener("submit", submitRemove);
  for (const id of ["remove-day", "remove-from", "remove-to"]) {
    $(id).addEventListener("input", schedulePreview);
  }
}

async function api(path, body = null, method = null) {
  const options = { method: method || (body ? "POST" : "GET") };
  if (body) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const text = await response.text();
  let payload = {};
  try { payload = text ? JSON.parse(text) : {}; } catch (_) { payload = {}; }
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function renderSummary(summary) {
  state.summary = summary;
  const window_ = summary.window;

  $("chart-title").textContent =
    window_.days === 1 ? "Where the time went, by hour" : "Where the time went, by day";

  renderTiles(summary);
  columnChart($("chart"), summary.series, window_.granularity);

  const categoryKeys = (summary.by_category || []).map((row) => row.key);
  const slots = assignSlots(summary.series.keys || categoryKeys);

  const timelineCard = $("timeline-card");
  if (window_.days === 1) {
    timelineCard.hidden = false;
    $("timeline-note").textContent = `${window_.start_date}, hover any block for detail`;
    dayStrip($("timeline"), summary.timeline || [], window_, summary.series.keys || categoryKeys);
  } else {
    timelineCard.hidden = true;
  }

  barTable($("by_client"), summary.by_client, {
    heading: "Client", empty: "No client labels yet.",
  });
  barTable($("by_app"), summary.by_app, { heading: "App" });
  barTable($("by_category"), summary.by_category, { heading: "Category", slots });
  barTable($("by_domain"), summary.by_domain, {
    heading: "Site", empty: "No browser data yet.",
  });

  renderReview(summary);

  $("export-link").href = `/api/export.csv?range=${encodeURIComponent(state.range)}`;
  // The panel starts on the range you are already looking at, since that is
  // almost always the one you want out.
  const picker = $("export-range");
  if (picker && !picker.dataset.touched &&
      [...picker.options].some((o) => o.value === state.range)) {
    picker.value = state.range;
  }
}

function renderDatalists(labels) {
  for (const [id, values] of [
    ["known-clients", labels.clients],
    ["known-categories", labels.categories],
  ]) {
    const host = clear($(id));
    for (const value of values || []) host.appendChild(h("option", { value }));
  }
}

async function refresh() {
  try {
    const [summary, labels] = await Promise.all([
      api(`/api/summary?range=${encodeURIComponent(state.range)}`),
      api("/api/labels"),
    ]);
    state.labels = labels;
    renderDatalists(labels);
    renderSummary(summary);
    if (state.view === "rules") await renderRules();
    if (state.view === "setup") await renderSetup();
  } catch (error) {
    note(`Could not load data: ${error.message}`);
  }
  await pollStatus();
}

async function pollStatus() {
  try {
    const status = await api("/api/status");
    if (status.first_run && !state.welcomed) {
      state.welcomed = true;
      showWelcome();
    }
    state.status = status;
    renderStatus(status);
    renderPause(status);
    renderNotices(status);
  } catch (_) {
    state.status = null;
    renderStatus(null);
    renderPause(null);
    renderNotices(null);
  }
}

/* -- wiring ------------------------------------------------------------- */

function selectRange(range) {
  state.range = range;
  for (const button of $("ranges").querySelectorAll("button")) {
    button.setAttribute("aria-selected", String(button.dataset.range === range));
  }
  try { localStorage.setItem("range", range); } catch (_) { /* private window */ }
  refresh();
}

$("ranges").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-range]");
  if (button) selectRange(button.dataset.range);
});

$("pause-open").addEventListener("click", (event) => {
  event.stopPropagation();
  const menu = $("pause-menu");
  menu.hidden = !menu.hidden;
  $("pause-open").setAttribute("aria-expanded", String(!menu.hidden));
});

$("pause-menu").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-minutes]");
  if (!button) return;
  const raw = button.dataset.minutes;
  closePauseMenu();
  setPaused(raw === "" ? { indefinite: true } : { minutes: Number(raw) });
});

for (const id of ["pause-resume", "pause-banner-resume"]) {
  $(id).addEventListener("click", () => setPaused(null));
}

document.addEventListener("click", (event) => {
  if (!event.target.closest(".pause-wrap")) closePauseMenu();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closePauseMenu();
});

$("theme").addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme");
  const next = current === "dark" ? "light" : current === "light" ? "" : "dark";
  if (next) document.documentElement.setAttribute("data-theme", next);
  else document.documentElement.removeAttribute("data-theme");
  try { localStorage.setItem("theme", next); } catch (_) { /* ignore */ }
});

$("category-add").addEventListener("submit", (event) => {
  event.preventDefault();
  addTaxon("category", $("category-new"));
});

$("client-add").addEventListener("submit", (event) => {
  event.preventDefault();
  addTaxon("client", $("client-new"));
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".swatch, .swatch-menu")) closeSwatchMenus();
});

/* -- first run -----------------------------------------------------------
 * Five seconds, no way out. The promise on that screen is the whole reason
 * somebody is willing to run this, so it gets read rather than clicked past.
 * The flag lives on the tracker, not in this browser, so a second browser
 * does not see it again and a colleague's machine sees it exactly once. */

const WELCOME_MS = 5000;

function showWelcome() {
  const screen = $("welcome");
  const go = $("welcome-go");
  screen.hidden = false;
  document.body.style.overflow = "hidden";

  // Focus is parked on the screen so a keyboard user is not tabbing around
  // the dashboard behind it, and Escape does nothing on purpose.
  screen.setAttribute("tabindex", "-1");
  screen.focus({ preventScroll: true });
  const trap = (event) => {
    if (event.key === "Escape" || event.key === "Tab") event.preventDefault();
  };
  document.addEventListener("keydown", trap, true);

  setTimeout(() => {
    go.disabled = false;
    go.focus({ preventScroll: true });
  }, WELCOME_MS);

  go.addEventListener("click", async () => {
    if (go.disabled) return;
    document.removeEventListener("keydown", trap, true);
    screen.hidden = true;
    document.body.style.overflow = "";
    try {
      await api("/api/welcome", {});
    } catch (_) {
      /* If this fails you simply get greeted again next time, which is a
         better outcome than blocking the dashboard over it. */
    }
  });
}

/* -- routing ------------------------------------------------------------
 * Three views in one page, addressed by hash so a section can be linked,
 * bookmarked and reloaded into. No router library: there are three of them. */

const VIEWS = ["dashboard", "day", "setup", "rules"];

async function showView(name, push = true) {
  if (!VIEWS.includes(name)) name = "dashboard";
  state.view = name;
  for (const section of document.querySelectorAll(".view")) {
    section.hidden = section.dataset.view !== name;
  }
  for (const button of $("views").querySelectorAll("button")) {
    const on = button.dataset.view === name;
    if (on) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  if (push && location.hash !== `#/${name}`) {
    history.replaceState(null, "", `#/${name}`);
  }
  window.scrollTo({ top: 0 });

  // Fetched when the section is opened rather than on every refresh, so the
  // dashboard does not pay for two lists nobody is looking at.
  if (name === "setup") await renderSetup();
  if (name === "rules") { await renderRules(); previewRule(); }
  if (name === "day") await renderDay();
}

$("views").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-view]");
  if (button) showView(button.dataset.view);
});

window.addEventListener("hashchange", () => {
  showView((location.hash || "").replace(/^#\/?/, ""), false);
});

$("rule-search").addEventListener("input", (event) => {
  state.ruleSearch = event.target.value;
  paintRules();
});

$("rule-source").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-source]");
  if (!button) return;
  state.ruleSource = button.dataset.source;
  for (const other of $("rule-source").querySelectorAll("button")) {
    other.setAttribute("aria-selected", String(other === button));
  }
  paintRules();
});

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (state.summary) renderSummary(state.summary);
  }, 160);
});

document.addEventListener("keydown", (event) => {
  if (event.target.tagName === "INPUT" || event.target.tagName === "SELECT") return;
  const map = { 1: "today", 2: "yesterday", 3: "week", 4: "this_month", 5: "month" };
  if (map[event.key]) selectRange(map[event.key]);
  if (event.key === "r") refresh();
});

try {
  const savedTheme = localStorage.getItem("theme");
  if (savedTheme) document.documentElement.setAttribute("data-theme", savedTheme);
} catch (_) { /* ignore */ }

let savedRange = "today";
try { savedRange = localStorage.getItem("range") || "today"; } catch (_) { /* ignore */ }

wireRemove();
wireDay();
wireRuleBuilder();
wireExport();
selectRange(savedRange);
setInterval(pollStatus, 15000);
setInterval(() => { if (LIVE_RANGES.has(state.range)) refresh(); }, 90000);

showView((location.hash || "").replace(/^#\/?/, ""), false);
