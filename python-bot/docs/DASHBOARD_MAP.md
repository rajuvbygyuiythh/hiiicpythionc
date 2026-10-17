# EVA Bot Dashboard Map

এই গাইডে Dashboard-এর প্রতিটি page/option কী করে এবং কোন code/config/data file ব্যবহার করে তা দেখানো হয়েছে। UI-টি মূলত `entry/main.py`-তে তৈরি।

## 1. পুরো Dashboard-এর layout

```text
┌ Sidebar ─────────────────┐ ┌ Top bar ─────────────────────────────────────┐
│ Dashboard / Live Chat    │ │ Chats • Sent • Recv • Snaps • Pics • Status │
│ Sessions / Pictures      │ └──────────────────────────────────────────────┘
│ Accounts / Settings / Logs│ ┌ Selected page ─────────────────────────────┐
│ CPU / RAM                │ │                                            │
│ START / STOP             │ │                                            │
└──────────────────────────┘ └────────────────────────────────────────────┘
```

- **Sidebar:** page বদলানো, CPU/RAM monitor, START ও STOP।
- **Top bar:** মোট chat/send/receive/snap/picture counters ও বর্তমান status।
- **মূল UI source:** [`entry/main.py`](../entry/main.py); worker orchestration [`entry/thread_manager.py`](../entry/thread_manager.py)-তে।

## 2. Page অনুযায়ী option ও file mapping

### A. Dashboard

**Status cards:** Status, Threads, Sessions, Banned, Users Chatted, Snaps, Pics Sent, Runtime। এগুলো live counters; আলাদা config file নয়। GUI ও worker callback থেকে update হয়।

| Option | কাজ / সীমা | কোথায় প্রভাব পড়ে |
|---|---|---|
| Browser Threads | একসাথে browser worker; 1–10 (default 1)। Login/Restore-এ account-এর সংখ্যার বেশি হলে কমিয়ে নেয়। | `entry/main.py` → `entry/thread_manager.py` |
| Max Replies | এক chat-এ bot-এর সর্বোচ্চ reply; 1–20 (default 8)। | `entry/main.py` → `entry/thread_manager.py` → `browser/browser_automation.py` |
| Reply Delay | দুই reply-এর মাঝে random delay range; 0–60 সেকেন্ড (default 1–3)। | Run-এর সময় worker-এ পাঠানো হয়; GUI field নিজে `data/config.json`-এ save হয় না। |
| Chat Time | `Until Snap Share` অথবা 1, 2, 3, 5, 10, 15, 20, 30, 45, 60 মিনিট। | Run-এর সময় `browser/browser_automation.py`-তে ব্যবহৃত হয়। |
| New Chat Delay / Rest Every / Rest For | ফাঁকা রাখলে `data/config.json`-এর `chat_timing` defaults; value দিলে ওই run-এর জন্য override। | `core/config_loader.py` + run-time `chat_timing` |
| Browser Engine | Chromium / Camoufox নির্বাচন; Dashboard থেকে পছন্দটি `data/config.json`-এ save হয়, পরের browser launch-এ প্রযোজ্য। | `performance.browser_engine` → `browser/browser_engine.py` |
| Show Browser | browser window দেখাবে; off হলে headless mode (default off)। | `entry/main.py` → `entry/thread_manager.py` → `browser/browser_automation.py` |
| Hide After Login | login-এর পর browser window লুকায় (default on)। | Run-time worker option |
| Shuffle Chat | conversation message order shuffle করে (default off)। | `entry/main.py` → `entry/thread_manager.py` |
| First Message | Send first / Wait for stranger / Random; delay range 0–60 সেকেন্ড (default Wait for stranger, delay 1–3)। | `entry/main.py` → `browser/browser_automation.py` |
| Performance presets | Low = 1 thread, 2–4s reply delay, 8 max replies; Medium = 3, 1–3s, 8; High = 5, 0.5–2s, 6। | শুধু Dashboard run controls বদলায়; preset button নিজে config file save করে না। |
| Picture quick-toggle | মাঝের chat-এ random picture পাঠানো on/off; Pictures page-এ যায়। | `picture_sending` config + `browser/browser_automation.py` |
| Alert Sounds | captcha/ban/connect/snap event-এর beep on/off (default on)। | GUI runtime option; `entry/main.py` |
| Captcha banner | captcha ধরা পড়লে সতর্কতা দেখায়; এটি control নয়, status indicator। | `entry/main.py` + browser worker event |
| Saved Browser Profiles | local saved-profile count, Refresh এবং Restore Saved shortcut; successful login-এর পর portable auth/session state auto-save হয় (full browser installation profile নয়)। | `browser/account_session_store.py`; project-root `account_sessions/` |
| Login & Save Only | Login mode-এ ঠিক একটি account নিলে এক visible browser-এ login করে session save করে browser বন্ধ করে; chat loop/message পাঠানো শুরু করে না। | `entry/main.py` → `entry/thread_manager.py` → `browser/browser_automation.py` |
| Debug Mode (manual chat) | Login/Restore-এ ঠিক একটি account/session; এক visible browser login-এর পর খোলা থাকে। User নিজে chat করেন; bot match/message/skip/leave করে না, account ঘোরায় না, নতুন session auto-save করে না। STOP browser বন্ধ করে। | `entry/main.py` → `entry/thread_manager.py` → `browser/browser_automation.py` → `browser/socket_trace.py` |
| CDP Capture Browser (manual only) | আলাদা isolated Chrome/Chromium/Edge browser চালিয়ে CDP capture শুরু করে; Dashboard থেকেই STOP-এ capture ও browser বন্ধ হয়। Account file বা bot START লাগে না; কোনো bot chat action নয়। Trace `capture/cdp-*/capture.jsonl`-এ। | `entry/main.py` → `browser/cdp_capture_launcher.py` → `capture.py` |
| Thread Status / Live Log | worker status ও সাম্প্রতিক log দেখায়। | `entry/main.py`, `entry/thread_manager.py` |

