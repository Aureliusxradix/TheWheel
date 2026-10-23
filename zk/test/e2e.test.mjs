// End to end with real Groth16 proofs: join, open a check-in, prove show-ups, and every refusal.
// Run: npm test (inside the pinned node image). Needs artifacts/ (bash fetch-artifacts.sh).
import { test } from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { Identity } from "@semaphore-protocol/identity"
import { Group } from "@semaphore-protocol/group"
import { generateProof } from "@semaphore-protocol/proof"
import { Wheel, showupScope, doorMessage, CHECKIN_TTL_MS, ACCOUNT_SCOPE, NONCE_TTL_MS, rotatingCode, ROTATE_MS } from "../core.mjs"

const ART = new URL("../artifacts/", import.meta.url).pathname
const prove = (id, members, message, scope) => {
  const group = new Group(members.map(BigInt))
  const depth = Math.max(1, group.depth)
  return generateProof(id, group, message, scope, depth, { wasm: `${ART}semaphore-${depth}.wasm`, zkey: `${ART}semaphore-${depth}.zkey` })
}
const EV = "0123456789abcdef"
const EV2 = "fedcba9876543210"

test("members, check-in and show-ups", async (t) => {
  // snarkjs keeps worker threads alive after proving; close them or the run never exits
  t.after(async () => { await globalThis.curve_bn128?.terminate?.() })
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wheel-"))
  let now = new Date("2026-10-24T18:00:00+13:00")
  const w = new Wheel(dir, () => now)
  const [a, b, c] = ["a", "b", "c"].map((s) => new Identity(`secret-${s}`))
  for (const id of [a, b, c]) assert.equal(w.join(id.commitment.toString()).ok, true)
  assert.equal(w.join(a.commitment.toString()).size, 3, "a repeat join changes nothing")
  assert.equal(w.join("0").ok, false)
  assert.equal(w.join("abc").ok, false)

  const open = w.openCheckin(EV)
  assert.equal(open.ok, true)
  assert.match(open.code, /^[A-Z2-9]{6}$/)
  const members = w.group().members

  const pa = await prove(a, members, doorMessage(open.code), showupScope(EV))
  assert.deepEqual(await w.showup(EV, open.code.toLowerCase(), pa), { ok: true, count: 1 }, "the code is case-blind")
  assert.equal((await w.showup(EV, open.code, pa)).why, "again", "one show-up per person per event")
  const pa2 = await prove(a, members, doorMessage(open.code), showupScope(EV))
  assert.equal((await w.showup(EV, open.code, pa2)).why, "again", "a fresh proof by the same person: same nullifier")

  const pb = await prove(b, members, doorMessage(open.code), showupScope(EV))
  assert.equal((await w.showup(EV, "WRONG1", pb)).why, "code")
  assert.equal((await w.showup(EV2, open.code, pb)).why, "closed", "no check-in open for the other event")
  w.openCheckin(EV2)
  assert.equal((await w.showup(EV2, w.checkins[EV2] && open.code, pb)).why, "code", "another event's code")
  const pbOtherCode = await prove(b, members, doorMessage("AAAAAA"), showupScope(EV))
  assert.equal((await w.showup(EV, open.code, pbOtherCode)).why, "message", "the proof is bound to the door code")
  const pbOtherScope = await prove(b, members, doorMessage(open.code), showupScope(EV2))
  assert.equal((await w.showup(EV, open.code, pbOtherScope)).why, "scope")
  assert.deepEqual(await w.showup(EV, open.code, pb), { ok: true, count: 2 })

  const outsider = new Identity("not-a-member")
  const fake = await prove(outsider, [...members, outsider.commitment.toString()], doorMessage(open.code), showupScope(EV))
  assert.equal((await w.showup(EV, open.code, fake)).why, "root", "a list the service never had")
  const tampered = { ...(await prove(c, members, doorMessage(open.code), showupScope(EV))), nullifier: "123" }
  assert.equal((await w.showup(EV, open.code, tampered)).why, "proof")

  // the fixed-per-event nullifier differs across events for the same person
  const openB = w.openCheckin(EV2)
  const pa3 = await prove(a, members, doorMessage(openB.code), showupScope(EV2))
  assert.deepEqual(await w.showup(EV2, openB.code, pa3), { ok: true, count: 1 })
  assert.notEqual(w.showups[EV][0], w.showups[EV2][0])

  now = new Date(now.getTime() + CHECKIN_TTL_MS + 1000)
  const pc = await prove(c, members, doorMessage(open.code), showupScope(EV))
  assert.equal((await w.showup(EV, open.code, pc)).why, "closed", "the check-in closes")
  assert.equal(w.count(EV), 2)

  // what the store holds: no codes, no timestamps beside members, no identities
  const disk = fs.readdirSync(dir).map((f) => fs.readFileSync(path.join(dir, f), "utf8")).join("\n")
  assert.equal(disk.includes(open.code), false, "no door code in plain text")
  assert.equal(/20\d\d-\d\d-\d\d/.test(disk), false, "no dates")
  for (const s of ["secret-a", "secret-b", "secret-c"]) assert.equal(disk.includes(s), false)
})

