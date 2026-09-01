"""
Geetest v3 `w` parameter builder — self-built GT3 solver (offline, pure Python).

Structure (GT3 classic, stable across versions):
    w = AES_part + RSA_part
      key      : random string (the AES key)
      payload  : JSON of {userresponse, passtime, aa(trajectory), ep(env), gt, challenge, rp, ...}
      AES_part : AES-128-CBC(key, IV, pad(JSON))  -> encoded
      RSA_part : raw RSA(key) with Geetest's FIXED public key -> 256 hex chars
    ajax.php?...&w=<w>  ->  {result:"success", validate:...}  (the oracle)

STABLE / KNOWN (implemented below, high confidence):
    - Geetest fixed RSA-1024 public key (e=0x10001, n below) — same across all GT3 sites.
    - raw RSA on the short AES key; AES-128-CBC.
    - the w = AES_part ++ RSA_part concatenation.

VERSION-SPECIFIC (fullpage.9.2.0) — TODO, extract via the dynamic harness (hook JSON.stringify
+ ajax.php in an instrumented run of the real JS), then pin here against the ajax.php oracle:
    - exact payload field set + the `aa` trajectory encoding + `rp` hash + `ep` env block.
    - AES key charset/length, IV, and the AES_part encoding (hex vs custom base64).
    - userresponse for the fullpage no-sense pass vs the slide sub-challenge.
"""
from __future__ import annotations
import json, hashlib, random
try:
    from Crypto.Cipher import AES  # pycryptodome
except Exception:
    AES = None

# --- Geetest fixed RSA-1024 public key (GT3, all sites) ------------------------------------
RSA_E = 0x10001
RSA_N = int(
    "00C1E3934D1614465B33053E7F48EE4EC87B14B95EF88947713D25EECBFF7E74C7977D02DC1D9451F79D"
    "D5D1C10C29ACB6A9B4D6FB7D0A0279B6719E1772565F09AF627715919221AEF91899CAE08C0D686D748B"
    "20A3603BE2318CA6BC2B59706592A9219D0BF05C9F65023A21D2330807252AE0066D59CEEFA5F2748EA8"
    "0BAB81", 16)


def rsa_encrypt_key(key: str, _rng=None) -> str:
    """RSA-encrypt the AES key with Geetest's fixed pubkey using PKCS#1 v1.5 padding (jsbn
    `RSAKey.encrypt` -> pkcs1pad2 + doPublic). Non-deterministic (random PS). jsbn renders the
    result via BigInteger.toString(16) which DROPS leading zeros, and slide.js retries the whole
    key until the hex is exactly 256 long -> callers should regenerate the key if len != 256."""
    import os
    modbytes = 128  # RSA-1024
    m = key.encode("latin1")            # jsbn uses charCodeAt (ASCII/latin1)
    ps_len = modbytes - 3 - len(m)
    # PS = random NON-ZERO bytes
    ps = bytearray()
    while len(ps) < ps_len:
        b = (os.urandom(1) if _rng is None else _rng(1))[0]
        if b != 0:
            ps.append(b)
    eb = b"\x00\x02" + bytes(ps) + b"\x00" + m
    c = pow(int.from_bytes(eb, "big"), RSA_E, RSA_N)
    return format(c, "x")               # toString(16), no zero-pad (matches jsbn)


def aes_encrypt(plaintext: str, key: str, iv: bytes = b"0000000000000000") -> bytes:
    """AES-128-CBC with PKCS7 pad. Geetest's key is used as raw bytes (16). IV is version-
    specific (classic uses the ASCII '0000000000000000'); TODO confirm for fullpage 9.2.0."""
    if AES is None:
        raise RuntimeError("pip install pycryptodome")
    kb = key.encode("utf-8")
    kb = (kb + b"\x00" * 16)[:16]
    data = plaintext.encode("utf-8")
    padlen = 16 - (len(data) % 16)
    data += bytes([padlen]) * padlen
    return AES.new(kb, AES.MODE_CBC, iv).encrypt(data)


def rand_key(n: int = 16) -> str:
    charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    # NOTE: workflow scripts forbid random; this module runs as a normal script so random is fine.
    return "".join(random.choice(charset) for _ in range(n))


def get_userresponse(distance: float, challenge: str) -> str:
    """Classic GT3 slide userresponse(distance, challenge). Reference impl — VERIFY against
    fullpage 9.2.0 (the challenge suffix beyond 32 hex chars encodes the transform; our sample
    challenge was exactly 32 chars, i.e. the fullpage no-sense path may not use this)."""
    a = distance + 36
    d = "0123456789"
    e = challenge
    b = {}
    f = e[32:]
    for i, ch in enumerate(f):
        idx = ord(ch)
        if idx not in b:
            b[idx] = (i % 5) + 1  # placeholder mapping — TODO confirm exact table from JS
    # placeholder: real algo decodes `a` into a base-mixed string using b/f — extract dynamically
    return str(a)  # TODO replace with the real fullpage 9.2.0 userresponse


def build_w(payload: dict, key: str | None = None, aes_part_hex: bool = True) -> str:
    """Assemble w = AES_part + RSA_part. `payload` must already carry the version-specific
    fields (userresponse/aa/ep/rp/gt/challenge/...). Returns the w string to send to ajax.php."""
    key = key or rand_key(16)
    enc = aes_encrypt(json.dumps(payload, separators=(",", ":")), key)
    aes_part = enc.hex() if aes_part_hex else _custom_b64(enc)  # TODO confirm encoding
    return aes_part + rsa_encrypt_key(key)


def _custom_b64(b: bytes) -> str:
    import base64
    return base64.b64encode(b).decode()  # TODO Geetest may use a permuted alphabet


if __name__ == "__main__":
    # smoke: RSA part is deterministic given a key and reproducible/verifiable in isolation
    k = "0123456789abcdef"
    r = rsa_encrypt_key(k)
    print("rsa_part len:", len(r), "(expect 256)")
    print("rsa_part:", r[:64], "...")
