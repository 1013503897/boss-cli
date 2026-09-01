"""Byte-exact regression tests for the login flow (encodePassword + m.e() send-code signing).

Vectors in oracle/login_signing.json were captured from BOSS直聘 v14.050 on a Pixel 6 via
frida RPC straight into com.twl.signer.a (a.f / a.d / a.i, key=null) — no network, no SMS.
Run: python -m pytest tests/  (or plain: python tests/test_login.py)
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bosscli import yzwg, signer

OD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "oracle")
ORACLE = json.load(open(os.path.join(OD, "login_signing.json"), encoding="utf-8"))


def test_encode_password_byte_exact():
    for plain, expected in ORACLE["encode_password"].items():
        assert yzwg.native_encode_password(plain) == expected, plain


def test_send_code_strD_and_sig():
    o = ORACLE["send_code_signing"]
    strD = signer.build_query(o["params"])
    assert strD == o["strD"]
    s = signer.sign_request(o["params"], o["path"], key=None)
    assert s["strD"] == o["strD"]
    assert s["sig"] == o["sig"]
    # sp is RC4(LZ4(strD)); the LZ4 encoder's choices differ from the device but it must
    # decrypt back to the exact strD (server only decompresses).
    assert yzwg.native_decode_content(s["sp"], None) == strD.encode("utf-8")


def test_login_account_uses_encode_password():
    # login `account` field is encodePassword(phone), same primitive as send-code `phone`
    phone = "13800138000"
    assert yzwg.native_encode_password(phone) == ORACLE["encode_password"][phone]


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ok  {name}"); n += 1
    print(f"all {n} tests passed")
