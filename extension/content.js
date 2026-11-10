/* Activity signal.
 *
 * This is what separates "I had the tab open" from "I was working in it" — the
 * difference between a document you left open over lunch and one you spent
 * forty minutes writing in.
 *
 * It counts events. It never reads what you typed, what you selected, or
 * anything on the page: the only things that leave this script are four
 * integers and a boolean for whether media is playing.
 */

"use strict";

const FLUSH_MS = 5000;

let keys = 0;
let clicks = 0;
let scrolls = 0;
let media = 0;
let timer = null;

function schedule() {
  if (timer !== null) return;
  timer = setTimeout(flush, FLUSH_MS);
}

function flush() {
  timer = null;
  if (!keys && !clicks && !scrolls && !media) return;
  const payload = { type: "activity", keys, clicks, scrolls, media };
  keys = clicks = scrolls = media = 0;
  try {
    // The worker may be asleep; the callback exists only to swallow the
    // "receiving end does not exist" error that would otherwise log.
    chrome.runtime.sendMessage(payload, () => void chrome.runtime.lastError);
  } catch (_) {
    /* extension reloading */
  }
}

addEventListener("keydown", () => { keys += 1; schedule(); }, { passive: true, capture: true });
addEventListener("mousedown", () => { clicks += 1; schedule(); }, { passive: true, capture: true });
addEventListener("scroll", () => { scrolls += 1; schedule(); }, { passive: true, capture: true });

addEventListener("play", (event) => {
  if (event.target instanceof HTMLMediaElement) { media = 1; schedule(); }
}, { passive: true, capture: true });

// Leaving the page is the last chance to report what happened on it.
addEventListener("pagehide", flush, { capture: true });
addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") flush();
}, { capture: true });
