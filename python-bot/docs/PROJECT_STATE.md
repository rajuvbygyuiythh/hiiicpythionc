# PROJECT_STATE.md — EVA Bot Current State

Last updated: 2026-10-09 — Dashboard CDP launcher and startup diagnostics added; user artifact pending

---

## Current Status: Dashboard manual capture and a separate CDP Capture Browser launcher are available; windowless startup failures are logged; no CDP artifact has been analyzed and browserless match/chat actions remain unverified

### Test Results
- `test_chat_detect.py`: 34 offline checks passed; jsdom fixtures skipped (not installed)
- `tests/test_smooth_debug.py`: 10/10 passed
- `tests/test_socket_trace.py`: 13/13 passed
- `tests/test_session_only.py`: 10/10 passed
- `tests/test_account_session_store.py`: 2/2 passed
- `tests/test_chitchat_socket.py`: 7/7 passed
- `tests/test_cdp_capture.py`: 13/13 passed (offline metadata/redaction tests)
- `tests/test_cdp_capture_launcher.py`: 13/13 passed (offline browser/loopback/process lifecycle/import-contract checks)
- `tests/test_launcher.py`: 3/3 passed (windowless startup-error logging/notice checks)
- `test_flow.py`: 124/124 passed
- `test_live.py`: 44/44 passed
- `test_fuzz.py`: 4/4 passed
- `test_matcher.py`: ALL CATEGORIES ROUND-TRIP OK

### What Works
1. **Chat Engine** — 12 flow types, horny deflection, IO TXT matcher, regex classifier
2. **File-Based Replies** — All replies from editable txt files (32 files total)
3. **Debug Output** — Shows exact file path + line number for each reply
4. **Runtime Diagnostics** — `EVA_DEBUG=1` adds phase timings and bounded, redacted tracebacks; idle polling is configurable
5. **Style Mirroring** — Enabled after 5 messages
6. **Memory-Aware** — Uses known facts for follow-ups
7. **Flow Mixing** — 70% main pool / 30% flow-specific variety
8. **Country Collection** — Directly to flirty_questions.txt after country capture
9. **All Pools Editable** — 10 previously hardcoded pools now in txt files
10. **Browser API Diagnostics** — bounded WebSocket, fetch/XHR, handshake/error/close, timing, navigation, and payload-shape summaries; raw messages and credential values are omitted
11. **Dashboard Manual Debug** — one visible browser/account remains open for user-driven chat; bot chat automation/account rotation are disabled; writes redacted combined + WS/API sidecars under `capture/`
12. **Login & Save Only** — a one-account visible login saves browser state and closes before starting the chat loop
13. **Browserless Socket.IO foundation** — reuses saved storage state, forces WebSocket transport, sends the captured `presenceSync`, and observes only captured server events; it does not match or send chat messages
14. **CDP metadata capture tool** — attaches only to loopback Chromium CDP, filters persisted traffic to `chitchat.gg` subdomains, writes a 5 MB bounded redacted JSONL trace, and does not automate site actions; no live trace has been collected in this checkout
15. **Dashboard CDP Capture Browser** — launches an isolated Chrome/Chromium/Edge profile, starts `capture.py`, shows session/output status, and stops the capture/browser separately from bot START and existing Debug Mode
16. **GUI startup diagnostics** — `run.vbs` and the Desktop shortcut use `entry.launcher`; windowless import/startup errors are logged to `data/logs/gui_console.log` and shown as a Windows notice; installer checks Dashboard imports before refreshing the shortcut
17. **Dashboard CDP import contract fix** — Windows installer exposed that `entry/main.py` imported `find_browser_executable` while the helper only defined `resolve_browser_executable`; added the auto-detect alias and an AST-backed regression test verifying every CDP helper imported by the Dashboard exists

### File Structure
- `data/output/` — 22 txt files (ALL EDITABLE BY USER)
- `data/output/middle_chat/` — 5 txt files (ALL EDITABLE BY USER)
- `data/input/` — 8 txt files (trigger patterns)

