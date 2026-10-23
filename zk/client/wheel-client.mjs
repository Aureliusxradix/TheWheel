// wheel-client.mjs — the browser half of The Wheel's anonymous members. Bundled by `npm run build`
// into dist/wheel-zk.js and copied to hub/static/vendor/. Pattern from the members client on
// aureliusxradix.com, with its own key so the two lists never meet.
//
// One secret lives in this browser. The member identity is derived from it; the secret never leaves the
// device. The service only ever sees the commitment and proofs. Proving files load from our own host.
import { Identity } from "@semaphore-protocol/identity"
import { Group } from "@semaphore-protocol/group"
import { generateProof } from "@semaphore-protocol/proof"

const KEY = "wheel.master"
const SHOWUPS = "wheel.showups"
const VOUCHES = "wheel.vouches"
const GOINGS = "wheel.goings"
const FIELD = 21888242871839275222717131064758314466096019186001779448845833037201683149097n

const store = {
  get(k) { try { return localStorage.getItem(k) } catch { return null } },
  set(k, v) { try { localStorage.setItem(k, v); return true } catch { return false } },
}
const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("")
async function sha256hex(s) { return hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s))) }
// same as zk/core.mjs toField: sha256 of the text, reduced into the field
async function toField(s) { return (BigInt("0x" + (await sha256hex(s))) % FIELD).toString() }

function master(create) {
  let m = store.get(KEY)
  if (!m && create) {
    m = hex(crypto.getRandomValues(new Uint8Array(32)))
    if (!store.set(KEY, m)) return null
  }
  return m
}
async function identity(create = false) {
  const m = master(create)
  if (!m) return null
  return new Identity(await sha256hex(`${m}:wheel`))
}

// The hub's join work (hub/server.py work_ok): find n with sha256("nonce:commitment:n") starting in `bits` zero bits.
// Hashed in batches so the browser's crypto runs them together.
export async function solveWork(nonce, commitment, bits) {
  const enc = new TextEncoder()
  for (let base = 0; ; base += 256) {
    const hs = await Promise.all(Array.from({ length: 256 }, (_, i) => crypto.subtle.digest("SHA-256", enc.encode(`${nonce}:${commitment}:${base + i}`))))
    for (let i = 0; i < 256; i++) {
      let z = 0
      for (const x of new Uint8Array(hs[i])) { if (x === 0) { z += 8; continue } z += Math.clz32(x) - 24; break }
      if (z >= bits) return base + i
    }
  }
}

