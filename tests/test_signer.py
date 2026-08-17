"""Request-assembly tests: Java-URLEncoder reproduction, batch signing round-trip, response codec."""
import os, sys, json, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bosscli import signer, yzwg

OD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "oracle")
CAP = json.load(open(os.path.join(OD, "search_capture.json"), encoding='utf-8'))


def _decode_params(qs):
    d = {}
    for kv in qs.split('&'):
        k, _, v = kv.partition('=')
        d[k] = urllib.parse.unquote_plus(v)
    return d


def test_build_query_matches_outer_strD():
    outer = _decode_params(CAP['strD'])
    assert signer.build_query(outer) == CAP['strD']


def test_build_query_matches_cardlist_subquery():
    body = json.loads(CAP['body'])
    card = next(s for s in body['subReqs'] if 'cardlist' in s['path'])
    assert signer.build_query(_decode_params(card['query'])) == card['query']


def test_sign_batch_roundtrips():
    outer = _decode_params(CAP['strD'])
    r = signer.sign_batch(outer, CAP['body'], "/api/batch/requests", key=None)
    # sp must decrypt back to strD
    assert yzwg.native_decode_content(r['sp'], None) == r['strD'].encode('utf-8')
    # strA is decimal crc of the encrypted body
    assert r['strA'] == yzwg.native_calculate_crc32(r['encBody'])
    # sig shape
    assert r['sig'].startswith("V3.0") and len(r['sig']) == 36


def test_response_codec_roundtrip():
    # server response B path: base64url is not used here; frame+RC4 like the body
    payload = json.dumps({"code": 0, "message": "Success"}).encode()
    blob = yzwg.native_encode_request_body(payload, None)     # RC4(frame(LZ4(payload)))
    back = yzwg.native_decode_content(blob, None)
    assert json.loads(back)["message"] == "Success"


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ok  {name}"); n += 1
    print(f"all {n} tests passed")