### B. Live Chat

- **Show:** All sessions অথবা নির্দিষ্ট session (`S1`, `S2`, …)।
- **Auto-scroll:** নতুন message এলে feed নিচে scroll করে।
- **Clear Feed:** শুধু GUI feed পরিষ্কার করে; saved session/config মুছে না।
- Incoming/outgoing message UI-তে পাঠায় `entry/main.py`; worker event আসে `entry/thread_manager.py` এবং browser chat loop থেকে। Feed runtime memory-তে থাকে।

### C. Sessions

- Summary cards: Active Sessions, Banned, Pics Sent।
- Table: Session #, Account, Status, Chats, Msgs In/Out, Snaps, Pics।
- Live counters আসে `entry/main.py`/`entry/thread_manager.py` থেকে। Saved login state রাখে [`browser/account_session_store.py`](../browser/account_session_store.py)-এর code; data থাকে project root-এর `account_sessions/` folder-এ (`storage_state.json`, metadata, fingerprint, history; selected proxy credentials-ও থাকতে পারে)। **এই folder private—share/commit করবেন না।**

### D. Pictures

| Option | কাজ | File/data |
|---|---|---|
| Select Folder | আপনার PC-র image folder বেছে নেয়। | Images নির্বাচিত local folder-এ থাকে; project-এ copy হয় না। |
| Rename All Now | folder-এর supported image-গুলো `eva_pic_001` ইত্যাদি নামে সাজায়। | `entry/main.py` |
| Enable picture sending | Dashboard-এর quick-toggle-এর সঙ্গে synced। | `data/config.json` → `picture_sending.enabled` |
| Send pic at message # | Default 4; code 1–20 range-এ সীমাবদ্ধ করে। | `picture_sending.after_messages` |
| Pics per stranger | Default 1; code 1–5 range-এ সীমাবদ্ধ করে। | `picture_sending.pics_per_chat` |
| Picture folder | folder path। | `picture_sending.folder` |
| Pool preview | প্রথম 60টি file দেখায়। | নির্বাচিত local folder; `entry/main.py` |

ছবি upload/send করে `browser/browser_automation.py`; UI/config logic `entry/main.py`-তে। Settings-এ **Save Config** চাপলে picture settings-ও `data/config.json`-এ লেখা হয়।

### E. Accounts

- **Account Mode:** Create / Login / Restore।
- **Accounts File:** user-selected file; format এক লাইনে `email:password`। Browse/Clear ও loaded account preview আছে।
- **Proxy File:** ঐচ্ছিক proxy list; Browse/Clear ও proxy warning আছে।
- **Create mode limitation:** radio option-টি UI-তে আছে, কিন্তু বর্তমান `start_bot()` Create বেছে নিলে start না করে Login mode ব্যবহার করতে বলে।
- Login/Restore workers তৈরি হয় `entry/main.py` → `entry/thread_manager.py` দিয়ে। Account credential file-এর path user বেছে নেয়; repo-তে credentials রাখবেন না।
- Restore mode saved sessions পড়ে `browser/account_session_store.py`-এর `account_sessions/` directory থেকে।
- Dashboard-এর **Login & Save Only** checkbox শুধু Login mode-এ চলে এবং accounts file-এ ঠিক একটি account চাই; এটি login শেষে session save করে worker/browser বন্ধ করে, chat loop চালায় না.
- **Debug Mode (manual chat)** Login/Restore-এ ঠিক একটি account/session চায়; visible browser login-এর পর খোলা রাখে। User browser-এ নিজে chat করেন; bot chat/match automation, account rotation, বা session auto-save চলে না। Dashboard STOP browser বন্ধ করে.

### F. Settings

