// The Wheel: three mode views (Day, Night, Recovery) and the tools, hash-routed.
// Built on the aureliusxradix instrument; looks his picks of 2026-10-20 (style.css).
"use strict";
// screenshot aid: ?shot holds the load event while the data arrives
if (new URLSearchParams(location.search).has("shot")) { const i = new Image(); i.src = "/__wait?ms=3000"; i.hidden = true; document.body?.append(i); }

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { events: [], areas: [], today: "", mode: "night", range: "all", date: "", dateOnlyMode: false, kind: null, area: null, facet: null, allKinds: false, favOnly: false };

/* Reading and comfort (the Roadmap's "Your way around", built 2026-10-22). Kept in this browser, set on <html> as
   data-size, data-font, data-space, data-contrast and data-motion; style.css does the rest. The site ships no web fonts,
   so the easy-reading font is OpenDyslexic where the device has it installed, with Verdana in its place elsewhere. */
const COMFORT_KEY = "wheel.comfort";
const COMFORT = [
  ["size", "Text size", [["", "Standard"], ["big", "Bigger"], ["bigger", "Biggest"]]],
  ["font", "Font", [["", "The Wheel's own"], ["plain", "Plain"], ["easy", "Easy reading"]],
    "Plain is your device's everyday font. Easy reading uses OpenDyslexic when your device has it installed, and Verdana otherwise."],
  ["space", "Spacing", [["", "Standard"], ["wide", "More space between lines, words and letters"]]],
  ["contrast", "Contrast", [["", "Standard"], ["high", "Higher: solid backgrounds, every line at full strength"]]],
  ["motion", "Motion", [["", "Follow my device"], ["less", "Less motion"]]],
];
const comfort = (() => { try { return JSON.parse(localStorage.getItem(COMFORT_KEY) || "{}"); } catch { return {}; } })();
function applyComfort() {
  for (const [k] of COMFORT) {
    if (comfort[k]) document.documentElement.dataset[k] = comfort[k]; else delete document.documentElement.dataset[k];
  }
}
applyComfort();

/* Simple and Full (his ask 2026-10-22: "there is a lot of info on the screen for new users to navigate, a simple/complex
   mode/view is probably on call"). Simple puts the list first, with the filters behind one button and the tools in a
   menu; Full shows everything at once. A first visit on a phone-sized screen starts Simple; a choice is kept here. */
