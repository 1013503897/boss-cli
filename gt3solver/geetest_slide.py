"""
Geetest v3 slide (slide3) `w` builder — pure Python, reversed from slide.7.9.3.js + gct.b71a90...js.

w = customBase64( AES-128-CBC( JSON(payload), key ) ) + RSA_hex( key )
  key       = 16 random hex chars (rt(): 4x [4-hex])          # slide $_CCEp -> rt
  AES        = key/iv as UTF-8 bytes, iv="0000000000000000", PKCS7   # V.encrypt, line 2807
  base64     = standard alphabet with +->'(' , '/'->')' , no padding # alphabet [264], CryptoJS map(64)
  RSA        = raw RSA(keyString) with Geetest fixed pubkey -> 256 hex (retry if <256)  # $_CCDh
  payload o  = {lang, userresponse, passtime, imgload, aa, ep, rp}   # $_CCBb, line 5300
    userresponse = H(distance, challenge)                     # line 658 (classic GT3)
    aa           = BBEl( FDd(track), c, s )                    # line 3564/3632 (c,s from get.php)
    rp           = md5(gt + challenge[:32] + passtime)         # line 5357 (X = md5)
    ep           = {v:'7.9.3', $_BIT:touch, me:mouse, tm:{...}, td:-1}   # line 5492
  (the window._gct anti-tamper `h9s9` field is skipped first — try without it.)
"""
from __future__ import annotations
import json, hashlib, base64, random
from Crypto.Cipher import AES
try:
    from . import geetest_w            # RSA pubkey + rsa_encrypt_key
except ImportError:
    import geetest_w

FDD_ALPHA = "()*,-./0123456789:?@ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqr"  # len 64

# custom base64 ($_FCV / m.$_DJJ): NOT standard grouping — the 24 bits of each 3-byte block are
# regrouped into four 6-bit indices via these fixed masks (each selects 6 of the 24 bits, MSB-first).
B64_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789()"
B64_PAD = "."
B64_MASKS = [7274496, 9483264, 19220, 235]   # $_ECx $_EDQ $_EEu $_EFh
B64_BITS = 24                                 # $_EGw


def _extract(val: int, mask: int) -> int:
    n = 0
    for r in range(B64_BITS - 1, -1, -1):
        if (mask >> r) & 1:
            n = (n << 1) + ((val >> r) & 1)
    return n


# ---- key gen (rt) : 16 random hex ----
def gen_key() -> str:
    def t():  # (65536*(1+random)|0).toString(16).substring(1) -> 4 hex chars
        return format(int(65536 * (1 + random.random())) & 0xFFFF, "04x")
    return t() + t() + t() + t()


# ---- custom base64 ($_FCV): bit-permuted base64 via B64_MASKS, alphabet A-Za-z0-9(), pad '.' ----
def custom_b64(data: bytes) -> str:
    res, end, s, a = "", "", len(data), 0
    while a < s:
        if a + 2 < s:
            v = (data[a] << 16) + (data[a + 1] << 8) + data[a + 2]
            res += "".join(B64_ALPHA[_extract(v, m)] for m in B64_MASKS)
        else:
            c = s % 3
            if c == 2:
                v = (data[a] << 16) + (data[a + 1] << 8)
                res += "".join(B64_ALPHA[_extract(v, m)] for m in B64_MASKS[:3]); end = B64_PAD
            elif c == 1:
                v = data[a] << 16
                res += "".join(B64_ALPHA[_extract(v, m)] for m in B64_MASKS[:2]); end = B64_PAD * 2
        a += 3
    return res + end


# ---- AES-128-CBC(JSON, key), key/iv as UTF-8 bytes ----
def aes_encrypt(plaintext: str, key: str) -> bytes:
    kb = key.encode("utf-8")[:16]
    iv = b"0000000000000000"
    data = plaintext.encode("utf-8")
    pad = 16 - (len(data) % 16)
    data += bytes([pad]) * pad
    return AES.new(kb, AES.MODE_CBC, iv).encrypt(data)


# ---- userresponse H(distance, challenge)  (slide.js line 658) ----
def userresponse(distance: float, challenge: str) -> str:
    last2 = challenge[-2:]
    r = [(ord(ch) - 87 if ord(ch) > 57 else ord(ch) - 48) for ch in last2]
    n = 36 * r[0] + r[1]
    a = round(distance) + n
    ch = challenge[:-2]
    buckets = [[], [], [], [], []]
    seen, u = {}, 0
    for s in ch:
        if s not in seen:
            seen[s] = 1
            buckets[u].append(s)
            u = 0 if u + 1 == 5 else u + 1
    f, d, p, g = a, 4, "", [1, 2, 5, 10, 50]
    while f > 0:
        if f - g[d] >= 0:
            p += random.choice(buckets[d])
            f -= g[d]
        else:
            buckets.pop(d); g.pop(d); d -= 1
    return p


# ---- trajectory encode FDd (line 3564) then BBEl c/s insertion (line 3632) ----
def _fdd_num(t: int) -> str:
    e, n = FDD_ALPHA, len(FDD_ALPHA)
    i = abs(t)
    o = i // n
    if o >= n:
        o = n - 1
    r = e[o] if o else ""
    s = ""
    if t < 0:
        s += "!"
    if r:
        s += "$"
    return s + r + e[i % n]

