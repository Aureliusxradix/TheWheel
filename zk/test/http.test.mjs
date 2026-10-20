// The service as the browser meets it: its own process, over HTTP. The in-process test missed a hang that only
// showed here (2026-10-20, a proof check waiting on worker threads in the long-running service).
import { test } from "node:test"
import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import { createHash } from "node:crypto"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { Identity } from "@semaphore-protocol/identity"
import { Group } from "@semaphore-protocol/group"
import { generateProof } from "@semaphore-protocol/proof"

const FIELD = 21888242871839275222717131064758314466096019186001779448845833037201683149097n
const toField = (s) => (BigInt("0x" + createHash("sha256").update(s).digest("hex")) % FIELD).toString()
const ART = new URL("../artifacts/", import.meta.url).pathname
const PORT = 18000 + Math.floor(Math.random() * 1000)
const B = `http://127.0.0.1:${PORT}`

test("login over HTTP with one member and with three", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wheel-http-"))
  const srv = spawn(process.execPath, [new URL("../server.mjs", import.meta.url).pathname], {
    env: { ...process.env, WHEEL_ZK_PORT: String(PORT), WHEEL_ZK_STATE: dir, WHEEL_ADMIN_TOKEN: "test-token", WHEEL_ZK_HOST: "127.0.0.1" },
    stdio: ["ignore", "pipe", "inherit"],
  })
  t.after(async () => { srv.kill(); await globalThis.curve_bn128?.terminate?.() })
  await new Promise((resolve) => srv.stdout.on("data", (d) => String(d).includes("wheel-zk on") && resolve()))
  const post = async (p, b, h = {}) => {
    const r = await fetch(B + p, { method: "POST", headers: { "content-type": "application/json", ...h }, body: JSON.stringify(b), signal: AbortSignal.timeout(10000) })
    return { status: r.status, json: await r.json() }
  }
  const ids = ["one", "two", "three"].map((s) => new Identity(`http-${s}`))
  for (const n of [1, 3]) {
    for (const id of ids.slice(0, n)) await post("/join", { commitment: id.commitment.toString() })
    const g = new Group((await (await fetch(B + "/group")).json()).members.map(BigInt))
    const depth = Math.max(1, g.depth)
    const nonce = (await post("/challenge", {})).json.nonce
    const proof = await generateProof(ids[0], g, nonce, toField("wheel-account"), depth, { wasm: `${ART}semaphore-${depth}.wasm`, zkey: `${ART}semaphore-${depth}.zkey` })
    const t0 = Date.now()
    const r = await post("/login", { proof })
    assert.equal(r.status, 200, `login with ${n} member(s)`)
    assert.ok(Date.now() - t0 < 5000, "answered in under 5 s")
    const s = await fetch(`${B}/session?token=${r.json.token}`, { headers: { "x-wheel-admin": "test-token" } })
    assert.equal((await s.json()).account, r.json.account)
  }
})
