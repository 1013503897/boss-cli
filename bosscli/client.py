"""
BossClient — off-device BOSS直聘 search over /api/batch/requests.

A session (t2 auth token + this device's client_info/uniqid + cardlist template) is the
only account-bound input; extract it once from a logged-in device. See session.example.json.
"""
from __future__ import annotations
import json, os, uuid
import requests
from . import yzwg, signer

HOST = "https://api5.zhipin.com"
BATCH_PATH = "/api/batch/requests"
CARDLIST_PATH = "/api/zpgeek/app/geek/search/cardlist"


class BossClient:
    def __init__(self, session: dict):
        self.s = session
        self.http = requests.Session()

    @classmethod
    def from_file(cls, path: str) -> "BossClient":
        with open(path, encoding='utf-8') as f:
            return cls(json.load(f))

    # ---- response decode: server picks encoding via zp-* headers ----
    @staticmethod
    def _decode(raw: bytes, key: str | None):
        # A) base64url(RC4(json|frame))  B) raw RC4(frame(LZ4(json)))  C) raw RC4(json)
        try:
            dec = yzwg.rc4(yzwg._rc4_key(key), yzwg._unb64(raw.decode('ascii')))
            if dec[:8] == yzwg.MAGIC:
                dec = yzwg._deframe(dec)
            return json.loads(dec)
        except Exception:
            pass
        dec = yzwg.rc4(yzwg._rc4_key(key), raw)
        if dec[:8] == yzwg.MAGIC:
            return json.loads(yzwg._deframe(dec))
        return json.loads(dec)

    def _headers(self) -> dict:
        return {
            "User-Agent": self.s.get("user_agent", "NetType/wifi Screen/1080X2209 BossZhipin/14.050 Android 36"),
            "zp-accept-encoding": "1", "zp-accept-compressing": "3", "zp-accept-encrypting": "1",
            "t2": self.s["t2"], "traceId": "A-" + str(uuid.uuid4()),
        }

    def _outer_params(self) -> dict:
        ci = self.s["client_info"]
        ci = ci if isinstance(ci, str) else json.dumps(ci, separators=(',', ':'), ensure_ascii=False)
        return {
            "client_info": ci,
            "curidentity": self.s.get("curidentity", "0"),
            "req_time": signer.now_ms(),
            "uniqid": self.s["uniqid"],
            "v": self.s.get("v", "14.050"),
        }

    def search(self, query: str, city: str | None = None, page: int = 1, sort: int = -1) -> dict:
        # cardlist subReq params from template, with query/page/sort/city overridden
        cq = dict(self.s.get("cardlist_defaults", {}))
        cq["query"] = query
        cq["page"] = str(page)
        cq["sort"] = str(sort)
        if city:
            fp = json.loads(cq.get("filterParams", '{}'))
            fp["cityCode"] = str(city)
            cq["filterParams"] = json.dumps(fp, separators=(',', ':'), ensure_ascii=False)
        subreq_query = signer.build_query(cq)
        body_obj = {"subReqs": [{"method": "GET", "path": CARDLIST_PATH, "query": subreq_query}]}
        body_json = json.dumps(body_obj, separators=(',', ':'), ensure_ascii=False)

        outer = self._outer_params()
        s = signer.sign_batch(outer, body_json, BATCH_PATH, key=None)
        q = (s["strD"] + "&sp=" + requests.utils.quote(s["sp"], safe='')
             + "&sig=" + s["sig"] + "&app_id=" + self.s.get("app_id", "1003"))
        r = self.http.request("GET", HOST + BATCH_PATH + "?" + q, data=s["encBody"],
                              headers=self._headers(), timeout=20)
        r.raise_for_status()
        return self._decode(r.content, key=None)

    @staticmethod
    def parse_jobs(resp: dict) -> list[dict]:
        card = resp.get("zpData", {}).get(CARDLIST_PATH, {})
        zp = card.get("zpData", {}) or {}
        jobs = []
        for cl in zp.get("cardList", []) or []:
            jobs += cl.get("positionSearchCardList", []) or []
        if not jobs and isinstance(zp.get("jobList"), list):
            jobs = zp["jobList"]
        out = []
        for j in jobs:
            pn = j.get("positionName")
            out.append({
                "jobId": j.get("jobId") or j.get("encryptJobId"),
                "name": pn.get("name") if isinstance(pn, dict) else (pn or j.get("jobName")),
                "salary": j.get("salaryDesc"),
                "company": j.get("brandName") or j.get("company"),
                "city": j.get("cityName") or j.get("city"),
                "labels": j.get("jobLabels") or j.get("skills"),
                "hr": (j.get("bossName") or j.get("name")),
                "securityId": j.get("securityId"),
            })
        return out