Settings page-এর **Save Config** `core/config_loader.py`-এর save helper দিয়ে `data/config.json`-এ লিখে।

| UI group | Option | Config key / file |
|---|---|---|
| Browser | Settings page-এ Dashboard Engine setting-এর নির্দেশনা | `data/config.json` → `performance.browser_engine` (`chromium` / `camoufox`) |
| Chat Timing | New Chat Delay min/max, Rest Interval min/max, Rest Duration min/max | `chat_timing.*` |
| Human Behavior | Reaction Pause, Typing Speed, Read Reply min/max | `human_behavior.*` |
| Resource Governor | CPU Warn, RAM Warn, RAM Recycle, RAM Redline | `resource_governor.cpu_warn`, `mem_warn`, `mem_recycle`, `mem_redline` |
| Config buttons | Reload Config / Save Config | `core/config_loader.py` ↔ `data/config.json` |

Browser Engine নির্বাচন এখন Dashboard-এর Browser group-এ আছে। Engine পরিবর্তন `data/config.json`-এর `performance.browser_engine`-এ auto-save হয় এবং পরের browser launch-এ প্রয়োগ হয়; চলমান threads-এর সময় selector বন্ধ থাকে। Settings page-এর **Save Config**-ও এই engine value-সহ Chat Timing, Human Behavior, Resource Governor ও Picture Sending sections save করে। **Reload Config** Chat Timing ও Browser Engine reload করে।

Settings page-এ edit/save হয় না এমন `performance` key-গুলো (যেমন poll/idle-poll interval) `data/config.json`-এ সরাসরি edit করতে হয়।

### G. Logs

- **Search logs:** GUI-তে log filter।
- **Clear Logs:** GUI log buffers clear করে।
- **Export Logs:** আপনি যে `.txt` path বেছে দেবেন সেখানে visible logs export করে।
- **Auto-scroll**, **All Logs**, এবং running thread অনুযায়ী tabs।
- Main UI/log handling: `entry/main.py`; windowless GUI stdout: `data/logs/gui_console.log`; legacy rule-engine trace: `data/logs/chat_debug.log`; DOM dump (`EVA_DUMP_CHAT_DOM=1`): root `logs/chat_dom_dump_*.html`।
- `EVA_DEBUG=1` timing/traceback helpers: `core/debug.py`, integrated in `browser/browser_automation.py`। Logs/DOM dump-এ chat text থাকতে পারে—share করার আগে review/redact করুন।
- Browser API/WebSocket capture: Dashboard-এর **Debug Mode (manual chat)** স্বয়ংক্রিয়ভাবে trace চালু করে; `capture/debug-api.txt` হলো combined JSONL এবং `capture/websocket.jsonl`, `capture/http-api.jsonl` হলো sidecar। প্রতি ফাইল সর্বোচ্চ 1 MB। Timestamp, event/direction, safe host/path, query-key names, request method/status/elapsed time, credential-header names, ও payload schema/type থাকে; raw frame/body, message text, token/cookie/password/UID/account ID বা value থাকে না। এটি শুধু `chitchat.gg` ও subdomain-এর browser-visible metadata, server-side log নয়; অন্য browsing trace হয় না। Normal bot run-এ opt-in `EVA_SOCKET_TRACE=1`-ও ব্যবহার করা যায়। Share করার আগে routes/events review করুন।

## 3. Chat reply files

Dashboard START করলে browser worker chat message `browser/chat_reader.py` দিয়ে পড়ে; reply selection হয় `chat/rule_bot.py` থেকে:

- Default flow engine: `eva_flow.py`।
- Legacy engine: `chat/rules.py` (`EVA_ENGINE=legacy`)।
- Trigger/reply text pools: `data/input/` ও `data/output/`।
- অতিরিক্ত reply/database data: `data/local_db/`।
- `entry/main.py` START-এর সময় `data/output/flirty_questions.txt`-ও পড়ে worker-এ fixed-message template list হিসেবে পাঠায়।
- Snapchat username pool: `data/snap_ids.txt`।

`data/config.json` runtime settings; `config/eva_config.json` intent tuning।

## 4. Source files at a glance

```text
entry/main.py                     Dashboard pages, widgets, callbacks, start/stop
entry/thread_manager.py           Worker threads and GUI event/signals
browser/browser_automation.py     Login/browser/chat loop, message/picture sending
browser/chat_reader.py            Incoming SMS extraction and new-message tracking
browser/account_session_store.py  Saved-session file handling
chat/rule_bot.py                  Engine switch and reply API
eva_flow.py                       Default flow engine
chat/rules.py                     Legacy rule engine
core/config_loader.py             Read/write/normalize config.json
core/debug.py                     EVA_DEBUG timings, tracebacks, redaction
```

আরও overall system diagram: [`PROJECT_MAP.md`](PROJECT_MAP.md)।