const UI_KEY = "wheel.ui";
let UI = (() => { try { return localStorage.getItem(UI_KEY); } catch { return null; } })() || (matchMedia("(max-width: 700px)").matches ? "simple" : "full");
document.documentElement.dataset.ui = UI;
function setUI(v, keep = true) {
  UI = v;
  document.documentElement.dataset.ui = v;
  if (keep) try { localStorage.setItem(UI_KEY, v); } catch {}
  $$("[data-ui]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.ui === v)));
  $$("input[data-uiradio]").forEach((r) => (r.checked = r.value === v));
  const sw = $("#ui-switch");  // one switch, in the same corner in both views (beta note 2026-10-23)
  if (sw) { sw.setAttribute("aria-checked", String(v === "simple")); sw.title = v === "simple" ? "Simple view is on. Tap for everything at once." : "Everything at once. Tap for the simple view."; }
}
function setMenu(open) {
  document.documentElement.classList.toggle("menu-open", open);
  $("#menu-btn").setAttribute("aria-expanded", String(open));
  $("#menu-panel").hidden = !open;
  if (open) $("#menu-panel a")?.focus();
}

/* Favourite kinds (his ask 2026-10-20: "personalisation of tags, as in a favorite system"). Kept in this browser only:
   The Wheel never learns what anyone favours. Starred kinds come first, and "My kinds" shows only listings with them. */
const FAVS_KEY = "wheel.favkinds";
const favs = new Set((() => { try { return JSON.parse(localStorage.getItem(FAVS_KEY) || "[]"); } catch { return []; } })());
function saveFavs() { try { localStorage.setItem(FAVS_KEY, JSON.stringify([...favs])); } catch {} }

/* Each mode is its own view: its own look, its own words, its own way of finding. */
const MODES = {
  day: {
    look: "day", title: "Day",
    lede: "Shifts that need hands, workshops and skillshares. Help where you can.",
    search: "Search: cooking, set-up, Orewa…",
    ranges: [["week", "Next 7 days", "7 days"], ["weekend", "This weekend", "Weekend"], ["all", "Everything coming up", "All"]],
    facetLabel: "Help with",
  },
  night: {
    look: "night", title: "Night",
    lede: "Gigs, socials and gatherings. Where to go out.",
    search: "Search: kava, poetry, Orewa…",
    ranges: [["tonight", "Tonight", "Tonight"], ["weekend", "This weekend", "Weekend"], ["week", "Next 7 days", "7 days"], ["all", "Everything coming up", "All"]],
  },
  recovery: {
    look: "recovery", title: "Recovery",
    lede: "Retreats, rest and restoring. Time to come back to yourself.",
    search: "Search: breathwork, retreat, sound bath…",
    ranges: [["week", "Next 7 days", "7 days"], ["weekend", "This weekend", "Weekend"], ["all", "Everything coming up", "All"]],
    facetLabel: "How long",
  },
};
const LENGTHS = ["An evening or less", "A day", "More than a day"];

// Where the data comes from: the same server locally; wheel.aureliusxradix.com once the page is a shell on the site.
const API = document.body.dataset.api || "";

async function api(path, body, retried = false) {
  const headers = {};
  const token = window.createWheel ? W.session() : null;
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(API + path, body === undefined ? { headers } : { method: "POST", headers, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({ error: "The Wheel sent back something unreadable." }));
  if (res.status === 401 && data.login && !retried && W) {
    // a member whose session lapsed signs back in by itself: one proof, about a second
    const st = await W.status();
    if (st.member) { const l = await W.login(); if (l.ok) return api(path, body, true); }
  }
  if (!res.ok) throw new Error(data.error || `The Wheel answered ${res.status}.`);
  return data;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 2600);
}

/* ---------- members: the device holds the key; the service sees only commitments and proofs ---------- */
const W = window.createWheel ? window.createWheel({ api: API + "/api/zk", zk: document.body.dataset.zk || "zk/" }) : null;
let ACTIVE = null;  // his "Do A-F" (2026-10-22): the cover claim counts members in good standing, beside the total
async function loadActive() { try { ACTIVE = (await api("/api/active")).active; } catch { ACTIVE = null; } }
const MIN_CROWD = 3;   // proposal (rep study): no check-in proof offered below 3 members; his to set
const WARN_CROWD = 10; // proposal: under 10, say plainly that a proof hides little

function crowdLine(size) {
  if (size < MIN_CROWD) return `The Wheel has ${size} member${size === 1 ? "" : "s"}. Check-ins open once ${MIN_CROWD} people have joined, so a check-in can hide who made it.`;
  const a = ACTIVE;  // members in good standing (Regular and up), from the hub; null until it answers
  if (a !== null && a < WARN_CROWD) return `You are one of ${size} members; ${a} ${a === 1 ? "has" : "have"} rep from work others confirmed. A check-in proves that a member was there and keeps which one to them. Spare accounts add names and leave the people the same, so count on the ${a} active ${a === 1 ? "member" : "members"} as your cover: among so few, a check-in still narrows it a lot. It gets stronger as people join and take part.`;
  if (a !== null) return `You are one of ${size} members, ${a} of them active with rep others confirmed. A check-in proves that a member was there and keeps which one to them, among the ${a} active members at least.`;
  if (size < WARN_CROWD) return `You are one of ${size} members. A check-in proves that a member was there and keeps which one to them, though among ${size} people that still narrows it a lot. It gets stronger as people join.`;
  return `You are one of ${size} members. A check-in proves that a member was there and keeps which one to them.`;
}

// Hardened browsers (secureblue's Trivalent among them) switch the JavaScript optimiser off, and WebAssembly with it.
// The proofs need WebAssembly, so say so plainly instead of failing quietly.
const NO_WASM = typeof WebAssembly === "undefined";
const NO_WASM_TEXT = "This browser has WebAssembly switched off, and the proof that logs you in needs it. Hardened browsers do this (secureblue's Trivalent does by default). To fix it for The Wheel only: open the site settings from the icon left of the address, find JavaScript optimisation (V8 optimiser), allow it for this site, and reload. Or use another browser.";

async function loadMe() {
  const box = $("#me-body");
  if (!W) { box.innerHTML = `<p class="status err">The member tools failed to load. Reload the page.</p>`; return; }
  const [st] = await Promise.all([W.status(), loadActive()]);
  if (!st.online) { box.innerHTML = `<p class="status err">The member service is down or busy. Try again in a minute.</p>`; return; }
  if (!st.member) {
    // Two doors, side by side, returning first (2026-10-20: a returning member joined as someone new by accident).
    box.innerHTML = `${st.hasKey ? `<div class="warn">This browser holds a key that is not on the members list. Sign in with your own key, or join as someone new.</div>` : ""}
      <div class="me-doors">
      <div class="card"><h2>Been here before?</h2>
        <p class="lede">Sign in with your key. It is on the Me page of the device you joined on (Your key, then Copy), or wherever you saved it.</p>
        <label for="restore-key">Your key</label><input id="restore-key" type="password" autocomplete="off" spellcheck="false">
        <button type="button" class="primary" data-restore="1">Sign in with my key</button>
        <p class="status" id="restore-status" role="status"></p></div>
      <div class="card"><h2>New here?</h2>
        <p class="lede">Join in one tap. A key is made on this device, and a sealed copy of it joins the members list. The list holds no names. ${esc(crowdLine(st.size))}</p>
        <button type="button" class="quiet" data-join="1">Join as someone new</button>
        <p class="status" id="me-status" role="status"></p></div>
      </div>`;
    return;
  }
  const mine = W.myShowups();
  let me = null, why = "";
  try {
    me = (await api("/api/me")).me;
    if (!me) {
      if (NO_WASM) why = NO_WASM_TEXT;
      else { const l = await W.login(); if (l.ok) me = (await api("/api/me")).me; else why = l.detail || l.why; }
    }
  } catch (e) { why = String(e.message || e); }
  const loginNote = me ? "" : `<div class="warn">Your pen name didn't load. ${esc(why || "The member service did not answer.")}</div>`;
  const standing = me ? `<div class="terms" style="margin-top:.8rem"><div class="term key"><span class="k">Pen name</span><span class="v" style="font-size:1rem">${esc(me.account)}</span></div>
      <div class="term"><span class="k">Tier</span><span class="v">${esc(me.tier_name)}</span></div>
      <div class="term"><span class="k">Rep</span><span class="v">${me.points}</span></div></div>
      <p class="hint">${me.next ? `Next: ${esc(me.next)}. ` : ""}Listings added today: ${me.deposits_today} of ${me.deposit_limit}. Rep comes from listings that pass review and reviews that agree with how a listing settled. <a href="#rep">How rep works</a>.</p>` : "";
  box.innerHTML = `<div class="card"><h2>You're in</h2>
    <p>${esc(crowdLine(st.size))}</p>${loginNote}${standing}
    <div id="me-profile"></div>
    <div id="me-mine"></div>
    <h2 class="sub">Your key</h2>
    <p class="lede">The key lives on this device alone. Keep a copy somewhere only you can reach, such as your password manager, so a new phone can carry on as you. Your key is you: anyone holding it is you on The Wheel. Giving it away gives away you, and whoever hands you a key still holds it.</p>
    <div class="keyrow"><input id="my-key" type="password" readonly value="${esc(W.key() || "")}" aria-label="Your key">
    <button type="button" class="quiet" data-showkey="1">Show</button><button type="button" class="quiet" data-copykey="1">Copy</button></div>
    <h2 class="sub">Where you've checked in</h2>
    ${mine.length ? `<ul class="claims">${mine.map((s) => `<li>${esc(s.label || s.event)}</li>`).join("")}</ul>` : `<p class="lede">Your check-ins show here. At an event, open its listing and tap "I'm here".</p>`}
    <p class="hint">This list is kept on this device only. The Wheel itself never learns who checked in where.</p>
    <h2 class="sub">Sign out</h2>
    <p class="lede">Signing out takes your key and your check-in list off this browser. To come back as ${me ? esc(me.account) : "this pen name"}, you need the key, so copy it first.</p>
    <div class="actions"><button type="button" class="quiet" data-copykey="1">Copy my key</button>
    <button type="button" class="danger" data-signout="1">Sign out of this browser</button></div>
    <p class="status" id="signout-status" role="status"></p></div>`;
  if (me) loadMine().catch(() => {});
  if (me) loadProfileEditor(me).catch((e) => { const b = $("#me-profile"); if (b) b.innerHTML = `<p class="status err">${esc(e.message)}</p>`; });
}

async function joinWheel(btn) {
  if (!btn.dataset.sure) {  // one more tap: a returning member should sign in, not start over
    btn.dataset.sure = "1";
    btn.textContent = "Yes, make me a new pen name";
    $("#me-status").textContent = "Joined before? Sign in with your key instead, on the left. Joining again makes a second, separate you.";
    return;
  }
  $("#me-status").textContent = "Joining. This device does a few seconds of work first, which keeps bulk sign-ups slow.";
  const r = await W.join();
  if (!r.ok) { $("#me-status").textContent = r.why === "storage" ? "This browser refused to keep the key (a private window?). Try a normal window." : r.why === "work" ? "The join check failed. Tap Join again." : "The member service failed to answer. Try again in a moment."; return; }
  toast("Joined");
  loadMe();
}

async function signIn() {
  const out = $("#restore-status");
  if (!W.restore($("#restore-key").value)) { out.textContent = "A key from The Wheel is 64 letters and numbers. Check what you pasted."; return; }
  const st = await W.status();
  if (!st.member) { W.signOut(); out.textContent = "That key matches no member of this Wheel. Check you copied all of it."; return; }
  toast("Signed in");
  loadMe();
}

function signOut(btn) {
  if (!btn.dataset.sure) {
    btn.dataset.sure = "1";
    btn.textContent = "Yes, sign out";
    $("#signout-status").textContent = "Have you copied your key? It is the one way back to this pen name; the pen name stays on the list either way.";
    return;
  }
  W.signOut();
  forgetSavedList();
  toast("Signed out of this browser");
  loadMe();
}

async function checkIn(btn) {
  const box = btn.closest(".checkin");
  const code = $("input", box).value.trim();
  const out = $(".status", box);
  if (!/^[A-Za-z2-9]{6}$/.test(code)) { out.textContent = "The door code is six letters and numbers, shown at the event."; return; }
  const st = await W.status();
  if (!st.member) { out.innerHTML = `Join first, on the <a href="#me">Me</a> page. It takes one tap.`; return; }
  await loadActive();
  if (st.size < MIN_CROWD) { out.textContent = crowdLine(st.size); return; }
  if (NO_WASM) { out.textContent = NO_WASM_TEXT; return; }
  btn.disabled = true;
  out.textContent = "Making your proof on this device. This takes a few seconds.";
  try {
    const r = await W.showup(box.dataset.event, code, box.dataset.label);
    out.textContent = r.ok ? `Checked in. ${r.count} ${r.count === 1 ? "person has" : "people have"} checked in here.`
      : ({ again: "You've already checked in here.", code: "That code is wrong for this event. Check it with the host.", closed: "Check-in for this event is closed.", notmember: "Join first, on the Me page.", root: "The members list just changed. Tap again." }[r.why] || "That check-in failed. Try again.");
  } catch (e) { out.textContent = "Your device failed to make the proof. Try again, or on another device."; }
  btn.disabled = false;
}

async function openCheckin(btn) {
  const id = btn.dataset.opencheckin;
  const out = btn.closest(".actions").nextElementSibling;
  const r = await api("/api/zk/checkin", { event: id }).catch((e) => ({ ok: false, why: e.message }));
  if (!r.ok) { out.textContent = "Opening check-in failed: " + (r.why || "the member service failed to answer") + "."; return; }
  const closes = new Date(r.closes).toLocaleTimeString("en-NZ", { hour: "2-digit", minute: "2-digit" });
  out.innerHTML = `<div class="doorcode">${esc(r.code)}</div><p class="hint">Show this at the door. It works until ${esc(closes)}. The Wheel keeps only a fingerprint of it to check against, and opening check-in again makes a new one.</p>`;
}

/* ---------- look ---------- */
function setLook(look) { document.documentElement.dataset.look = look; }

/* ---------- dates ---------- */
const d = (iso) => new Date(iso + "T12:00:00");
const fmtMonth = (iso) => d(iso).toLocaleDateString("en-NZ", { month: "long", year: "numeric" });
const fmtDay = (iso) => d(iso).toLocaleDateString("en-NZ", { weekday: "short" });
const fmtShort = (iso) => d(iso).toLocaleDateString("en-NZ", { weekday: "short", day: "numeric", month: "short" });
const addDays = (iso, n) => { const x = d(iso); x.setDate(x.getDate() + n); return x.toISOString().slice(0, 10); };
// the date a listing is on: a repeating one shows its next date (worked out by the server), never the past one it was found with
const onPicked = (ev) => state.range === "date" && (ev.repeats_on || []).includes(state.date);  // shown on the day picked
const on = (ev) => (onPicked(ev) ? state.date : ev.next_date || ev.start_date);
const onEnd = (ev) => (onPicked(ev) ? state.date : ev.next_end || ev.end_date || ev.start_date);
const mins = (t) => (t ? +t.slice(0, 2) * 60 + +t.slice(3, 5) : null);

function inRange(ev) {
  const t = state.today, r = state.range;
  if (r === "all") return true;
  if (r === "date") {  // a picked day: running then, a shift then, or repeating onto it
    const x = state.date;
    return (on(ev) <= x && onEnd(ev) >= x) || (ev.repeats_on || []).includes(x) || (ev.slots || []).some((s) => s.date === x);
  }
  if (r === "tonight") return on(ev) <= t && onEnd(ev) >= t;
  if (r === "week") return on(ev) <= addDays(t, 7);
  const dow = d(t).getDay(); // 0 Sun .. 6 Sat
  const fri = addDays(t, dow === 0 ? -2 : 5 - dow);
  const sun = addDays(fri, 2);
  return on(ev) <= sun && onEnd(ev) >= (dow === 0 || dow === 6 ? t : fri);
}

function lengthOf(ev) {
  if (ev.end_date && ev.end_date !== ev.start_date) return LENGTHS[2];
  const a = mins(ev.start_time), b = mins(ev.end_time);
  if (a == null || b == null) return null;
  return (b - a + 1440) % 1440 >= 300 ? LENGTHS[1] : LENGTHS[0];
}

/* what a Day listing asks of you: its shift tasks and its stated requirements */
function helpWith(ev) {
  const out = new Set();
  (ev.slots || []).forEach((s) => s.task && out.add(s.task.toLowerCase()));
  (ev.requirements || []).forEach((r) => out.add(r.toLowerCase()));
  return [...out];
}

/* ---------- mode views ---------- */
async function loadEvents() {
  const unreviewed = $("#unreviewed").checked ? "1" : "0";
  const data = await api(`/api/events?unreviewed=${unreviewed}`);
  Object.assign(state, { events: data.events, areas: data.areas, today: data.today });
  const note = $("#offline-note");  // the app's saved copy, while offline (sw.js marks it)
  note.hidden = !data.offline;
  if (data.offline) note.textContent = `You're offline. This is the list as it was at ${new Date(data.at).toLocaleString("en-NZ", { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}.`;
  renderMode();
}

function inMode(ev) { return (ev.modes || []).includes(state.mode); }

function renderHead() {
  const m = MODES[state.mode];
  $("#h-mode").textContent = m.title;
  $("#mode-lede").textContent = m.lede;
  $("#q").placeholder = m.search;
}

// Simple keeps the filters behind one button; its label counts the ones in use
function filterLabel() {
  const n = [state.kind, state.area, state.facet, state.favOnly, state.range === "date", $("#archive").checked, !$("#unreviewed").checked].filter(Boolean).length;
  $("#filter-btn").textContent = n ? `Filters · ${n} on` : "Filters";
}

function renderMode() {
  const m = MODES[state.mode];
  renderHead();
  if (state.range !== "date" && !m.ranges.some(([k]) => k === state.range)) state.range = "all";
  $("#ranges").innerHTML = m.ranges.map(([k, label, short]) => `<button type="button" data-range="${k}" class="${state.range === k ? "on" : ""}"><span class="long">${label}</span><span class="short">${short}</span></button>`).join("") +
    `<label class="pickday${state.range === "date" ? " on" : ""}">On a date <input type="date" id="pickday" min="${state.today}" value="${state.range === "date" ? state.date : ""}"></label>` +
    (state.range === "date" ? `<button type="button" data-onlymode="1" class="${state.dateOnlyMode ? "on" : ""}" aria-pressed="${state.dateOnlyMode}">Only ${m.title}</button>` : "");
  $("#mode-lede").textContent = allModes() ? `Everything on ${fmtShort(state.date)}: Day, Night and Recovery together.` : m.lede;
  renderTerms();
  renderChips();
  renderList();
  renderFollow();
  filterLabel();
}

/* the site's terms grid: three figures for the mode, read at a glance */
function renderTerms() {
  const live = state.events.filter((e) => inMode(e) && !e.past);
  let terms;
  if (state.mode === "day") {
    const today = new Date().toLocaleDateString("en-CA");
    const shifts = live.flatMap((e) => (e.listing_kind === "volunteer" ? e.slots || [] : [])).filter((s) => s.date >= today);
    const prev = state.range;
    state.range = "week"; const week = live.filter(inRange).length; state.range = prev;
    // the next day something is on: a listing already running or repeating counts from today, never from a past date
    const next = live.map((e) => (on(e) < today ? today : on(e))).sort()[0];
    terms = [["This week", week], ["Shifts open", shifts.length], ["Next", next ? (next === today ? "Today" : fmtShort(next)) : "–"]];
  } else if (state.mode === "night") {
    const prev = state.range;
    const count = (r) => { state.range = r; const n = live.filter(inRange).length; state.range = prev; return n; };
    terms = [["Tonight", count("tonight")], ["This weekend", count("weekend")], ["Coming up", live.length]];
  } else {
    terms = LENGTHS.map((l, i) => [["An evening", "A day", "Longer"][i], live.filter((e) => lengthOf(e) === l).length]);
  }
  $("#terms").innerHTML = terms.map(([k, v], i) => `<div class="term${i === 0 ? " key" : ""}"><span class="k">${esc(k)}</span><span class="v">${esc(v)}</span></div>`).join("");
}

function chipRow(label, items, key, current, extra = "") {
  if (!items.length) return "";
  return `<span class="rowlabel">${label}</span>` + items.map(([t, n]) =>
    `<button type="button" class="tag${current === t ? " on" : ""}" data-${key}="${esc(t)}">${esc(t)}${n != null ? `<small>${n}</small>` : ""}</button>`).join("") + extra;
}

function renderChips() {
  const m = MODES[state.mode];
  const live = state.events.filter((e) => inMode(e) && !e.past);
  // facet row: Day = what you could help with; Recovery = how long
  let facets = [];
  if (state.mode === "day") {
    const c = {};
    live.forEach((e) => helpWith(e).forEach((h) => (c[h] = (c[h] || 0) + 1)));
    facets = Object.entries(c).sort((a, b) => b[1] - a[1]).slice(0, 12);
  } else if (state.mode === "recovery") {
    facets = LENGTHS.map((l) => [l, live.filter((e) => lengthOf(e) === l).length]).filter(([, n]) => n);
  }
  $("#facet-row").innerHTML = m.facetLabel ? chipRow(m.facetLabel, facets, "facet", state.facet) : "";
  const tc = {};
  live.forEach((e) => (e.tags || []).forEach((t) => (tc[t] = (tc[t] || 0) + 1)));
  const all = Object.entries(tc).sort((a, b) => favs.has(b[0]) - favs.has(a[0]) || b[1] - a[1] || a[0].localeCompare(b[0]));
  const starred = all.filter(([t]) => favs.has(t)).length;
  const kinds = state.allKinds ? all : all.slice(0, Math.max(10, starred));
  if (state.kind && !kinds.some(([t]) => t === state.kind)) { const k = all.find(([t]) => t === state.kind); if (k) kinds.push(k); }
  const more = all.length > kinds.length || state.allKinds ? `<button type="button" class="linklike" data-morekinds="1">${state.allKinds ? "Fewer kinds" : `All ${all.length} kinds`}</button>` : "";
  const mine = favs.size ? `<button type="button" class="tag mine${state.favOnly ? " on" : ""}" data-favfilter="1" aria-pressed="${state.favOnly}">★ My kinds</button>` : "";
  $("#kind-row").innerHTML = `<span class="rowlabel">Kinds</span>${mine}` + kinds.map(([t, n]) =>
    `<span class="kchip"><button type="button" class="tag${state.kind === t ? " on" : ""}" data-kind="${esc(t)}">${esc(t)}<small>${n}</small></button><button type="button" class="star${favs.has(t) ? " on" : ""}" data-fav="${esc(t)}" aria-pressed="${favs.has(t)}" aria-label="${favs.has(t) ? "Remove from" : "Add to"} my kinds: ${esc(t)}">${favs.has(t) ? "★" : "☆"}</button></span>`).join("") + more;
  $("#area-row").innerHTML = chipRow("Areas", state.areas.map((a) => [a.name, null]), "area", state.area);
}

const allModes = () => state.range === "date" && !state.dateOnlyMode;  // a date alone: every mode at once
function matches(ev) {
  if (!allModes() && !inMode(ev)) return false;
  const q = $("#q").value.trim().toLowerCase();
  if (state.kind && !(ev.tags || []).includes(state.kind)) return false;
  if (state.favOnly && !(ev.tags || []).some((t) => favs.has(t))) return false;
  if (state.area && !(ev.areas || []).includes(state.area)) return false;
  if (state.facet && state.mode === "day" && !helpWith(ev).includes(state.facet)) return false;
  if (state.facet && state.mode === "recovery" && lengthOf(ev) !== state.facet) return false;
  if ((state.range === "date" || !ev.past) && !inRange(ev)) return false;
  if (!q) return true;
  const hay = [ev.name, ev.summary, ev.description, ev.location_name, ev.location_locality, ev.organiser,
    ...(ev.tags || []), ...(ev.areas || []), ...helpWith(ev)].join(" ").toLowerCase();
  return q.split(/\s+/).every((w) => hay.includes(w));
}

function when(ev) {
  let s = ev.start_time ? (ev.end_time ? `${ev.start_time}–${ev.end_time}` : `from ${ev.start_time}`) : "Time TBC";
  if (onEnd(ev) !== on(ev)) s += `, until ${d(onEnd(ev)).toLocaleDateString("en-NZ", { day: "numeric", month: "short" })}`;
  return s;
}

function shiftsTable(ev) {
  if (!(ev.slots || []).length) return "";
  return `<div class="shifts-wrap"><table class="shifts"><thead><tr><th scope="col">When</th><th scope="col">Task</th><th scope="col">People</th></tr></thead><tbody>` +
    ev.slots.map((s) => `<tr><td>${esc(fmtShort(s.date))}, ${esc(s.start || "")}${s.end ? "–" + esc(s.end) : ""}</td><td>${esc(s.task || "")}</td><td>${s.needed ? `<span class="seats" aria-hidden="true">${"<i></i>".repeat(Math.min(s.needed, 20))}</span>${s.needed}` : "?"}</td></tr>`).join("") +
    `</tbody></table></div>`;
}

// The same event added once per date stays as separate listings (his call 2026-10-23), each linked to its next dates
const nameKey = (ev) => (ev.name || "").toLowerCase().replace(/[^a-z0-9āēīōū]+/g, " ").trim();
function laterDates(ev) {
  const k = nameKey(ev), from = on(ev);
  return state.events.filter((e) => e.id !== ev.id && !e.past && nameKey(e) === k && on(e) > from).sort((a, b) => on(a).localeCompare(on(b)));
}

function eventRow(ev, i = 0) {
  const where = [ev.location_name, ev.location_locality && !(ev.location_name || "").includes(ev.location_locality) ? ev.location_locality : null].filter(Boolean).join(", ");
  const unreviewed = ev.review?.state !== "approved";
  const volunteer = ev.listing_kind === "volunteer";
  const chips = [];
  if (volunteer) chips.push(`<span class="chip strong">Helpers wanted</span>`);
  if (ev.chat_platform) chips.push(`<span class="chip">${esc(CHAT[ev.chat_platform] ? `${CHAT[ev.chat_platform]} group` : "Group chat")}</span>`);
  if (ev.recurrence) chips.push(`<span class="chip">Repeats: ${esc(ev.recurrence.slice(0, 50))}</span>`);
  if (ev.recurrence && !ev.next_date && onEnd(ev) < state.today) chips.push(`<span class="chip">Next date: check the link</span>`);
  if (allModes()) (ev.modes || []).forEach((md) => chips.push(`<span class="chip strong">${esc(MODES[md]?.title || md)}</span>`));
  else if ((ev.modes || []).includes("recovery") && state.mode !== "recovery") chips.push(`<span class="chip">Recovery</span>`);
  (ev.areas || []).forEach((a) => chips.push(`<span class="chip">${esc(a)}</span>`));
  (ev.tags || []).slice(0, 4).forEach((t) => chips.push(`<span class="chip">${esc(t)}</span>`));
  const src = ev.website || ev.source?.url;  // where to sign up: the organiser's page first
  const dt = d(on(ev));
  const pct = (x) => `${Math.round((x || 0) * 100)}%`;
  const c = ev.certainty || {};
  const status = ev.status && ev.status !== "confirmed"
    ? `<span class="state flag">${esc(ev.status)}</span>`
    : ev.reopened && unreviewed ? `<span class="state flag" title="Members reported it, so reviewers are checking it again">reported · checking again</span>`
    : unreviewed ? `<span class="state" title="${c.reviews || 0} review(s) so far">waiting${c.reviews ? ` · ${pct(c.for)}` : ""}</span>`
      : `<span class="state ok" title="How sure the reviewers are, weighted by their rep">√ checked · ${pct(c.for)}</span>`;
  return `<article class="ev k${i % 3}${volunteer ? " volunteer" : ""}${ev.past ? " past" : ""}" id="ev-${ev.id}">
    <span class="n">${dt.getDate()} ${dt.toLocaleDateString("en-NZ", { month: "short" })}<small>${fmtDay(on(ev))}</small></span>
    <div class="ev-main">
      <button type="button" class="ev-name" aria-expanded="false" data-open="${ev.id}">${esc(ev.name)}</button>
      <div class="meta"><span>${esc(when(ev))}</span>${where ? `<span>${esc(where)}</span>` : ""}${ev.price ? `<span>${esc(ev.price)}</span>` : ""}</div>
      ${(() => { const more = laterDates(ev); return more.length ? `<div class="more-dates">Also on ${more.slice(0, 4).map((e) => `<a href="#l/${e.id}">${esc(fmtShort(on(e)))}</a>`).join(", ")}${more.length > 4 ? ` and ${more.length - 4} more` : ""}</div>` : ""; })()}
      ${ev.org_note ? `<div class="org-note"><b>Update from the organiser, ${esc(fmtShort(ev.org_note.day))}:</b> ${esc(ev.org_note.text)}</div>` : ""}
      ${shiftsTable(ev)}
      ${(ev.requirements || []).length ? `<div class="line">Asks for: ${esc(ev.requirements.join(", "))}</div>` : ""}
      ${volunteer && src && !ev.past ? `<div><a class="signup" href="${esc(src)}" target="_blank" rel="noopener">Sign up with the organiser</a></div>` : ""}
      <div class="chips">${chips.join("")}</div>
      ${unreviewed ? `<div class="actions inline-review"><button type="button" class="quiet" data-inline="${ev.id}">Review this one</button></div>` : ""}
      <div class="inline-card" hidden></div>
      <div class="more" hidden>
        ${ev.description ? `<p>${esc(ev.description)}</p>` : ""}
        ${ev.claimed_by ? `<div>Kept up to date by <a href="#o/${esc(ev.claimed_by.id)}">${esc(ev.claimed_by.name)}</a>, a proven organiser</div>`
          : ev.organiser ? `<div>Organised by ${esc(ev.organiser)}</div>` : ""}
        ${whereFrom(ev)}
        <div class="actions ev-tools"><button type="button" class="quiet" data-share="${ev.id}">Share</button>
          <a class="quiet" href="${API}/api/ics/${ev.id}.ics" rel="nofollow">Add to calendar</a>
          <button type="button" class="quiet" data-report="1" aria-expanded="false">Report a problem</button></div>
        <div class="share-out"></div>
        ${reportForm(ev)}
        ${ev.past ? "" : `<div class="checkin" data-event="${ev.id}" data-label="${esc(ev.name)}, ${esc(on(ev))}">
          <label for="code-${ev.id}">At the event? Enter the door code</label>
          <div class="keyrow"><input id="code-${ev.id}" type="text" maxlength="6" autocomplete="off" spellcheck="false" placeholder="A1B2C3"><button type="button" class="quiet" data-checkin="1">I'm here</button></div>
          <p class="status" role="status"></p></div>`}
      </div>
    </div>
    ${status}</article>`;
}

/* ---------- getting events to people (2026-10-22): a link to share, the calendar, reports ---------- */
const BASE = API || location.origin;  // the data host also answers share links, with a preview for chat apps
const shareUrl = (id) => `${BASE}/l/${id}`;

async function shareListing(btn) {
  const ev = state.events.find((e) => e.id === btn.dataset.share);
  if (!ev) return;
  const url = shareUrl(ev.id), text = `${ev.name}, ${fmtShort(on(ev))}${ev.start_time ? `, ${ev.start_time}` : ""}`;
  if (navigator.share) {
    try { await navigator.share({ title: ev.name, text, url }); return; } catch (e) { if (e.name === "AbortError") return; }
  }
  try { await navigator.clipboard.writeText(url); toast("Link copied"); return; } catch {}
  const out = $(".share-out", btn.closest(".more"));  // no clipboard: the link, selected, to copy by hand
  out.innerHTML = `<input type="text" readonly value="${esc(url)}" aria-label="Link to this listing">`;
  $("input", out).select();
}

function reportForm(ev) {
  return `<div class="report" hidden>
    <fieldset class="report-why"><legend>What's wrong?</legend>
      <label class="tick"><input type="radio" name="why-${ev.id}" value="wrong"> The details are wrong</label>
      <label class="tick"><input type="radio" name="why-${ev.id}" value="over"> It's cancelled, moved or over</label>
      <label class="tick"><input type="radio" name="why-${ev.id}" value="unsafe"> It's unsafe or harmful</label>
    </fieldset>
    <label for="rnote-${ev.id}">A note for the reviewers, if you like</label>
    <textarea id="rnote-${ev.id}" rows="2" maxlength="300"></textarea>
    <p class="hint">Reviewers read the reason and your note; your pen name stays on the server. Names and phone numbers come out of the note first.</p>
    <div class="actions"><button type="button" class="quiet" data-sendreport="${ev.id}">Send the report</button></div>
    <p class="status" role="status"></p></div>`;
}

async function sendReport(btn) {
  const box = btn.closest(".report"), out = $(".status", box);
  const why = $("input[type=radio]:checked", box)?.value;
  if (!why) { out.textContent = "Pick what's wrong first."; return; }
  btn.disabled = true;
  try {
    const r = await api(`/api/report/${btn.dataset.sendreport}`, { reason: why, note: $("textarea", box).value });
    box.innerHTML = `<p class="status">${r.reopened ? "Thank you. With your report it goes back to review, and reviewers check it again." : "Thank you. Reviewers see your report."}</p>`;
    if (r.reopened) setTimeout(loadEvents, 2500);
  } catch (e) { out.innerHTML = /join/i.test(e.message) ? `Reports come from members: join on the <a href="#me">Me</a> page, one tap.` : esc(e.message); }
  btn.disabled = false;
}

function renderFollow() {
  const m = state.mode, cal = `${BASE}/api/feed.ics?mode=${m}`, rss = `${BASE}/api/feed.xml?mode=${m}`;
  $("#follow-body").innerHTML = `<p class="hint">Checked ${esc(MODES[m].title)} listings, kept up to date by your calendar app or feed reader. It asks The Wheel for the list now and then, the same list everyone following it gets.</p>
    <div class="actions"><a class="quiet" href="${esc(cal.replace(/^https?:/, "webcal:"))}">Subscribe in my calendar</a>
      <button type="button" class="quiet" data-copylink="${esc(cal)}">Copy the calendar link</button>
      <a class="quiet" href="${esc(rss)}">RSS feed</a></div>
    <p class="hint">Google Calendar on a computer: Other calendars, then From URL, and paste the calendar link.</p>
    <h3 class="follow-h">Weekly, on your phone</h3>
    <p class="hint">Every Monday morning, the week ahead in one notification. Install the free ntfy app, add the server <b>ntfy.aureliusxradix.com</b> and subscribe to the topic <b>thewheel</b>. It works without an account, an email or a phone number.</p>
    <div class="actions"><a class="quiet" href="https://ntfy.aureliusxradix.com/thewheel" target="_blank" rel="noopener">Open the topic</a>
      <a class="quiet" href="${esc(`${BASE}/api/digest.xml`)}">Weekly RSS</a></div>`;
}

function grouped(list) {
  let html = "", month = "", i = 0;
  for (const ev of list) {
    const m = fmtMonth(on(ev));
    if (m !== month) { html += `<h2 class="month">${m}</h2>`; month = m; }
    html += eventRow(ev, i++);
  }
  return html;
}

function renderList() {
  const key = (e) => on(e) + (e.start_time || "");
  const shown = state.events.filter(matches);
  const upcoming = shown.filter((e) => !e.past).sort((a, b) => key(a).localeCompare(key(b)));
  const past = $("#archive").checked ? shown.filter((e) => e.past).sort((a, b) => key(b).localeCompare(key(a))) : [];
  let html = "";
  if (state.mode === "day") {  // shifts first: the Day view leads with what needs hands
    const shifts = upcoming.filter((e) => e.listing_kind === "volunteer");
    const rest = upcoming.filter((e) => e.listing_kind !== "volunteer");
    if (shifts.length) html += `<h2 class="month">Helpers wanted</h2>` + shifts.map((e, i) => eventRow(e, i)).join("");
    if (rest.length) html += (shifts.length ? `<h2 class="month">On in the day</h2>` + rest.map((e, i) => eventRow(e, i)).join("") : grouped(rest));
  } else {
    html += grouped(upcoming);
  }
  if (past.length) html += `<h2 class="month archive-head">Already happened</h2>` + past.map((e, i) => eventRow(e, i)).join("");
  if (!html) {
    const any = state.events.some(inMode);
    html = any
      ? state.range === "date" ? `<p class="empty">${allModes() ? "" : `${MODES[state.mode].title} on `}${esc(fmtShort(state.date))} is empty so far. Pick another date, or clear it to see everything coming up.</p>`
      : `<p class="empty">The search and chips hide every listing in ${MODES[state.mode].title}. Clear the search or pick another chip.</p>`
      : `<p class="empty">${MODES[state.mode].title} is empty so far. <a href="#add">Add the first listing</a> from a post, a link or a flyer.</p>`;
  }
  $("#list").innerHTML = html;
  if (state.focus) {  // arrived from a shared link: that listing, opened
    const row = $(`#ev-${state.focus}`);
    state.focus = null;
    if (row) {
      $(".more", row).hidden = false;
      $("[data-open]", row).setAttribute("aria-expanded", "true");
      row.classList.add("focus");
      row.scrollIntoView({ block: "center" });
    }
  }
}

async function openShared(id) {
  $("#unreviewed").checked = true;
  const data = await api("/api/events?unreviewed=1");
  const ev = data.events.find((e) => e.id === id);
  if (!ev) { toast("That listing has gone from The Wheel"); history.replaceState(null, "", "#night"); route(); return; }
  const mode = (ev.modes || []).includes(state.mode) ? state.mode : (ev.modes || ["night"])[0];
  Object.assign(state, { mode, range: "all", kind: null, area: null, facet: null, favOnly: false, focus: id });
  $("#q").value = "";
  if (ev.past) $("#archive").checked = true;
  history.replaceState(null, "", `#${mode}`);
  route();
}

/* Where a listing came from, said plainly (his ruling 2026-10-20: no page online is allowed, labelled, the flyer shown).
   The organiser's page and the page we found it on are two different links. */
function flyerImg(ev) {
  const f = ev.source?.flyer;
  return f && /^[0-9a-f]{16}\.webp$/.test(f)
    ? `<a class="flyer" href="${API}/api/flyer/${f}" target="_blank" rel="noopener"><img src="${API}/api/flyer/${f}" alt="The flyer for ${esc(ev.name)}" loading="lazy"></a>` : "";
}
// listings organised in a group chat (his rulings 2026-10-21): the link to members with the organiser's OK
const CHAT = { signal: "Signal", whatsapp: "WhatsApp", telegram: "Telegram", discord: "Discord", other: "" };
const chatName = (ev) => (CHAT[ev.chat_platform] ? `a ${CHAT[ev.chat_platform]} group` : "a group chat");
function chatLine(ev) {
  if (!ev.chat_platform) return "";
  const guide = `<a href="#chats">Joining group chats: keeping private</a>`;
  if (ev.chat_link) return `<div class="chatline">Organised in ${chatName(ev)}. <a href="${esc(ev.chat_link)}" target="_blank" rel="noopener noreferrer">Join the group</a>. Before you join: ${guide}.</div>`;
  if (ev.chat_link_hidden) return `<div class="chatline">Organised in ${chatName(ev)}. <a href="#me">Sign in</a> to see how to join. ${guide}.</div>`;
  return `<div class="chatline">Organised in ${chatName(ev)}: ask the organiser to add you. ${guide}.</div>`;
}

function whereFrom(ev) {
  const found = ev.source?.url && ev.source.url !== ev.website ? ev.source.url : null;
  const out = [];
  if (ev.website) out.push(`<div><a href="${esc(ev.website)}" target="_blank" rel="noopener">Organiser's page</a></div>`);
  if (ev.tickets_url) out.push(`<div><a href="${esc(ev.tickets_url)}" target="_blank" rel="noopener">Tickets</a></div>`);
  if (found) out.push(`<div><a href="${esc(found)}" target="_blank" rel="noopener">Where we found it</a></div>`);
  if (ev.source?.flyer) out.push(`<div class="hint">Found on a flyer${ev.website ? "" : ", no page online"}.</div>${flyerImg(ev)}`);
  else if (!ev.website && !found && !ev.chat_platform) out.push(`<div class="hint">From a post, no page online.</div>`);
  return chatLine(ev) + out.join("");
}

/* ---------- the listing editor (add and review share it) ---------- */
const FIELDS = [
  ["name", "Name", "wide"], ["start_date", "Date (2026-10-24)"], ["start_time", "Starts (19:30)"],
  ["end_date", "Ends on"], ["end_time", "Ends at"], ["location_name", "Place"], ["location_locality", "Town or suburb"],
  ["price", "Price"], ["recurrence", "Repeats"], ["tags", "Kinds, separated by commas", "wide"],
  ["website", "Organiser's page or post (a link)", "wide"], ["tickets_url", "Tickets (a link)", "wide"],
  ["description", "Description (the organiser's words)", "wide"],
];

// a suggested fix shown to a Reviewer: each changed field, by the editor's own label
const FIELD_LABEL = Object.fromEntries([...FIELDS.map(([k, l]) => [k, l.replace(/ \(.*\)$|, separated by commas$/, "")]),
  ["modes", "Modes"], ["listing_kind", "Kind of listing"], ["requirements", "What it asks for"], ["slots", "Shifts"]]);
const showValue = (k, v) => v == null || (Array.isArray(v) && !v.length) ? "(left empty)"
  : k === "slots" ? v.map((sl) => [sl.date, sl.start && `${sl.start}${sl.end ? `–${sl.end}` : ""}`, sl.task].filter(Boolean).join(" ")).join("; ")
  : k === "modes" ? v.map((m) => MODES[m]?.title || m).join(", ")
  : k === "listing_kind" ? (v === "volunteer" ? "A call for volunteers" : "An event")
  : Array.isArray(v) ? v.join(", ") : String(v);
const suggestionHtml = (sg) => `<div class="rv-sug" data-sid="${sg.id}"><div class="rv-sug-head">A member suggests a fix:</div>
  <ul>${Object.entries(sg.fields).map(([k, v]) => `<li><b>${esc(FIELD_LABEL[k] || k)}:</b> ${esc(showValue(k, v))}</li>`).join("")}</ul>
  <div class="actions"><button type="button" class="quiet" data-sug="use">Use it</button><button type="button" class="quiet" data-sug="drop">Drop it</button></div></div>`;

function slotRow(s = {}) {
  return `<div class="slot">
    <input type="text" data-s="date" value="${esc(s.date || "")}" placeholder="2026-10-31" aria-label="Shift date">
    <input type="text" data-s="start" value="${esc(s.start || "")}" placeholder="09:00" aria-label="Starts">
    <input type="text" data-s="end" value="${esc(s.end || "")}" placeholder="12:00" aria-label="Ends">
    <input type="text" data-s="needed" value="${esc(s.needed ?? "")}" placeholder="People" aria-label="People needed">
    <input type="text" data-s="task" value="${esc(s.task || "")}" placeholder="Task" aria-label="Task">
    <button type="button" class="linklike" data-dropslot="1">Remove</button></div>`;
}

function editorHtml(ev, prefix) {
  const modes = ev.modes || [];
  const vol = ev.listing_kind === "volunteer";
  return `<fieldset class="modes-pick"><legend>Modes</legend>` +
    ["day", "night", "recovery"].map((m) => `<label><input type="checkbox" data-mode="${m}"${modes.includes(m) ? " checked" : ""}> ${MODES[m].title}</label>`).join("") +
    `</fieldset>
    <label for="${prefix}-kind">Kind of listing</label>
    <select id="${prefix}-kind" data-k="listing_kind"><option value="event"${vol ? "" : " selected"}>An event</option><option value="volunteer"${vol ? " selected" : ""}>A call for volunteers</option></select>
    <div class="fields">` + FIELDS.map(([k, label, cls]) => {
    const v = k === "tags" ? (ev.tags || []).join(", ") : ev[k] ?? "";
    const id = `${prefix}-${k}`;
    const input = k === "description"
      ? `<textarea id="${id}" data-k="${k}" rows="4">${esc(v)}</textarea>`
      : `<input id="${id}" data-k="${k}" type="text" value="${esc(v)}">`;
    return `<div class="${cls || ""}"><label for="${id}">${label}</label>${input}</div>`;
  }).join("") + `</div>
    <div class="shift-editor"${vol ? "" : " hidden"}>
      <label for="${prefix}-req">What it asks for, separated by commas</label>
      <input id="${prefix}-req" data-k="requirements" type="text" value="${esc((ev.requirements || []).join(", "))}">
      <div class="slots-label">Shifts</div>
      <div class="slots">${(ev.slots || []).map(slotRow).join("")}</div>
      <button type="button" class="linklike" data-addslot="1">Add a shift</button>
    </div>
    <details class="chat-pick"${ev.chat_platform ? " open" : ""}><summary>Organised in a group chat?</summary>
      <label for="${prefix}-cp">The app</label>
      <select id="${prefix}-cp" data-k="chat_platform"><option value="">(leave empty)</option>${Object.entries(CHAT).map(([k, n]) =>
        `<option value="${k}"${ev.chat_platform === k ? " selected" : ""}>${n || "Another app"}</option>`).join("")}</select>
      <label for="${prefix}-cl">The group's invite link (signed-in members see it)</label>
      <input id="${prefix}-cl" data-k="chat_link" type="text" value="${esc(ev.chat_link || "")}" placeholder="https://signal.group/#…">
      <label class="tick"><input type="checkbox" data-k="chat_link_ok"${ev.chat_link_ok ? " checked" : ""}> The organiser shares this link openly: on a flyer, in a public post, or by asking for it to be passed on.</label>
      <p class="hint">Links to one person (wa.me, signal.me, a Telegram username) stay out. <a href="#chats">Joining group chats</a></p>
      ${ev.chat_text != null ? `<label for="${prefix}-ct">The announcement, as reviewers see it</label>
      <textarea id="${prefix}-ct" data-k="chat_text" rows="5">${esc(ev.chat_text)}</textarea>
      <p class="hint">Senders' names, phone numbers, emails and @handles are already out. Take out anything else that names a person.</p>` : ""}
    </details>`;
}

function readEditor(card) {
  const out = {};
  $$("[data-k]", card).forEach((el) => {
    const k = el.dataset.k;
    out[k] = el.type === "checkbox" ? el.checked
      : k === "tags" || k === "requirements" ? el.value.split(",").map((t) => t.trim()).filter(Boolean) : el.value;
  });
  out.modes = $$("[data-mode]", card).filter((c) => c.checked).map((c) => c.dataset.mode);
  out.slots = out.listing_kind === "volunteer"
    ? $$(".slot", card).map((r) => Object.fromEntries($$("[data-s]", r).map((i) => [i.dataset.s, i.value.trim()]))).filter((s) => s.date)
    : [];
  if (out.listing_kind !== "volunteer") out.requirements = [];
  return out;
}

function dupWarn(ev) {
  return ev.duplicates?.length
    ? `<div class="warn">Maybe already listed: ${ev.duplicates.map((x) => esc(x.name)).join("; ")}. Check before sending.</div>` : "";
}

/* ---------- add ---------- */
let flyer = null;

function showFlyer(file) {
  if (!file) return;
  if (!/^image\/(png|jpeg|webp|gif)$/.test(file.type)) { $("#add-status").textContent = "Flyers need to be PNG, JPG, WEBP or GIF."; return; }
  const r = new FileReader();
  r.onload = () => {
    flyer = { name: file.name, data: r.result };
    $("#drop-label").innerHTML = `<img src="${r.result}" alt="The flyer you added">${esc(file.name)}, <button type="button" class="linklike" id="unpick">remove</button>`;
  };
  r.readAsDataURL(file);
}

async function readDeposit(e) {
  e.preventDefault();
  const text = $("#add-text").value.trim();
  if (!text && !flyer) { $("#add-status").textContent = "Paste a post or a link, or add a flyer."; return; }
  const btn = $("#read-btn");
  btn.disabled = true;
  $("#add-status").className = "status";
  $("#add-status").textContent = "Reading it. This takes between 5 and 30 seconds.";
  $("#found").innerHTML = "";
  try {
    const out = await api("/api/read", { text, image: flyer, chat: $("#add-chat").checked });
    $("#add-status").textContent = out.records.length
      ? `Found ${out.records.length} listing${out.records.length > 1 ? "s" : ""}. Check each one, fix anything wrong, then send it for review.`
      : `Nothing to list. ${out.notes.join(" ")}`;
    $("#found").innerHTML = out.records.map((ev, i) => `<div class="card" data-i="${i}">
      <h2>${esc(ev.name)}</h2>${dupWarn(ev)}${flyerImg(ev)}
      ${ev.chat_platform ? `<div class="warn">From ${esc(chatName(ev))}. Check the cleaned announcement and the group link under "Organised in a group chat" below.</div>` : ""}
      ${!ev.website && !ev.source?.url && !ev.chat_platform ? `<div class="warn">Where can people find this online? If the organiser has a page or a post, put its link in "Organiser's page or post" below. If there is none, it goes out marked "no page online"${ev.source?.flyer ? ", with the flyer shown" : ""}.</div>` : ""}
      ${editorHtml(ev, `f${i}`)}
      <div class="actions"><button type="button" class="primary" data-send="${i}">Send for review</button>
      <button type="button" class="quiet" data-drop="${i}">Leave this one out</button></div></div>`).join("");
    state.found = out.records;
  } catch (err) {
    $("#add-status").className = "status err";
    $("#add-status").textContent = err.message;
  } finally {
    btn.disabled = false;
  }
}

async function sendFound(i) {
  const card = $(`.card[data-i="${i}"]`);
  const rec = { ...state.found[i], ...readEditor(card) };
  try {
    await api("/api/submit", { records: [rec] });
    card.remove();
    toast("Sent for review");
    refreshCount();
  } catch (err) { toast(err.message); }
}

/* ---------- review ---------- */
let reviewMe = null;
function reviewCard(ev) {
  const src = ev.source?.url;
  const c = ev.certainty || { for: 0, against: 0, reviews: 0 };
  const pct = (x) => `${Math.round(x * 100)}%`;
  const sure = c.reviews ? `${c.reviews} review${c.reviews > 1 ? "s" : ""}: ${pct(c.for)} sure it's right, ${pct(c.against)} sure it's wrong. It settles at 70%.` : "No reviews yet.";
  const notes = ev.extraction?.confidence_notes || "";
  const canFix = reviewMe && reviewMe.tier >= 2;
  const canSuggest = reviewMe && !canFix;  // below Reviewer: a fix goes in as a suggestion (his ruling 2026-10-21)
  const modeNames = (ev.modes || []).map((m) => MODES[m]?.title || m).join(", ");
  const where = [ev.location_name, ev.location_locality && !(ev.location_name || "").includes(ev.location_locality) ? ev.location_locality : null].filter(Boolean).join(", ");
  // compact first: what to check, and the two answers; the editor waits behind "Fix details" (2026-10-20, Finishing what's here)
  return `<div class="card rv" data-id="${ev.id}">
      <div class="rv-when">${esc(fmtDay(on(ev)))} ${esc(d(on(ev)).getDate())} ${esc(d(on(ev)).toLocaleDateString("en-NZ", { month: "short" }))} · ${esc(when(ev))}</div>
      <h2>${esc(ev.name)}</h2>
      ${ev.recurrence ? `<div class="rv-where">Repeats: ${esc(ev.recurrence)}${ev.next_date ? ` (shown on its next date; found for ${esc(fmtShort(ev.start_date))})` : ""}</div>` : ""}
      ${where || ev.price ? `<div class="rv-where">${esc([where, ev.price].filter(Boolean).join(" · "))}</div>` : ""}
      ${modeNames ? `<div class="rv-where">Shows in: ${esc(modeNames)}${ev.extraction?.modes_by ? " (set by a batch pass)" : ""}</div>` : ""}
      ${ev.chat_text ? `<div class="source">From ${esc(chatName(ev))}. Check the listing against the announcement (names and numbers taken out):</div><blockquote class="chat-src">${esc(ev.chat_text)}</blockquote>`
        : ev.chat_text_hidden ? `<div class="source">From ${esc(chatName(ev))}. <a href="#me">Sign in</a> to see the announcement it came from.</div>` : ""}
      ${ev.chat_link ? `<div class="source">Group link (members see it): <a href="${esc(ev.chat_link)}" target="_blank" rel="noopener noreferrer">${esc(ev.chat_link)}</a></div>` : ""}
      <div class="source"${ev.chat_platform && !src && !ev.website ? " hidden" : ""}>${src ? `Check it against <a href="${esc(src)}" target="_blank" rel="noopener">the page it came from</a>.` : ev.source?.flyer ? "Read from a flyer. Check the listing against the flyer; the flyer goes out with it." : ev.website ? `Pasted in. Check it against <a href="${esc(ev.website)}" target="_blank" rel="noopener">the organiser's page</a>.` : "Pasted in, with no page to check against."}</div>
      ${flyerImg(ev)}
      ${!ev.website && !src && !ev.chat_platform ? `<div class="warn">No link yet: it goes out marked "no page online".${canFix ? " Add the organiser's page under Fix details if you know it." : ""}</div>` : ""}
      ${notes ? `<div class="warn">${esc(notes)}</div>` : ""}${dupWarn(ev)}
      ${ev.appeal_round != null && ev.appeal_round === ev.round ? `<div class="warn"><b>Turned down, back on appeal.</b> Reviewers who saw it before leave it to others.${ev.appeal_note ? ` The member who added it says: "${esc(ev.appeal_note)}"` : ""}</div>` : ""}
      ${(ev.reports || []).length ? `<div class="warn"><b>${ev.reopened ? "Reported, so it's back in review." : "Reported."}</b> ${ev.reports.map((r) => esc(r.reason) + (r.note ? `: "${esc(r.note)}"` : "")).join("; ")}</div>` : ""}
      <div class="source">${esc(sure)}${ev.my_verdict ? ` You said: ${ev.my_verdict === "approve" ? "right" : "wrong"}.` : ""}</div>
      ${ev.mine ? `<p class="hint">You added this one, so someone else checks it.</p>` : `<div class="actions"><button type="button" class="primary" data-act="approve">It's right</button>
      <button type="button" class="danger" data-act="reject">It's wrong</button>
      ${canFix ? `<button type="button" class="quiet" data-fix="1" aria-expanded="false">Fix details</button>` : ""}
      ${canSuggest ? `<button type="button" class="quiet" data-fix="1" aria-expanded="false">Suggest a fix</button>` : ""}
      ${reviewMe && reviewMe.tier >= 3 ? `<button type="button" class="quiet" data-opencheckin="${ev.id}">Open check-in</button>` : ""}</div>`}
      ${(canFix || canSuggest) && !ev.mine ? `<div class="rv-edit" hidden>${editorHtml(ev, `r-${ev.id}`)}
        <div class="actions"><button type="button" class="quiet" data-act="${canFix ? "save" : "suggest"}">${canFix ? "Save my fixes" : "Send my suggestion"}</button></div>
        <p class="hint">${canFix ? `"It's right" also saves what you changed here.` : "A Reviewer or Steward looks at your fix before it goes on the listing."}</p></div>` : ""}
      ${ev.my_suggestion ? `<p class="hint">Your suggested fix waits for a Reviewer or Steward. Sending another replaces it.</p>` : ""}
      ${(ev.suggestions || []).map(suggestionHtml).join("")}
      <div class="door"></div>
      ${reviewMe && reviewMe.tier < 2 && !ev.mine ? `<p class="hint">Your review counts for ${Math.round((({0:.2,1:.4,2:.7,3:.9})[reviewMe.tier]) * 100)}% as a ${esc(reviewMe.tier_name)}. Your fixes go to a Reviewer first; from the Reviewer tier you fix details yourself. <a href="#rep">How rep works</a>.</p>` : ""}</div>`;
}

let reviewQueue = [], reviewMode = "";
const isPast = (ev) => !!ev.past;  // the server's call, the same one the list makes
const toCheck = (ev) => !ev.mine && !ev.my_verdict;  // a listing waits for others' reviews too, so one you marked stays in the queue
function renderReview() {
  const q = ($("#rq").value || "").trim().toLowerCase();
  const shown = reviewQueue.filter((ev) => (!reviewMode || (ev.modes || []).includes(reviewMode)) && (!q || q.split(/\s+/).every((w) =>
    [ev.name, ev.location_name, ev.location_locality, ev.start_date, ev.source?.url, ...(ev.tags || []), ...(ev.modes || [])].join(" ").toLowerCase().includes(w))));
  // soonest first; your own last; what already happened set aside
  const order = (a, b) => (a.mine - b.mine) || (on(a) + (a.start_time || "")).localeCompare(on(b) + (b.start_time || ""));
  const done = shown.filter((e) => e.my_verdict).sort(order);  // checked by you: set aside, your answer can still change
  const upcoming = shown.filter((e) => !isPast(e) && !e.my_verdict).sort(order);
  const past = shown.filter((e) => isPast(e) && !e.my_verdict).sort(order);
  const open = upcoming.filter((e) => !e.mine).length;
  $("#rq-count").textContent = reviewQueue.length ? `${open} coming up to check${past.length ? `, ${past.length} already happened` : ""}${done.length ? `, ${done.length} checked by you` : ""}.` : "";
  $("#review-list").innerHTML = upcoming.length ? upcoming.map(reviewCard).join("")
    : reviewQueue.length ? `<p class="empty">The search hides everything coming up. Clear it or pick All.</p>`
    : `<p class="empty">All checked. New listings land here when someone adds them.</p>`;
  $("#rq-past").hidden = !past.length;
  $("#rq-past-label").textContent = `Already happened (${past.length}): check these last, or mark them wrong`;
  $("#review-past").innerHTML = $("#rq-past").open ? past.map(reviewCard).join("") : "";
  $("#rq-past").ontoggle = () => { $("#review-past").innerHTML = $("#rq-past").open ? past.map(reviewCard).join("") : ""; };
  $("#rq-done").hidden = !done.length;
  $("#rq-done-label").textContent = `You've checked these (${done.length}): they wait for other reviews, and you can change your answer here`;
  $("#review-done").innerHTML = $("#rq-done").open ? done.map(reviewCard).join("") : "";
  $("#rq-done").ontoggle = () => { $("#review-done").innerHTML = $("#rq-done").open ? done.map(reviewCard).join("") : ""; };
}

async function inlineReview(id, btn) {
  const box = $(".inline-card", btn.closest(".ev-main"));
  if (!box.hidden) { box.hidden = true; box.innerHTML = ""; return; }
  const { events, me } = await api("/api/review");
  reviewMe = me;  // the card's tools depend on the reviewer's tier
  const ev = events.find((e) => e.id === id);
  if (!ev) { toast("Already reviewed. Reloading the list."); loadEvents(); return; }
  box.innerHTML = reviewCard(ev);
  box.hidden = false;
}

async function loadReview() {
  const { events, me } = await api("/api/review");
  reviewMe = me;
  loadAppeals().catch(() => {});
  loadOrgWaiting().catch(() => {});
  loadDupes().catch(() => {});
  setCount(events.filter(toCheck).length);
  reviewQueue = events;
  renderReview();
}

async function review(card, action) {
  try {
    const res = await api(`/api/review/${card.dataset.id}`, { action, edits: readEditor(card) });
    if (action === "suggest") {
      const ev = reviewQueue.find((e) => e.id === card.dataset.id);
      if (ev) ev.my_suggestion = true;
      if (card.closest(".ev")) $(".rv-edit", card).hidden = true; else renderReview();
    } else if (action !== "save") {
      const ev = reviewQueue.find((e) => e.id === card.dataset.id);
      if (ev) ev.my_verdict = action;  // moves to "You've checked these"
      if (res.event?.review?.state !== "pending") reviewQueue = reviewQueue.filter((e) => e.id !== card.dataset.id);  // settled: out of the queue
      const row = card.closest(".ev");
      if (row) { card.remove(); loadEvents(); } else renderReview();
    }
    toast({ approve: "Marked right", save: "Fixes saved", suggest: "Suggestion sent", reject: "Marked wrong" }[action]);
    refreshCount();
  } catch (err) { toast(err.message); }
}

async function useSuggestion(box, action) {
  try {
    const res = await api(`/api/suggestion/${box.dataset.sid}`, { action });
    const ev = reviewQueue.find((e) => e.id === box.closest(".card").dataset.id);
    if (ev) {
      if (res.event) Object.assign(ev, res.event);
      ev.suggestions = (ev.suggestions || []).filter((sg) => String(sg.id) !== box.dataset.sid);
    }
    toast(action === "use" ? "Fix used" : "Suggestion dropped");
    if (box.closest(".ev")) { box.remove(); loadEvents(); } else renderReview();
  } catch (err) { toast(err.message); }
}

function setCount(n) { $$("#pending-count, .menu-count").forEach((el) => (el.textContent = n || "")); }

async function refreshCount() {
  try { const { events } = await api("/api/review"); setCount(events.filter(toCheck).length); } catch (e) { /* the count waits for the next load */ }
}

/* ---------- areas ---------- */
let map, pin, ring, centre = null;

function initMap() {
  if (map || !window.L) return;
  map = L.map("map").setView([-36.75, 174.72], 9);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap contributors" }).addTo(map);
  map.on("click", (e) => { centre = e.latlng; drawRing(); });
  $("#area-reach").addEventListener("input", drawRing);
}

function drawRing() {
  if (!centre) return;
  const km = parseFloat($("#area-reach").value) || 1;
  if (!pin) { pin = L.marker(centre).addTo(map); ring = L.circle(centre, { radius: km * 1000 }).addTo(map); }
  pin.setLatLng(centre); ring.setLatLng(centre); ring.setRadius(km * 1000);
  $("#area-centre").textContent = `Centre set at ${centre.lat.toFixed(4)}, ${centre.lng.toFixed(4)}.`;
}

async function loadAreas() {
  initMap();
  setTimeout(() => map && map.invalidateSize(), 50);
  const { areas } = await api("/api/areas");
  $("#area-list").innerHTML = areas.length ? areas.map((a) => `<li><span><b>${esc(a.name)}</b>, reaches ${a.reach_km} km</span>
    <button type="button" class="quiet" data-del="${a.id}">Remove</button></li>`).join("")
    : `<li class="hint">No areas yet. Set the first one on the map.</li>`;
  if (map) {
    (loadAreas.layers || []).forEach((l) => l.remove());
    loadAreas.layers = areas.map((a) => L.circle([a.lat, a.lng], { radius: a.reach_km * 1000, weight: 1, fillOpacity: 0.08 }).bindTooltip(a.name).addTo(map));
  }
}

const WHY = { same: "the same words", close: "one letter apart", inside: "one sits inside the other" };
async function loadKinds() {
  const box = $("#kinds-tidy");
  let k;
  try { k = await api("/api/kinds"); } catch (e) { box.innerHTML = `<p class="hint">Stewards tidy the kinds. ${esc(e.message)}</p>`; return; }
  const rows = k.suggestions.map((s) => `<li><span><b>${esc(s.merge)}</b> (${s.n_merge}) into <b>${esc(s.keep)}</b> (${s.n_keep}), ${WHY[s.why]}</span>
    <span class="actions"><button type="button" class="quiet" data-kmerge="${esc(s.merge)}" data-kkeep="${esc(s.keep)}">Merge</button>
    <button type="button" class="quiet" data-kapart="${esc(s.merge)}" data-kkeep="${esc(s.keep)}">Keep apart</button></span></li>`).join("");
  const done = k.merged.map((m) => `<li><span><b>${esc(m.alias)}</b> shows as <b>${esc(m.canonical)}</b></span>
    <button type="button" class="quiet" data-kundo="${esc(m.alias)}">Undo</button></li>`).join("");
  box.innerHTML = `<p class="hint">${k.kinds} kinds in use, ${k.suggestions.length} suggestion${k.suggestions.length === 1 ? "" : "s"}.</p>
    ${rows ? `<ul class="area-list kinds-list">${rows}</ul>` : `<p class="hint">Every kind looks tidy right now.</p>`}
    ${done ? `<h3 class="rm-group">Merged</h3><ul class="area-list kinds-list">${done}</ul>` : ""}`;
}
async function kindsAct(body, msg) {
  try { await api("/api/kinds", body); toast(msg); loadKinds(); } catch (e) { toast(e.message); }
}

async function saveArea(e) {
  e.preventDefault();
  const status = $("#area-status");
  if (!centre) { status.textContent = "Click the map to set the centre first."; return; }
  try {
    await api("/api/areas", { name: $("#area-name").value, lat: centre.lat, lng: centre.lng, reach_km: parseFloat($("#area-reach").value) });
    toast("Area saved");
    $("#area-name").value = ""; centre = null;
    if (pin) { pin.remove(); ring.remove(); pin = ring = null; }
    status.textContent = "";
    loadAreas();
  } catch (err) { status.textContent = err.message; }
}

/* ---------- routing + wiring ---------- */
/* ---------- the first-visit guide (his ask 2026-10-20: "pop-up when loading the page, which shows people how to use it
   and gives context"). Shown once per browser, reopened from "How it works". ---------- */
const GUIDE = [
  ["Welcome to The Wheel", `<p>Community events gathered in one place, starting in Auckland and open to anywhere. People add what they find, and other people check it. Each listing links to its organiser when there is a page.</p>`],
  ["Three ways in", `<p><b>Day</b>: workshops, skillshares and volunteer shifts. <b>Night</b>: gigs, socials and evening gatherings. <b>Recovery</b>: retreats, sound baths, breathwork and rest.</p><p>Switch at the top. Each mode has its own look.</p>`],
  ["Add what you find", `<p>Under <b>Add a listing</b>, paste a post or a link, or drop in a flyer. The Wheel reads it and fills in the listing. You check it and send it for review.</p><p>Members check each listing before it shows as checked. Their reviews count by their <a href="#rep">rep</a>.</p>`],
  ["Your place, on your device", `<p>On <b>Me</b>, one tap makes you a key and a pen name. The key is the whole sign-up, and it stays on your device.</p><p>Copy your key somewhere safe, like a password manager. With it you sign in on any device as the same pen name. <a href="#rep">Rep</a> grows as your listings and reviews hold up, and it opens more of the tools.</p>`],
  ["More is coming soon", `<p>This is version one of The Wheel. Private profiles, a volunteer layer, a community board and more are on the way as people join.</p><p>See what comes next, and what each stage waits for, on the <a href="#roadmap">Roadmap</a>.</p>`],
];
let guideAt = 0, guideFrom = null;
function showGuideStep() {
  const [h, body] = GUIDE[guideAt];
  $("#guide-step").textContent = `${guideAt + 1} of ${GUIDE.length}`;
  $("#guide-h").textContent = h;
  $("#guide-body").innerHTML = body;
  $("#guide-back").hidden = guideAt === 0;
  $("#guide-next").textContent = guideAt === GUIDE.length - 1 ? "Show me the events" : "Next";
}
function openGuide() {
  guideAt = 0; guideFrom = document.activeElement;
  $("#guide").hidden = false; showGuideStep(); $("#guide-next").focus();
}
function closeGuide() {
  $("#guide").hidden = true;
  try { localStorage.setItem("wheel.guided", "1"); } catch {}
  if (guideFrom && guideFrom.focus) guideFrom.focus();
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && document.documentElement.classList.contains("menu-open")) { setMenu(false); $("#menu-btn").focus(); }
  if (e.key === "Escape" && !$("#guide").hidden) closeGuide();
});
// the Menu closes on a click anywhere outside it (his ask 2026-10-23: one Menu in both views, in place of "Additional info")
document.addEventListener("click", (e) => {
  if (document.documentElement.classList.contains("menu-open") && !e.target.closest("#menu-panel, #menu-btn")) setMenu(false);
});

