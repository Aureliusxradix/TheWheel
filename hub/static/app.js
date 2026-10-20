// The Wheel: three mode views (Day, Night, Recovery) and the tools, hash-routed.
// Built on the aureliusxradix instrument; looks his picks of 2026-10-20 (style.css).
"use strict";
// screenshot aid: ?shot holds the load event while the data arrives
if (new URLSearchParams(location.search).has("shot")) { const i = new Image(); i.src = "/__wait?ms=3000"; i.hidden = true; document.body?.append(i); }

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { events: [], areas: [], today: "", mode: "night", range: "all", kind: null, area: null, facet: null, allKinds: false };

/* Each mode is its own view: its own look, its own words, its own way of finding. */
const MODES = {
  day: {
    look: "day", title: "Day",
    lede: "Shifts that need hands, workshops and skillshares. Help where you can.",
    search: "Search: cooking, set-up, Orewa…",
    ranges: [["week", "Next 7 days"], ["weekend", "This weekend"], ["all", "Everything coming up"]],
    facetLabel: "Help with",
  },
  night: {
    look: "night", title: "Night",
    lede: "Gigs, socials and gatherings. Where to go out.",
    search: "Search: kava, poetry, Orewa…",
    ranges: [["tonight", "Tonight"], ["weekend", "This weekend"], ["week", "Next 7 days"], ["all", "Everything coming up"]],
  },
  recovery: {
    look: "recovery", title: "Recovery",
    lede: "Retreats, rest and restoring. Time to come back to yourself.",
    search: "Search: breathwork, retreat, sound bath…",
    ranges: [["week", "Next 7 days"], ["weekend", "This weekend"], ["all", "Everything coming up"]],
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
const MIN_CROWD = 3;   // proposal (rep study): no check-in proof offered below 3 members; his to set
const WARN_CROWD = 10; // proposal: under 10, say plainly that a proof hides little

function crowdLine(size) {
  if (size < MIN_CROWD) return `The Wheel has ${size} member${size === 1 ? "" : "s"}. Check-ins open once ${MIN_CROWD} people have joined, so a check-in can hide who made it.`;
  if (size < WARN_CROWD) return `You are one of ${size} members. A check-in proves a member was there, not which one, but among ${size} people that hides little. It gets stronger as people join.`;
  return `You are one of ${size} members. A check-in proves a member was there, not which one.`;
}

// Hardened browsers (secureblue's Trivalent among them) switch the JavaScript optimiser off, and WebAssembly with it.
// The proofs need WebAssembly, so say so plainly instead of failing quietly.
const NO_WASM = typeof WebAssembly === "undefined";
const NO_WASM_TEXT = "This browser has WebAssembly switched off, and the proof that logs you in needs it. Hardened browsers do this (secureblue's Trivalent does by default). To fix it for The Wheel only: open the site settings from the icon left of the address, find JavaScript optimisation (V8 optimiser), allow it for this site, and reload. Or use another browser.";

async function loadMe() {
  const box = $("#me-body");
  if (!W) { box.innerHTML = `<p class="status err">The member tools did not load. Reload the page.</p>`; return; }
  const st = await W.status();
  if (!st.online) { box.innerHTML = `<p class="status err">The member service is not answering. Try again in a minute.</p>`; return; }
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
    <h2 class="sub">Your key</h2>
    <p class="lede">The key lives on this device alone. Keep a copy somewhere only you can reach, such as your password manager, so a new phone can carry on as you. Anyone holding it is you on The Wheel.</p>
    <div class="keyrow"><input id="my-key" type="password" readonly value="${esc(W.key() || "")}" aria-label="Your key">
    <button type="button" class="quiet" data-showkey="1">Show</button><button type="button" class="quiet" data-copykey="1">Copy</button></div>
    <h2 class="sub">Where you've checked in</h2>
    ${mine.length ? `<ul class="claims">${mine.map((s) => `<li>${esc(s.label || s.event)}</li>`).join("")}</ul>` : `<p class="lede">Nothing yet. At an event, open its listing and tap "I'm here".</p>`}
    <p class="hint">This list is kept on this device only. The Wheel itself never learns who checked in where.</p>
    <h2 class="sub">Sign out</h2>
    <p class="lede">Signing out takes your key and your check-in list off this browser. To come back as ${me ? esc(me.account) : "this pen name"}, you need the key, so copy it first.</p>
    <div class="actions"><button type="button" class="quiet" data-copykey="1">Copy my key</button>
    <button type="button" class="danger" data-signout="1">Sign out of this browser</button></div>
    <p class="status" id="signout-status" role="status"></p></div>`;
}

async function joinWheel(btn) {
  if (!btn.dataset.sure) {  // one more tap: a returning member should sign in, not start over
    btn.dataset.sure = "1";
    btn.textContent = "Yes, make me a new pen name";
    $("#me-status").textContent = "Joined before? Sign in with your key instead, on the left. Joining again makes a second, separate you.";
    return;
  }
  $("#me-status").textContent = "Joining…";
  const r = await W.join();
  if (!r.ok) { $("#me-status").textContent = r.why === "storage" ? "This browser won't keep the key (private window?). Try a normal window." : "The member service did not answer. Try again in a moment."; return; }
  toast("Joined");
  loadMe();
}

async function signIn() {
  const out = $("#restore-status");
  if (!W.restore($("#restore-key").value)) { out.textContent = "That isn't a key from The Wheel. A key is 64 letters and numbers."; return; }
  const st = await W.status();
  if (!st.member) { W.signOut(); out.textContent = "That key is not on this Wheel's members list. Check you copied all of it."; return; }
  toast("Signed in");
  loadMe();
}

function signOut(btn) {
  if (!btn.dataset.sure) {
    btn.dataset.sure = "1";
    btn.textContent = "Yes, sign out";
    $("#signout-status").textContent = "Have you copied your key? Without it, this pen name stays on the list but you can't come back as it.";
    return;
  }
  W.signOut();
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
  if (st.size < MIN_CROWD) { out.textContent = crowdLine(st.size); return; }
  if (NO_WASM) { out.textContent = NO_WASM_TEXT; return; }
  btn.disabled = true;
  out.textContent = "Making your proof on this device. This takes a few seconds.";
  try {
    const r = await W.showup(box.dataset.event, code, box.dataset.label);
    out.textContent = r.ok ? `Checked in. ${r.count} ${r.count === 1 ? "person has" : "people have"} checked in here.`
      : ({ again: "You've already checked in here.", code: "That code doesn't match. Check it with the host.", closed: "Check-in isn't open for this event.", notmember: "Join first, on the Me page.", root: "The members list just changed. Tap again." }[r.why] || "That didn't work. Try again.");
  } catch (e) { out.textContent = "Your device couldn't make the proof. Try again, or on another device."; }
  btn.disabled = false;
}

async function openCheckin(btn) {
  const id = btn.dataset.opencheckin;
  const out = btn.closest(".actions").nextElementSibling;
  const r = await api("/api/zk/checkin", { event: id }).catch((e) => ({ ok: false, why: e.message }));
  if (!r.ok) { out.textContent = "Couldn't open check-in: " + (r.why || "the member service did not answer") + "."; return; }
  const closes = new Date(r.closes).toLocaleTimeString("en-NZ", { hour: "2-digit", minute: "2-digit" });
  out.innerHTML = `<div class="doorcode">${esc(r.code)}</div><p class="hint">Show this at the door. It works until ${esc(closes)} and is not stored anywhere; opening check-in again makes a new one.</p>`;
}

/* ---------- look ---------- */
function setLook(look) { document.documentElement.dataset.look = look; }

/* ---------- dates ---------- */
const d = (iso) => new Date(iso + "T12:00:00");
const fmtMonth = (iso) => d(iso).toLocaleDateString("en-NZ", { month: "long", year: "numeric" });
const fmtDay = (iso) => d(iso).toLocaleDateString("en-NZ", { weekday: "short" });
const fmtShort = (iso) => d(iso).toLocaleDateString("en-NZ", { weekday: "short", day: "numeric", month: "short" });
const addDays = (iso, n) => { const x = d(iso); x.setDate(x.getDate() + n); return x.toISOString().slice(0, 10); };
const mins = (t) => (t ? +t.slice(0, 2) * 60 + +t.slice(3, 5) : null);

function inRange(ev) {
  const t = state.today, r = state.range;
  if (r === "all") return true;
  if (r === "tonight") return ev.start_date <= t && (ev.end_date || ev.start_date) >= t;
  if (r === "week") return ev.start_date <= addDays(t, 7);
  const dow = d(t).getDay(); // 0 Sun .. 6 Sat
  const fri = addDays(t, dow === 0 ? -2 : 5 - dow);
  const sun = addDays(fri, 2);
  return ev.start_date <= sun && (ev.end_date || ev.start_date) >= (dow === 0 || dow === 6 ? t : fri);
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
  renderMode();
}

function inMode(ev) { return (ev.modes || []).includes(state.mode); }

function renderMode() {
  const m = MODES[state.mode];
  $("#h-mode").textContent = m.title;
  $("#mode-lede").textContent = m.lede;
  $("#q").placeholder = m.search;
  if (!m.ranges.some(([k]) => k === state.range)) state.range = "all";
  $("#ranges").innerHTML = m.ranges.map(([k, label]) => `<button type="button" data-range="${k}" class="${state.range === k ? "on" : ""}">${label}</button>`).join("");
  renderTerms();
  renderChips();
  renderList();
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
    const next = live.map((e) => (e.start_date < today ? today : e.start_date)).sort()[0];
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
  const all = Object.entries(tc).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const kinds = state.allKinds ? all : all.slice(0, 10);
  if (state.kind && !kinds.some(([t]) => t === state.kind)) { const k = all.find(([t]) => t === state.kind); if (k) kinds.push(k); }
  const more = all.length > 10 ? `<button type="button" class="linklike" data-morekinds="1">${state.allKinds ? "Fewer kinds" : `All ${all.length} kinds`}</button>` : "";
  $("#kind-row").innerHTML = chipRow("Kinds", kinds, "kind", state.kind, more);
  $("#area-row").innerHTML = chipRow("Areas", state.areas.map((a) => [a.name, null]), "area", state.area);
}

function matches(ev) {
  if (!inMode(ev)) return false;
  const q = $("#q").value.trim().toLowerCase();
  if (state.kind && !(ev.tags || []).includes(state.kind)) return false;
  if (state.area && !(ev.areas || []).includes(state.area)) return false;
  if (state.facet && state.mode === "day" && !helpWith(ev).includes(state.facet)) return false;
  if (state.facet && state.mode === "recovery" && lengthOf(ev) !== state.facet) return false;
  if (!ev.past && !inRange(ev)) return false;
  if (!q) return true;
  const hay = [ev.name, ev.summary, ev.description, ev.location_name, ev.location_locality, ev.organiser,
    ...(ev.tags || []), ...(ev.areas || []), ...helpWith(ev)].join(" ").toLowerCase();
  return q.split(/\s+/).every((w) => hay.includes(w));
}

function when(ev) {
  let s = ev.start_time ? (ev.end_time ? `${ev.start_time}–${ev.end_time}` : `from ${ev.start_time}`) : "Time not given";
  if (ev.end_date && ev.end_date !== ev.start_date) s += `, until ${d(ev.end_date).toLocaleDateString("en-NZ", { day: "numeric", month: "short" })}`;
  return s;
}

function shiftsTable(ev) {
  if (!(ev.slots || []).length) return "";
  return `<div class="shifts-wrap"><table class="shifts"><thead><tr><th scope="col">When</th><th scope="col">Task</th><th scope="col">People</th></tr></thead><tbody>` +
    ev.slots.map((s) => `<tr><td>${esc(fmtShort(s.date))}, ${esc(s.start || "")}${s.end ? "–" + esc(s.end) : ""}</td><td>${esc(s.task || "")}</td><td>${s.needed ? `<span class="seats" aria-hidden="true">${"<i></i>".repeat(Math.min(s.needed, 20))}</span>${s.needed}` : "?"}</td></tr>`).join("") +
    `</tbody></table></div>`;
}

function eventRow(ev, i = 0) {
  const where = [ev.location_name, ev.location_locality && !(ev.location_name || "").includes(ev.location_locality) ? ev.location_locality : null].filter(Boolean).join(", ");
  const unreviewed = ev.review?.state !== "approved";
  const volunteer = ev.listing_kind === "volunteer";
  const chips = [];
  if (volunteer) chips.push(`<span class="chip strong">Helpers wanted</span>`);
  if (ev.recurrence) chips.push(`<span class="chip">Repeats: ${esc(ev.recurrence.slice(0, 50))}</span>`);
  if ((ev.modes || []).includes("recovery") && state.mode !== "recovery") chips.push(`<span class="chip">Recovery</span>`);
  (ev.areas || []).forEach((a) => chips.push(`<span class="chip">${esc(a)}</span>`));
  (ev.tags || []).slice(0, 4).forEach((t) => chips.push(`<span class="chip">${esc(t)}</span>`));
  const src = ev.website || ev.source?.url;  // where to sign up: the organiser's page first
  const dt = d(ev.start_date);
  const pct = (x) => `${Math.round((x || 0) * 100)}%`;
  const c = ev.certainty || {};
  const status = ev.status && ev.status !== "confirmed"
    ? `<span class="state flag">${esc(ev.status)}</span>`
    : unreviewed ? `<span class="state" title="${c.reviews || 0} review(s) so far">waiting${c.reviews ? ` · ${pct(c.for)}` : ""}</span>`
      : `<span class="state ok" title="How sure the reviewers are, weighted by their rep">√ checked · ${pct(c.for)}</span>`;
  return `<article class="ev k${i % 3}${volunteer ? " volunteer" : ""}${ev.past ? " past" : ""}" id="ev-${ev.id}">
    <span class="n">${dt.getDate()} ${dt.toLocaleDateString("en-NZ", { month: "short" })}<small>${fmtDay(ev.start_date)}</small></span>
    <div class="ev-main">
      <button type="button" class="ev-name" aria-expanded="false" data-open="${ev.id}">${esc(ev.name)}</button>
      <div class="meta"><span>${esc(when(ev))}</span>${where ? `<span>${esc(where)}</span>` : ""}${ev.price ? `<span>${esc(ev.price)}</span>` : ""}</div>
      ${shiftsTable(ev)}
      ${(ev.requirements || []).length ? `<div class="line">Asks for: ${esc(ev.requirements.join(", "))}</div>` : ""}
      ${volunteer && src && !ev.past ? `<div><a class="signup" href="${esc(src)}" target="_blank" rel="noopener">Sign up with the organiser</a></div>` : ""}
      <div class="chips">${chips.join("")}</div>
      ${unreviewed ? `<div class="actions inline-review"><button type="button" class="quiet" data-inline="${ev.id}">Review this one</button></div>` : ""}
      <div class="inline-card" hidden></div>
      <div class="more" hidden>
        ${ev.description ? `<p>${esc(ev.description)}</p>` : ""}
        ${ev.organiser ? `<div>Organised by ${esc(ev.organiser)}</div>` : ""}
        ${whereFrom(ev)}
        ${ev.past ? "" : `<div class="checkin" data-event="${ev.id}" data-label="${esc(ev.name)}, ${esc(ev.start_date)}">
          <label for="code-${ev.id}">At the event? Enter the door code</label>
          <div class="keyrow"><input id="code-${ev.id}" type="text" maxlength="6" autocomplete="off" spellcheck="false" placeholder="A1B2C3"><button type="button" class="quiet" data-checkin="1">I'm here</button></div>
          <p class="status" role="status"></p></div>`}
      </div>
    </div>
    ${status}</article>`;
}

function grouped(list) {
  let html = "", month = "", i = 0;
  for (const ev of list) {
    const m = fmtMonth(ev.start_date);
    if (m !== month) { html += `<h2 class="month">${m}</h2>`; month = m; }
    html += eventRow(ev, i++);
  }
  return html;
}

function renderList() {
  const key = (e) => e.start_date + (e.start_time || "");
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
      ? `<p class="empty">Nothing in ${MODES[state.mode].title} matches. Clear the search or pick another chip.</p>`
      : `<p class="empty">Nothing in ${MODES[state.mode].title} yet. <a href="#add">Add the first listing</a> from a post, a link or a flyer.</p>`;
  }
  $("#list").innerHTML = html;
}

/* Where a listing came from, said plainly (his ruling 2026-10-20: no page online is allowed, labelled, the flyer shown).
   The organiser's page and the page we found it on are two different links. */
function flyerImg(ev) {
  const f = ev.source?.flyer;
  return f && /^[0-9a-f]{16}\.webp$/.test(f)
    ? `<a class="flyer" href="${API}/api/flyer/${f}" target="_blank" rel="noopener"><img src="${API}/api/flyer/${f}" alt="The flyer for ${esc(ev.name)}" loading="lazy"></a>` : "";
}
function whereFrom(ev) {
  const found = ev.source?.url && ev.source.url !== ev.website ? ev.source.url : null;
  const out = [];
  if (ev.website) out.push(`<div><a href="${esc(ev.website)}" target="_blank" rel="noopener">Organiser's page</a></div>`);
  if (ev.tickets_url) out.push(`<div><a href="${esc(ev.tickets_url)}" target="_blank" rel="noopener">Tickets</a></div>`);
  if (found) out.push(`<div><a href="${esc(found)}" target="_blank" rel="noopener">Where we found it</a></div>`);
  if (ev.source?.flyer) out.push(`<div class="hint">Found on a flyer${ev.website ? "" : ", no page online"}.</div>${flyerImg(ev)}`);
  else if (!ev.website && !found) out.push(`<div class="hint">From a post, no page online.</div>`);
  return out.join("");
}

/* ---------- the listing editor (add and review share it) ---------- */
const FIELDS = [
  ["name", "Name", "wide"], ["start_date", "Date (2026-10-24)"], ["start_time", "Starts (19:30)"],
  ["end_date", "Ends on"], ["end_time", "Ends at"], ["location_name", "Place"], ["location_locality", "Town or suburb"],
  ["price", "Price"], ["recurrence", "Repeats"], ["tags", "Kinds, separated by commas", "wide"],
  ["website", "Organiser's page or post (a link)", "wide"], ["tickets_url", "Tickets (a link)", "wide"],
  ["description", "Description (the organiser's words)", "wide"],
];

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
    </div>`;
}

function readEditor(card) {
  const out = {};
  $$("[data-k]", card).forEach((el) => {
    const k = el.dataset.k;
    out[k] = k === "tags" || k === "requirements" ? el.value.split(",").map((t) => t.trim()).filter(Boolean) : el.value;
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
    const out = await api("/api/read", { text, image: flyer });
    $("#add-status").textContent = out.records.length
      ? `Found ${out.records.length} listing${out.records.length > 1 ? "s" : ""}. Check each one, fix anything wrong, then send it for review.`
      : `Nothing to list. ${out.notes.join(" ")}`;
    $("#found").innerHTML = out.records.map((ev, i) => `<div class="card" data-i="${i}">
      <h2>${esc(ev.name)}</h2>${dupWarn(ev)}${flyerImg(ev)}
      ${!ev.website && !ev.source?.url ? `<div class="warn">Where can people find this online? If the organiser has a page or a post, put its link in "Organiser's page or post" below. If there is none, it goes out marked "no page online"${ev.source?.flyer ? ", with the flyer shown" : ""}.</div>` : ""}
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
  const modeNames = (ev.modes || []).map((m) => MODES[m]?.title || m).join(", ");
  const where = [ev.location_name, ev.location_locality && !(ev.location_name || "").includes(ev.location_locality) ? ev.location_locality : null].filter(Boolean).join(", ");
  // compact first: what to check, and the two answers; the editor waits behind "Fix details" (2026-10-20, Finishing what's here)
  return `<div class="card rv" data-id="${ev.id}">
      <div class="rv-when">${esc(fmtDay(ev.start_date))} ${esc(d(ev.start_date).getDate())} ${esc(d(ev.start_date).toLocaleDateString("en-NZ", { month: "short" }))} · ${esc(when(ev))}</div>
      <h2>${esc(ev.name)}</h2>
      ${where || ev.price ? `<div class="rv-where">${esc([where, ev.price].filter(Boolean).join(" · "))}</div>` : ""}
      ${modeNames ? `<div class="rv-where">Shows in: ${esc(modeNames)}${ev.extraction?.modes_by ? " (set by a batch pass)" : ""}</div>` : ""}
      <div class="source">${src ? `Check it against <a href="${esc(src)}" target="_blank" rel="noopener">the page it came from</a>.` : ev.source?.flyer ? "Read from a flyer. Check the listing against the flyer; the flyer goes out with it." : ev.website ? `Pasted in. Check it against <a href="${esc(ev.website)}" target="_blank" rel="noopener">the organiser's page</a>.` : "Pasted in, with no page to check against."}</div>
      ${flyerImg(ev)}
      ${!ev.website && !src ? `<div class="warn">No link yet: it goes out marked "no page online".${canFix ? " Add the organiser's page under Fix details if you know it." : ""}</div>` : ""}
      ${notes ? `<div class="warn">${esc(notes)}</div>` : ""}${dupWarn(ev)}
      <div class="source">${esc(sure)}${ev.my_verdict ? ` You said: ${ev.my_verdict === "approve" ? "right" : "wrong"}.` : ""}</div>
      ${ev.mine ? `<p class="hint">You added this one, so someone else checks it.</p>` : `<div class="actions"><button type="button" class="primary" data-act="approve">It's right</button>
      <button type="button" class="danger" data-act="reject">It's wrong</button>
      ${canFix ? `<button type="button" class="quiet" data-fix="1" aria-expanded="false">Fix details</button>` : ""}
      ${reviewMe && reviewMe.tier >= 3 ? `<button type="button" class="quiet" data-opencheckin="${ev.id}">Open check-in</button>` : ""}</div>`}
      ${canFix && !ev.mine ? `<div class="rv-edit" hidden>${editorHtml(ev, `r-${ev.id}`)}
        <div class="actions"><button type="button" class="quiet" data-act="save">Save my fixes</button></div>
        <p class="hint">"It's right" also saves what you changed here.</p></div>` : ""}
      <div class="door"></div>
      ${reviewMe && reviewMe.tier < 2 && !ev.mine ? `<p class="hint">Your review counts for ${Math.round((({0:.2,1:.4,2:.7,3:.9})[reviewMe.tier]) * 100)}% as a ${esc(reviewMe.tier_name)}. Fixing details opens at the Reviewer tier. <a href="#rep">How rep works</a>.</p>` : ""}</div>`;
}

let reviewQueue = [], reviewMode = "";
const isPast = (ev) => !ev.recurrence && (ev.end_date || ev.start_date) < new Date().toLocaleDateString("en-CA");
function renderReview() {
  const q = ($("#rq").value || "").trim().toLowerCase();
  const shown = reviewQueue.filter((ev) => (!reviewMode || (ev.modes || []).includes(reviewMode)) && (!q || q.split(/\s+/).every((w) =>
    [ev.name, ev.location_name, ev.location_locality, ev.start_date, ev.source?.url, ...(ev.tags || []), ...(ev.modes || [])].join(" ").toLowerCase().includes(w))));
  // soonest first; your own last; what already happened set aside
  const order = (a, b) => (a.mine - b.mine) || (a.start_date + (a.start_time || "")).localeCompare(b.start_date + (b.start_time || ""));
  const upcoming = shown.filter((e) => !isPast(e)).sort(order);
  const past = shown.filter(isPast).sort(order);
  const open = upcoming.filter((e) => !e.mine).length;
  $("#rq-count").textContent = reviewQueue.length ? `${open} coming up to check${past.length ? `, ${past.length} already happened` : ""}.` : "";
  $("#review-list").innerHTML = upcoming.length ? upcoming.map(reviewCard).join("")
    : reviewQueue.length ? `<p class="empty">Nothing coming up matches. Clear the search or pick All.</p>`
    : `<p class="empty">Nothing waiting. New listings land here when someone adds them.</p>`;
  $("#rq-past").hidden = !past.length;
  $("#rq-past-label").textContent = `Already happened (${past.length}): check these last, or mark them wrong`;
  $("#review-past").innerHTML = $("#rq-past").open ? past.map(reviewCard).join("") : "";
  $("#rq-past").ontoggle = () => { $("#review-past").innerHTML = $("#rq-past").open ? past.map(reviewCard).join("") : ""; };
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
  $("#pending-count").textContent = events.length || "";
  reviewQueue = events;
  renderReview();
}

async function review(card, action) {
  try {
    await api(`/api/review/${card.dataset.id}`, { action, edits: readEditor(card) });
    if (action !== "save") {
      reviewQueue = reviewQueue.filter((e) => e.id !== card.dataset.id);
      const row = card.closest(".ev");
      card.remove();
      if (row) loadEvents();
    }
    toast({ approve: "Marked right", save: "Fixes saved", reject: "Marked wrong" }[action]);
    refreshCount();
  } catch (err) { toast(err.message); }
}

async function refreshCount() {
  try { const { events } = await api("/api/review"); $("#pending-count").textContent = events.length || ""; } catch (e) { /* the count waits for the next load */ }
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
  if (e.key === "Escape" && !$("#guide").hidden) closeGuide();
  if (e.key === "Escape" && $("#more-menu").open) { $("#more-menu").open = false; $("#more-menu summary").focus(); }
});
// the Additional info drop-down closes on a pick or a click anywhere else
document.addEventListener("click", (e) => {
  const m = $("#more-menu");
  if (m.open && (!m.contains(e.target) || e.target.closest(".more-panel a"))) m.open = false;
});

async function loadRoadmap() {
  const [g, ev] = await Promise.all([W ? W.status() : { size: 0 }, api("/api/events?unreviewed=1")]);
  const n = g.size || 0;
  $("#rm-members").textContent = n;
  $("#rm-listings").textContent = ev.events.length;
  $("#rm-checked").textContent = ev.events.filter((e) => e.review?.state === "approved").length;
  $$("#rm-stages li").forEach((li) => {
    const at = +li.dataset.at;
    li.classList.toggle("reached", n >= at);
    $(".stage-state", li).textContent = n >= at ? " Reached." : ` ${at - n} more member${at - n === 1 ? "" : "s"} to go.`;
  });
}

function route() {
  const view = (location.hash.slice(1) || "night").split("/")[0];
  const isMode = view in MODES;
  if (isMode && state.mode !== view) { state.mode = view; state.facet = null; state.kind = null; }
  setLook(MODES[state.mode].look);
  $("#view-mode").hidden = !isMode;
  $$(".view").forEach((v) => { if (v.id !== "view-mode") v.hidden = v.id !== `view-${view}`; });
  $$(".top nav a").forEach((a) => a.classList.toggle("on", a.dataset.view === view || (a.dataset.view === "events" && isMode)));
  $("#more-menu").classList.toggle("on", ["roadmap", "rep"].includes(view));
  $("#more-menu").open = false;
  $("#events-link").setAttribute("href", `#${state.mode}`);
  if (isMode) loadEvents().catch((e) => ($("#list").innerHTML = `<p class="empty">${esc(e.message)}</p>`));
  if (view === "review") loadReview().catch((e) => toast(e.message));
  if (view === "areas") loadAreas().catch((e) => toast(e.message));
  if (view === "roadmap") loadRoadmap().catch((e) => toast(e.message));
  if (view === "me") loadMe().catch((e) => ($("#me-body").innerHTML = `<p class="status err">${esc(e.message)}</p>`));
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("button, a");
  if (!t) return;
  if (t.dataset.guide) { e.preventDefault(); openGuide(); return; }
  if (t.closest("#guide-body") && t.getAttribute("href")?.startsWith("#")) { closeGuide(); return; }  // a link in the guide: close it, then go
  if (t.dataset.guidenav) {
    const next = guideAt + Number(t.dataset.guidenav);
    if (next >= GUIDE.length) { closeGuide(); location.hash = `#${state.mode}`; return; }
    guideAt = Math.max(0, next); showGuideStep(); return;
  }
  if (t.dataset.guideclose) { closeGuide(); return; }
  if (t.dataset.range) { state.range = t.dataset.range; renderMode(); }
  if (t.dataset.morekinds) { state.allKinds = !state.allKinds; renderChips(); }
  if (t.dataset.kind) { state.kind = state.kind === t.dataset.kind ? null : t.dataset.kind; renderChips(); renderList(); }
  if (t.dataset.area) { state.area = state.area === t.dataset.area ? null : t.dataset.area; renderChips(); renderList(); }
  if (t.dataset.facet) { state.facet = state.facet === t.dataset.facet ? null : t.dataset.facet; renderChips(); renderList(); }
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
  if (t.dataset.del) api(`/api/areas/${t.dataset.del}/delete`, {}).then(() => { toast("Area removed"); loadAreas(); }).catch((err) => toast(err.message));
});

document.addEventListener("change", (e) => {
  if (e.target.dataset?.k === "listing_kind") $(".shift-editor", e.target.closest(".card")).hidden = e.target.value !== "volunteer";
});

$("#q").addEventListener("input", renderList);
$("#rq").addEventListener("input", renderReview);
$("#unreviewed").addEventListener("change", loadEvents);
$("#archive").addEventListener("change", renderList);
$("#add-form").addEventListener("submit", readDeposit);
$("#add-file").addEventListener("change", (e) => showFlyer(e.target.files[0]));
const drop = $("#drop");
["dragenter", "dragover"].forEach((n) => drop.addEventListener(n, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((n) => drop.addEventListener(n, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => showFlyer(e.dataTransfer.files[0]));
drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#add-file").click(); } });
$("#area-form").addEventListener("submit", saveArea);
window.addEventListener("hashchange", route);

route();
// the guide opens by itself on a first visit (?guide forces it; screenshots with ?shot skip it)
(() => {
  const q = new URLSearchParams(location.search);
  let seen = null;
  try { seen = localStorage.getItem("wheel.guided"); } catch {}
  if (q.has("guide") || (!seen && !q.has("shot"))) openGuide();
})();
refreshCount();
