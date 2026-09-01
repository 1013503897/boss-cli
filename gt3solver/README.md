# gt3solver — BOSS直聘 login captcha solvers (Geetest GT3 + 网易易盾)

BOSS's login man/machine picks the captcha **per phone number** (`captchaType` in the man/machine
response): `0/1` = Geetest GT3, `4` = 网易易盾 (NetEase Yidun). Both branches feed the same
`GetVerifyCodeRequest` — Geetest fills `challenge/validate/seccode`, 网易 fills **only `validate`**
(see `z1$c.onValidate` → `AbsAuthCodeActivity.xf`). This package has a working harvester for each.

## 网易易盾 (captchaType 4) — `netease_harvest.py` ✅ end-to-end verified

The current path for numbers that draw 网易易盾. A stealth Chrome (patchright) loads NECaptcha
(`initNECaptcha`, captchaId = man/machine `wyCaptchaId`) **inside the real https://www.zhipin.com
origin**, detects the slider gap on the served bg image (Canny template-match; the bg is NOT
scrambled, natural==display so drag px == image px), and **closed-loop drags** the knob — reading
the live `.yidun_jigsaw` left via `getBoundingClientRect` and releasing when the piece reaches the
gap, which sidesteps the knob→piece movement ratio entirely. On solve, NECaptcha's `onVerify`
yields the `validate`, which BOSS `send_sms_code(validate=…, precheck=False)` accepts (`code=0`,
verified 2026-09-01, headless).

```bash
cd boss-cli
python -m gt3solver.netease_harvest --attempts 3                 # harvest a validate
python -m gt3solver.netease_harvest --send 15969236932           # + feed it into send_sms_code (real SMS)
# or the integrated one-shot login:
python -m bosscli.cli login --phone 15969236932 --solve          # solve → send → prompt code → t2
```

DOM (captured 2026-09-01, captchaId ae17e488…, wyCaptchaType 0 = slide): `.yidun_bg-img` (bg IMG),
`.yidun_jigsaw` (piece IMG, rests at bg-left), `.yidun_slider` (knob), `.yidun_refresh` (free
new-image). `wyCaptchaType 1` = MODE_INTELLIGENT_NO_SENSE (not yet handled). Requires patchright
(+ Chrome), opencv-python, numpy, requests.

---

## Geetest GT3 (captchaType 0/1) — pure-Python `w` builder + browser harvester

Reversed from BOSS直聘's login man/machine captcha (`GT3GeetestUtils`, gt=`c1c659ff…`), i.e.
Geetest v3 `fullpage`→`slide3`. This reproduces the entire `w` parameter **offline in pure Python**
and is **byte-exact against the real JS** and **accepted by Geetest's server** (`api.geetest.com`).

## What was reversed

`w = customBase64( AES-128-CBC(JSON(payload), key) ) + RSA_hex(key)`  (slide.7.9.3.js, `$_CCBb`)

| piece | algorithm | where (slide.7.9.3.js) |
|---|---|---|
| `key` | 16 random hex chars (`rt`: 4×4-hex) | 3691 |
| AES | AES-128-CBC, key/iv = UTF-8 bytes, iv=`0000000000000000`, PKCS7 | 2807, `keySize:4` |
| base64 | **bit-permuted** base64: 24 bits regrouped by masks `[7274496,9483264,19220,235]`, alphabet `A-Za-z0-9()`, pad `.` | `$_FCV` 1485 |
| RSA | jsbn **PKCS#1 v1.5** with Geetest's fixed 1024-bit pubkey (e=0x10001) → 256 hex | `$_CCDh` 5482 |
| `userresponse` | `H(distance, challenge)` — classic GT3 (a=round(dist)+base36(chal[-2:]), bucket-encode) | 658 |
| `aa` | trajectory delta-encode (`$_FDd`) + c/s noise insert (`$_BBEl`) | 3564, 3632 |
| `rp` | `md5(gt + challenge[:32] + passtime)` | 5357, `X`=md5 1732 |
| `ep` | `{v:'7.9.3', $_BIT, me, tm, td:-1}` | `$_CCC_` 5492 |
| bg de-scramble | 52-slice canvas reassembly via permutation `Ut` (312→260) | 258-276, 4700 |
| gap → distance | template-match slice piece on de-scrambled bg | — |

