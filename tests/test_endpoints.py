"""
Offline checks for the authenticated read/write endpoints (no network): intercept the HTTP
layer, then re-derive `sig` from the captured strD to prove each endpoint signs with the correct
key — key=None for whitelisted paths (cities/recommend), key=secretKey for the rest
(whoami/detail/chat). This is the part we cannot verify live while the test account is rate-limited.
"""
import os, sys, types
from urllib.parse import unquote
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bosscli.client import BossClient
from bosscli import yzwg

SECRET = "ab8d5d0665ef5d5bbba3699b14d1a825"
SESSION = {
    "t2": "T2TOKEN", "v": "14.050", "app_id": "1003", "uniqid": "uniq-123",
    "client_info": {"os": "Android", "uniqid": "uniq-123"}, "curidentity": "0",
    "secretKey": SECRET, "uid": 42,
}


def _capture():
    """A BossClient whose _http records the last request and returns a plaintext-JSON body."""
    c = BossClient(dict(SESSION))
    calls = []

    def fake_http(method, url, *, data=None, headers=None, retries=2):
        calls.append({"method": method, "url": url, "data": data, "headers": headers})
        return types.SimpleNamespace(content=b'{"code":0,"zpData":{}}')

    c._http = fake_http
    return c, calls


def _split_wire(url_or_body: str):
    """wire = strD + '&sp=' + quote(sp) + '&sig=' + sig + '&app_id=' + id  -> (strD, sp, sig)."""
    wire = url_or_body.split("?", 1)[1] if "?" in url_or_body else url_or_body
    strD, _, rest = wire.partition("&sp=")
    sp_q, _, rest2 = rest.partition("&sig=")
    sig, _, _ = rest2.partition("&app_id=")
    return strD, unquote(sp_q), sig


def _assert_signed_with(call, path, key):
    url = call["url"] if call["method"] == "GET" else call["data"]
    strD, _sp, sig = _split_wire(url if call["method"] == "GET" else "?" + url)
    expect = yzwg.native_signature((path + strD).encode(), key)
    assert sig == expect, f"{path}: sig mismatch (key={'secretKey' if key else 'None'})"
    return strD


def test_whoami_uses_secretkey():
    c, calls = _capture()
    c.whoami()
    strD = _assert_signed_with(calls[-1], "/api/zpgeek/cvapp/geek/baseinfo/query", SECRET)
    assert "userId=0" in strD
    assert calls[-1]["headers"]["t2"] == "T2TOKEN"


def test_detail_uses_secretkey_and_security_id():
    c, calls = _capture()
    c.job_detail("SEC123", lid="l.search")
    strD = _assert_signed_with(calls[-1], "/api/zpgeek/jobapp/geek/job/querydetail", SECRET)
    assert "securityId=SEC123" in strD


def test_chat_uses_secretkey():
    c, calls = _capture()
    c.add_friend("SEC9", job_id="777")
    strD = _assert_signed_with(calls[-1], "/api/zpgeek/app/friend/add", SECRET)
    assert "securityId=SEC9" in strD and "jobId=777" in strD


def test_cities_is_whitelisted_keynull():
    c, calls = _capture()
    c.cities()
    _assert_signed_with(calls[-1], "/api/zpCommon/config/city", None)


def test_secretkey_and_null_sigs_differ():
    # sanity: signing the same input with vs without the secretKey must differ
    a = yzwg.native_signature(b"/x?a=1", None)
    b = yzwg.native_signature(b"/x?a=1", SECRET)
    assert a != b


def test_parse_expects_shapes():
    resp = {"zpData": {"geekDetail": {"expectPositionList": [
        {"expectId": 100, "encryptExpectId": "enc100", "positionName": "后端", "salaryDesc": "20-40K"}]}}}
    ex = BossClient.parse_expects(resp)
    assert ex and ex[0]["expectId"] == 100 and ex[0]["encryptExpectId"] == "enc100"


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name); n += 1
    print(f"\n{n} tests passed")
