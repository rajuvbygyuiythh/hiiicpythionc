# TASKS.md — Task Tracking for EVA Bot

---

## Active Tasks

- [ ] User runs the Dashboard CDP Capture Browser (or the optional CLI) in a
  controlled, loopback-only Chromium session and supplies the reviewed
  `capture/cdp-*/capture.jsonl`; then analyze real evidence
  and produce `ws_protocol.json`, `ws_message_map.json`, `auth_flow.json`,
  `api_surface.json`, and `identity.json` with unknowns marked explicitly.
- [ ] Only after Phase 1 artifacts are analyzed, consider browserless auth,
  match/message/Skip/Next/leave actions using observed contracts; verify
  authentication separately and never guess event names or payloads.

---

## Completed Tasks

### Phase 1 — Critical Bug Fixes ✅
- [x] GUI loads snap_ids.txt + flirty_questions.txt
- [x] Create mode error handling
- [x] Account marking fix
- [x] Resource cleanup fix
- [x] {snap} placeholder resolution
- [x] DB paths configurable

### Phase 2 — High Priority Fixes ✅
- [x] Style mirroring enabled
- [x] Multi-line message handling
- [x] Log filtering fix
- [x] Camoufox engine param
- [x] Proxy URL fix

### Phase 3 — Medium Priority Fixes ✅
- [x] Word-boundary matching
- [x] Non-blocking thread stagger
- [x] Stats counting fix
- [x] CPU monitoring fix
- [x] Exception handling fix

### Phase 4 — Dead Code Cleanup ✅
- [x] Removed 352 lines of unused pools
- [x] Restored FLOWS dict
- [x] Removed no-op replace
- [x] Removed unused function

### Phase 5 — Smarter Chat Rules ✅
- [x] Flow-type influence (70/30 mix)
- [x] Memory-aware follow-ups
- [x] Retry bound reduction

### Phase 6 — Test Fixes ✅
- [x] Phase 9 pattern detector fix
- [x] All files pass py_compile
- [x] All imports verified
- [x] 51/51 test_live passed
- [x] 4/4 test_fuzz passed

### Phase 7 — File Cleanup & Debug ✅
- [x] Removed 7 dead txt files
- [x] Merged 127 unique lines
- [x] Added line number tracking
- [x] Debug shows file paths

### Phase 8 — Country Collection Fix ✅
- [x] Country collection → flirty_questions.txt

### Phase 11 — Stranger-SMS detection ✅
- [x] `browser/chat_reader.py` created (multi-selector reader + MessageTracker)
- [x] `extract_chat_from_page()` no longer depends on one hardcoded selector set
- [x] Counter-drift bug removed (own message not rendered -> SMS went unseen)
- [x] Loud "0 messages parsed" warning + `EVA_DUMP_CHAT_DOM=1` page dump
- [x] `tools/chat_detect_debug.py` page inspector
- [x] `test_chat_detect.py` offline checks pass; jsdom fixture checks are optional

### Phase 9 — Hardcoded Pools to TXT ✅
- [x] Created 10 new txt files
- [x] All pools now from txt files
- [x] Debug shows file + line number

### Runtime diagnostics ✅
- [x] Added opt-in `EVA_DEBUG=1` phase timings and bounded tracebacks
- [x] Redacted common credential fields before diagnostic logging
- [x] Added idle polling controls and safe fallback for invalid values
- [x] Added 10 offline checks in `tests/test_smooth_debug.py`

### Browser API / WebSocket diagnostics ✅
- [x] Dashboard Manual Debug and `EVA_SOCKET_TRACE=1` share the bounded redacted recorder
- [x] Writes the combined `capture/debug-api.txt` plus `websocket.jsonl` and `http-api.jsonl` sidecars
- [x] Captures WebSocket frames/handshakes/errors, fetch/XHR request-response metadata, elapsed timing, payload shapes, and navigation
- [x] Omits raw frames/bodies, chat text, passwords, cookies/tokens, user IDs, header values, and URL query values
- [x] Added 13 offline checks in `tests/test_socket_trace.py`

### CDP metadata capture tool (Phase 1 only) ✅
- [x] Added local-loopback-only CDP attach and `chitchat.gg` domain filtering
- [x] Bounded JSONL metadata trace with redacted header/query/body/frame values
- [x] Added storage key/cookie-name metadata while omitting values and IndexedDB records
- [x] Added `websocket-client`, Bengali usage/privacy guide, and 13 offline tests
- [ ] Live capture and report analysis still require the user-supplied artifact; no protocol/auth details are claimed from synthetic tests

### Dashboard CDP Capture Browser launcher ✅
- [x] Added a separate main-Dashboard panel to launch an isolated Chrome/Chromium/Edge profile and start `capture.py`
- [x] Kept it independent from bot START, account files, and existing Debug Mode; loopback-only CDP and Dashboard stop/cleanup
- [x] Display capture status and discovered JSONL output path; added offline launcher tests
- [x] Fixed the `find_browser_executable`/`resolve_browser_executable` export mismatch and added an AST-backed import-contract regression test
- [ ] Live GUI/browser operation still requires verification on the user's Windows machine

### Windowless GUI startup diagnostics ✅
- [x] Added `entry/launcher.py` to log startup/import errors and show a native Windows notice for windowless runs
- [x] Routed `run.vbs` and the Desktop shortcut through the diagnostic launcher; console launcher now uses the project venv
- [x] Installer verifies `entry.main` imports and checks the websocket module before updating the shortcut
- [x] Added offline launcher diagnostics tests; Windows runtime still requires user verification

### Dashboard Manual Debug Mode ✅
- [x] One visible browser/account; manual user chat only; no automated chat loop or account rotation
- [x] Leaves browser open until Dashboard STOP; disables warmup/background tabs and picture automation
- [x] Enables redacted capture without environment-variable setup; no new session auto-save
- [x] Added 10 offline lifecycle/visibility/restart checks in `tests/test_session_only.py`

### Browserless Socket.IO foundation (partial; outbound chat not implemented)
- [x] Reuse saved Playwright storage state without launching a browser
- [x] Force a Socket.IO WebSocket-only connection and send captured `presenceSync`
- [x] Listen only to observed incoming event names; keep probe logs to payload shape
- [x] Add an opt-in exact localStorage token key / Authorization header path; do not guess token keys
- [x] Add seven offline transport tests and the optional `tools/socket_live_probe.py`
- [ ] Capture and implement real matchmaking, message, Skip/Next, and leave actions

### Login & Save Only ✅
- [x] Added a Dashboard mode that uses one visible browser and requires one Login account
- [x] Stops after login, saves browser state, and closes without starting the chat loop
- [x] Prevents ThreadManager from restarting or rotating to another account
- [x] Added 10 offline checks for save-only and manual-debug lifecycle in `tests/test_session_only.py`

---

## How to Add a New Task

1. Describe the task clearly
2. Identify which files need modification
3. Check AGENTS.md for completed work
4. Verify the change doesn't break completed work
5. Run tests after implementation
6. Mark as [x] when done and verified
