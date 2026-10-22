// core.mjs — The Wheel's anonymous members and show-ups. No HTTP here; server.mjs calls in.
// Pattern taken from the members service on aureliusxradix.com, with The Wheel's own rulings
// (2026-10-20): its own members list, profiles before the floor with low friction first, a show-up nullifier
// fixed per event.
//
// What this file refuses to hold:
//   - any name, email, phone, IP or user agent
//   - any timestamp beside a commitment (a join lands at a random place in the list)
//   - any door code in plain text (only its hash, and only while the check-in is open; a code that changes every
//     minute keeps the secret it is derived from, also only while the check-in is open)
//   - any link between a show-up and a member: the store keeps per event only the nullifiers,
//     which differ for the same person from one event to the next
import { createHash, createHmac, randomBytes, randomInt } from "node:crypto"
import fs from "node:fs"
import path from "node:path"
import { Group } from "@semaphore-protocol/group"
import { verifyProof } from "@semaphore-protocol/proof"

// BN254 scalar field: commitments, scopes and messages are field elements.
export const FIELD = 21888242871839275222717131064758314466096019186001779448845833037201683149097n
export const ROOT_HISTORY = 32 // a proof made against one of the last 32 member lists still counts
export const CHECKIN_TTL_MS = 6 * 60 * 60 * 1000
const CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789" // no 0/O, 1/I/L
// A door code that changes every minute (organisers' check-ins, 2026-10-23): while such a check-in is open it keeps a
// secret, and each minute's code is derived from it; the opener's screen derives the same codes from the same secret.
// A code read out at the door works for its minute and the two after, so a code passed around outside soon stops.
export const ROTATE_MS = 60 * 1000
const ROTATE_GRACE = 2
export function rotatingCode(secretHex, eventId, minute) {
  const mac = createHmac("sha256", Buffer.from(secretHex, "hex")).update(`${eventId}:${minute}`).digest()
  return Array.from(mac.subarray(0, 6), (b) => CODE_ALPHABET[b % CODE_ALPHABET.length]).join("")
}

const sha256hex = (s) => createHash("sha256").update(s).digest("hex")
// The browser computes the same two values (client/wheel-client.mjs); keep them identical.
export const toField = (s) => (BigInt("0x" + sha256hex(s)) % FIELD).toString()
export const showupScope = (eventId) => toField(`wheel-showup:${eventId}`)
export const doorMessage = (code) => toField(`wheel-door:${String(code).trim().toUpperCase()}`)
// Account login (his ruling 2026-10-20: review open, tied to an account): one fixed scope, so a member's nullifier
// here is the same every time and serves as their pen name inside The Wheel. It differs from every show-up nullifier
// (scoped per event), so a pen name cannot be joined to where its owner checked in.
export const ACCOUNT_SCOPE = toField("wheel-account")
export const accountId = (nullifier) => sha256hex(`wheel-pen:${nullifier}`).slice(0, 16)
export const NONCE_TTL_MS = 5 * 60 * 1000
export const SESSION_TTL_MS = 12 * 60 * 60 * 1000

