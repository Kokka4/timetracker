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

let config = { endpoint: "http://127.0.0.1:8734/api/ingest/chrome", paused: false };

async function paint() {
  const reply = await send({ type: "ping" });
  config = reply.config || config;
  $("endpoint").value = config.endpoint;
  $("pause").textContent = config.paused ? "Resume" : "Pause";

  if (config.paused) {
    $("dot").className = "dot";
    $("state").textContent = "paused — no tab data is being sent";
    $("today").textContent = "—";
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
      '<span class="err">tracker not reachable</span> — is it running?';
  }
}

$("open").addEventListener("click", () => {
  chrome.tabs.create({ url: base(config.endpoint) });
  window.close();
});

$("pause").addEventListener("click", async () => {
  config.paused = !config.paused;
  await chrome.storage.local.set({ paused: config.paused });
  if (!config.paused) await send({ type: "report" });
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
