# ChitChat Bot (EVA Bot) — two versions live in this repo

This repository now holds **both** generations of the chitchat.gg bot.

| Where | What | Language | Status |
|---|---|---|---|
| `root-project-proxy-diagnostics-UNVERIFIED.zip` | ChitChat Bot / EVAChat Flow — Wails desktop app + CLI worker + proxy diagnostics | **Go** (67 `.go` files) | still zipped, as uploaded |
| `python-bot/` | EVA Bot — Full Project (diagram flow engine + legacy engine, PyQt6 dashboard, CLI runner, WebSocket bot) | **Python** (74 `.py` files, 171 files / ~14 MB) | extracted, ready to read & run |

## `python-bot/` — the last Python version

Source of truth: repo [`rajuvbygyuiythh/chatchat2222`](https://github.com/rajuvbygyuiythh/chatchat2222)
→ `eva_bot_complete.zip` → `extracted_project/papipapi/`.
Newest file timestamp inside the archive: **2026‑10‑09 00:18**.

This is the most complete Python build found across the account. Compared with the
`cccccchhtt11` copy (`EVA_Bot_full_project_CDP_dashboard_capture_verified.zip`,
69 `.py` files, 2026‑10‑08) it adds exactly five files — the WebSocket bot layer:

- `main_pro.py`
- `run_ws_bot.py`
- `ws_cli.py`
- `transport/ws_bot.py`
- `entry/main_pro.py`

Everything else is byte-identical between the two.

### Layout

```
python-bot/
  eva_flow.py            diagram flow engine (default)
  flow_reference.py      reference implementation of the flow
  chat/                  rules, persona, style, geo, content filter, databases
  browser/               automation, engine, context pool, chat reader, CDP capture
  transport/             chitchat_socket.py, ws_bot.py  (WebSocket transport)
  entry/                 main.py, main_pro.py, cli_runner.py, launcher.py, thread_manager.py
  core/                  account manager, config loader, engine bridge, resource governor
  data/                  input/output .txt categories + local_db rule packs
  tests/, tools/, docs/  tests, debug probes, architecture & flow docs
```

The one rule (from `python-bot/README.md`):

```
data/input/<category>.txt   = WHAT THE USER SAYS   (trigger keywords)
data/output/<category>.txt  = WHAT THE BOT REPLIES (reply lines)
same file name = same category — edit the txt files, restart, done.
```

### Notes

- No account/session material was carried over: no `.env`, `account_sessions/`,
  `storage_state.json`, cookies, browser profiles or logs. `python-bot/.gitignore`
  keeps it that way.
- Older Python snapshots still exist in other repos of the same account, if you
  need history: `tgbot` (`eva_bot_v9_0_deepseek_only_ready.zip`, v9.0, 2026‑09‑20),
  `chatfilehere` / `lastch` (`eva_bot_sms_detect_fixed.zip`, 2026‑09‑22),
  `updatec` (`picccccccfull-project.zip`, 2026‑09‑16), `didactic-system` (`22.zip`).

## Go version

`root-project-proxy-diagnostics-UNVERIFIED.zip` is the Go + Wails port (EVAChat Flow
engine, Rod / ChromeDP / Show Mode browser options, proxy diagnostics). Its own docs
state it has **no Python runtime dependency**. Unzip it if you want to work on it —
see `START-HERE.md` and `docs/PROJECT_MAP.md` inside the archive.
