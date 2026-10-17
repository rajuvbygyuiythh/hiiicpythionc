# ChitChat WebSocket proposal review

This note separates what the captured HAR establishes from what the proposed
Node.js example assumes. The repository's existing runtime is Python +
Playwright; it already stores browser `storage_state`, restores it in a fresh
browser context, and closes that browser/context when its worker stops. The
live chat loop itself still runs through the browser.

## Supported by the captured trace

- The connection uses the Engine.IO / Socket.IO packet format.
- The client sent the namespace-connect packet `40{"release":...}` and the
  event packet `42["presenceSync"]`; Engine.IO ping/pong traffic was present.
- The server sent `onlineFriends`, `matchUpdate`, `typing`, `chatMessage`, and
  closure updates in the capture.
- The capture does **not** show a client-originated message-send, typing,
  matchmaking, skip/next, or leave/disconnect business event.
- The recorded WebSocket request has no `Cookie` or `Authorization` header.
  This says only what is in this capture; it does not establish how an earlier
  HTTP login or another omitted request authenticates the browser.

## Claims the trace does not establish

- `Access-Control-Allow-Credentials: true` is not proof that the WebSocket
  authenticates with a cookie. CORS response headers do not reveal a supported
  Socket.IO business-event contract.
- The capture does not establish a JWT cookie, `/users/@me`, or that the
  `release` value is an account credential. It also does not establish that a
  participant/closure ID is the logged-in account ID without an independent
  mapping.
- `presenceSync` / `onlineFriends` describes friend presence; it is not a
  matchmaking request. The capture does not show that visiting `/chat/new`
  enqueues a match.
- Event names such as `skip`, `leaveMatch`, `findMatch`, `startMatch`, and
  `chatMessage` for **outbound** actions, plus their payload schemas, remain
  unverified. Sending several guesses for one UI action risks duplicate or
  unintended actions.

## Concrete issues in the pasted Node.js sample

1. `40{"release":...}` is a Socket.IO namespace-connect packet. With
   `socket.io-client`, a server-defined connect-auth object belongs in the
   client's `auth` option if the server contract confirms it. Calling
   `socket.emit("message", ...)` sends a different event packet; it does not
   reproduce that handshake.
2. A top-level `import './autoReply.js'` in `index.js` evaluates the bot before
   the `login`/`start` command is selected. Therefore `login` can start the bot
   too, and `start` imports a module that is already cached.
3. The example assumes `/users/@me`, `userInfo.id`, match/message object shapes,
   and all outbound events without evidence from the trace.
4. The login wait accepts pathname `/` as success and browser shutdown is not
   protected by `finally`; a false positive or exception can save the wrong
   state or leave the browser running.

## Browserless transport foundation (observer only)

`transport/chitchat_socket.py` can load the existing saved Playwright
`storage_state.json` directly, without launching a browser. It uses the
observed Socket.IO release connect-auth field, forces
`transports=["websocket"]`, sends only the observed `presenceSync` event, and
listens for the captured incoming events. The captured notes omit the release
scalar, so the transport requires it explicitly (CLI `--release` or
`CHITCHAT_RELEASE`) rather than inventing a default. The optional
`tools/socket_live_probe.py --account <saved-email> --release <captured-value>`
is a passive CLI; its output shows event payload shape, not values.

Cookie headers are forwarded only when the saved cookie matches the configured
socket host/path, is unexpired, and is valid for the connection security. No
localStorage token key is guessed: an exact key must be configured. The trace
recorded no Cookie or Authorization header, so neither cookie nor token auth is
claimed to be verified.

This foundation does **not** yet implement matching or chat. No outbound
message, matchmaking, Skip/Next, or leave action is sent. The service's observed
`chatMessage` event is only registered as an incoming event; its outbound use
and payload are unverified.

## Safe browser-side protocol capture

For a user-driven session, use Dashboard **Debug Mode (manual chat)**:

1. Choose Login or Restore with exactly one account/session.
2. Enable **Debug Mode (manual chat)** and click **START**.
3. Log in/restore in the visible browser, then navigate and chat manually.
   There is no automated match, message, skip, or leave loop. Dashboard **STOP**
   closes the browser and ends capture.

The browser-side tracer writes live JSONL records to `capture/debug-api.txt`
(the combined timeline), `capture/websocket.jsonl`, and
`capture/http-api.jsonl`. All files are reset once on first use per app process
and capped at 1 MB each. Records include WebSocket frame direction/packet/event,
handshake metadata, close/error markers, fetch/XHR method, safe host/path,
query-key names only, response status, elapsed time, header names only, and
bounded body/payload field/type/length shapes. Page navigation is included in
the combined timeline. Capture is scoped to `chitchat.gg` and its subdomains so
unrelated browsing is not traced. The files are git-ignored.

The trace never persists raw frames or HTTP bodies, chat contents, form values,
passwords, cookies, tokens, account/user IDs, header values, or URL query
values. Header names and JSON field names may appear. Endpoint paths and event
names can still expose implementation details, so review the files before
sharing. This is browser-visible request/response metadata, **not server-side
logs**. It does not establish how authentication works if credential values
are intentionally omitted.

For a richer Phase 1 browser trace, the separate top-level `capture.py` tool
attaches to a loopback-only Chromium CDP endpoint and writes a bounded
`capture/cdp-*/capture.jsonl` metadata trace. It captures handshake header names
(not values/order), event/packet labels, and payload shapes while you use the
site manually. See [`CDP_CAPTURE.md`](CDP_CAPTURE.md) for the disposable-profile
launch flags and privacy limits. No real CDP artifact has been collected in
this checkout yet; analyze the user's reviewed artifact before producing
protocol/auth/API/identity reports.

For a normal bot run, the Dashboard recorder remains opt-in via
`EVA_SOCKET_TRACE=1`; that flag only adds diagnostics and does not disable or
change the chat automation. Neither capture path adds outbound Socket.IO
business actions or implements browserless chat. Matchmaking, send, Skip/Next,
and leave remain unverified and must not be guessed.

বাংলায়: trace-এ আসল message, password, cookie, token, UID/account ID বা
header/query-এর value রাখা হয় না। শুধু metadata/schema থাকে; তাই এটা পুরো
chat content বা server-এর ভেতরের log নয়। `capture/` share করার আগে routes ও
event names দেখে নিন।
