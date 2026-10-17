# EVA Bot — Full Project (Diagram Flow Engine + Legacy Engine)

Complete EVA chitchat.gg bot: browser automation, PyQt6 GUI dashboard, CLI
runner, account/session management — now running the **updated diagram flow
logic** with **symmetric input/output txt categories**, plus the original
full engine kept as a selectable legacy option.

```
DEFAULT ENGINE (flow):   greeting -> age/gender -> country -> flirty
                         -> positive reply -> share snap -> END CHAT
LEGACY ENGINE:           EVA_ENGINE=legacy  (original 6-flow brain)
```

---

## The one rule (customizable without code)

```
data/input/<category>.txt   = WHAT THE USER SAYS   (trigger keywords)
data/output/<category>.txt  = WHAT THE BOT REPLIES (reply lines)

same file name = same category — edit the txt files, restart, done.
```

Example: user sends `m 21` → matches a line in `input/age_gender.txt` →
bot replies from `output/age_gender.txt` (`f19`).

| # | User says | Category | Next |
|---|-----------|----------|------|
| 1 | first SMS `hi` | `greeting.txt` | wait age/gender |
| 2 | `m21` | `age_gender.txt` | wait country |
| 3 | `from?` | `country.txt` | wait country answer |
| 4 | `usa` | → `flirty_questions.txt` | MIDDLE |
| 5a | `u horny?` / `send nudes` | `horny.txt` | MIDDLE |
| 5b | `ur cute` / `love u` | `middle_chat/flirty_reply.txt` | MIDDLE |
| 5c | `lol` / `ok` / `nice` | `middle_chat/warm_reply.txt` | MIDDLE |
| 5d | `gtg` / `bye` / `brb` | `middle_chat/busy_later.txt` | MIDDLE |
| 5e | `how are u` / `how old are u` | `how_are_you.txt` / `your_age.txt` | MIDDLE |
| 5f | **positive**: `yes` / `yeop` / `ur sc?` / `whats ur snap` | `share_snap.txt` | **END CHAT** |
| 5g | user offers snap: `my snap is…` | `snapchat.txt` | **END CHAT** |
| 5h | anything else | `flirty_questions.txt` | MIDDLE |
| 6 | after 8 bot replies | `closer.txt` | **END CHAT** |

Matching layers (one fails → next works): exact → substring →
slang-normalized → token-subset → smart fallback (regex, countries.txt).

**Bangla A-to-Z guide:** `data/output/info.txt` (কোন SMS পেলে কোন ফাইল
থেকে reply আসবে — সব বাংলায় ব্যাখ্যা করা)।

---

## Engine switch

```bash
python -m entry.main                # GUI (default = flow engine)
EVA_ENGINE=legacy python -m entry.main   # GUI with the original engine
python entry/cli_runner.py          # terminal runner
```

Both engines share `data/input/` + `data/output/` and the same
`ChatRuleBot` API, so the browser worker, GUI and tools work with either.

## Install & run (Windows)

```bat
install.bat      :: venv + all packages + Playwright Chromium (one run)
run.vbs          :: start the bot app (GUI, NO console window)
"EVA Bot" desktop :: created by install.bat - double-click app icon
run_console.bat  :: debug launcher (console visible; keeps startup errors visible)

If a previous Desktop shortcut was created before an update, run `install.bat`
once to refresh it. Windowless startup failures are shown in a message and logged
to `data/logs/gui_console.log`; `run_console.bat` prints the actual startup error.
test.bat         :: automated checks + demo + live REPL
```

Manual (any OS): `python -m venv .venv` → `pip install -r
data/requirements.txt` → `python -m playwright install chromium`.

## Browserless Socket.IO status

A one-time visible **Login & Save Only** run can persist a session under the
private `account_sessions/` folder. The optional probe then opens a
WebSocket-only Socket.IO connection directly from that saved state—no browser
is launched for the probe:

```bash
python tools/socket_live_probe.py --account account@example.com --release <captured-release>
```

The exact `release` scalar must come from the captured client handshake; it is
not guessed or stored as a fake default. It can also be passed through the
`CHITCHAT_RELEASE` environment variable.

The probe sends only the captured `presenceSync` packet and reports the shape
of observed server events. It does **not** start matchmaking, send chat replies,
or skip/leave a match. Those outbound actions and the account-authentication
contract are not yet established by the available capture, so the transport
intentionally does not guess them. See
[`docs/WEBSOCKET_ANALYSIS.md`](docs/WEBSOCKET_ANALYSIS.md) for evidence and the
next capture needed to complete browserless chat. Treat saved sessions as
credentials; do not share or commit `account_sessions/`.

### Dashboard Manual Debug Mode (visible browser + live capture)

Use this mode when you want to log in and chat **yourself** in one visible
browser while collecting a shareable network trace:

1. In Dashboard, choose **Login** and load an account file with exactly one
   account (or choose **Restore** with exactly one saved session).
