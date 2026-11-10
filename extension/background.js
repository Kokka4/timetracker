/* Service worker: the enrichment stream.
 *
 * The one rule this file obeys: it never accumulates time. Manifest V3 kills
 * an idle service worker after about thirty seconds, taking every global
 * variable with it, so any counter kept here would be wrong by design. What it
 * does instead is post "at this timestamp, this tab was frontmost" and let the
 * tracker — a process that is not killed every half minute — turn those into
 * intervals. If this worker dies, the worst case is that the tracker closes the
 * open interval at the last heartbeat and the desktop watcher goes on counting
 * the time as plain browser time with no tab attached.
 *
 * Every listener is registered at the top level, because a worker woken by an
 * event has not run any of your async setup yet.
 */

"use strict";

const DEFAULTS = {
  endpoint: "http://127.0.0.1:8734/api/ingest/chrome",
};

const HEARTBEAT_ALARM = "heartbeat";
const IDLE_SECONDS = 60;
const MIN_POST_GAP_MS = 700;
const REPEAT_AFTER_MS = 20000;
const MAX_TRACKED_TABS = 300;
/* How long a cached pause answer is trusted. Shorter than the heartbeat
   alarm, so a pause that expires on the tracker side is noticed on the next
   beat rather than whenever the user next opens the popup. */
const PAUSE_TTL_MS = 25000;

/* Globals are a cache, never state: every one of them may be gone on the next
   event, and nothing below depends on them surviving. */
let lastKey = null;
let lastPostAt = 0;

/* -- settings ----------------------------------------------------------- */

async function settings() {
  try {
    const stored = await chrome.storage.local.get(DEFAULTS);
    return { ...DEFAULTS, ...stored };
  } catch (_) {
    return { ...DEFAULTS };
  }
}

function baseFrom(endpoint) {
  try {
    return new URL(endpoint).origin;
  } catch (_) {
    return "http://127.0.0.1:8734";
  }
}

/* -- the off switch ------------------------------------------------------
 * The switch itself lives in the tracker, not here. This file holds a cache
 * of the answer and nothing more, because an extension-local flag could only
 * ever stop the browser half: the desktop watcher would carry on recording
 * Chrome time, and a button that silently does a quarter of what it says is
 * worse than no button. Everything below is about keeping the cache honest
 * and the badge truthful. */

async function cachedPause() {
  try {
    return (await chrome.storage.session.get("pause")).pause || null;
  } catch (_) {
    return null;
  }
}

async function paintBadge(entry) {
  const paused = Boolean(entry && entry.paused);
  try {
    await chrome.action.setBadgeText({ text: paused ? "off" : "" });
    if (paused) {
      await chrome.action.setBadgeBackgroundColor({ color: "#d03b3b" });
      await chrome.action.setTitle({
        title: "Local Time Tracker: PAUSED, nothing is being recorded",
      });
    } else {
      await chrome.action.setTitle({ title: "Local Time Tracker" });
    }
  } catch (_) {
    /* no action surface, e.g. during install */
  }
}

async function setPauseState(state) {
  const entry = {
    paused: Boolean(state && state.paused),
    indefinite: Boolean(state && state.indefinite),
    until: (state && state.until) || null,
    reachable: true,
    at: Date.now(),
  };
  try {
    await chrome.storage.session.set({ pause: entry });
  } catch (_) {
    /* ignore */
  }
  await paintBadge(entry);
  return entry;
}

async function refreshPause() {
  const config = await settings();
  try {
    const response = await fetch(`${baseFrom(config.endpoint)}/api/pause`);
    const body = await response.json();
    return await setPauseState(body && body.pause);
  } catch (_) {
    /* The tracker is unreachable, which is not the same as paused and must
       not be shown as it: nothing is being recorded either way, but telling
       someone they paused it when they did not is how you lose a day. */
    const entry = await cachedPause();
    return entry ? { ...entry, reachable: false } : null;
  }
}

async function isPaused() {
  const entry = await cachedPause();
  if (entry && Date.now() - entry.at < PAUSE_TTL_MS) return entry.paused;
  const fresh = await refreshPause();
  return Boolean(fresh && fresh.paused);
}