test("account login: a fixed pen name, single-use nonces, unlinkable to show-ups", async (t) => {
  t.after(async () => { await globalThis.curve_bn128?.terminate?.() })
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wheel-"))
  let now = new Date("2026-10-24T18:00:00+13:00")
  const w = new Wheel(dir, () => now)
  const [a, b] = ["a", "b"].map((s) => new Identity(`login-${s}`))
  for (const id of [a, b]) w.join(id.commitment.toString())
  const members = w.group().members
  const n1 = w.challenge().nonce
  const l1 = await w.login(await prove(a, members, n1, ACCOUNT_SCOPE))
  assert.equal(l1.ok, true)
  assert.match(l1.account, /^[0-9a-f]{16}$/)
  assert.deepEqual(w.session(l1.token), { account: l1.account })
  assert.equal((await w.login(await prove(a, members, n1, ACCOUNT_SCOPE))).why, "nonce", "a nonce works once")
  const l2 = await w.login(await prove(a, members, w.challenge().nonce, ACCOUNT_SCOPE))
  assert.equal(l2.account, l1.account, "the same member keeps the same pen name")
  const lb = await w.login(await prove(b, members, w.challenge().nonce, ACCOUNT_SCOPE))
  assert.notEqual(lb.account, l1.account)
  assert.equal((await w.login(await prove(a, members, w.challenge().nonce, showupScope(EV)))).why, "scope")
  assert.equal((await w.login(await prove(a, members, "12345", ACCOUNT_SCOPE))).why, "nonce", "an unissued nonce")
  const stale = w.challenge().nonce
  now = new Date(now.getTime() + NONCE_TTL_MS + 1000)
  assert.equal((await w.login(await prove(a, members, stale, ACCOUNT_SCOPE))).why, "nonce", "nonces expire")
  // the pen name is not the show-up nullifier
  const open = w.openCheckin(EV)
  const show = await prove(a, members, doorMessage(open.code), showupScope(EV))
  assert.equal((await w.showup(EV, open.code, show)).ok, true)
  assert.equal(w.showups[EV].includes(l1.account), false)
  const disk = fs.readdirSync(dir).map((f) => fs.readFileSync(path.join(dir, f), "utf8")).join("\n")
  assert.equal(disk.includes(l1.account) || disk.includes(l1.token), false, "pen names and sessions are not on disk")
})

test("a door code that changes every minute", async (t) => {
  t.after(async () => { await globalThis.curve_bn128?.terminate?.() })
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wheel-rot-"))
  let now = new Date("2026-10-24T18:00:30+13:00")
  const w = new Wheel(dir, () => now)
  const a = new Identity("secret-rot-a"), b = new Identity("secret-rot-b"), c = new Identity("secret-rot-c")
  for (const id of [a, b, c]) w.join(id.commitment.toString())
  const open = w.openCheckin(EV, true)
  assert.equal(open.ok, true)
  assert.equal(open.code, undefined, "no fixed code")
  assert.match(open.secret, /^[0-9a-f]{64}$/)
  const minute = Math.floor(now.getTime() / ROTATE_MS)
  const code = rotatingCode(open.secret, EV, minute)
  assert.match(code, /^[A-Z2-9]{6}$/)
  assert.notEqual(rotatingCode(open.secret, EV, minute + 1), code, "the next minute has its own code")
  const members = w.group().members
  now = new Date(now.getTime() + 2 * ROTATE_MS)  // read out at the door two minutes ago: still fine
  const pa = await prove(a, members, doorMessage(code), showupScope(EV))
  assert.deepEqual(await w.showup(EV, code, pa), { ok: true, count: 1 })
  now = new Date(now.getTime() + ROTATE_MS)  // three minutes on, that code has gone
  const pb = await prove(b, members, doorMessage(code), showupScope(EV))
  assert.equal((await w.showup(EV, code, pb)).why, "code")
  const fresh = rotatingCode(open.secret, EV, Math.floor(now.getTime() / ROTATE_MS))
  const pc = await prove(c, members, doorMessage(fresh), showupScope(EV))
  assert.deepEqual(await w.showup(EV, fresh, pc), { ok: true, count: 2 })
})

test("vouches: one per member per practitioner, nothing else accepted", async (t) => {
  t.after(async () => { await globalThis.curve_bn128?.terminate?.() })
  const { vouchScope, VOUCH_MESSAGE } = await import("../core.mjs")
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wheel-v-"))
  const w = new Wheel(dir)
  const [a, b] = ["va", "vb"].map((s) => new Identity(`secret-${s}`))
  for (const id of [a, b]) w.join(id.commitment.toString())
  const members = w.group().members
  const P = "aaaaaaaaaaaaaaaa", Q = "bbbbbbbbbbbbbbbb"
  assert.deepEqual(await w.vouch(P, await prove(a, members, VOUCH_MESSAGE, vouchScope(P))), { ok: true, count: 1 })
  assert.equal((await w.vouch(P, await prove(a, members, VOUCH_MESSAGE, vouchScope(P)))).why, "again", "once per member")
  assert.equal((await w.vouch(Q, await prove(a, members, VOUCH_MESSAGE, vouchScope(P)))).why, "scope", "a vouch fits its practitioner")
  assert.equal((await w.vouch(P, await prove(b, members, "1", vouchScope(P)))).why, "message")
  assert.equal((await w.vouch(Q, await prove(a, members, VOUCH_MESSAGE, vouchScope(Q)))).ok, true, "the same member, another practitioner")
  assert.deepEqual(w.vouchCounts([P, Q, "nope"]), { [P]: 1, [Q]: 1 })
  assert.deepEqual(new Wheel(dir).vouchCounts([P]), { [P]: 1 }, "kept on disk")
  const kept = fs.readFileSync(path.join(dir, "vouches.json"), "utf8")
  assert.ok(!kept.includes(a.commitment.toString()), "the store keeps nullifiers, never who")
})