export class Wheel {
  constructor(dir, clock = () => new Date()) {
    this.dir = dir
    this.clock = clock
    fs.mkdirSync(dir, { recursive: true })
    this.members = this.#load("members.json", [])
    this.roots = this.#load("roots.json", [])
    this.checkins = this.#load("checkins.json", {})
    this.showups = this.#load("showups.json", {})
  }
  #load(name, empty) {
    try { return JSON.parse(fs.readFileSync(path.join(this.dir, name), "utf8")) } catch { return empty }
  }
  #save(name, value) {
    const f = path.join(this.dir, name)
    fs.writeFileSync(f + ".tmp", JSON.stringify(value))
    fs.renameSync(f + ".tmp", f)
  }
  #root() {
    return this.members.length ? new Group(this.members.map(BigInt)).root.toString() : null
  }

  group() {
    return { size: this.members.length, members: this.members }
  }

  join(commitment) {
    const c = String(commitment ?? "")
    if (!/^\d{1,80}$/.test(c)) return { ok: false, why: "commitment" }
    const n = BigInt(c)
    if (n <= 0n || n >= FIELD) return { ok: false, why: "commitment" }
    if (!this.members.includes(c)) {
      this.members.splice(randomInt(0, this.members.length + 1), 0, c) // order says nothing about who came when
      this.roots = [...this.roots, this.#root()].slice(-ROOT_HISTORY)
      this.#save("members.json", this.members)
      this.#save("roots.json", this.roots)
    }
    return { ok: true, size: this.members.length }
  }

  openCheckin(eventId, rotating = false) {
    const id = String(eventId ?? "")
    if (!/^[0-9a-f]{16}$/.test(id)) return { ok: false, why: "event" }
    if (rotating) {  // the secret goes once to the opener's screen and is kept here only while the check-in is open
      const secret = randomBytes(32).toString("hex"), closes = this.clock().getTime() + CHECKIN_TTL_MS
      this.checkins[id] = { secret, closes }
      this.#sweep()
      this.#save("checkins.json", this.checkins)
      return { ok: true, secret, closes, rotate: ROTATE_MS }
    }
    const code = Array.from(randomBytes(6), (b) => CODE_ALPHABET[b % CODE_ALPHABET.length]).join("")
    const closes = this.clock().getTime() + CHECKIN_TTL_MS
    this.checkins[id] = { hash: sha256hex(code), closes }
    this.#sweep()
    this.#save("checkins.json", this.checkins)
    return { ok: true, code, closes } // the code is shown once to whoever opened the check-in, never stored
  }

  #sweep() {
    const now = this.clock().getTime()
    for (const [id, c] of Object.entries(this.checkins)) if (c.closes < now) delete this.checkins[id]
  }

  async showup(eventId, code, proof) {
    const id = String(eventId ?? "")
    this.#sweep()
    const c = this.checkins[id]
    if (!c) return { ok: false, why: "closed" }
    const door = String(code ?? "").trim().toUpperCase()
    if (c.secret) {
      const m = Math.floor(this.clock().getTime() / ROTATE_MS)
      const fits = Array.from({ length: ROTATE_GRACE + 1 }, (_, i) => rotatingCode(c.secret, id, m - i)).includes(door)
      if (!fits) return { ok: false, why: "code" }
    } else if (sha256hex(door) !== c.hash) return { ok: false, why: "code" }
    if (!proof || typeof proof !== "object") return { ok: false, why: "proof" }
    if (String(proof.scope) !== showupScope(id)) return { ok: false, why: "scope" }
    if (String(proof.message) !== doorMessage(door)) return { ok: false, why: "message" }
    if (!this.roots.includes(String(proof.merkleTreeRoot))) return { ok: false, why: "root" }
    const seen = (this.showups[id] ||= [])
    const nullifier = String(proof.nullifier)
    if (seen.includes(nullifier)) return { ok: false, why: "again", count: seen.length }
    let valid = false
    try { valid = await verifyProof(proof) } catch { valid = false }
    if (!valid) return { ok: false, why: "proof" }
    seen.push(nullifier)
    this.#save("showups.json", this.showups)
    return { ok: true, count: seen.length }
  }

  // ---- sessions: in memory only; a restart signs everyone out and the client signs back in by itself ----
  challenge() {
    const now = this.clock().getTime()
    this.nonces ||= new Map()
    for (const [k, exp] of this.nonces) if (exp < now) this.nonces.delete(k)
    const nonce = BigInt("0x" + randomBytes(31).toString("hex")).toString() // below the field
    this.nonces.set(nonce, now + NONCE_TTL_MS)
    return { nonce }
  }

  async login(proof) {
    const now = this.clock().getTime()
    this.nonces ||= new Map()
    this.sessions ||= new Map()
    if (!proof || typeof proof !== "object") return { ok: false, why: "proof" }
    const nonce = String(proof.message)
    const exp = this.nonces.get(nonce)
    if (!exp || exp < now) return { ok: false, why: "nonce" }
    this.nonces.delete(nonce) // single use, whatever happens next
    if (String(proof.scope) !== ACCOUNT_SCOPE) return { ok: false, why: "scope" }
    if (!this.roots.includes(String(proof.merkleTreeRoot))) return { ok: false, why: "root" }
    let valid = false
    try { valid = await verifyProof(proof) } catch { valid = false }
    if (!valid) return { ok: false, why: "proof" }
    const token = randomBytes(32).toString("base64url")
    const account = accountId(String(proof.nullifier))
    this.sessions.set(token, { account, exp: now + SESSION_TTL_MS })
    return { ok: true, token, account }
  }

  session(token) {
    const s = token && this.sessions?.get(String(token))
    if (!s || s.exp < this.clock().getTime()) return null
    return { account: s.account }
  }

  count(eventId) {
    return (this.showups[String(eventId ?? "")] || []).length
  }
}
