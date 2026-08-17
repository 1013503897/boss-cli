"""
BOSS直聘 request assembly (batch /api/batch/requests): builds strD / subReq queries,
computes sp / sig / encrypted body / strA exactly as net.bosszhipin.base.m does.

Reference (decompiled net.bosszhipin.base.m.f, the batch branch):
    strD  = sorted(outer params), values Java-URLEncoder'd, joined "k=v&"
    encBody = nativeEncodeRequestBody(bodyJson, key)      # raw encrypted bytes -> request body
    strA  = nativeCalculateCRC32(encBody)                 # "%u" decimal
    sp    = nativeEncodeRequest(strD, key)                # query param "sp"
    sig   = nativeSignature(f(url) + strD + strA, key)    # query param "sig" ; f(url)=path from /api/
    (+ app_id appended to query AFTER signing; batch endpoint key == None)
"""
from __future__ import annotations
import time
from . import yzwg

# Java URLEncoder.encode(s, "UTF-8") keeps only [A-Za-z0-9.-*_], space -> '+', else %XX (upper).
_KEEP = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-*_")


def java_url_encode(s: str) -> str:
    out = []
    for ch in s:
        if ch in _KEEP:
            out.append(ch)
        elif ch == ' ':
            out.append('+')
        else:
            for b in ch.encode('utf-8'):
                out.append('%%%02X' % b)
    return ''.join(out)


def build_query(params: dict) -> str:
    """sorted keys, Java-URLEncoder'd non-empty values, joined 'k=v&' (mirrors net...m.d)."""
    parts = []
    for k in sorted(params.keys()):
        v = params[k]
        v = '' if v is None else str(v)
        parts.append(k + '=' + (java_url_encode(v) if v != '' else ''))
    return '&'.join(parts)


def sign_batch(outer_params: dict, body_json: str, url_path: str = "/api/batch/requests",
               key: str | None = None) -> dict:
    """Return everything needed to send: query string, encrypted body, and the app_id-appended query."""
    strD = build_query(outer_params)
    encBody = yzwg.native_encode_request_body(body_json.encode('utf-8'), key)
    strA = yzwg.native_calculate_crc32(encBody)
    sp = yzwg.native_encode_request(strD.encode('utf-8'), key)
    sig = yzwg.native_signature((url_path + strD + strA).encode('utf-8'), key)
    return {"strD": strD, "encBody": encBody, "strA": strA, "sp": sp, "sig": sig}


def now_ms() -> str:
    return str(int(time.time() * 1000))
