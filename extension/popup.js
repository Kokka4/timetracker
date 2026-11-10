"use strict";

/* The popup talks to the tracker directly for everything it reads, and goes
   through the service worker only for the off switch, which also has to
   repaint the toolbar badge.

   That split matters for one reason worth stating: popup.html and this file
   are read fresh from disk every time the popup opens, but the service worker
   is only re-evaluated when the extension is reloaded. So a popup from a new
   build can be talking to a worker from an old one. Everything below is
   written to notice that and say so, rather than failing blankly. */

const $ = (id) => document.getElementById(id);

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

function stopwatch(seconds) {
  const total = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

function clockTime(unixSeconds) {
  try {
    return new Date(unixSeconds * 1000)
      .toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch (_) {
    return "";
  }
}

function base(endpoint) {
  try { return new URL(endpoint).origin; } catch (_) { return "http://127.0.0.1:8734"; }
}

function send(message) {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(message, (reply) => {
        const failed = chrome.runtime.lastError;
        resolve(reply || (failed ? { __noworker: true } : {}));
      });
    } catch (_) {
      resolve({ __noworker: true });
    }
  });
}

let config = { endpoint: "http://127.0.0.1:8734/api/ingest/chrome" };
let ticker = null;
let current = null;          // what the tracker says is in front right now
let staleWorker = false;     // the popup is newer than the service worker

async function api(path, body) {
  const response = await fetch(base(config.endpoint) + path, body
    ? { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) }
    : undefined);
  const text = await response.text();
  let payload = {};
  try { payload = text ? JSON.parse(text) : {}; } catch (_) { /* not json */ }
  if (!response.ok) {
    throw new Error(payload.error || `the tracker said ${response.status}`);
  }
  return payload;
}

/* -- painting ----------------------------------------------------------- */

function showBanner(title, detail, html) {
  $("banner").classList.add("on");
  $("banner-title").textContent = title;
  if (html) $("banner-detail").innerHTML = html;
  else $("banner-detail").textContent = detail || "";
}

function paintPause(pause) {
  const paused = Boolean(pause && pause.paused && pause.reachable !== false);
  document.body.classList.toggle("off", paused);
  $("resume").hidden = !paused;
  $("pause-row").hidden = paused;
  $("pause-label").style.display = paused ? "none" : "block";
  $("now").hidden = paused || !current;

  if (!paused) {
    if (!staleWorker) $("banner").classList.remove("on");
    return;
  }
  if (pause.indefinite) {
    showBanner("Tracking is off.",
      "It stays off until you turn it back on, including after a restart.");
  } else if (pause.until) {
    showBanner("Tracking is off.", `Recording resumes at ${clockTime(pause.until)}.`);
  } else {
    showBanner("Tracking is off.", "Recording is stopped.");
  }
}

function paintNow(status) {
  const watcher = status.watcher || {};
  const browser = status.browser || {};
  const block = watcher.current;

  if (!block) {
    current = null;
    $("now").hidden = true;
    return;
  }

  /* When a browser is in front, the tab is the useful identity and the app
     is the footnote. Everywhere else it is the other way round. */
  const tab = browser.current;
  const inBrowser = Boolean(tab) && browser.connected;

  current = {
    app: block.app,
    title: inBrowser ? tab.title : block.title,
    domain: inBrowser ? tab.domain : null,
    url: inBrowser ? tab.url : null,
    seconds: block.seconds || 0,
    at: Date.now(),
  };

  $("now").hidden = false;
  $("now-what").textContent = current.domain || current.title || current.app;
  $("now-what").title = current.url || current.title || current.app;
  $("now-meta").textContent = [current.app, inBrowser ? current.title : null]
    .filter(Boolean).join(" · ");

  const scope = $("scope");
  scope.textContent = "";
  const short = (text, max) => {
    const value = String(text || "");
    return value.length > max ? `${value.slice(0, max - 1)}…` : value;
  };
  const option = (value, text) => {
    const node = document.createElement("option");
    node.value = value;
    node.textContent = text;
    scope.appendChild(node);
  };
  if (current.domain) option("domain", `all of ${short(current.domain, 24)}`);
  option("app", `all of ${short(current.app, 24)}`);
  if (current.title) option("title", "only this window");
  if (current.url) option("url", "only this page");

  startTicker();
}

function startTicker() {
  if (ticker) clearInterval(ticker);
  const paint = () => {
    if (!current) return;
    const elapsed = current.seconds + (Date.now() - current.at) / 1000;
    $("now-timer").textContent = stopwatch(elapsed);
  };
  paint();
  ticker = setInterval(paint, 1000);
}

function paintLabels(labels) {
  for (const [id, values] of [["clients", labels.clients], ["categories", labels.categories]]) {
    const host = $(id);
    host.textContent = "";
    for (const value of values || []) {
      const option = document.createElement("option");
      option.value = value;
      host.appendChild(option);
    }
  }
  $("client").placeholder = (labels.clients || []).length
    ? "client" : "client (type to add)";
}