async function loadFund() {  // the pool toward The Wheel's own AI (his ask 2026-10-23): total and count only
  const f = await api("/api/fund");
  const pct = f.goal ? Math.min(100, (f.raised / f.goal) * 100) : 0;
  $("#fund-fill").style.width = `${pct.toFixed(1)}%`;
  const nz = (n) => `NZ$${Math.round(n).toLocaleString("en-NZ")}`;
  $("#fund-line").textContent = `${nz(f.raised)} raised of ${nz(f.goal)}${f.gifts ? `, from ${f.gifts} ${f.gifts === 1 ? "gift" : "gifts"}` : ""}.`;
}

async function loadRoadmap() {
  const [g, ev] = await Promise.all([W ? W.status() : { size: 0 }, api("/api/events?unreviewed=1"), loadActive()]);
  loadFund().catch(() => ($("#fund-line").textContent = "The fund's total loads with the next update."));
  const n = g.size || 0, a = ACTIVE ?? 0;
  $("#rm-members").textContent = n;
  $("#rm-active").textContent = ACTIVE ?? "…";
  $("#rm-checked").textContent = `${ev.events.filter((e) => e.review?.state === "approved").length} of ${ev.events.length}`;
  $$("#rm-stages li").forEach((li) => {
    const at = +li.dataset.at, by = li.dataset.by === "active" ? a : n, word = li.dataset.by === "active" ? "active member" : "member";
    li.classList.toggle("reached", by >= at);
    $(".stage-state", li).textContent = by >= at ? " Reached." : ` ${at - by} more ${word}${at - by === 1 ? "" : "s"} to go.`;
  });
}