async function requestPause(minutes) {
  const config = await settings();
  const body = minutes === null ? { indefinite: true } : { minutes };
  const response = await fetch(`${baseFrom(config.endpoint)}/api/pause`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const parsed = await response.json();
  if (!response.ok) throw new Error(parsed.error || `HTTP ${response.status}`);
  return setPauseState(parsed.pause);
}

async function requestResume() {
  const config = await settings();
  const response = await fetch(`${baseFrom(config.endpoint)}/api/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const parsed = await response.json();
  if (!response.ok) throw new Error(parsed.error || `HTTP ${response.status}`);
  return setPauseState(parsed.pause);
}

/* -- activity counters --------------------------------------------------
 * Counts only. Never a keystroke, never a selection, never page text. */

async function bumpActivity(tabId, delta) {
  if (tabId === undefined || tabId === null) return;
  const bag = (await chrome.storage.session.get("activity")).activity || {};
  const key = String(tabId);
  const current = bag[key] || { keys: 0, clicks: 0, scrolls: 0, media: 0 };
  current.keys += Math.max(0, delta.keys | 0);
  current.clicks += Math.max(0, delta.clicks | 0);
  current.scrolls += Math.max(0, delta.scrolls | 0);
  current.media = Math.max(current.media, delta.media ? 1 : 0);
  bag[key] = current;

  const keys = Object.keys(bag);
  if (keys.length > MAX_TRACKED_TABS) {
    for (const stale of keys.slice(0, keys.length - MAX_TRACKED_TABS)) delete bag[stale];
  }
  await chrome.storage.session.set({ activity: bag });
}

async function drainActivity(tabId) {
  const empty = { keys: 0, clicks: 0, scrolls: 0, media: 0 };
  if (tabId === undefined || tabId === null) return empty;
  const bag = (await chrome.storage.session.get("activity")).activity || {};
  const key = String(tabId);
  const taken = bag[key];
  if (!taken) return empty;
  delete bag[key];
  await chrome.storage.session.set({ activity: bag });
  return taken;
}

/* -- the heartbeat ------------------------------------------------------ */

function browserLabel() {
  const brands = (self.navigator.userAgentData && self.navigator.userAgentData.brands) || [];
  const names = brands.map((b) => b.brand).join(" ");
  if (/Brave/i.test(names)) return "Brave";
  if (/Edge/i.test(names)) return "Edge";
  if (/Opera|OPR/i.test(names)) return "Opera";
  if (/Vivaldi/i.test(names)) return "Vivaldi";
  return "Chrome";
}

async function currentTab() {
  try {
    const window_ = await chrome.windows.getLastFocused();
    if (!window_ || !window_.focused) return { focused: false, tab: null };
    const tabs = await chrome.tabs.query({ active: true, windowId: window_.id });
    return { focused: true, tab: tabs && tabs[0] ? tabs[0] : null };
  } catch (_) {
    return { focused: false, tab: null };
  }
}

async function userIsActive() {
  try {
    const state = await chrome.idle.queryState(IDLE_SECONDS);
    return state === "active";
  } catch (_) {
    return true; // the desktop watcher is the authority on this anyway
  }
}

async function report(reason, force = false) {
  const config = await settings();

  /* The gate sits before currentTab() rather than before the fetch, and that
     ordering is the whole point: while paused this worker never asks Chrome
     which page you are on, so there is no URL to leak, drop or forget to
     drop. The tracker refuses heartbeats while paused anyway, but that is a
     second line, not the first. */
  if (await isPaused()) return;

  let { focused, tab } = await currentTab();
  if (focused && !(await userIsActive())) focused = false;

  const activity = await drainActivity(tab ? tab.id : null);
  const busy = activity.keys || activity.clicks || activity.scrolls || activity.media;

  const key = `${focused}|${tab ? tab.url : ""}|${tab ? tab.title : ""}`;
  const now = Date.now();
  if (!force && !busy) {
    if (now - lastPostAt < MIN_POST_GAP_MS) return;
    if (key === lastKey && now - lastPostAt < REPEAT_AFTER_MS) return;
  }
  lastKey = key;
  lastPostAt = now;

  const payload = {
    ts: now / 1000,
    reason,
    browser: browserLabel(),
    focused,
    tab: tab
      ? {
          id: tab.id,
          url: tab.url || "",
          title: tab.title || "",
          incognito: Boolean(tab.incognito),
          audible: Boolean(tab.audible),
        }
      : null,
    activity,
  };

  try {
    const response = await fetch(config.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await chrome.storage.session.set({
      health: { ok: response.ok, at: now, status: response.status, reason },
    });
    /* Every reply carries the pause state, so the common case refreshes the
       cache for free and the dedicated poll is only needed while paused. */
    try {
      const body = await response.json();
      if (body && body.pause) await setPauseState(body.pause);
    } catch (_) {
      /* a reply we cannot parse tells us nothing about the switch */
    }
  } catch (error) {
    // The tracker is not running. Nothing to retry: the next heartbeat carries
    // a fresh timestamp, and stale ones would be worse than none.
    await chrome.storage.session.set({
      health: { ok: false, at: now, error: String(error && error.message), reason },
    });
  }
}

/* -- listeners (top level, always) -------------------------------------- */

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(HEARTBEAT_ALARM, { periodInMinutes: 0.5 });
  chrome.idle.setDetectionInterval(IDLE_SECONDS);
  refreshPause().then(() => report("installed", true));
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(HEARTBEAT_ALARM, { periodInMinutes: 0.5 });
  chrome.idle.setDetectionInterval(IDLE_SECONDS);
  /* A pause that was running when Chrome quit is still running now: the
     tracker kept it, and the badge has to say so before the first beat. */
  refreshPause().then((entry) => {
    if (!entry || !entry.paused) report("startup", true);
  });
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== HEARTBEAT_ALARM) return;
  /* The beat is also the only thing that notices a pause expiring, since a
     paused worker sends no heartbeats whose replies could tell it. */
  refreshPause().then((entry) => {
    if (!entry || !entry.paused) report("alarm", true);
  });
});

chrome.tabs.onActivated.addListener(() => report("tab-activated", true));

chrome.tabs.onUpdated.addListener((_tabId, change, tab) => {
  if (!tab || !tab.active) return;
  if (change.url || change.title || change.status === "complete" || "audible" in change) {
    report("tab-updated");
  }
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  await drainActivity(tabId);
});

chrome.windows.onFocusChanged.addListener((windowId) => {
  report(windowId === chrome.windows.WINDOW_ID_NONE ? "blur" : "focus", true);
});

/* Single-page apps change the URL without a navigation, which is most of a
   working day: Gmail, Notion, Instantly, Clay. */
chrome.webNavigation.onHistoryStateUpdated.addListener((details) => {
  if (details.frameId === 0) report("spa-navigation");
});
chrome.webNavigation.onCommitted.addListener((details) => {
  if (details.frameId === 0) report("navigation");
});

chrome.idle.onStateChanged.addListener((state) => {
  report(`idle-${state}`, true);
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message) return false;

  if (message.type === "activity") {
    const tabId = sender && sender.tab ? sender.tab.id : null;
    (async () => {
      /* Counters are discarded rather than banked while paused. Banking them
         would hand the tracker a keystroke count for the paused stretch the
         moment it resumed, which is exactly the thing being switched off. */
      if (!(await isPaused())) await bumpActivity(tabId, message);
      sendResponse({ ok: true });
    })();
    return true;
  }

  if (message.type === "ping") {
    (async () => {
      const [config, session] = await Promise.all([
        settings(),
        chrome.storage.session.get("health"),
      ]);
      const pause = await refreshPause();
      sendResponse({ ok: true, config, health: session.health || null, pause });
    })();
    return true;
  }

  if (message.type === "pause") {
    (async () => {
      try {
        const pause = await requestPause(
          message.minutes === undefined ? null : message.minutes
        );
        sendResponse({ ok: true, pause });
      } catch (error) {
        sendResponse({ ok: false, error: String(error && error.message) });
      }
    })();
    return true;
  }

  if (message.type === "resume") {
    (async () => {
      try {
        const pause = await requestResume();
        await report("resumed", true);
        sendResponse({ ok: true, pause });
      } catch (error) {
        sendResponse({ ok: false, error: String(error && error.message) });
      }
    })();
    return true;
  }

  if (message.type === "report") {
    report("popup", true).then(() => sendResponse({ ok: true }));
    return true;
  }

  return false;
});

// A worker woken for any reason makes sure the alarm still exists, and that
// the badge still reflects the tracker rather than whatever it said when the
// worker was last killed.
chrome.alarms.get(HEARTBEAT_ALARM).then((alarm) => {
  if (!alarm) chrome.alarms.create(HEARTBEAT_ALARM, { periodInMinutes: 0.5 });
});
cachedPause().then((entry) => {
  if (entry) paintBadge(entry);
});
