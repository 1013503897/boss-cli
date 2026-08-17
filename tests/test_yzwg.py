"""Byte-exact regression tests for the pure-Python libyzwg reproduction.

Oracles under tests/oracle/ are real captures from BOSS直聘 v14.050 on a Pixel 6
(frida hook of com.twl.signer.a). Run: python -m pytest tests/  (or plain: python tests/test_yzwg.py)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bosscli import yzwg

OD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "oracle")


def _read(name, binary=False):
    with open(os.path.join(OD, name), "rb" if binary else "r") as f:
        return f.read() if binary else f.read().strip()


def test_signature_byte_exact():
    inp = _read("oracle_input.bin", binary=True)
    key = _read("oracle_key.txt")
    exp = _read("oracle_sig.txt")
    assert yzwg.native_signature(inp, key) == exp


def test_sp_roundtrip_and_prefix():
    inp = _read("oracle_sp_input.bin", binary=True)
    key = _read("oracle_sp_key.txt")
    pref = _read("oracle_sp_prefix.txt")
    sp = yzwg.native_encode_request(inp, key)
    # constant 24-byte frame header -> first 16 base64 chars identical to the device
    assert sp[:16] == pref[:16]
    # and it round-trips to the exact plaintext (server only decompresses; bytes may differ)
    assert yzwg.native_decode_content(sp, key) == inp


def test_crc32():
    assert yzwg.native_calculate_crc32(b"A") == "3554254475"
    assert yzwg.native_calculate_crc32(b"hello world") == "222957957"
    assert yzwg.native_calculate_crc32(b"") == ""


def test_encode_body_is_sp_without_base64():
    inp = b"ABCDEFGHIJKLMNOP"
    key = "82a8b7f0c9b504426ae7abe305d1e388"
    body = yzwg.native_encode_request_body(inp, key)
    sp = yzwg.native_encode_request(inp, key)
    assert yzwg._b64(body) == sp


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ok  {name}"); n += 1
    print(f"all {n} tests passed")
