"use strict";

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

function clockTime(unixSeconds) {
  try {
    return new Date(unixSeconds * 1000).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch (_) {
    return "";
  }
}

function base(endpoint) {
  try { return new URL(endpoint).origin; } catch (_) { return "http://127.0.0.1:8734"; }
}

async function send(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (reply) => {
      void chrome.runtime.lastError;
      resolve(reply || {});
    });
  });
}

let config = { endpoint: "http://127.0.0.1:8734/api/ingest/chrome" };

/* The switch is the tracker's, not this popup's, so every control here goes
   through the service worker and then repaints from whatever came back. The
   popup never holds an opinion about whether tracking is on. */

function paintPause(pause) {
  const paused = Boolean(pause && pause.paused);
  document.body.classList.toggle("off", paused);
  $("banner").classList.toggle("on", paused);
  $("resume").hidden = !paused;
  $("pause-row").hidden = paused;
  $("pause-label").hidden = paused;

  if (!paused) return;

  if (pause.indefinite) {
    $("banner-detail").textContent =
      "It stays off until you turn it back on, including after a restart.";
  } else if (pause.until) {
    $("banner-detail").textContent =
      `Recording resumes at ${clockTime(pause.until)}.`;
  } else {
    $("banner-detail").textContent = "Recording is stopped.";
  }
}

async function paint() {
  const reply = await send({ type: "ping" });
  config = reply.config || config;
  $("endpoint").value = config.endpoint;

  const pause = reply.pause || null;
  paintPause(pause);

  if (pause && pause.paused) {
    $("dot").className = "dot bad";
    $("today").textContent = dur(0);
    $("state").textContent = "nothing is being recorded, by either half";
    return;
  }

  try {
    const response = await fetch(`${base(config.endpoint)}/api/status`);
    const status = await response.json();
    const watcher = status.watcher || {};
    const browser = status.browser || {};
    $("dot").className = `dot ${browser.connected ? "ok" : "bad"}`;
    $("today").textContent = dur(status.today_seconds);
    $("state").textContent = browser.connected
      ? `connected · ${browser.heartbeats} heartbeats${
          watcher.current ? ` · now in ${watcher.current.app}` : ""
        }`
      : "tracker is up, but has not seen this extension yet";
  } catch (_) {
    $("dot").className = "dot bad";
    $("today").textContent = "—";
    $("state").innerHTML =
      '<span class="err">tracker not reachable</span> is it running?';
  }
}

function busy(on) {
  for (const button of document.querySelectorAll("button")) {
    button.disabled = on;
  }
}

$("open").addEventListener("click", () => {
  chrome.tabs.create({ url: base(config.endpoint) });
  window.close();
});

$("pause-row").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-minutes]");
  if (!button) return;
  const raw = button.dataset.minutes;
  busy(true);
  const reply = await send(
    raw === "" ? { type: "pause" } : { type: "pause", minutes: Number(raw) }
  );
  busy(false);
  if (!reply.ok) {
    $("state").innerHTML =
      `<span class="err">could not pause</span> ${reply.error || ""}`;
    return;
  }
  paint();
});

$("resume").addEventListener("click", async () => {
  busy(true);
  const reply = await send({ type: "resume" });
  busy(false);
  if (!reply.ok) {
    $("state").innerHTML =
      `<span class="err">could not resume</span> ${reply.error || ""}`;
    return;
  }
  paint();
});

$("endpoint").addEventListener("change", async () => {
  const value = $("endpoint").value.trim();
  if (!value) return;
  await chrome.storage.local.set({ endpoint: value });
  config.endpoint = value;
  await send({ type: "report" });
  paint();
});

paint();