function route() {
  const view = (location.hash.slice(1) || "night").split("/")[0];
  if (view === "l") { openShared(location.hash.slice(1).split("/")[1]).catch((e) => toast(e.message)); return; }
  const isMode = view in MODES;
  if (isMode && state.mode !== view) { state.mode = view; state.facet = null; state.kind = null; }
  setLook(MODES[state.mode].look);
  $("#view-mode").hidden = !isMode;
  $$(".view").forEach((v) => { if (v.id !== "view-mode") v.hidden = v.id !== `view-${view}`; });
  $$(".top nav a, .add-cta").forEach((a) => a.classList.toggle("on", a.dataset.view === view || (a.dataset.view === "events" && isMode)));
  $$(".menu-events").forEach((a) => a.setAttribute("href", `#${state.mode}`));
  setMenu(false);
  $("#events-link").setAttribute("href", `#${state.mode}`);
  if (isMode) renderHead();
  if (isMode) loadEvents().catch((e) => ($("#list").innerHTML = `<p class="empty">${esc(e.message)}</p>`));
  if (view === "review") loadReview().catch((e) => toast(e.message));
  if (view === "areas") { loadAreas().catch((e) => toast(e.message)); loadKinds(); }
  if (view === "roadmap") loadRoadmap().catch((e) => toast(e.message));
  if (view === "p") loadProfile(location.hash.slice(1).split("/")[1]).catch((e) => ($("#profile-body").innerHTML = `<p class="status err">${esc(e.message)}</p>`));
  if (view === "support") loadSupport().catch((e) => ($("#support-buy").innerHTML = `<p class="status err">${esc(e.message)}</p>`));
  if (view === "comfort") { renderComfort(); renderInstall(); }
  if (view === "board") loadBoard().catch((e) => ($("#board").innerHTML = `<p class="status err">${esc(e.message)}</p>`));
  if (view === "s") loadSeries(location.hash.slice(1).split("/")[1]).catch((e) => ($("#series").innerHTML = `<p class="status err">${esc(e.message)}</p>`));
  if (view === "org") { (state.events.length ? Promise.resolve() : api("/api/events?unreviewed=1").then((d) => (state.events = d.events))).then(loadOrg).catch((e) => ($("#org-body").innerHTML = `<p class="status err">${esc(e.message)}</p>`)); }
  if (view === "o") loadPublicOrg(location.hash.slice(1).split("/")[1]);
  if (view === "log") loadLog().catch((e) => ($("#modlog").innerHTML = `<li class="status err">${esc(e.message)}</li>`));
  if (view === "me") loadMe().catch((e) => ($("#me-body").innerHTML = `<p class="status err">${esc(e.message)}</p>`));
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("button, a");
  if (!t) return;
  if (t.dataset.guide) { e.preventDefault(); setMenu(false); openGuide(); return; }
  if (t.dataset.kmerge) kindsAct({ action: "merge", merge: t.dataset.kmerge, keep: t.dataset.kkeep }, `Merged into ${t.dataset.kkeep}`);
  if (t.dataset.kapart) kindsAct({ action: "keep", merge: t.dataset.kapart, keep: t.dataset.kkeep }, "Kept apart");
  if (t.dataset.kundo) kindsAct({ action: "undo", merge: t.dataset.kundo }, "Merge undone");
  if (t.closest("#guide-body") && t.getAttribute("href")?.startsWith("#")) { closeGuide(); return; }  // a link in the guide: close it, then go
  if (t.dataset.guidenav) {
    const next = guideAt + Number(t.dataset.guidenav);
    if (next >= GUIDE.length) { closeGuide(); location.hash = `#${state.mode}`; return; }
    guideAt = Math.max(0, next); showGuideStep(); return;
  }
  if (t.dataset.guideclose) { closeGuide(); return; }
  if (t.dataset.range) { state.range = t.dataset.range; renderMode(); }
  if (t.dataset.onlymode) { state.dateOnlyMode = !state.dateOnlyMode; renderMode(); }
  if (t.dataset.morekinds) { state.allKinds = !state.allKinds; renderChips(); }
  if (t.dataset.fav) { const k = t.dataset.fav; favs.has(k) ? favs.delete(k) : favs.add(k); saveFavs(); if (!favs.size) state.favOnly = false; renderChips(); renderList(); return; }
  if (t.dataset.favfilter) { state.favOnly = !state.favOnly; renderChips(); renderList(); filterLabel(); return; }
  if (t.dataset.kind) { state.kind = state.kind === t.dataset.kind ? null : t.dataset.kind; renderChips(); renderList(); filterLabel(); }
  if (t.dataset.area) { state.area = state.area === t.dataset.area ? null : t.dataset.area; renderChips(); renderList(); filterLabel(); }
  if (t.dataset.facet) { state.facet = state.facet === t.dataset.facet ? null : t.dataset.facet; renderChips(); renderList(); filterLabel(); }
  if (t.dataset.open) {
    const more = $(".more", t.closest(".ev-main"));
    more.hidden = !more.hidden;
    t.setAttribute("aria-expanded", String(!more.hidden));
  }
  if (t.id === "pick") $("#add-file").click();
  if (t.id === "unpick") { flyer = null; $("#add-file").value = ""; $("#drop-label").innerHTML = `Drop a flyer here, or <button type="button" id="pick" class="linklike">choose an image</button>`; }
  if (t.dataset.send) sendFound(t.dataset.send);
  if (t.dataset.drop) $(`.card[data-i="${t.dataset.drop}"]`).remove();
  if (t.dataset.act) review(t.closest(".card"), t.dataset.act);
  if (t.dataset.sug) useSuggestion(t.closest("[data-sid]"), t.dataset.sug);
  if (t.dataset.fix) { const ed = $(".rv-edit", t.closest(".card")); ed.hidden = !ed.hidden; t.setAttribute("aria-expanded", String(!ed.hidden)); }
  if (t.dataset.rqmode !== undefined) { reviewMode = t.dataset.rqmode; $$("[data-rqmode]").forEach((b) => b.classList.toggle("on", b === t)); renderReview(); }
  if (t.dataset.inline) inlineReview(t.dataset.inline, t).catch((err) => toast(err.message));
  if (t.dataset.addslot) $(".slots", t.closest(".shift-editor")).insertAdjacentHTML("beforeend", slotRow());
  if (t.dataset.dropslot) t.closest(".slot").remove();
  if (t.dataset.join) joinWheel(t);
  if (t.dataset.restore) signIn();
  if (t.dataset.signout) signOut(t);
  if (t.dataset.showkey) { const k = $("#my-key"); k.type = k.type === "password" ? "text" : "password"; t.textContent = k.type === "password" ? "Show" : "Hide"; }
  if (t.dataset.copykey) navigator.clipboard?.writeText(W.key() || "").then(() => toast("Key copied")).catch(() => { $("#my-key").type = "text"; $("#my-key").select(); });
  if (t.dataset.checkin) checkIn(t);
  if (t.dataset.copyxmr) navigator.clipboard?.writeText($("#xmr").value).then(() => toast("Address copied")).catch(() => $("#xmr").select());
  if (t.dataset.opencheckin) openCheckin(t);
  if (t.dataset.share) shareListing(t);
  if (t.dataset.ui) setUI(t.dataset.ui);
  if (t.id === "ui-switch") setUI(UI === "simple" ? "full" : "simple");
  if (t.dataset.dupkeep) dupAct({ action: "merge", keep: t.dataset.dupkeep, drop: t.dataset.dupdrop });
  if (t.dataset.dupapart) dupAct({ action: "apart", a: t.dataset.dupapart, b: t.dataset.dupother });
  if (t.dataset.orgnew) orgNew(t);
  if (t.dataset.orgsignin) { const k = $("#org-key-in").value.trim(); if (k.length < 20) { $(".status", t.closest(".card")).textContent = "An organiser key is about 43 letters and numbers."; } else { try { localStorage.setItem(ORG_KEY, k); } catch {} loadOrg(); } }
  if (t.dataset.orgsignout) { if (t.dataset.sure) { try { localStorage.removeItem(ORG_KEY); } catch {} loadOrg(); } else { t.dataset.sure = "1"; t.textContent = "Yes, sign out (copied the key?)"; } }
  if (t.dataset.orgcheck) orgCheck(t);
  if (t.dataset.orgask) orgApi("/api/org/ask", {}).then(() => { toast("A steward has your request"); loadOrg(); }).catch((err) => toast(err.message));
  if (t.dataset.orgclaim) orgClaim(t);
  if (t.dataset.orgedit) { const ed = $(".org-edit", t.closest(".org-claim")); ed.hidden = !ed.hidden; t.setAttribute("aria-expanded", String(!ed.hidden)); }
  if (t.dataset.orgsave) orgSave(t);
  if (t.dataset.orgdoor) openDoor(t);
  if (t.dataset.doorclose) closeDoor();
  if (t.dataset.copyfield2) navigator.clipboard?.writeText(t.dataset.copyfield2).then(() => toast("Copied")).catch(() => toast(t.dataset.copyfield2));
  if (t.dataset.orgvouch) api(`/api/org/${t.dataset.orgvouch}/vouch`, {}).then(() => { toast("Vouched"); loadOrgWaiting(); }).catch((err) => toast(err.message));
  if (t.dataset.orgclaimans) api(`/api/org/claims/${t.dataset.lid}`, { action: t.dataset.orgclaimans }).then(() => { toast(t.dataset.orgclaimans === "grant" ? "Given" : "Turned down"); loadOrgWaiting(); }).catch((err) => toast(err.message));
  if (t.id === "modlog-more") loadLog(true).catch((err) => toast(err.message));
  if (t.dataset.appeal) appealListing(t);
  if (t.dataset.appealrank) appealRank(t);
  if (t.dataset.rankanswer) answerAppeal(t);
  if (t.id === "menu-btn") setMenu(!document.documentElement.classList.contains("menu-open"));
  if (t.id === "filter-btn") { const v = $("#view-mode"); v.classList.toggle("filters-open"); t.setAttribute("aria-expanded", String(v.classList.contains("filters-open"))); }
  if (t.dataset.report) { const r = $(".report", t.closest(".more")); r.hidden = !r.hidden; t.setAttribute("aria-expanded", String(!r.hidden)); }
  if (t.dataset.sendreport) sendReport(t);
  if (t.dataset.copylink) navigator.clipboard?.writeText(t.dataset.copylink).then(() => toast("Link copied")).catch(() => toast(t.dataset.copylink));
  if (t.dataset.install) installApp();
  if (t.dataset.del) api(`/api/areas/${t.dataset.del}/delete`, {}).then(() => { toast("Area removed"); loadAreas(); }).catch((err) => toast(err.message));
});

