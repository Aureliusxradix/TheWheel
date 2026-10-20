# The Wheel

One list of community events around Auckland, in three modes: **Day** for workshops, skillshares and volunteer
shifts, **Night** for gigs and evening gatherings, **Recovery** for retreats, sound baths, breathwork and rest.
People add what they find, and other people check it.

Live at **[aureliusxradix.com/thewheel](https://aureliusxradix.com/thewheel/)**, version one. The roadmap is on
the site, under Additional info.

## How it works

- **Adding a listing.** A member pastes a post or a link, or drops in a flyer. A reader turns it into a listing:
  a page's own event data when it has some, otherwise an AI call with a fixed schema (`reader/`, prompt in
  `prompts/extract-v4.md`). The member checks it and sends it for review.
- **Review.** Other members mark a listing right or wrong. Each review counts by the reviewer's tier, and a listing
  settles at 70% sure (`hub/rep.py`; the rules are on the site's *How rep works* page).
- **Members.** Joining makes a key in the browser. The server sees a commitment and, at sign-in, a
  [Semaphore](https://semaphore.pse.dev) zero-knowledge proof; the pen name is derived from that proof's nullifier.
  Check-ins at events are separate proofs, scoped to each event, so a pen name and a check-in stay apart (`zk/`).
- **Flyers.** An uploaded flyer is redrawn into a fresh image with no metadata (GPS, camera, time) before it is
  kept, and the words on it pass the identity gate first (`hub/flyer.py`).
- **The identity gate.** Every answer the server sends is checked against a private word list, and the server
  starts only with one in place (`hub/gate.py`). The list in this repository is a made-up one for tests; bring your
  own (`WHEEL_GATE_PATTERNS`, ten lines or more, one regular expression per line); the server needs it to start.
- **Pasted links** are fetched from the public internet only: the address the server dials must be public, so a
  link into the host's own network goes nowhere (`reader/netguard.py`).

## Run your own

You need Python 3.12 or newer, Node 22 (or podman), and, for the AI reader, the
[Claude Code](https://code.claude.com) CLI signed in on the machine.

```sh
git clone https://github.com/Aureliusxradix/TheWheel && cd TheWheel
python3 -m pip install requests lxml pillow
bash zk/fetch-artifacts.sh                      # Semaphore proving files, checked against zk/artifacts.sha256
mkdir -p ~/.config/the-wheel && $EDITOR ~/.config/the-wheel/gate-patterns.txt   # your gate's word list
./hub-app                                       # starts the member service (zk/run.sh, podman) and the app
```

The app opens at `http://localhost:8790`. On a machine with Node and no podman, start the member service by hand:
`cd zk && npm ci && WHEEL_ADMIN_TOKEN=$(cat ../data/zk-admin.token) WHEEL_ZK_STATE=../data/zk-state node server.mjs`.
`hub-app` and the scripts call `/usr/bin/python3`; change that line if your Python lives elsewhere.

**Serving it publicly** (how aureliusxradix.com runs it): the server in API-only mode
(`WHEEL_API_ONLY=1`, `WHEEL_ORIGINS=<your site>`, `WHEEL_HOST`), the page built as a static shell by
`site/build.sh` (`WHEEL_API=<your data address>`), and sealed backups by `ops/backup.py`. Each setting is described
at the top of `hub/server.py`.

## Layout

| Path | What |
|---|---|
| `hub/` | the web app: server, store, rep, gate, flyers, steward tool (`wheelctl.py`), the page in `static/` |
| `reader/` | turning a post, link, flyer or calendar file into listings |
| `zk/` | the member service (Semaphore groups, sign-in, check-ins) and the browser client |
| `prompts/`, `schema/` | the reader's prompt versions and the event schema |
| `site/` | building the static page for a public site |
| `ops/` | sealed backups |
| `tests/` | `python3 -m unittest tests/test_*.py`, `tests/test_backup.sh`, `cd zk && npm test`, real proofs in a browser under `tests/browser/` |

## Credits

The open projects in `ref-manifest.tsv` were read as references while building it. Bundled:
[Leaflet](https://leafletjs.com) (BSD-2-Clause, its licence beside it), and inside `hub/static/vendor/wheel-zk.js`
the Semaphore libraries, poseidon-lite and LeanIMT (MIT) with snarkjs and ffjavascript (GPL-3.0). Map tiles from
OpenStreetMap.

## Licence

GPL-3.0 (`LICENSE`). Take it, change it, run your own: versions you hand on stay as free as this one.

Support the project: [aureliusxradix.com/thewheel](https://aureliusxradix.com/thewheel/), under Support.