The string tables (control-flow-flattened, XOR-obfuscated) were cracked to make the JS readable;
the RSA modulus recovered from the JS **matches the fixed Geetest v3 public key exactly**.

## Verified

- `custom_b64(AES(plaintext, key)) == h` — **byte-exact** vs a real device-captured triple.
- Submitting our `w` to `ajax.php`: a **wrong** distance → `{"message":"fail"}`; the **correct**
  (template-matched) distance → `"forbidden"`. i.e. the server **decrypts our w, validates the
  answer, and only then risk-blocks** — proving crypto + distance are correct.

## The `error_113 forbidden` wall — what it actually is (2026-08-19)

Submitting the offline `w` to `ajax.php` returns `error_113 服务端forbidden`. This is **not** a
crypto/answer failure. Empirically it has **two** causes, and neither is payload quality:

1. **Domain/Origin whitelist.** BOSS's `gt` is bound to a domain whitelist. A `127.0.0.1` / `file://`
   harness **always** gets `error_113` (Origin not whitelisted) — spoofing the `Referer` header is not
   enough (Geetest's JS also reads `location`, and the `Origin` header isn't the referer).
2. **IP rate/reputation.** Even from the correct origin, a *fresh, low-volume* attempt passes; hammering
   `ajax.php` (many rapid solves) degrades the source IP's reputation and re-triggers `error_113`.

So the reverse engineering is complete and correct; the barrier is **where the request comes from**
(origin + IP reputation), which is what `browser_harvest.py` addresses.

## Practical path — `browser_harvest.py` (stealth real browser) ✅

Instead of an offline `w`, drive a stealthed **real Chrome** (`patchright`) that actually solves the
slide **inside the real `https://www.zhipin.com` origin** (satisfying the whitelist) and harvest the
`validate`. This has produced a real, server-accepted validate end-to-end:

```
man/machine → gt+challenge → inject Geetest into zhipin.com → radar click → slide
→ gap on the rendered canvases → human drag → onSuccess → {geetest_validate, geetest_seccode}
```

```bash
cd boss-cli
python -m gt3solver.browser_harvest --attempts 3                     # harvest a validate (headful)
python -m gt3solver.browser_harvest --send 138xxxxxxxx               # + feed it into send_sms_code
```

**Constraints (must-read, in the module docstring):**
- **Run inside zhipin.com origin** — the module injects the widget there; a local harness always forbids.
- **Low frequency only** — occasional login (harvest → cache `t2` → re-login on expiry) is the regime
  that works; tight retry loops degrade the IP and re-trigger `error_113`. A clean/residential CN IP helps.
- patchright's `evaluate` is isolated-world → state goes through the DOM; canvas pixels via `toDataURL`
  (not `element.screenshot`, which composites the stacked canvases). knob px == piece px (ratio 1.000).

Requires `patchright` (+ a Chrome install), `opencv-python`, `numpy`, `pycryptodome`.

## Offline `w` path — `geetest_slide.py` (reversed, byte-exact, but origin/IP-gated)

Kept for reference and completeness (the crypto is 100% reversed and server-*decrypted*):

```python
from gt3solver import geetest_slide, slide_gap
dist = slide_gap.gap_distance(bg_bytes, slice_bytes, xpos)   # from slide get.php + image URLs
w = geetest_slide.build_w(dist, slide_challenge, gt, c, s)   # slide_challenge carries a 2-char suffix!
# GET https://apiv6.geetest.com/ajax.php?gt=..&challenge=slide_challenge&lang=zh-cn&$_BCm=0&client_type=web&w=<w>
```

The dynamic-RE harness (Playwright, drives the real JS to capture ground-truth) lives in the lab
scratchpad, not here.