document.addEventListener("change", (e) => {
  if (e.target.id === "pickday") { state.date = e.target.value; state.range = e.target.value ? "date" : "all"; renderMode(); return; }
  if (e.target.dataset?.k === "listing_kind") $(".shift-editor", e.target.closest(".card")).hidden = e.target.value !== "volunteer";
});

$("#q").addEventListener("input", renderList);
$("#rq").addEventListener("input", renderReview);
document.addEventListener("input", (e) => { if (e.target.id === "org-find") orgFind(); });
$("#unreviewed").addEventListener("change", loadEvents);
$("#archive").addEventListener("change", () => { renderList(); filterLabel(); });
$("#add-form").addEventListener("submit", readDeposit);
$("#add-file").addEventListener("change", (e) => showFlyer(e.target.files[0]));
const drop = $("#drop");
["dragenter", "dragover"].forEach((n) => drop.addEventListener(n, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((n) => drop.addEventListener(n, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => showFlyer(e.dataTransfer.files[0]));
drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#add-file").click(); } });
$("#area-form").addEventListener("submit", saveArea);

/* ---------- supporters and profiles (his calls 2026-10-22): looks for supporter months, paid as codes; a profile in
   the Ledger layout where every item carries its audience and a note on what it gives away ---------- */
let SUP = null, profilePen = null;  // /api/support: names, prices, looks, which ways to pay are open
async function supportConfig() { if (!SUP) SUP = await api("/api/support"); return SUP; }

function glyphSvg(seed, style = "ring", hex = "", size = 64) {
  let h = 0; for (const c of seed) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  const rnd = () => ((h = (h * 1664525 + 1013904223) >>> 0) / 4294967296);
  const col = hex || "currentColor", f = (n) => n.toFixed(1);
  let marks = "";
  for (let i = 0; i < 30; i++) {
    const a = (i / 30) * Math.PI * 2, r1 = 19 + rnd() * 5, r2 = 28 + rnd() * 6;
    if (style === "bloom") marks += `<ellipse cx="${f(36 + Math.cos(a) * 26)}" cy="${f(36 + Math.sin(a) * 26)}" rx="${f(2 + rnd() * 2)}" ry="1.2" transform="rotate(${f(a * 180 / Math.PI)} ${f(36 + Math.cos(a) * 26)} ${f(36 + Math.sin(a) * 26)})"/>`;
    else if (style === "tide") marks += i % 2 ? "" : `<path d="M${f(36 + Math.cos(a) * r1)} ${f(36 + Math.sin(a) * r1)} Q${f(36 + Math.cos(a + .2) * (r1 + 5))} ${f(36 + Math.sin(a + .2) * (r1 + 5))} ${f(36 + Math.cos(a + .1) * r2)} ${f(36 + Math.sin(a + .1) * r2)}"/>`;
    else marks += `<line x1="${f(36 + Math.cos(a) * r1)}" y1="${f(36 + Math.sin(a) * r1)}" x2="${f(36 + Math.cos(a + .13) * r2)}" y2="${f(36 + Math.sin(a + .13) * r2)}"/>`;
  }
  const k = 3 + (h % 4); let poly = "";
  for (let i = 0; i < k; i++) { const a = (i / k) * Math.PI * 2 - Math.PI / 2; poly += `${f(36 + Math.cos(a) * 10)},${f(36 + Math.sin(a) * 10)} `; }
  const body = `<circle cx="36" cy="36" r="13" stroke-width="1.4"/><polygon points="${poly}" stroke-width="1.4"/>${marks}`;
  const haze = style === "haze" ? `<g opacity=".35" transform="translate(1.6 1.2)">${body}</g>` : "";
  return `<svg class="glyph${style === "turning" ? " turning" : ""}" width="${size}" height="${size}" viewBox="0 0 72 72" aria-hidden="true" fill="${style === "bloom" ? col : "none"}" stroke="${col}" stroke-width="1.6" stroke-linecap="round">${haze}${style === "bloom" ? body.replace(/<(circle|polygon)/g, '<$1 fill="none"') : body}</svg>`;
}

const AUD = { all: "Everyone", mem: "Members", me: "Only me" };
const PROFILE_NOTES = {  // tone-checked (plain), from the pathway page
  name: "Others see this name on your profile. Pick one that is new here: a name you use elsewhere joins this profile to those accounts, and search engines keep what they find.",
  about: "Your words, your details. A job, a suburb, a child's age: each is small alone, and together they describe a person. Your way of writing is recognisable too.",
  kinds: "Shows what draws you. Common kinds blend in; two or three rare ones together can point to one person.",
  area: "Shows where you go. With the kinds you follow, an area can narrow you to a few people in a small scene.",
  status: "A small sign beside your pen name. Change it as often as you like.",
  mark: "Says you hold a supporter code. Codes are gifted too, so the mark shows a code, and who paid for it stays open. Others see it once 15 members hold one.",
  look: "Looks only. A rare look makes you a little easier to spot while few members use it.",
};
const dot = (a) => `<span class="dot ${a}" aria-hidden="true"></span>`;
const audSelect = (k, a) => `<span class="aud-pick">${dot(a || "me")}<select data-aud="${k}" aria-label="Who sees this">${Object.entries(AUD).map(([v, t]) => `<option value="${v}"${(a || "me") === v ? " selected" : ""}>${t}</option>`).join("")}</select></span>`;
const longDate = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-NZ", { day: "numeric", month: "long", year: "numeric" });

async function loadProfileEditor(me) {
  const box = $("#me-profile");
  if (!box || !me) return;
  profilePen = me.account;
  const [cfg, mine] = await Promise.all([supportConfig(), api("/api/profile")]);
  const p = mine.profile || {}, sup = mine.supporter, look = p.look || { colour: "ink", glyph: "ring" };
  const v = (k) => p[k]?.v ?? "", a = (k) => p[k]?.a || "me";
  const terms = $("#me-body .terms");  // the glyph joins the standing row, in the member's own look
  if (terms && !$(".glyphcell", terms)) {
    terms.classList.add("with-glyph");
    const hex = sup ? cfg.colours[look.colour]?.hex || "" : "";
    terms.insertAdjacentHTML("afterbegin", `<div class="term glyphcell" style="color:${hex || "inherit"}">${glyphSvg(me.account, sup ? look.glyph : "ring", hex, 44)}</div>`);
  }
  const lock = (on) => (on && !sup ? ` disabled title="A Supporter look"` : "");
  const row = (k, label, input) => `<div class="pl-row"><span class="k">${label}</span><div class="pl-in">${input}<p class="hint">${PROFILE_NOTES[k]}</p></div>${audSelect(k, a(k))}</div>`;
  box.innerHTML = `<h2 class="sub">Your profile</h2>
    <p class="lede">Show as much or as little as you like. Each item has its own audience, and every item starts with only you.</p>
    <div class="pl">
      ${row("name", "Name", `<input id="pf-name" maxlength="40" value="${esc(v("name"))}" autocomplete="off">`)}
      ${row("about", "About", `<textarea id="pf-about" maxlength="280" rows="2">${esc(v("about"))}</textarea>`)}
      ${row("kinds", "Kinds", `<input id="pf-kinds" value="${esc((v("kinds") || []).join(", "))}" placeholder="sound bath, fire and flow" autocomplete="off">`)}
      ${row("area", "Area", `<input id="pf-area" maxlength="40" value="${esc(v("area"))}" autocomplete="off">`)}
      ${row("status", "Status", `<select id="pf-status"${lock(true)}><option value="">None</option>${Object.entries(cfg.signs).map(([k, s]) => `<option value="${k}"${v("status") === k ? " selected" : ""}>${s} ${k}</option>`).join("")}</select>${sup ? "" : ` <span class="hint">A Supporter look.</span>`}`)}
      ${row("mark", "Supporter mark", `<label class="tick"><input type="checkbox" id="pf-mark"${v("mark") ? " checked" : ""}${lock(true)}> Show ◇ supporter</label>${sup ? "" : ` <span class="hint">A Supporter look.</span>`}`)}
    </div>
    <h3 class="sub">Looks</h3>
    <p class="hint">${PROFILE_NOTES.look}</p>
    <div class="swatches" role="radiogroup" aria-label="Colour">${Object.entries(cfg.colours).map(([k, c]) => `<label class="swatch" title="${k}${c.supporter ? ", a Supporter look" : ""}"><input type="radio" name="pf-colour" value="${k}"${look.colour === k ? " checked" : ""}${c.supporter && !sup ? " disabled" : ""}><span style="--sw:${c.hex || "currentColor"}"></span>${k}</label>`).join("")}</div>
    <div class="glyphs" role="radiogroup" aria-label="Glyph style">${Object.entries(cfg.glyphs).map(([k, locked]) => `<label class="gl"><input type="radio" name="pf-glyph" value="${k}"${look.glyph === k ? " checked" : ""}${locked && !sup ? " disabled" : ""}>${glyphSvg(me.account, k, cfg.colours[look.colour]?.hex, 44)}<span>${k}${locked ? " ◇" : ""}</span></label>`).join("")}</div>
    <p class="hint">◇ marks a Supporter look. Choices you make while a Supporter stay saved when the months end and come back with the next code.</p>
    <p class="band">${["all", "mem"].map((w) => `To ${w === "all" ? "everyone" : "members"}, you look like <b>${mine.lookalike[w]}</b> members.`).join(" ")}</p>
    <div class="actions"><button type="button" class="primary" data-saveprofile="1">Save profile</button>
      <a class="quiet" href="#p/${me.account}">See your profile as others do</a></div>
    <p class="status" id="pf-status-line" role="status"></p>
    <h2 class="sub">Supporter</h2>
    ${sup ? `<p>Supporter until <b>${longDate(mine.until)}</b>. Thank you: it keeps the machine on and the time free.</p>`
      : `<p class="lede">Supporter months add looks to your profile and keep The Wheel running. <a href="#support">Become a Supporter</a>.</p>`}
    <label for="pf-code">Have a code?</label>
    <div class="keyrow"><input id="pf-code" autocomplete="off" spellcheck="false" placeholder="WHEEL-XXXX-XXXX-XXXX"><button type="button" class="quiet" data-redeem="1">Use code</button></div>
    <p class="status" id="pf-code-status" role="status"></p>`;
}

function readProfile() {
  const aud = (k) => $(`[data-aud="${k}"]`).value;
  return {
    name: { v: $("#pf-name").value, a: aud("name") }, about: { v: $("#pf-about").value, a: aud("about") },
    kinds: { v: $("#pf-kinds").value.split(",").map((s) => s.trim()).filter(Boolean), a: aud("kinds") },
    area: { v: $("#pf-area").value, a: aud("area") },
    status: { v: $("#pf-status").value, a: aud("status") }, mark: { v: $("#pf-mark").checked, a: aud("mark") },
    look: { colour: $('input[name="pf-colour"]:checked')?.value || "ink", glyph: $('input[name="pf-glyph"]:checked')?.value || "ring" },
  };
}

async function saveProfile(btn) {
  const out = $("#pf-status-line");
  btn.disabled = true;
  try { await api("/api/profile", readProfile()); toast("Profile saved"); loadMe(); }
  catch (e) { out.textContent = e.message; out.classList.add("err"); }
  btn.disabled = false;
}

async function redeemCode(code, out) {
  try {
    const r = await api("/api/support/redeem", { code });
    toast("Supporter months added");
    if (out) out.textContent = `Supporter until ${longDate(r.added_until)}.`;
    SUP = null; loadMe();
  } catch (e) { if (out) { out.textContent = e.message; out.classList.add("err"); } }
}

async function loadProfile(pen) {
  const box = $("#profile-body");
  box.innerHTML = `<p class="status">Loading…</p>`;
  if (!/^[0-9a-f]{16}$/.test(pen || "")) { box.innerHTML = `<p class="status err">A pen name is 16 letters and numbers, 0 to 9 and a to f.</p>`; return; }
  const [cfg, r] = await Promise.all([supportConfig(), api(`/api/p/${pen}`)]);
  const p = r.profile, hex = cfg.colours[p.look.colour]?.hex || "";
  const rows = [["Name", p.name], ["Status", p.status && `${cfg.signs[p.status]} ${p.status}`], ["About", p.about],
    ["Kinds", p.kinds && p.kinds.join(" · ")], ["Area", p.area], ["Supporter", p.mark && "◇ supporter"]].filter(([, v]) => v);
  box.innerHTML = `<div class="card">
    <div class="terms pl-head"><div class="term glyphcell" style="color:${hex || "inherit"}">${glyphSvg(pen, p.look.glyph, hex, 56)}</div>
      <div class="term key"><span class="k">Pen name</span><span class="v pen">${esc(pen)}</span></div>
      <div class="term"><span class="k">Tier</span><span class="v">${esc(r.tier_name)}</span></div></div>
    ${rows.length ? `<div class="pl">${rows.map(([k, v]) => `<div class="pl-row view"><span class="k">${k}</span><span>${esc(v)}</span></div>`).join("")}</div>`
      : `<p class="lede">This member shows only a pen name${r.viewer === "all" ? " to everyone" : ""}.</p>`}
    <p class="hint">${r.viewer === "me" ? "This is your profile as you see it, with every item. Others see only what you've set for them; sign out or open it in a private window to see it as everyone does." : r.viewer === "mem" ? "You see what this member shows to members and to everyone." : "You see what this member shows to everyone. Members may see more."}</p></div>`;
}

async function loadSupport() {
  const box = $("#support-buy");
  if (!box) return;
  const cfg = await supportConfig();
  const saved = (() => { try { return localStorage.getItem("wheel-order"); } catch { return null; } })();
  $("#supporters-count").textContent = cfg.supporters ? `${cfg.supporters} ${cfg.supporters === 1 ? "member holds" : "members hold"} supporter months today. Thank you.` : "";
  box.innerHTML = `<div class="buy">
    <div><span class="k">Months</span><div class="ranges" role="radiogroup" aria-label="Months">${cfg.months.map((m, i) => `<button type="button" data-months="${m}" class="${i === 0 ? "on" : ""}" aria-pressed="${i === 0}">${m} ${m === 1 ? "month" : "months"}</button>`).join("")}</div></div>
    <div><label for="buy-nzd">NZ$ a month, from ${cfg.min_nzd}</label><input id="buy-nzd" type="number" inputmode="decimal" min="${cfg.min_nzd}" step="1" value="${cfg.suggest_nzd}"></div>
    <p class="buy-total" id="buy-total"></p></div>
    <div class="give">
      <div class="give-way"><h3>Monero</h3>
        ${cfg.monero ? `<p class="hint">Nobody learns who paid. The Wheel sees that the amount arrived, and your code shows here after 10 blocks, about 20 minutes.</p>
        <button type="button" class="primary" data-xmrorder="1">Pay with Monero</button>` : `<p class="hint">Paused while the payment watcher is offline. Try again later, or pay another way.</p>`}
        <div id="xmr-order"></div></div>
      ${cfg.paypal ? `<div class="give-way"><h3>PayPal</h3>
        <p class="hint">Put the months in PayPal's note. We email your code to the address PayPal gives us, within a day. PayPal and our PayPal account then hold your name; your Wheel profile holds only the code.</p>
        <p><a class="primary" href="${esc(cfg.paypal)}" target="_blank" rel="noopener">Pay with PayPal</a></p></div>` : ""}
      <div class="give-way"><h3>Cash</h3>
        <p class="hint">At an event, a steward or organiser with code cards takes cash and hands you a code. The person handing it over is the only one who knows.</p></div>
    </div>`;
  updateTotal();
  if (saved) watchOrder(saved);
}

function updateTotal() {
  const m = +($("[data-months].on")?.dataset.months || 1), n = Number($("#buy-nzd")?.value || 0);
  const el = $("#buy-total"); if (!el) return;
  el.textContent = n >= (SUP?.min_nzd || 2) ? `NZ$${(m * n).toFixed(2)} for ${m} ${m === 1 ? "month" : "months"}.` : `From NZ$${SUP?.min_nzd || 2} a month.`;
}

async function startOrder(btn) {
  const out = $("#xmr-order");
  btn.disabled = true;
  try {
    const r = await api("/api/support/order", { months: +($("[data-months].on")?.dataset.months || 1), nzd: Number($("#buy-nzd").value) });
    try { localStorage.setItem("wheel-order", r.token); } catch {}
    showOrder(r, { state: "waiting", confirmations: 0, need: r.confirmations });
    watchOrder(r.token, r);
  } catch (e) { out.innerHTML = `<p class="status err">${esc(e.message)}</p>`; }
  btn.disabled = false;
}

function showOrder(o, st) {
  const out = $("#xmr-order"); if (!out) return;
  if (st.code) {
    out.innerHTML = `<div class="warn"><p><b>Paid. Your code:</b></p>
      <div class="keyrow"><input id="got-code" readonly value="${esc(st.code)}" spellcheck="false"><button type="button" class="quiet" data-copycode="1">Copy</button></div>
      <p class="hint">This code shows once. Copy it now, then use it on <a href="#me">Me</a> or give it to someone.</p>
      ${W && W.session() ? `<button type="button" class="primary" data-usecode="1">Use it on my profile</button>` : ""}</div>`;
    return;
  }
  out.innerHTML = `<div class="xmr-pay">
    <label for="pay-addr">Send to</label><div class="keyrow"><input id="pay-addr" readonly value="${esc(o.address)}" spellcheck="false"><button type="button" class="quiet" data-copyfield="pay-addr">Copy</button></div>
    <label for="pay-amt">Exactly this amount of XMR</label><div class="keyrow"><input id="pay-amt" readonly value="${esc(o.amount)}" spellcheck="false"><button type="button" class="quiet" data-copyfield="pay-amt">Copy</button></div>
    <p class="hint">Send the amount to the last digit: those digits tell your payment apart from everyone else's. The amount holds for an hour.</p>
    <p class="status" role="status">${st.state === "seen" ? `Payment seen: ${st.confirmations} of ${st.need} blocks.` : "Waiting for your payment. This page checks every 30 seconds; you can close it and come back on this device."}</p></div>`;
}

async function watchOrder(token, first) {
  clearTimeout(watchOrder.t);
  let o = first;
  try {
    const st = await api(`/api/support/order/${token}`);
    o = o || st;
    showOrder(o, st);
    if (st.code) { try { localStorage.removeItem("wheel-order"); } catch {} return; }
  } catch (e) { try { localStorage.removeItem("wheel-order"); } catch {} $("#xmr-order").innerHTML = `<p class="status">${esc(e.message)}</p>`; return; }
  watchOrder.t = setTimeout(() => { if (location.hash.startsWith("#support")) watchOrder(token, o); }, 30000);
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("button, a");
  if (!t) return;
  if (t.dataset.saveprofile) saveProfile(t);
  if (t.dataset.redeem) redeemCode($("#pf-code").value, $("#pf-code-status"));
  if (t.dataset.months) { $$("[data-months]").forEach((b) => { b.classList.toggle("on", b === t); b.setAttribute("aria-pressed", String(b === t)); }); updateTotal(); }
  if (t.dataset.xmrorder) startOrder(t);
  if (t.dataset.copyfield) { const f = $("#" + t.dataset.copyfield); navigator.clipboard?.writeText(f.value).then(() => toast("Copied")).catch(() => f.select()); }
  if (t.dataset.copycode) { const f = $("#got-code"); navigator.clipboard?.writeText(f.value).then(() => toast("Code copied")).catch(() => f.select()); }
  if (t.dataset.usecode) redeemCode($("#got-code").value, null).then(() => { location.hash = "#me"; });
});
document.addEventListener("input", (e) => { if (e.target.id === "buy-nzd") updateTotal(); });
document.addEventListener("change", (e) => {
  if (e.target.dataset?.aud) { const d = $(".dot", e.target.parentElement); d.className = `dot ${e.target.value}`; }
  if (e.target.name === "pf-colour" || e.target.name === "pf-glyph") {  // redraw the glyph previews in the new colour
    const hex = SUP?.colours[$('input[name="pf-colour"]:checked')?.value]?.hex || "";
    $$(".glyphs .gl").forEach((l) => { const k = $("input", l).value; $("svg", l).outerHTML = glyphSvg(profilePen || "x", k, hex, 44); });
  }
});

/* ---------- the community board and pages for regular events (2026-10-22) ---------- */
const placeOf = (ev) => [ev.location_name, ev.location_locality && !(ev.location_name || "").includes(ev.location_locality) ? ev.location_locality : null].filter(Boolean).join(", ");
const isRegular = (ev) => !!ev.recurrence;

async function loadBoard() {
  const { events, today } = await api("/api/events?unreviewed=1");
  const seen = new Set();  // the same name at the same place once, the checked copy first
  const series = {};  // the same event added once per date: one row, with how many dates are ahead
  events.filter((e) => !isRegular(e) && !e.past).forEach((e) => (series[nameKey(e)] = series[nameKey(e)] || []).push(e));
  const asSeries = Object.values(series).filter((g) => g.length > 1).map((g) => {
    const first = g.sort((a, b) => on(a).localeCompare(on(b)))[0];
    return { ...first, recurrence: `${g.length} dates coming up`, _series: true };
  });
  const regular = [...events.filter(isRegular), ...asSeries].sort((a, b) => (b.review?.state === "approved") - (a.review?.state === "approved"))
    .filter((e) => { const k = `${e.name.trim().toLowerCase()}|${placeOf(e).toLowerCase()}`; return !seen.has(k) && seen.add(k); })
    .sort((a, b) => on(a).localeCompare(on(b)));
  const groups = {};
  events.filter((e) => !isRegular(e) && !e.past && e.organiser).forEach((e) => {
    const k = e.organiser.trim().toLowerCase();
    (groups[k] = groups[k] || { name: e.organiser.trim(), events: [] }).events.push(e);
  });
  const orgs = Object.values(groups).filter((g) => g.events.length > 1).sort((a, b) => b.events.length - a.events.length);
  const regRow = (ev) => `<li class="board-row"><a class="board-name" href="${ev._series ? `#l/${ev.id}` : `#s/${ev.id}`}">${esc(ev.name)}</a>
    <span class="board-meta">${esc(ev.recurrence.slice(0, 60))}${placeOf(ev) ? ` · ${esc(placeOf(ev))}` : ""}</span>
    <span class="board-next">${on(ev) < today && onEnd(ev) >= today ? `On now, until ${esc(fmtShort(onEnd(ev)))}`
      : on(ev) >= today ? `Next: ${esc(fmtShort(on(ev)))}` : "Next date: check the organiser's page"}</span></li>`;
  const orgRow = (g) => `<li class="board-row"><span class="board-name">${esc(g.name)}</span>
    <span class="board-meta">${g.events.length} coming up</span>
    <ul class="board-events">${g.events.sort((a, b) => on(a).localeCompare(on(b))).map((e) => `<li><a href="#l/${e.id}">${esc(e.name)}</a>, ${esc(fmtShort(on(e)))}</li>`).join("")}</ul></li>`;
  $("#board").innerHTML = `<h2>Meets regularly</h2>${regular.length ? `<ul class="board">${regular.map(regRow).join("")}</ul>` : `<p class="hint">A listing that repeats shows here. Add one under Add a listing.</p>`}
    <h2>Organisers with more coming up</h2>${orgs.length ? `<ul class="board">${orgs.map(orgRow).join("")}</ul>` : `<p class="hint">An organiser with two or more listings ahead shows here.</p>`}`;
}

async function loadSeries(id) {
  const box = $("#series");
  const { events } = await api("/api/events?unreviewed=1");
  const ev = events.find((e) => e.id === id);
  if (!ev) { box.innerHTML = `<h1>Gone</h1><p class="lede">That listing has gone from The Wheel. <a href="#board">See the communities</a>.</p>`; return; }
  const dates = ev.repeats_on || [on(ev)];
  box.innerHTML = `<h1>${esc(ev.name)}</h1>
    <p class="lede">${ev.recurrence ? `${esc(ev.recurrence)}. ` : ""}${esc([when(ev), placeOf(ev), ev.price].filter(Boolean).join(" · "))}</p>
    <div class="actions"><a class="primary" href="${API}/api/ics/${ev.id}.ics?all=1" rel="nofollow">Add every date to my calendar</a>
      <button type="button" class="quiet" data-share="${ev.id}">Share</button><a class="quiet" href="#l/${ev.id}">See it in the list</a></div>
    <div class="share-out"></div>
    <h2>Coming up</h2>
    <ul class="series-dates">${dates.map((day) => `<li>${esc(fmtShort(day))}${ev.start_time ? `, ${esc(ev.start_time)}` : ""}</li>`).join("")}</ul>
    ${ev.description ? `<h2>About it</h2><p class="series-about">${esc(ev.description)}</p>` : ""}
    ${ev.organiser ? `<p>Organised by ${esc(ev.organiser)}</p>` : ""}
    <div class="series-links">${whereFrom(ev)}</div>`;
  if (!state.events.some((e) => e.id === ev.id)) state.events = [...state.events, ev];  // Share finds it here
}

/* ---------- organiser accounts (his ruling 2026-10-23: "A, and yes to organiser accounts") ----------
   An organiser account is its own key with a public name. It goes only with organiser calls (orgApi), never beside
   a member's login, so the two stay unlinked even on one device. */
const ORG_KEY = "wheel.organiser";
const orgKey = () => { try { return localStorage.getItem(ORG_KEY); } catch { return null; } };
async function orgApi(path, body) {
  const headers = { "X-Wheel-Organiser": orgKey() || "" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(API + path, body === undefined ? { headers } : { method: "POST", headers, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({ error: "The Wheel sent back something unreadable." }));
  if (!res.ok) throw new Error(data.error || data.why || `The Wheel answered ${res.status}.`);
  return data;
}
const ORG_EDIT = [["start_date", "Date (2026-10-24)"], ["start_time", "Starts (19:30)"], ["end_time", "Ends at"], ["location_name", "Place"],
  ["location_locality", "Town or suburb"], ["price", "Price"], ["tickets_url", "Tickets (a link)"], ["recurrence", "Repeats"]];

async function loadOrg() {
  const box = $("#org-body");
  if (!orgKey()) {
    box.innerHTML = `<div class="me-doors">
      <div class="card"><h2>New organiser account</h2>
        <p class="lede">Your organiser name shows on the listings you keep. Your own pen name stays separate from it, on its own key.</p>
        <label for="org-name">Organiser name</label><input id="org-name" maxlength="60" autocomplete="organization">
        <label for="org-page">Your page (https://…)</label><input id="org-page" placeholder="https://www.facebook.com/yourgroup" autocomplete="url">
        <p class="hint">Your site, or your page on Facebook or Instagram. You prove it's yours by putting a short code on it.</p>
        <button type="button" class="primary" data-orgnew="1">Make the account</button><p class="status" role="status"></p></div>
      <div class="card"><h2>Have an organiser key?</h2>
        <label for="org-key-in">Organiser key</label><input id="org-key-in" type="password" autocomplete="off" spellcheck="false">
        <button type="button" class="quiet" data-orgsignin="1">Sign in as the organiser</button><p class="status" role="status"></p></div></div>`;
    return;
  }
  let r;
  try { r = await orgApi("/api/org/me"); } catch (e) { box.innerHTML = `<p class="status err">${esc(e.message)}</p><button type="button" class="quiet" data-orgsignout="1">Forget this organiser key</button>`; return; }
  const o = r.organiser;
  box.innerHTML = `<div class="card"><h2>${esc(o.name)}</h2>
    <p class="hint">Your page: <a href="${esc(o.page)}" target="_blank" rel="noopener">${esc(o.page)}</a>${o.proven ? ` · <a href="#o/${o.id}">Your public page on The Wheel</a>` : ""}</p>
    ${o.proven ? `<p>√ Proven${o.proven_by === "steward" ? " by a steward" : " by your page"}. You can claim listings.</p>`
      : `<h2 class="sub">Prove your page</h2><p>Put this code anywhere on your page (the about text, a post, a pinned comment), then check:</p>
         <div class="keyrow"><input readonly value="${esc(o.code)}" aria-label="Your code"><button type="button" class="quiet" data-copyfield2="${esc(o.code)}">Copy</button></div>
         <div class="actions"><button type="button" class="primary" data-orgcheck="1">Check my page</button>
         ${o.asked ? `<span class="hint">A steward has your request.</span>` : `<button type="button" class="quiet" data-orgask="1">Ask a steward instead</button>`}</div>
         <p class="hint">Facebook and Instagram often turn outside readers away. When the check comes back empty-handed, ask a steward: they confirm it another way, often in person.</p>
         <p class="status" id="org-check-status" role="status"></p>`}
    <h2 class="sub">Your organiser key</h2>
    <p class="lede">This key is the account. Save a copy in your password manager; anyone holding it acts as ${esc(o.name)}.</p>
    <div class="keyrow"><input id="org-key" type="password" readonly value="${esc(orgKey())}" aria-label="Your organiser key"><button type="button" class="quiet" data-copyfield2="${esc(orgKey())}">Copy</button>
      <button type="button" class="quiet" data-orgsignout="1">Sign out of the organiser account</button></div></div>
    ${o.proven ? `<div class="card"><h2>Your listings</h2>${r.claims.length ? r.claims.map(orgClaimCard).join("") : `<p class="lede">Claim the listings you run, below.</p>`}</div>
    <div class="card"><h2>Claim a listing</h2><p class="lede">A listing that links to your page is yours straight away. Others go to a steward.</p>
      <label for="org-find">Find it</label><input id="org-find" type="search" placeholder="Name, place or date" autocomplete="off">
      <ul class="org-found" id="org-found"></ul></div>` : ""}`;
  ORG_CLAIMS = r.claims;
}
let ORG_CLAIMS = [], DOOR = null;
function orgClaimCard(c) {
  const l = c.listing;
  if (c.state !== "claimed") return `<div class="org-claim"><b>${esc(c.name)}</b>, ${esc(fmtShort(c.date))}: <span class="hint">waiting for a steward</span></div>`;
  return `<div class="org-claim" data-lid="${c.id}"><b>${esc(c.name)}</b>, ${esc(fmtShort(c.date))}
    <div class="actions"><button type="button" class="primary" data-orgdoor="${c.id}">Open check-in</button>
      <button type="button" class="quiet" data-orgedit="1" aria-expanded="false">Update it</button></div>
    <div class="org-edit" hidden>
      <label for="st-${c.id}">Status</label><select id="st-${c.id}" data-of="status">${["confirmed", "tentative", "postponed", "cancelled"].map((v) =>
        `<option value="${v}"${(l.status || "confirmed") === v ? " selected" : ""}>${v}</option>`).join("")}</select>
      <div class="fields">${ORG_EDIT.map(([k, label]) => `<div><label for="of-${c.id}-${k}">${label}</label><input id="of-${c.id}-${k}" data-of="${k}" value="${esc(l[k] ?? "")}"></div>`).join("")}</div>
      <label for="on-${c.id}">An update for everyone (moved, sold out, bring a plate…)</label><textarea id="on-${c.id}" data-of="note" rows="2" maxlength="280">${esc(l.org_note?.text || "")}</textarea>
      <button type="button" class="quiet" data-orgsave="${c.id}">Save the update</button><p class="status" role="status"></p></div></div>`;
}

const ROT = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";  // the member service's own alphabet (zk/core.mjs)
async function rotatingCode(secretHex, id, minute) {
  const raw = new Uint8Array(secretHex.match(/../g).map((h) => parseInt(h, 16)));
  const key = await crypto.subtle.importKey("raw", raw, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${id}:${minute}`)));
  return Array.from(mac.slice(0, 6), (b) => ROT[b % ROT.length]).join("");
}
async function openDoor(btn) {
  const id = btn.dataset.orgdoor, card = btn.closest(".org-claim");
  btn.disabled = true;
  try {
    const r = await orgApi(`/api/org/checkin/${id}`, {});
    DOOR = { id, name: $("b", card).textContent, secret: r.secret, closes: r.closes, rotate: r.rotate || 60000 };
    showDoor();
  } catch (e) { $(".status", card)?.replaceChildren(document.createTextNode(e.message)); toast(e.message); }
  btn.disabled = false;
}
async function showDoor() {
  clearTimeout(showDoor.t);
  if (!DOOR) return;
  let el = $("#doorscreen");
  if (!el) { document.body.insertAdjacentHTML("beforeend", `<div id="doorscreen" class="doorscreen" role="dialog" aria-modal="true" aria-labelledby="door-h"></div>`); el = $("#doorscreen"); }
  const now = Date.now();
  if (now > DOOR.closes) { el.innerHTML = `<div class="door-panel"><h2 id="door-h">Check-in closed</h2><button type="button" class="primary" data-doorclose="1">Close</button></div>`; return; }
  const minute = Math.floor(now / DOOR.rotate), left = Math.ceil(((minute + 1) * DOOR.rotate - now) / 1000);
  const code = await rotatingCode(DOOR.secret, DOOR.id, minute);
  el.innerHTML = `<div class="door-panel"><p class="hint">${esc(DOOR.name)}</p><h2 id="door-h">Door code</h2>
    <div class="doorcode">${esc(code)}</div><p>Changes in ${left} s. A code works for about three minutes, so one passed around outside soon stops.</p>
    <p class="hint">Members type it into the listing's "I'm here". Open until ${esc(new Date(DOOR.closes).toLocaleTimeString("en-NZ", { hour: "2-digit", minute: "2-digit" }))}.</p>
    <button type="button" class="quiet" data-doorclose="1">Hide the code</button></div>`;
  showDoor.t = setTimeout(showDoor, 1000);
  try { if (!showDoor.lock && navigator.wakeLock) showDoor.lock = await navigator.wakeLock.request("screen"); } catch {}
}
function closeDoor() { clearTimeout(showDoor.t); $("#doorscreen")?.remove(); try { showDoor.lock?.release(); } catch {} showDoor.lock = null; DOOR = null; }