_PAIR_MAP = [[1, 0], [2, 0], [1, -1], [1, 1], [0, 1], [0, -1], [3, 0], [2, -1], [2, 1]]
_PAIR_CH = "stuvwxyz~"

def fdd(track: list[list[int]]) -> str:
    """track = list of [x, y, t] absolute points. Returns aa_raw."""
    deltas, o = [], 0
    for s in range(len(track) - 1):
        e = round(track[s + 1][0] - track[s][0])
        n = round(track[s + 1][1] - track[s][1])
        r = round(track[s + 1][2] - track[s][2])
        if e == 0 and n == 0 and r == 0:
            continue
        if e == 0 and n == 0:
            o += r
        else:
            deltas.append([e, n, r + o]); o = 0
    if o != 0:
        deltas.append([e, n, o])
    rr, ii, oo = [], [], []
    for pt in deltas:
        ch = 0
        for k, pair in enumerate(_PAIR_MAP):
            if pt[0] == pair[0] and pt[1] == pair[1]:
                ch = _PAIR_CH[k]; break
        if ch:
            ii.append(ch)
        else:
            rr.append(_fdd_num(pt[0])); ii.append(_fdd_num(pt[1]))
        oo.append(_fdd_num(pt[2]))
    return "".join(rr) + "!!" + "".join(ii) + "!!" + "".join(oo)

def bbel(aa: str, c: list[int], s: str) -> str:
    """insert noise from c/s (get.php) into aa (line 3632)."""
    if not c or not s:
        return aa
    o = aa
    s0, s2, s4 = c[0], c[2], c[4]
    i = 0
    while i + 2 <= len(s):
        r = s[i:i + 2]; i += 2
        cc = int(r, 16)
        u = chr(cc)
        l = (s0 * cc * cc + s2 * cc + s4) % len(o)
        o = o[:l] + u + o[l:]
    return o


# ---- ep environment ----
def build_ep(passtime: int, touch=False, mouse=True) -> dict:
    # tm timing map a..u (page-load timings); fabricate monotonic plausible values
    base = 1000
    tm = {k: (base if k in "ab" else base + i * 3) for i, k in enumerate("abcdefghijklmnopqrstu")}
    tm["b"] = 0
    return {"v": "7.9.3", "$_BIT": touch, "me": mouse, "tm": tm, "td": -1}


# ---- a human-like track ending at `distance` (accel -> decel -> overshoot -> correct) ----
def make_track(distance: float) -> list[list[int]]:
    pts, t = [], 0
    overshoot = distance + random.randint(2, 6)
    # accelerate to ~70% then decelerate to the overshoot point
    x = 0.0; v = 0.0
    mid = overshoot * random.uniform(0.62, 0.72)
    while x < overshoot:
        a = random.uniform(1.8, 3.2) if x < mid else -random.uniform(1.6, 2.6)
        v = max(0.4, v + a)
        x = min(overshoot, x + v)
        t += random.randint(9, 22)
        pts.append([round(x), round(random.uniform(-1.2, 1.2)), t])
    # settle back from overshoot to the exact distance (human correction)
    for _ in range(random.randint(2, 4)):
        x -= random.uniform(1, 2.5)
        t += random.randint(18, 45)
        pts.append([round(max(distance, x)), round(random.uniform(-1, 1)), t])
    t += random.randint(30, 90)
    pts.append([round(distance), 0, t])       # final resting point at the gap
    return pts


def build_w(distance: float, challenge: str, gt: str, c: list[int], s: str,
            imgload: int | None = None, passtime: int | None = None) -> str:
    track = make_track(distance)
    passtime = passtime or track[-1][2]
    imgload = imgload if imgload is not None else random.randint(80, 300)
    aa = bbel(fdd(track), c, s)
    ur = userresponse(distance, challenge)
    rp = hashlib.md5((gt + challenge[:32] + str(passtime)).encode()).hexdigest()
    payload = {
        "lang": "zh-cn",
        "userresponse": ur,
        "passtime": passtime,
        "imgload": imgload,
        "aa": aa,
        "ep": build_ep(passtime),
        "rp": rp,
    }
    key = gen_key()
    aes_part = custom_b64(aes_encrypt(json.dumps(payload, separators=(",", ":")), key))
    rsa_part = geetest_w.rsa_encrypt_key(key)
    while len(rsa_part) != 256:               # $_CCDh retry (leading-zero -> regen key)
        key = gen_key()
        aes_part = custom_b64(aes_encrypt(json.dumps(payload, separators=(",", ":")), key))
        rsa_part = geetest_w.rsa_encrypt_key(key)
    return aes_part + rsa_part


if __name__ == "__main__":
    # smoke: userresponse round-trips distance; w has plausible shape
    ch = "3d021bcfa7dcd720c189b2ab51d059df"
    print("userresponse(50):", userresponse(50, ch))
    print("fdd sample:", fdd([[0, 0, 0], [1, 0, 10], [2, 1, 22], [5, 0, 40]])[:60])
    w = build_w(120, ch, "c1c659ff7a6576d290b547c7759c7465", [12, 58, 98, 36, 43], "6d314546")
    print("w len:", len(w), "tail256 hex:", all(x in "0123456789abcdef" for x in w[-256:]))
    print("w:", w[:80], "...")
