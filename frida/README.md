# frida capture

One-shot session extractor for boss-cli. Attaches to a logged-in BOSS直聘, correlates the
signer primitives with the real URL, and dumps everything needed to build `session.local.json`.

## What it captures (`boss_capture.js`)

- `SP` / `SIG` — `com.twl.signer.a.d/.i` inputs+outputs, with the real URL (thread-labelled via
  `net.bosszhipin.base.m.e/f`). The `SP.strD` is the exact outer param string (`client_info`,
  `curidentity`, `req_time`, `uniqid`, `v`).
- `BODY` — `com.twl.signer.a.e` plaintext (the `{"subReqs":[...]}` before encryption).
- `HDR` — the outgoing request headers via `net.bosszhipin.base.a` (BOSS's ApiDecodeInterceptor),
  including the **`t2`** auth token and the `zp-accept-*` / `User-Agent` headers. (okhttp3 is
  shaded to `okhttp3.h0/a0/c0`, so it's captured through BOSS's own interceptor, not `okhttp3.*`.)

## Run

```bash
# 1) version-matched frida-server on the device (Morphida art-runtime-srv here); forward a port
adb -s <dev> forward tcp:27142 tcp:27042

# 2) compile (frida 17 dropped the global Java bridge -> bundle it)
frida-compile boss_capture.js -o boss_capture.c.js

# 3) attach by PID (anti-detect frida masks process names -> frida-ps shows blanks)
python boss_frida_run.py <PID> boss_capture.c.js

# 4) do a search in the app; read the [CAP] {...} blocks and fill session.local.json:
#    t2            <- HDR.headers  (t2: ...)
#    client_info   <- SP.strD      (url-decode the client_info= value)
#    uniqid        <- client_info.uniqid
#    cardlist_defaults <- BODY.bodyPlain  (the cardlist subReq query, url-decoded k=v)
```

`boss_frida_run.py` connects to a remote device at `127.0.0.1:27142` and prints each `send()`
payload as `[CAP] {json}`.
