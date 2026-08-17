# boss-cli

Off-device **BOSS直聘 (com.hpbr.bosszhipin) job-search** client — a pure-Python
reproduction of the app's native request-signing / response-decryption library
`libyzwg.so` (`com.twl.signer.YZWG`), so search requests can be built and sent from a
script with **no device, no emulator, and no unidbg at runtime**.

```
$ python -m bosscli.cli search "安卓逆向" --city 101210100
# 15 jobs for '安卓逆向' (city=101210100, page=1)
- 安卓android逆向工程师 | 25-50K | 杭州云链矩阵科技 | 杭州  [1-3年 本科 Android Java]
- android逆向开发 | 50-75K | 小算科技 | 杭州  [经验不限 学历不限]
- ...
```

> Research / educational project on mobile API signing. Search uses your own logged-in
> account's `t2` token; you are responsible for complying with BOSS直聘's terms.

## What was reversed

`libyzwg.so` (BOSS直聘 v14.050, arm64-v8a) exposes 10 JNI methods via `RegisterNatives`
(names/signatures are XOR-obfuscated in the `.so`; per-string key = trailing byte). The
request/response crypto was recovered with IDA + a unidbg differential oracle and
re-implemented in [`bosscli/yzwg.py`](bosscli/yzwg.py):

| native primitive | pure-Python formula | fidelity |
|---|---|---|
| `nativeSignature([B,String)` | `"V3.0" + md5(input ‖ SALT ‖ key)` | **byte-exact** |
| `nativeEncodeRequest([B,String)` (`sp`) | `b64url₋_~( RC4(SALT‖key, "BZPBlock"+hdr+LZ4(input)) )` | byte-exact cipher/header/base64; valid + round-trips |
| `nativeEncodeRequestBody([B,String)` | same as `sp` but raw bytes (no base64) → request body | verified vs unidbg |
| `nativeCalculateCRC32([B)` | `"%u"` of IEEE `crc32` | verified |
| `nativeDecodeContent(...)` | RC4-decrypt (+ optional `BZPBlock`/LZ4 deframe) | verified |

- **SALT** = `a308f3628b3f39f7d35cdebeb6920e21` — a constant bound to BOSS's APK signing
  certificate (JNI_OnLoad derives it from `signatures[0]` hashCode and caches it). Re-signing the APK changes it.
- **RC4** here is standard RC4; the native PRGA wraps every byte in `TWIST(x)=(~x&0xCF|x&0x30)`
  on both keystream and plaintext, which cancels under XOR.
- **LZ4** frame is `"BZPBlock" + u32(0) + u32(complen) + u32(origlen) + u32(origlen^complen)` then an
  LZ4 block. The bundled liblz4 may encode a given input to different (equally valid) bytes than
  python-lz4; the server only decompresses, so requests validate regardless.

### The batch search endpoint

Search is a `GET /api/batch/requests` whose body wraps sub-requests
(`net.bosszhipin.base.m.f`, the batch branch):

```
strD    = sorted(outer params: client_info, curidentity, req_time, uniqid, v), Java-URLEncoder'd, "k=v&"
encBody = nativeEncodeRequestBody({"subReqs":[{path:/api/zpgeek/app/geek/search/cardlist, query:...}]}, null)
strA    = nativeCalculateCRC32(encBody)
sp      = nativeEncodeRequest(strD, null)                    # query param
sig     = nativeSignature("/api/batch/requests" + strD + strA, null)   # query param
```

Wire request = `?<strD>&sp=<sp>&sig=<sig>&app_id=1003` + body `encBody`, with headers
`t2` (auth), `zp-accept-encrypting: 1` (+ compressing/encoding), `traceId`, and the BOSS `User-Agent`.
The batch endpoint uses `key = null` (whitelisted). Responses are RC4(+LZ4) encrypted; the client
auto-detects the encoding from the reply.

## Install

```bash
pip install -r requirements.txt          # lz4, requests
```

## Get a session (one-time, from a logged-in device)

Search needs your account's `t2` token plus this device's `client_info`/`uniqid`. Capture them
once from a logged-in BOSS直聘 install (root + a version-matched frida):

1. `frida/boss_capture.js` (compile with `frida-compile`) dumps `client_info`, `uniqid`, `sp/sig`
   and the batch body; the `t2` header is on the outgoing request (see `frida/README` note).
2. Fill `session.local.json` (copy from `session.example.json`) with your `t2`, `client_info`,
   `uniqid`, and the `cardlist_defaults` template. `session.local.json` is gitignored.

`t2` expires with your session; re-capture when calls start returning `invalid auth`.

## Use

```bash
# CLI
python -m bosscli.cli search "Python" --city 101210100 --page 1
python -m bosscli.cli search "数据分析" --json          # parsed jobs as JSON
python -m bosscli.cli search "Golang" --raw             # full decrypted response

# MCP (thin wrapper, tool: boss_search)
BOSS_SESSION=./session.local.json python -m bosscli.mcp_server
```

Register the MCP server in your client (e.g. `~/.claude.json`) with `BOSS_SESSION` pointing at
your session file; the tool is `boss_search(query, city?, page?, sort?)`.

## Verify (optional, unidbg oracle)

`signer-unidbg/` is the black-box oracle used to reverse the crypto: it loads the real `libyzwg.so`
in unidbg (feeding the app cert DER to pass JNI_OnLoad's anti-tamper) and byte-compares against
frida captures. Drop `libyzwg-arm64-v8a.so` + `cert.der` into `signer-unidbg/yzwg/` and:

```bash
cd signer-unidbg && ./gradlew run          # oracle vs tests/oracle/*  -> signature MATCH = true
```

## Tests

```bash
python tests/test_yzwg.py       # native primitives, byte-exact vs real-device oracle
python tests/test_signer.py     # Java-URLEncoder reproduction + batch signing round-trip
```

## Layout

```
bosscli/yzwg.py        pure-Python libyzwg (sig/sp/body/crc/decode)
bosscli/signer.py      strD / subReq encoding + batch signing (net.bosszhipin.base.m)
bosscli/client.py      BossClient.search(): assemble, send, decrypt, parse
bosscli/cli.py         `python -m bosscli.cli search ...`
bosscli/mcp_server.py  FastMCP wrapper (tool: boss_search)
frida/                 capture hooks (signer + request + response)
signer-unidbg/         unidbg differential oracle (verification; .so/cert gitignored)
tests/oracle/          real-device captures used as byte-exact fixtures
```