2. Enable **Debug Mode (manual chat)** and click **START**. The browser stays
   visible after login; navigate and chat manually on the site.
3. The bot does **not** start matching, send messages, skip, or leave chats. It
   also does not rotate accounts or automatically save a new session in this
   mode. Click Dashboard **STOP** to close the browser and finish capture.
4. Share the files in the project `capture/` folder only after reviewing them:
   `debug-api.txt` is the combined JSONL timeline; `websocket.jsonl` and
   `http-api.jsonl` are focused sidecars. They are written/flushed as events
   happen, reset once per app process, and are bounded to 1 MB each.

The trace includes timestamps, event/packet names, direction, safe endpoint
host/path labels, query-key names only, request method/status/elapsed time,
auth-related **header names only**, and payload field/type/length shapes. It
never stores raw WebSocket frames or HTTP bodies, message text, passwords,
account/user IDs, cookies, tokens, or header/query values. It records only
browser-visible traffic and response metadata—not private server-side logs.
Capture is limited to `chitchat.gg` and its subdomains so unrelated browsing
is not traced. Endpoint and event names can still reveal implementation details,
so review before sharing.

**বাংলায় privacy note:** trace-এ message-এর লেখা, password, cookie, token,
UID/account ID বা header/query-এর value রাখা হয় না—শুধু field/event-এর নাম,
type, size, route, status ও সময় থাকে। তাই পুরো chat content বা server-এর
ভেতরের log এখানে পাওয়া যাবে না; শুধু browser থেকে দেখা network metadata
পাওয়া যাবে। `capture/` folder share করার আগে দেখে নিন।

This is a manual, browser-backed diagnostic mode, **not browserless automated
chat**. Normal bot chat still uses browser automation. The optional
`EVA_SOCKET_TRACE=1` environment flag can also capture a normal visible bot run;
it uses the same redacted output format and does not change its chat behavior.

### CDP metadata capture (Phase 1)

The main Dashboard has a separate **CDP Capture Browser — Manual Only** panel;
it is not the existing **Debug Mode (manual chat)** checkbox. Choose/browse to
Chrome, Chromium, or Edge, then click **Launch Browser & Start Capture**. A
blank tab opens with an isolated temporary profile. Navigate and log in
manually, then use **Stop Capture & Close Browser** in that panel. No account
file is read and no bot chat/match actions are started. The browser's CDP
listener is loopback-only; the temporary profile is removed when stopped.

The tool writes bounded, redacted metadata to
`capture/cdp-*/capture.jsonl`; raw credentials, chat text, and full frames are
not saved. See the [Bengali capture and privacy guide](docs/CDP_CAPTURE.md) for
privacy limits and the optional terminal fallback. Send only the reviewed JSONL
artifact for analysis—not a browser profile or session file.

The CDP tool is a capture step only: it does not generate protocol/auth/API/
identity reports. Those require analysis of a real capture; unknown details
will not be guessed.

## Offline verification

The following checks were run in this checkout; the optional DOM-fixture checks
need `node` + `npm install jsdom` and were skipped because jsdom was unavailable.

| Command | Result |
|---------|--------|
| `python test_flow.py` | **124 passed, 0 failed** |
| `python test_live.py` | **44/44 passed** |
| `python test_fuzz.py` | **4/4 passed** |
| `python test_matcher.py` | **All categories round-trip OK** |
| `python test_chat_detect.py` | **34 passed, 0 failed**; optional jsdom checks skipped |
| `python tests/test_smooth_debug.py` | **10 passed, 0 failed** |
| `python tests/test_socket_trace.py` | **13 passed, 0 failed** |
| `python tests/test_session_only.py` | **10 passed, 0 failed** |
| `python tests/test_chitchat_socket.py` | **7 passed, 0 failed** |
| `python -m unittest tests.test_cdp_capture -v` | **13 passed, 0 failed** |
| `python -m unittest tests.test_cdp_capture_launcher -v` | **13 passed, 0 failed** |
| `python -m unittest tests.test_launcher -v` | **3 passed, 0 failed** |

The live browser/GUI workflow was not run in this sandbox.

## Project layout

```
entry/      GUI dashboard (main.py), CLI runner, thread orchestration
browser/    Playwright/Camoufox automation, context pool, sessions,
            human behavior, device sign-in
chat/       rule_bot.py (engine switch) + rules.py (legacy engine)
core/       config loader, opt-in debug diagnostics, resource governor, engine bridge, accounts
config/     eva_config.json (intent tuning)
data/       input/ + output/ categories, countries.txt, snap_ids.txt,
            local_db/, config.json (runtime behavior)
docs/       architecture, flow spec, installers (INSTALL_SMOOTH.*)
tools/      live_chat.py REPL, coverage check, passive Socket.IO probe
capture.py  local loopback CDP metadata capture (manual Phase 1)
transport/  browserless Socket.IO transport foundation (no match/send yet)
eva_flow.py the diagram funnel engine (default)
run_chat.py / demo_flow.py / test_flow.py   flow-engine tools
install.bat / run.vbs / run_console.bat / test.bat   Windows helpers
```