/* -- the main refresh --------------------------------------------------- */

async function paint() {
  const reply = await send({ type: "ping" });
  if (reply.__noworker) staleWorker = true;
  config = reply.config || config;
  $("endpoint").value = config.endpoint;

  let status;
  try {
    status = await api("/api/status");
  } catch (error) {
    $("dot").className = "dot bad";
    $("today").textContent = "—";
    $("now").hidden = true;
    $("state").innerHTML =
      `<span class="err">tracker not reachable</span> ${error.message}`;
    return;
  }

  const pause = status.pause || null;
  const paused = Boolean(pause && pause.paused);
  $("today").textContent = dur(status.today_seconds);
  paintNow(status);
  paintPause(pause);

  const browser = status.browser || {};
  if (paused) {
    $("dot").className = "dot bad";
    $("state").textContent = "paused · nothing is being recorded, by either half";
  } else {
    $("dot").className = `dot ${browser.connected ? "ok" : "bad"}`;
    $("state").textContent = browser.connected
      ? `connected · ${browser.heartbeats} heartbeats today`
      : "tracker is up, but has not seen this extension yet";
  }

  try {
    paintLabels(await api("/api/labels"));
  } catch (_) { /* the pickers are a convenience, not a requirement */ }

  if (staleWorker) {
    showBanner("This extension needs reloading.", null,
      'The popup updated but the background worker did not. Open '
      + '<code>chrome://extensions</code> and press reload on Local Time '
      + 'Tracker Bridge.');
  }
}

/* -- actions ------------------------------------------------------------ */

function busy(on) {
  for (const button of document.querySelectorAll("button")) button.disabled = on;
}

/* Pause goes through the worker so the toolbar badge follows, but falls back
   to posting directly when the worker is too old to know the message. A
   button that works is worth more than a tidy call graph. */
async function setPause(minutes) {
  busy(true);
  const message = minutes === null ? { type: "pause" } : { type: "pause", minutes };
  let reply = await send(message);

  if (reply.__noworker || (!reply.ok && !reply.error)) {
    staleWorker = true;
    try {
      const body = minutes === null ? { indefinite: true } : { minutes };
      await api("/api/pause", body);
      reply = { ok: true };
    } catch (error) {
      reply = { ok: false, error: error.message };
    }
  }

  busy(false);
  if (!reply.ok) {
    $("state").innerHTML = `<span class="err">could not pause</span> ${reply.error || ""}`;
    return;
  }
  await paint();
}

async function doResume() {
  busy(true);
  let reply = await send({ type: "resume" });
  if (reply.__noworker || (!reply.ok && !reply.error)) {
    staleWorker = true;
    try {
      await api("/api/resume", {});
      reply = { ok: true };
    } catch (error) {
      reply = { ok: false, error: error.message };
    }
  }
  busy(false);
  if (!reply.ok) {
    $("state").innerHTML = `<span class="err">could not resume</span> ${reply.error || ""}`;
    return;
  }
  await paint();
}

async function labelCurrent() {
  if (!current) return;
  const client = $("client").value.trim();
  const category = $("category").value.trim();
  if (!client && !category) {
    $("client").focus();
    return;
  }
  busy(true);
  $("label").textContent = "…";
  try {
    const result = await api("/api/label", {
      signature: {
        app: current.app,
        domain: current.domain,
        title: current.title,
        url: current.url,
      },
      client: client || null,
      category: category || null,
      scope: $("scope").value,
    });
    const made = result.created || {};
    const extra = made.client ? ` · added ${made.client} as a client` : "";
    $("flash").textContent = `Labelled${extra}. Every matching block follows.`;
    $("client").value = "";
    $("category").value = "";
    setTimeout(() => { $("flash").textContent = ""; }, 4000);
    await paint();
  } catch (error) {
    $("flash").innerHTML = `<span class="err">${error.message}</span>`;
  } finally {
    busy(false);
    $("label").textContent = "Label this";
  }
}

/* -- wiring ------------------------------------------------------------- */

$("open").addEventListener("click", () => {
  chrome.tabs.create({ url: base(config.endpoint) });
  window.close();
});

$("pause-row").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-minutes]");
  if (!button) return;
  const raw = button.dataset.minutes;
  setPause(raw === "" ? null : Number(raw));
});

$("resume").addEventListener("click", doResume);
$("label").addEventListener("click", labelCurrent);

for (const id of ["client", "category"]) {
  $(id).addEventListener("keydown", (event) => {
    if (event.key === "Enter") labelCurrent();
  });
}

$("endpoint").addEventListener("change", async () => {
  const value = $("endpoint").value.trim();
  if (!value) return;
  await chrome.storage.local.set({ endpoint: value });
  config.endpoint = value;
  await send({ type: "report" });
  paint();
});

window.addEventListener("unload", () => {
  if (ticker) clearInterval(ticker);
});

paint();
