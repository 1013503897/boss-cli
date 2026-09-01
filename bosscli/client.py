"""
BossClient — off-device BOSS直聘 API client (search + authenticated read endpoints).

A session (t2 auth token + this device's client_info/uniqid + cardlist template) is the
only account-bound input; extract it once from a logged-in device, or obtain t2 with the
login flow (bosscli.login). See session.example.json.

Signing has two branches, both reproduced in signer.py:
  * batch  (/api/batch/requests, subReqs) — used by search().
  * plain  (ordinary GET/POST)            — used by the login endpoints and the read endpoints.
Search + login sit on the app's no-secretKey whitelist, so their sign key is None; call_plain /
call_batch expose a `key` argument so endpoints that DO need the account secretKey can pass it.
"""
from __future__ import annotations
import json, os, time, uuid
import requests
from . import yzwg, signer

HOST = "https://api5.zhipin.com"
BATCH_PATH = "/api/batch/requests"
CARDLIST_PATH = "/api/zpgeek/app/geek/search/cardlist"


class AuthExpired(RuntimeError):
    """The server rejected t2 (code==7, 当前登录状态已失效). Re-login to refresh it."""
    def __init__(self, message: str = "登录状态已失效 (t2 过期)", resp: dict | None = None):
        super().__init__(message)
        self.resp = resp


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
        # 0) plaintext JSON — the server returns some errors uncompressed/unencrypted, e.g.
        #    {"code":7,"message":"当前登录状态已失效"} (t2 expired) on the batch endpoint. Try
        #    this first so an auth error surfaces its message instead of crashing the RC4 path.
        if raw.lstrip()[:1] in (b'{', b'['):
            try:
                return json.loads(raw)
            except Exception:
                pass
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

    @staticmethod
    def raise_for_auth(resp: dict) -> dict:
        """Turn a top-level code==7 into AuthExpired; pass anything else through."""
        if isinstance(resp, dict) and resp.get("code") == 7:
            raise AuthExpired(resp.get("message") or "登录状态已失效", resp)
        return resp

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

    def _wire(self, s: dict) -> str:
        """strD + signed sp/sig + app_id (appended AFTER signing), the on-the-wire param string."""
        return (s["strD"] + "&sp=" + requests.utils.quote(s["sp"], safe='')
                + "&sig=" + s["sig"] + "&app_id=" + self.s.get("app_id", "1003"))

    def _http(self, method: str, url: str, *, data=None, headers=None, retries: int = 2):
        """One HTTP call with a small retry/backoff on transport errors (not on 4xx/5xx bodies)."""
        last = None
        for attempt in range(retries + 1):
            try:
                r = self.http.request(method, url, data=data, headers=headers, timeout=20)
                r.raise_for_status()
                return r
            except (requests.ConnectionError, requests.Timeout) as e:
                last = e
                if attempt < retries:
                    time.sleep(0.6 * (attempt + 1))
                    continue
                raise
        raise last  # pragma: no cover

    # ---- generic signed calls (reused by search + the read endpoints) ----
    def call_plain(self, method: str, path: str, req_params: dict, key: str | None = None) -> dict:
        """Sign an ordinary GET/POST (net.bosszhipin.base.m.e branch) and return the decoded body."""
        params = {**self._outer_params(), **{k: v for k, v in req_params.items() if v not in (None, "")}}
        s = signer.sign_request(params, path, key)
        wire = self._wire(s)
        if method.upper() == "GET":
            r = self._http("GET", HOST + path + "?" + wire, headers=self._headers())
        else:
            h = self._headers(); h["Content-Type"] = "application/x-www-form-urlencoded"
            r = self._http("POST", HOST + path, data=wire, headers=h)
        return self.raise_for_auth(self._decode(r.content, key))

    def call_batch(self, subreqs: list[dict], key: str | None = None) -> dict:
        """Sign a /api/batch/requests call (net.bosszhipin.base.m.f branch); subreqs is a list of
        {method, path, query} (and optional body). Returns the decoded envelope."""
        body_obj = {"subReqs": subreqs}
        body_json = json.dumps(body_obj, separators=(',', ':'), ensure_ascii=False)
        outer = self._outer_params()
        s = signer.sign_batch(outer, body_json, BATCH_PATH, key=key)
        q = self._wire(s)
        r = self._http("GET", HOST + BATCH_PATH + "?" + q, data=s["encBody"], headers=self._headers())
        return self.raise_for_auth(self._decode(r.content, key=key))

    # ---- search ----
    def search(self, query: str, city: str | None = None, page: int = 1, sort: int = -1,
               filter_params: dict | None = None) -> dict:
        """One page of geek job search. `filter_params` merges into the cardlist filterParams
        (e.g. {"salary": "407", "experience": "104,105"}); server honours these keys."""
        cq = dict(self.s.get("cardlist_defaults", {}))
        cq["query"] = query
        cq["page"] = str(page)
        cq["sort"] = str(sort)
        fp = json.loads(cq.get("filterParams", '{}'))
        if city:
            fp["cityCode"] = str(city)
        if filter_params:
            for k, v in filter_params.items():
                fp[k] = v
        cq["filterParams"] = json.dumps(fp, separators=(',', ':'), ensure_ascii=False)
        subreq_query = signer.build_query(cq)
        return self.call_batch([{"method": "GET", "path": CARDLIST_PATH, "query": subreq_query}], key=None)

    @staticmethod
    def cardlist_data(resp: dict) -> dict:
        """The inner cardlist zpData (holds cardList, nlpFilters, labelFilter, sorts, searchLid …)."""
        card = resp.get("zpData", {}).get(CARDLIST_PATH, {})
        return card.get("zpData", {}) or {}

    @staticmethod
    def parse_jobs(resp: dict) -> list[dict]:
        zp = BossClient.cardlist_data(resp)
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
                "encryptJobId": j.get("encryptJobId"),
                "name": pn.get("name") if isinstance(pn, dict) else (pn or j.get("jobName")),
                "salary": j.get("salaryDesc"),
                "company": j.get("brandName") or j.get("company"),
                "city": j.get("cityName") or j.get("city"),
                "area": j.get("areaDistrict") or j.get("businessDistrict"),
                "experience": j.get("jobExperience"),
                "degree": j.get("jobDegree"),
                "labels": j.get("jobLabels") or j.get("skills"),
                "hr": (j.get("bossName") or j.get("name")),
                "hrTitle": j.get("bossTitle"),
                "securityId": j.get("securityId"),
                "lid": j.get("lid"),
            })
        return out