## Behavior rules

- No line repeats within one conversation; never back-to-back
- Reply cap 8 (`EVA_MAX_REPLIES` env) → `closer.txt` → END
- Underage (<18) permanently blocks snap sharing (both engines)
- Snap usernames cycle round-robin via `data/snap_ids.txt`
- `%username%` / `{snap}` / `{country}` placeholders in reply lines
- Multi-line SMS: last line drives the machine

## Stranger-SMS detection (v2.2 — "bot user er sms detect korte parche na")

The browser worker reads the stranger's SMS through `browser/chat_reader.py`.

What was wrong before: extraction depended on ONE hardcoded selector set
(`main ol` → `li.select-text` → `span.font-bold[role=button]` →
`span.emoji-content`). If any class name changed on the site, or if our own
message was not rendered, the bot silently stopped seeing the stranger — no
error, no reply, just "blind" chats.

What it does now:

1. **Selector chain** — several container / row / username / text selector
   candidates are tried in order (the original ones first, so nothing regresses).
2. **Ancestor filtering** — a message row is never counted twice together with
   the text span inside it.
3. **Speaker detection** — own username from the sidebar, a cached hint, row
   alignment classes (`justify-end`, `self-end`, …), and finally "this text is
   something we just sent". Our own bubbles are never answered.
4. **Unknown markup fallback** — a generic `Name: message` line parser still
   finds SMS in a completely different layout.
5. **Fingerprint tracking** (`MessageTracker`) — new messages are found by
   diffing the DOM against the previous poll instead of the old
   `len(dom) > last_count` counter that ran ahead of the DOM whenever the site
   did not render our own message (the real reason replies were "not detected").
6. **Loud diagnostics** — if 0 messages are parsed for several polls the log
   says so, prints which selectors were tried, and with `EVA_DUMP_CHAT_DOM=1`
   saves the page HTML (`logs/chat_dom_dump_*.html`) so the selectors can be
   pointed at the new markup.

Debug a page by hand (no login needed for the saved-page mode):

```bash
# 1) open the chat page, right-click -> Save as -> "Webpage, HTML only"
python tools/chat_detect_debug.py --html path/to/chat_page.html
python tools/chat_detect_debug.py --url https://chitchat.gg/        # live
```

Tests: `python test_chat_detect.py` (34 offline checks; DOM-fixture checks need
`node` + `npm install jsdom`, otherwise they are skipped with a note). Runtime
diagnostics can be checked with `python tests/test_smooth_debug.py`.

## Runtime debug mode

Normal runs keep phase timings and traceback details quiet. To see why a chat
poll or reply is slow, enable the opt-in diagnostics before starting the bot:

```bat
set EVA_DEBUG=1
run_console.bat
```

The log adds `[T] extract: …ms` and `[T] engine: …ms` entries. Errors retain a
short message in normal mode; `EVA_DEBUG=1` adds a bounded traceback. Common
authentication fields are redacted by the diagnostic helper. In windowless GUI
mode, Python output is also appended to `data/logs/gui_console.log`; the rule
engine writes its decision trace to `data/logs/chat_debug.log`.

After 30 seconds with no detected chat activity, polling backs off to
`performance.idle_poll_interval_seconds` (default 1.5 seconds); active polling
still uses `performance.poll_interval_seconds`. Both values are editable in
`data/config.json`.

For a selector/DOM problem, `EVA_DUMP_CHAT_DOM=1` writes a page snapshot under
`logs/`. A snapshot can contain chat messages and page data: review and redact
it before sharing. Turn diagnostics off after collecting the evidence:

```bat
set EVA_DEBUG=
set EVA_DUMP_CHAT_DOM=
```

## Changes vs the original 22.zip snapshot

1. `data/input` + `data/output` renamed to direct symmetric names
   (`01_greeting.txt` → `greeting.txt`, …) + new categories
   (`middle_chat/` inputs, `share_snap.txt` triggers, `closer.txt`)
2. `chat/rule_bot.py`: engine switch (default flow, `EVA_ENGINE=legacy`)
3. `chat/rules.py`: filename refs updated + two fixes
   (punctuation-lossy trigger guard; minors never get IO snap reveals)
4. `eva_flow.py` + tools added (diagram engine, same API)
5. Legacy test scripts pinned to `EVA_ENGINE=legacy`
6. `data/countries.txt` added (editable country keywords)
7. `data/output/info.txt` — Bangla guide (A to Z)

This revision also adds `core/debug.py` runtime diagnostics, timings around the
chat extractor/reply engine, bounded redacted tracebacks, and configurable idle
polling. The tracked source intentionally excludes saved account sessions and
runtime logs.
