# CDP metadata capture — Phase 1

এই টুলটি আপনার **নিজের, local Chromium** browser-এর Chrome DevTools Protocol
(CDP)-এ যুক্ত হয়। আপনি browser-এ নিজে login ও chat করবেন; টুলটি কেবল
`chitchat.gg` এবং তার subdomain-এর redacted network/WebSocket metadata লেখে।
এটি click করে না, message পাঠায় না, match/skip/leave করে না।

## নিরাপদভাবে চালানো — Dashboard (প্রস্তাবিত)

1. EVA Bot চালু করে **main Dashboard**-এ যান। `CDP CAPTURE BROWSER — MANUAL ONLY`
   panel-টি `Debug Mode (manual chat)` থেকে আলাদা। Browser path auto-detect না
   হলে **Browse…** দিয়ে Chrome/Chromium/Edge executable বেছে নিন।
2. **Launch Browser & Start Capture** চাপুন। আলাদা temporary browser profile-এ
   blank tab খুলবে; এটি কোনো account file পড়ে না এবং bot-এর START/chat actions
   চালায় না।
3. সেই browser-এ নিজে `chitchat.gg` খুলে login/chat করুন। কাজ শেষে একই panel-এর
   **Stop Capture & Close Browser** চাপুন। Capture gracefulভাবে বন্ধ হবে, browser
   process বন্ধ হবে এবং temporary profile মুছে যাবে।

Output থাকবে `capture/cdp-<UTC timestamp>/capture.jsonl`-এ। Dashboard-এর STOP
button capture process-কে graceful stop-file signal দেয়। Browser-এর CDP port
শুধু `127.0.0.1`-এ bind হয়; নিজের দৈনন্দিন browser profile ব্যবহার হয় না।
Profile-এ login করলে browser খোলা থাকা অবস্থায় profile বা CDP port অন্যের সঙ্গে
share করবেন না।

### ঐচ্ছিক: terminal থেকে চালানো

Dashboard ব্যবহার না করলে আগে dependency install করুন:

```bash
python -m pip install -r data/requirements.txt
```

তারপর আলাদা temporary profile দিয়ে Chromium/Chrome চালান এবং capture চালান:

```bash
chrome --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
  --remote-allow-origins=http://localhost \
  --user-data-dir=/path/to/a-temporary-eva-cdp-profile
python capture.py --browser-url http://127.0.0.1:9222 --duration 300
```

`--duration 0` দিলে Ctrl+C বা `--stop-file <path>` না করা পর্যন্ত capture চলে।
Remote-debugging port কখনো `0.0.0.0`-এ expose করবেন না বা অন্যকে দেবেন না।

## Output ও সীমা

প্রতিটি run-এর output আলাদা directory-তে থাকবে; POSIX-এ restrictive file/folder mode ব্যবহৃত হয়। Windows-এ আপনার profile-এর OS access permissions প্রযোজ্য:

```text
capture/cdp-<UTC timestamp>/capture.jsonl
```

Default file cap 5 MB; `--max-mb 1..100` দিয়ে বদলানো যায়। Trace-এ endpoint
host ও redacted route, query/header **নাম** (value নয়), method/status,
WebSocket direction ও packet/event নাম, bounded payload-এর field/type shape,
byte-size bucket, storage key-এর নাম/size এবং visible cookie name থাকতে পারে।
WebSocket handshake header order ইচ্ছাকৃতভাবে রাখা হয় না। HTTP JSON/form body-এর
shape সর্বোচ্চ 256 KB পর্যন্ত রাখা হয়; বড় WebSocket frame/body-এর content
বাদ পড়ে, এবং `Content-Length` না থাকলে response body CDP থেকে local memory-তে
নিয়ে size যাচাই করার পরই shape তৈরি হয়।

**যা রাখা হয় না:** raw cookie/token/password/header/query value, সম্পূর্ণ
WebSocket frame বা HTTP body, chat/message text, user/account ID-এর value,
HttpOnly cookie value, IndexedDB record। IndexedDB-তে শুধু database-এর
redacted নাম/version দেখা হয়। কোনো key বা endpoint label-এ ব্যক্তিগত তথ্য
থাকার সম্ভাবনা থাকলে share করার আগে JSONL নিজে review করুন; redacted metadata-ও
সাইটের implementation detail প্রকাশ করতে পারে।

এই output দিয়ে পরে **বাস্তব trace-ভিত্তিক analysis** করা যাবে; tool নিজে
`ws_protocol.json`, `ws_message_map.json`, `auth_flow.json`, `api_surface.json`
বা `identity.json` বানায় না। Trace file-টি দিন—browser profile, cookies,
raw CDP log বা account session দেবেন না। Trace অসম্পূর্ণ হলে যা জানা যায় না,
তা অনুমান না করে স্পষ্টভাবে অজানা বলা হবে।

Offline checks:

```bash
python -m unittest tests.test_cdp_capture tests.test_cdp_capture_launcher -v
```