export function createWheel({ api, zk }) {
  const call = async (p, body) => {
    const r = await fetch(api + p, {
      method: body ? "POST" : "GET",
      headers: body ? { "content-type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
      credentials: "omit", referrerPolicy: "no-referrer",
    })
    let json = null
    try { json = await r.json() } catch {}
    return { status: r.status, json }
  }
  return {
    async status() {
      const g = await call("/group")
      if (g.status !== 200) return { online: false }
      const id = await identity(false)
      const member = !!id && g.json.members.includes(id.commitment.toString())
      return { online: true, size: g.json.size, member, hasKey: !!id }
    },
    async join() {
      const id = await identity(true)
      if (!id) return { ok: false, why: "storage" }
      const commitment = id.commitment.toString()
      const w = await call("/join-work", {}) // a few seconds of work first: cheap once, a cost per account in bulk
      if (w.status !== 200 || !w.json?.nonce) return { ok: false, why: "offline" }
      const n = await solveWork(w.json.nonce, commitment, Math.min(Number(w.json.bits) || 0, 24))
      const r = await call("/join", { commitment, work: { nonce: w.json.nonce, n } })
      return r.status === 200 ? { ok: true, size: r.json.size } : { ok: false, why: r.json?.why || "offline" }
    },
    async showup(event, code, label) {
      const id = await identity(false)
      if (!id) return { ok: false, why: "nokey" }
      const g = await call("/group")
      if (g.status !== 200) return { ok: false, why: "offline" }
      if (!g.json.members.includes(id.commitment.toString())) return { ok: false, why: "notmember" }
      const group = new Group(g.json.members.map(BigInt))
      const depth = Math.max(1, group.depth)
      const door = String(code).trim().toUpperCase()
      const scope = await toField(`wheel-showup:${event}`)
      const message = await toField(`wheel-door:${door}`)
      const proof = await generateProof(id, group, message, scope, depth, {
        wasm: `${zk}semaphore-${depth}.wasm`,
        zkey: `${zk}semaphore-${depth}.zkey`,
      })
      const r = await call("/showup", { event, code: door, proof })
      if (r.status === 200) {
        const mine = JSON.parse(store.get(SHOWUPS) || "[]")
        if (!mine.some((s) => s.event === event)) mine.push({ event, label })
        store.set(SHOWUPS, JSON.stringify(mine)) // the device keeps its own record; the service never can
        return { ok: true, count: r.json.count }
      }
      return { ok: false, why: r.json?.why || "offline", count: r.json?.count }
    },
    async vouch(practitioner) {  // one per member per practitioner; the device keeps its own list of whom it vouched for
      const id = await identity(false)
      if (!id) return { ok: false, why: "nokey" }
      const g = await call("/group")
      if (g.status !== 200) return { ok: false, why: "offline" }
      if (!g.json.members.includes(id.commitment.toString())) return { ok: false, why: "notmember" }
      const group = new Group(g.json.members.map(BigInt))
      const depth = Math.max(1, group.depth)
      const proof = await generateProof(id, group, await toField("wheel-vouch"), await toField(`wheel-vouch:${practitioner}`), depth, {
        wasm: `${zk}semaphore-${depth}.wasm`,
        zkey: `${zk}semaphore-${depth}.zkey`,
      })
      const r = await call("/vouch", { practitioner, proof })
      if (r.status === 200 || r.json?.why === "again") {
        const mine = JSON.parse(store.get(VOUCHES) || "[]")
        if (!mine.includes(practitioner)) mine.push(practitioner)
        store.set(VOUCHES, JSON.stringify(mine))
      }
      return r.status === 200 ? { ok: true, count: r.json.count } : { ok: false, why: r.json?.why || "offline", count: r.json?.count }
    },
    vouched: () => JSON.parse(store.get(VOUCHES) || "[]"),
    async going(event, undo = false) {  // an anonymous Going: counted once, taken back with the same member's proof
      const id = await identity(false)
      if (!id) return { ok: false, why: "nokey" }
      const g = await call("/group")
      if (g.status !== 200) return { ok: false, why: "offline" }
      if (!g.json.members.includes(id.commitment.toString())) return { ok: false, why: "notmember" }
      const group = new Group(g.json.members.map(BigInt))
      const depth = Math.max(1, group.depth)
      const proof = await generateProof(id, group, await toField(undo ? "wheel-going-undo" : "wheel-going"), await toField(`wheel-going:${event}`), depth, {
        wasm: `${zk}semaphore-${depth}.wasm`,
        zkey: `${zk}semaphore-${depth}.zkey`,
      })
      const r = await call("/going", { event, proof })
      if (r.status === 200 || r.json?.why === "again") {
        const mine = JSON.parse(store.get(GOINGS) || "[]").filter((e) => e !== event)
        if (!undo) mine.push(event)
        store.set(GOINGS, JSON.stringify(mine))
      }
      return r.status === 200 ? { ok: true, count: r.json.count } : { ok: false, why: r.json?.why || "offline", count: r.json?.count }
    },
    goings: () => JSON.parse(store.get(GOINGS) || "[]"),
    async login() {
      const id = await identity(false)
      if (!id) return { ok: false, why: "nokey" }
      const g = await call("/group")
      if (g.status !== 200) return { ok: false, why: "offline" }
      if (!g.json.members.includes(id.commitment.toString())) return { ok: false, why: "notmember" }
      const ch = await call("/challenge", {})
      if (ch.status !== 200) return { ok: false, why: "offline" }
      const group = new Group(g.json.members.map(BigInt))
      const depth = Math.max(1, group.depth)
      let proof
      try {
        proof = await generateProof(id, group, ch.json.nonce, await toField("wheel-account"), depth, {
          wasm: `${zk}semaphore-${depth}.wasm`,
          zkey: `${zk}semaphore-${depth}.zkey`,
        })
      } catch (e) {
        return { ok: false, why: "prover", detail: `The proof could not be made on this device (${String(e?.message || e).slice(0, 120)}).` }
      }
      const r = await call("/login", { proof })
      if (r.status !== 200) return { ok: false, why: r.json?.why || "refused" }
      try { sessionStorage.setItem("wheel.session", r.json.token) } catch {}
      return { ok: true, token: r.json.token, account: r.json.account }
    },
    session: () => { try { return sessionStorage.getItem("wheel.session") } catch { return null } },
    forget: () => { try { sessionStorage.removeItem("wheel.session") } catch {} },
    // Sign out of this browser: the key, the session and the device's own check-in list all go. The member list keeps
    // the sealed copy, so the same key brings the same pen name back on any device.
    signOut() {
      for (const k of [KEY, SHOWUPS]) { try { localStorage.removeItem(k) } catch {} }
      try { sessionStorage.removeItem("wheel.session") } catch {}
      return !store.get(KEY)
    },
    count: async (event) => (await call(`/count?event=${encodeURIComponent(event)}`)).json?.count ?? 0,
    myShowups: () => JSON.parse(store.get(SHOWUPS) || "[]"),
    key: () => master(false),
    restore(secret) {
      const s = String(secret || "").trim().toLowerCase()
      if (!/^[0-9a-f]{64}$/.test(s)) return false
      return store.set(KEY, s)
    },
  }
}

window.createWheel = createWheel
window.solveWheelWork = solveWork // the browser self-test joins filler members with it
