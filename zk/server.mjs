// server.mjs — The Wheel's member service, local only. The Python hub proxies to it at /api/zk/.
//   GET  /group                    -> {size, members}         the members list (commitments only)
//   POST /join     {commitment}    -> {ok, size}
//   POST /showup   {event, code, proof} -> {ok, count} | {ok:false, why}
//   GET  /count?event=<id>         -> {count}
//   POST /vouch    {practitioner, proof} -> {ok, count} | {ok:false, why}   one per member per practitioner
//   GET  /vouches?ids=a,b          -> {counts: {a: n}}
//   POST /going    {event, proof}  -> {ok, count}   message "going" counts once per member, "undo" takes it back
//   GET  /goings?ids=a,b           -> {counts: {a: n}}
//   POST /challenge                -> {nonce}                 single use, 5 minutes
//   POST /login    {proof}         -> {ok, token, account}    proof scoped "wheel-account", message = the nonce
//   GET  /session?token=           -> {ok, account}           hub only (X-Wheel-Admin)
//   POST /checkin  {event}         -> {ok, code, closes}      needs the X-Wheel-Admin token
//                  {event, rotating: true} -> {ok, secret, closes, rotate}  a code that changes every minute
// Logs nothing about requests: no IPs, no user agents, no paths.
import http from "node:http"
import { Wheel } from "./core.mjs"
import { buildBn128 } from "ffjavascript"

// One single-threaded curve, built at start and cached where snarkjs looks for it, so a proof check never waits on
// worker threads. In Red Hat's Node 22 image a check made from the long-running service hung on them
// (2026-10-20: logins timed out; the same proof checked in 0.3 s in a fresh process and in another Node image).
globalThis.curve_bn128 = await buildBn128(true)

const PORT = Number(process.env.WHEEL_ZK_PORT || 8792)
const ADMIN = process.env.WHEEL_ADMIN_TOKEN || ""
const wheel = new Wheel(process.env.WHEEL_ZK_STATE || new URL("./state/", import.meta.url).pathname)
const MAX_BODY = 64 * 1024

function send(res, code, body) {
  const data = JSON.stringify(body)
  res.writeHead(code, { "content-type": "application/json", "cache-control": "no-store", "content-length": Buffer.byteLength(data) })
  res.end(data)
}

function body(req) {
  return new Promise((resolve, reject) => {
    let size = 0
    const parts = []
    req.on("data", (c) => { size += c.length; if (size > MAX_BODY) { reject(new Error("big")); req.destroy() } else parts.push(c) })
    req.on("end", () => { try { resolve(JSON.parse(Buffer.concat(parts).toString() || "{}")) } catch { reject(new Error("json")) } })
    req.on("error", reject)
  })
}

const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, "http://local")
  try {
    if (req.method === "GET" && u.pathname === "/group") return send(res, 200, wheel.group())
    if (req.method === "GET" && u.pathname === "/count") return send(res, 200, { count: wheel.count(u.searchParams.get("event")) })
    if (req.method === "POST" && u.pathname === "/join") {
      const r = wheel.join((await body(req)).commitment)
      return send(res, r.ok ? 200 : 400, r)
    }
    if (req.method === "GET" && u.pathname === "/vouches") return send(res, 200, { counts: wheel.vouchCounts(String(u.searchParams.get("ids") || "").split(",").slice(0, 200)) })
    if (req.method === "GET" && u.pathname === "/goings") return send(res, 200, { counts: wheel.goingCounts(String(u.searchParams.get("ids") || "").split(",").slice(0, 300)) })
    if (req.method === "POST" && u.pathname === "/going") {
      const b = await body(req)
      const r = await wheel.going(b.event, b.proof)
      return send(res, r.ok ? 200 : r.why === "again" ? 409 : 400, r)
    }
    if (req.method === "POST" && u.pathname === "/vouch") {
      const b = await body(req)
      const r = await wheel.vouch(b.practitioner, b.proof)
      return send(res, r.ok ? 200 : r.why === "again" ? 409 : 400, r)
    }
    if (req.method === "POST" && u.pathname === "/showup") {
      const b = await body(req)
      const r = await wheel.showup(b.event, b.code, b.proof)
      return send(res, r.ok ? 200 : r.why === "again" ? 409 : 400, r)
    }
    if (req.method === "POST" && u.pathname === "/challenge") return send(res, 200, wheel.challenge())
    if (req.method === "POST" && u.pathname === "/login") {
      const r = await wheel.login((await body(req)).proof)
      return send(res, r.ok ? 200 : 400, r)
    }
    if (req.method === "GET" && u.pathname === "/session") { // the hub asks this; it is not passed through to the public
      if (!ADMIN || req.headers["x-wheel-admin"] !== ADMIN) return send(res, 403, { ok: false, why: "admin" })
      const s = wheel.session(u.searchParams.get("token"))
      return send(res, s ? 200 : 401, s ? { ok: true, ...s } : { ok: false, why: "session" })
    }
    if (req.method === "POST" && u.pathname === "/checkin") {
      if (!ADMIN || req.headers["x-wheel-admin"] !== ADMIN) return send(res, 403, { ok: false, why: "admin" })
      const b = await body(req)
      const r = wheel.openCheckin(b.event, b.rotating === true)
      return send(res, r.ok ? 200 : 400, r)
    }
    return send(res, 404, { ok: false, why: "route" })
  } catch {
    return send(res, 400, { ok: false, why: "request" })
  }
})
server.keepAliveTimeout = 65000
const HOST = process.env.WHEEL_ZK_HOST || "127.0.0.1" // 0.0.0.0 only inside a container whose port is published to 127.0.0.1
server.listen(PORT, HOST, () => process.stdout.write(`wheel-zk on ${HOST}:${PORT}\n`))