### How to Test
```bash
# Run all automated tests
test.bat

# Or manually:
python test_live.py             # 44 offline checks
python test_fuzz.py             # 4 fuzz checks
python test_matcher.py          # Pool roundtrip
python tests/test_smooth_debug.py  # Runtime debug helpers
python tests/test_socket_trace.py  # Safe WebSocket trace summaries
python tests/test_chitchat_socket.py # Offline browserless transport checks
python tests/test_session_only.py # Login-save-close flow

# Optional: passive browserless Socket.IO observer (requires a saved session)
python tools/socket_live_probe.py --account account@example.com --release <captured-release>
# Passive apart from presenceSync; it does not match, send, skip, or leave chats.

# Dashboard capture: choose Login/Restore with one account/session,
# check Debug Mode (manual chat), click START, and chat yourself in the visible browser.
# Click STOP to close it. Output: capture/debug-api.txt + websocket.jsonl + http-api.jsonl.
# Raw chat/credential values are omitted; review endpoint/event names before sharing.

# CDP Phase 1: on the main Dashboard, use the separate CDP Capture Browser
# panel to launch the isolated browser and start/stop metadata capture.
# Optional CLI fallback: python capture.py --browser-url http://127.0.0.1:9222 --duration 300
# Guide: docs/CDP_CAPTURE.md. Share only the reviewed capture/cdp-*/capture.jsonl.

# Interactive REPL:
python tools/live_chat.py
```

### Debug Output Format
```
you> hey
eva> hii stranger
   # greeting.txt line 61

you> m 21
eva> F-25
   # age_gender.txt line 14

you> uk
eva> what u do for fun?
   # flirty_questions.txt line 42
```

---

## Completed Work (DO NOT REPEAT)

See `AGENTS.md` Phase 1-8 for full details of all completed tasks.

### Key Fixes Applied
- `{snap}` placeholder resolved
- Style mirroring enabled
- Multi-line message handling
- Word-boundary matching
- Non-blocking thread stagger
- Dead code cleanup (352 lines removed)
- File cleanup (7 dead files removed, 127 lines merged)
- Country collection fix
- Debug output with file paths + line numbers
- **Stranger-SMS detection (Phase 11)** — see `browser/chat_reader.py`:
  multi-selector reading, fingerprint-based new-message tracking,
  "0 messages parsed" warning, `tools/chat_detect_debug.py` inspector

---

## Protocol Status / Remaining Work

- `Login & Save Only` completes the one-time login/save/close step. The new
  `transport/chitchat_socket.py` foundation can reuse that storage state from a
  separate process, force WebSocket-only Socket.IO, send the captured
  `presenceSync`, and observe captured incoming event names without launching a
  browser.
- Dashboard **Debug Mode (manual chat)** keeps one visible browser open after
  login/restore. It never runs the bot chat loop, sends bot messages, rotates
  accounts, or auto-saves a session; STOP closes the browser.
- The separate `capture.py` CDP tool and Dashboard launcher are implemented
  and offline-tested. The launcher uses a loopback-only CDP port and temporary
  browser profile; no real capture artifact has been collected here. Next is
  for the user to run it and provide the sanitized JSONL before any protocol
  reports or browserless action code are written. GUI/browser runtime still
  needs verification on Windows because PyQt6 and a browser are not installed
  in this sandbox.
- The browser-side trace writes a bounded live combined timeline and source
  sidecars under `capture/`: `debug-api.txt`, `websocket.jsonl`, and
  `http-api.jsonl`. It records event/direction, endpoint labels, query-key
  names, method/status/elapsed time, header names, and payload schema/types; it
  omits raw bodies/frames, chat text, header/query values, cookies, tokens,
  passwords, and account/user IDs. It is not a server-side log.
- This is **not browserless bot chat**: no verified client event/payload for
  matchmaking, sending a message, skip/next, or leaving a match has been
  captured. The probe does not guess or emit those actions.
- The capture also does not establish account authentication. Cookie forwarding
  is scoped to matching domain/path/expiry; an Authorization token is used only
  when an exact localStorage key or full header is explicitly configured.
  Verify authentication separately through approved docs or safe inspection.
- Next: use the Dashboard manual mode for an approved, controlled manual
  interaction and inspect the sanitized capture. Do not implement browserless
  actions until outbound contracts are independently verified. See
  [`WEBSOCKET_ANALYSIS.md`](WEBSOCKET_ANALYSIS.md).

---

## Future Tasks

When assigning a new task:
1. Read `AGENTS.md` first
2. Check this file for current state
3. Identify which files need modification
4. Verify the change doesn't break completed work
5. Run tests: `python test_live.py && python test_fuzz.py`
6. Update this file and `AGENTS.md`