async function orgNew(btn) {
  const out = $(".status", btn.closest(".card"));
  btn.disabled = true;
  try {
    const r = await orgApi("/api/org/new", { name: $("#org-name").value, page: $("#org-page").value });
    try { localStorage.setItem(ORG_KEY, r.key); } catch {}
    toast("Organiser account made"); loadOrg();
  } catch (e) { out.textContent = e.message; }
  btn.disabled = false;
}
async function orgCheck(btn) {
  const out = $("#org-check-status");
  btn.disabled = true; out.textContent = "Reading your page…";
  try {
    const r = await orgApi("/api/org/check", {});
    if (r.proven) { toast("Proven"); loadOrg(); return; }
    out.textContent = r.why === "fetch" ? "Your page turned The Wheel away, as Facebook and Instagram often do. Ask a steward instead." : "The check read your page and found it without the code so far. Check it's saved and public, then try again.";
  } catch (e) { out.textContent = e.message; }
  btn.disabled = false;
}
function orgFind() {
  const q = ($("#org-find")?.value || "").trim().toLowerCase(), out = $("#org-found");
  if (!out) return;
  if (q.length < 2) { out.innerHTML = ""; return; }
  const mine = new Set(ORG_CLAIMS.map((c) => c.id));
  const hits = state.events.filter((e) => !mine.has(e.id) && !e.claimed_by && [e.name, e.location_name, e.start_date, e.organiser].join(" ").toLowerCase().includes(q)).slice(0, 8);
  out.innerHTML = hits.map((e) => `<li><span><b>${esc(e.name)}</b>, ${esc(fmtShort(on(e)))}</span> <button type="button" class="quiet" data-orgclaim="${e.id}">Claim</button></li>`).join("") || `<li class="hint">Add it under Add a listing first, then claim it here.</li>`;
}
async function orgClaim(btn) {
  btn.disabled = true;
  try { const r = await orgApi(`/api/org/claim/${btn.dataset.orgclaim}`, {}); toast(r.state === "claimed" ? "Claimed" : "Sent to a steward"); loadOrg(); }
  catch (e) { toast(e.message); btn.disabled = false; }
}
async function orgSave(btn) {
  const box = btn.closest(".org-edit"), out = $(".status", box), body = {};
  $$("[data-of]", box).forEach((el) => (body[el.dataset.of] = el.value));
  try { const r = await orgApi(`/api/org/update/${btn.dataset.orgsave}`, body); out.textContent = r.changed.length ? "Saved. It shows on the listing now." : "Already up to date."; }
  catch (e) { out.textContent = e.message; }
}
async function loadPublicOrg(id) {
  const box = $("#o-body");
  try {
    const r = await api(`/api/o/${id}`);
    box.innerHTML = `<h1>${esc(r.organiser.name)}</h1><p class="lede">A proven organiser on The Wheel${r.organiser.proven_by === "steward" ? ", vouched for by a steward" : ", proven by its own page"}. <a href="${esc(r.organiser.page)}" target="_blank" rel="noopener">Their page</a></p>
      <h2>Their listings</h2>${r.listings.length ? `<ul class="board">${r.listings.map((l) => `<li class="board-row"><a class="board-name" href="#l/${l.id}">${esc(l.name)}</a><span class="board-meta">${esc(fmtShort(l.date))}${l.past ? ", already happened" : ""}</span></li>`).join("")}</ul>` : `<p class="hint">Their listings show here once they claim them.</p>`}`;
  } catch (e) { box.innerHTML = `<h1>Organiser</h1><p class="status err">${esc(e.message)}</p>`; }
}
async function loadOrgWaiting() {
  const box = $("#rv-orgs");
  if (!reviewMe || reviewMe.tier < 3) { box.innerHTML = ""; return; }
  const r = await api("/api/org/waiting");
  const vouch = r.vouch.map((o) => `<div class="rank-appeal"><p><b>${esc(o.name)}</b> asks for a vouch. Their page: <a href="${esc(o.page)}" target="_blank" rel="noopener">${esc(o.page)}</a></p>
    <p class="hint">Vouch only once you know this page is theirs: in person, or by a message from the page itself.</p>
    <div class="actions"><button type="button" class="quiet" data-orgvouch="${o.id}">Vouch for them</button></div></div>`).join("");
  const claims = r.claims.map((c) => `<div class="rank-appeal"><p><b>${esc(c.organiser.name)}</b> claims <b>${esc(c.name)}</b>. Its links: ${c.links.map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(u)}</a>`).join(", ") || "none"}. Their page: <a href="${esc(c.organiser.page)}" target="_blank" rel="noopener">${esc(c.organiser.page)}</a></p>
    <div class="actions"><button type="button" class="quiet" data-orgclaimans="grant" data-lid="${c.listing}">Give it to them</button><button type="button" class="quiet" data-orgclaimans="refuse" data-lid="${c.listing}">Turn it down</button></div></div>`).join("");
  box.innerHTML = vouch || claims ? `<div class="card"><h2>Organisers</h2>${vouch}${claims}<p class="hint">Each answer goes in the moderation log.</p></div>` : "";
}

/* ---------- duplicates (his ask 2026-10-23): look-alikes on the same day, as pairs; a Reviewer merges or keeps apart ---------- */
async function loadDupes() {
  const box = $("#rv-dupes");
  const { pairs } = await api("/api/duplicates");
  if (!pairs.length) { box.innerHTML = ""; return; }
  const can = reviewMe && reviewMe.tier >= 2;
  const side = (l, other) => `<div class="dup-side">
      <b>${esc(l.name)}</b>
      <span class="hint">${esc(fmtShort(l.start_date))}${l.start_time ? `, ${esc(l.start_time)}` : ""}${placeOf(l) ? ` · ${esc(placeOf(l))}` : ""} · ${l.review?.state === "approved" ? "checked" : "waiting"}</span>
      ${[l.website, l.source_url].filter(Boolean).slice(0, 1).map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener">Its page</a>`).join("")}
      ${can ? `<button type="button" class="quiet" data-dupkeep="${l.id}" data-dupdrop="${other.id}">Same event: keep this one</button>` : ""}</div>`;
  box.innerHTML = `<details class="card dupes"${pairs.some((p) => p.exact) ? " open" : ""}><summary><b>Possible duplicates (${pairs.length})</b></summary>
    <p class="hint">Listings on the same day with names alike.${can ? " Keep one and the other merges into it, bringing any link the kept one lacks. A merge leaves everyone's rep as it was." : " Reviewers merge copies; you can say which is right in the review list."}</p>
    ${pairs.map((p) => { const [a, b] = p.listings; return `<div class="dup-pair">
      ${p.exact ? `<p class="dup-tag">Same name, same day</p>` : ""}
      <div class="dup-sides">${side(a, b)}${side(b, a)}</div>
      ${can ? `<button type="button" class="linklike" data-dupapart="${a.id}" data-dupother="${b.id}">These are different events</button>` : ""}</div>`; }).join("")}</details>`;
}
async function dupAct(body) {
  try { await api("/api/duplicates", body); toast(body.action === "merge" ? "Merged" : "Kept apart"); loadDupes(); loadReview(); }
  catch (e) { toast(e.message); }
}

/* ---------- the moderation log and appeals (2026-10-22) ---------- */
let logBefore = null;
async function loadLog(more = false) {
  const r = await api(`/api/modlog${more && logBefore ? `?before=${logBefore}` : ""}`);
  const rows = r.entries.map((e) => `<li><span class="log-day">${esc(fmtShort(e.day))}</span> <span>${esc(e.text)}${e.listing ? ` <a href="#l/${e.listing}">See it</a>` : ""}</span></li>`).join("");
  $("#modlog").innerHTML = (more ? $("#modlog").innerHTML : "") + (rows || (more ? "" : `<li class="hint">The log starts with the next check or steward decision.</li>`));
  logBefore = r.entries.length ? r.entries[r.entries.length - 1].id : logBefore;
  $("#modlog-more").hidden = !r.more;
}

const STATE_WORD = { approved: "checked", pending: "waiting for review", rejected: "turned down" };
async function loadMine() {
  const box = $("#me-mine");
  if (!box) return;
  const r = await api("/api/mine");
  const rows = r.listings.map((l) => `<li><span><b>${esc(l.name)}</b>, ${esc(fmtShort(l.date))}: ${STATE_WORD[l.state] || esc(l.state)}</span>
    ${l.state === "rejected" && !l.appealed ? `<details class="appeal"><summary>Ask for another look</summary>
      <label for="ap-${l.id}">Why it belongs on The Wheel, if you like</label><textarea id="ap-${l.id}" rows="2" maxlength="300"></textarea>
      <p class="hint">It goes back to review once, to members who have yet to see it. Names and numbers come out of your note.</p>
      <button type="button" class="quiet" data-appeal="${l.id}">Send it back to review</button><p class="status" role="status"></p></details>`
      : l.appealed && l.state === "rejected" ? `<span class="hint">Appealed, and turned down again.</span>` : ""}</li>`).join("");
  box.innerHTML = `<h2 class="sub">Your listings</h2>${rows ? `<ul class="mine">${rows}</ul>` : `<p class="lede">Listings you add show here, with how their review went.</p>`}
    ${r.reset_day ? `<h2 class="sub">Your rank</h2><p>A steward reset your rank to zero on ${esc(longDate(r.reset_day))}. Your past reviews stay where they are.</p>
      ${r.rank_appeal ? `<p class="hint">Your appeal waits for a steward.</p>` : `<label for="rank-note">Ask the stewards to look again</label><textarea id="rank-note" rows="3" maxlength="500"></textarea>
      <button type="button" class="quiet" data-appealrank="1">Send to the stewards</button><p class="status" role="status"></p>`}` : ""}`;
}
async function appealListing(btn) {
  const box = btn.closest(".appeal"), out = $(".status", box);
  btn.disabled = true;
  try { await api(`/api/appeal/${btn.dataset.appeal}`, { note: $("textarea", box).value }); toast("Back in review"); loadMine(); }
  catch (e) { out.textContent = e.message; btn.disabled = false; }
}
async function appealRank(btn) {
  const out = btn.nextElementSibling;
  btn.disabled = true;
  try { await api("/api/appeal-rank", { note: $("#rank-note").value }); toast("Sent to the stewards"); loadMine(); }
  catch (e) { out.textContent = e.message; btn.disabled = false; }
}
async function loadAppeals() {
  const box = $("#rv-appeals");
  if (!reviewMe || reviewMe.tier < 3) { box.innerHTML = ""; return; }
  const { appeals } = await api("/api/appeals");
  box.innerHTML = appeals.length ? `<div class="card"><h2>Rank appeals</h2>${appeals.map((a) => `<div class="rank-appeal" data-aid="${a.id}">
      <p><b>${esc(a.account)}</b>, ${esc(fmtShort(a.day))}${a.note ? `: "${esc(a.note)}"` : ""}</p>
      <div class="actions"><button type="button" class="quiet" data-rankanswer="restore">Restore their rank</button>
      <button type="button" class="quiet" data-rankanswer="keep">Keep the reset</button></div></div>`).join("")}
    <p class="hint">Your answer goes in the moderation log by role. An appeal of your own waits for another steward.</p></div>` : "";
}
async function answerAppeal(btn) {
  const row = btn.closest(".rank-appeal");
  try { await api(`/api/appeals/${row.dataset.aid}`, { action: btn.dataset.rankanswer }); toast(btn.dataset.rankanswer === "restore" ? "Rank restored" : "Reset kept"); loadAppeals(); }
  catch (e) { toast(e.message); }
}

/* ---------- reading and comfort, and The Wheel as an app (2026-10-22) ---------- */
function renderComfort() {
  $("#comfort-body").innerHTML = `<fieldset class="comfort-set"><legend>View</legend>
    <label class="tick"><input type="radio" name="cf-ui" data-uiradio="1" value="simple"${UI === "simple" ? " checked" : ""}> Simple: the list first, with filters and tools tucked away</label>
    <label class="tick"><input type="radio" name="cf-ui" data-uiradio="1" value="full"${UI === "full" ? " checked" : ""}> Everything at once: every filter and tool on the screen</label></fieldset>` + COMFORT.map(([k, label, opts, note]) => `<fieldset class="comfort-set"><legend>${label}</legend>
    ${opts.map(([v, t]) => `<label class="tick"><input type="radio" name="cf-${k}" data-comfort="${k}" value="${v}"${(comfort[k] || "") === v ? " checked" : ""}> ${t}</label>`).join("")}
    ${note ? `<p class="hint">${note}</p>` : ""}</fieldset>`).join("") +
    `<p class="hint">Kept in this browser only. On another device, set them there too.</p>`;
}

let installPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt = e; if (!$("#view-comfort").hidden) renderInstall(); });
window.addEventListener("appinstalled", () => { installPrompt = null; toast("Installed"); renderInstall(); });
function renderInstall() {
  const box = $("#install-body");
  if (matchMedia("(display-mode: standalone)").matches || navigator.standalone) { box.innerHTML = `<p>You're using The Wheel as an app on this device.</p>`; return; }
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent);
  box.innerHTML = `<p class="lede">Put The Wheel on your home screen. It opens like an app, and offline it shows the last list it loaded.</p>
    ${installPrompt ? `<button type="button" class="primary" data-install="1">Install The Wheel</button>`
      : ios ? `<p>On an iPhone or iPad, in Safari: tap Share, then Add to Home Screen.</p>`
      : `<p>On Android, open the browser menu and tap Add to Home screen or Install. On a computer, Chrome and Edge show Install app in the menu or the address bar.</p>`}
    <p class="hint">The app keeps two things on this device: a copy of the page, and the last list it loaded.</p>`;
}
async function installApp() {
  if (!installPrompt) return;
  installPrompt.prompt();
  await installPrompt.userChoice.catch(() => null);
  installPrompt = null;
  renderInstall();
}
function forgetSavedList() {
  if (!window.caches) return;
  caches.keys().then((ks) => ks.forEach((k) => caches.open(k).then((c) => c.keys().then((reqs) =>
    reqs.filter((r) => r.url.includes("/api/events")).forEach((r) => c.delete(r)))))).catch(() => {});
}
document.addEventListener("change", (e) => {
  if (e.target.dataset?.uiradio) { setUI(e.target.value); return; }
  const k = e.target.dataset?.comfort;
  if (!k) return;
  if (e.target.value) comfort[k] = e.target.value; else delete comfort[k];
  try { localStorage.setItem(COMFORT_KEY, JSON.stringify(comfort)); } catch {}
  applyComfort();
});
window.addEventListener("online", () => { if (!$("#view-mode").hidden) loadEvents().catch(() => {}); });
if ("serviceWorker" in navigator && !new URLSearchParams(location.search).has("shot")) {
  navigator.serviceWorker.register("sw.js").catch(() => {});  // hardened browsers may refuse it; the page works without
}

// boot last, so every declaration above exists before the first view loads
setUI(UI, false);  // the screen-size default stays a default until someone picks
window.addEventListener("hashchange", route);

route();
// the guide opens by itself on a first visit (?guide forces it; screenshots with ?shot skip it)
(() => {
  const q = new URLSearchParams(location.search);
  let seen = null;
  try { seen = localStorage.getItem("wheel.guided"); } catch {}
  if (q.has("guide") || (!seen && !q.has("shot") && !location.hash.startsWith("#l/"))) openGuide();  // a shared link opens its listing
})();
refreshCount();
