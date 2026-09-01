"""
CapSolver token-mode client for BOSS's login Geetest (captchaType 0/1).

Unlike the browser harvester (drive a real Chrome, detect the gap / click the 九宫格 via 超级鹰),
CapSolver solves the WHOLE Geetest v3 challenge server-side — slide, icon-click (九宫格), gobang,
icon-crush are all marked stable — and returns the {challenge, validate, seccode} token directly.
So there is NO browser, opencv, coordinate mapping or clicking: we just hand it the gt+challenge
that BOSS's man/machine already gave us, and feed the returned validate into send_sms_code.

API (https://docs.capsolver.com):
    POST https://api.capsolver.com/createTask
        {"clientKey": KEY, "task": {"type": "GeetestTaskProxyless",
          "websiteURL": "https://www.zhipin.com", "gt": GT, "challenge": CH,
          "geetestApiServerSubdomain": "api.geetest.com"}}
      -> {"errorId":0, "taskId": "..."}
    POST https://api.capsolver.com/getTaskResult   {"clientKey": KEY, "taskId": TID}
      -> {"status":"processing"} ... {"status":"ready",
          "solution": {"challenge":..., "validate":..., "seccode":..., "userAgent":...}}
    (solve typically 3-10s)

Key from the environment (never commit it): CAPSOLVER_KEY.
"""
from __future__ import annotations
import os, time
import requests

BASE = "https://api.capsolver.com"


class CapSolverError(RuntimeError):
    pass


class CapSolver:
    def __init__(self, key: str | None = None, website_url: str = "https://www.zhipin.com",
                 api_subdomain: str = "api.geetest.com"):
        self.key = key or os.environ.get("CAPSOLVER_KEY")
        if not self.key:
            raise CapSolverError("缺少凭据：设置环境变量 CAPSOLVER_KEY")
        self.website_url = website_url
        self.api_subdomain = api_subdomain
        self.http = requests.Session()

    def _post(self, path: str, payload: dict) -> dict:
        # CapSolver returns its structured {errorId,errorCode,errorDescription} even on HTTP 4xx,
        # so parse the JSON body first and surface errorCode rather than a bare HTTPError.
        r = self.http.post(f"{BASE}/{path}", json=payload, timeout=30)
        try:
            j = r.json()
        except ValueError:
            r.raise_for_status()
            raise CapSolverError(f"{path}: 非 JSON 响应 (HTTP {r.status_code})")
        if j.get("errorId"):
            raise CapSolverError(f"{path}: {j.get('errorCode')} {j.get('errorDescription')}")
        return j

    def solve_geetest_v3(self, gt: str, challenge: str, poll: float = 2.0, timeout: float = 150) -> dict:
        """Solve a Geetest v3 challenge (slide / 九宫格点选 / gobang / icon-crush). Returns
        {challenge, validate, seccode, raw}. Raises CapSolverError on failure/timeout."""
        task = {"type": "GeetestTaskProxyless", "websiteURL": self.website_url,
                "gt": gt, "challenge": challenge, "geetestApiServerSubdomain": self.api_subdomain}
        tid = self._post("createTask", {"clientKey": self.key, "task": task}).get("taskId")
        if not tid:
            raise CapSolverError("createTask 未返回 taskId")
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(poll)
            g = self._post("getTaskResult", {"clientKey": self.key, "taskId": tid})
            if g.get("status") == "ready":
                sol = g.get("solution", {}) or {}
                return {"challenge": sol.get("challenge"), "validate": sol.get("validate"),
                        "seccode": sol.get("seccode"), "raw": sol}
        raise CapSolverError(f"getTaskResult 超时 ({timeout}s)")

    def balance(self) -> float:
        """Account balance in USD (getBalance)."""
        return float(self._post("getBalance", {"clientKey": self.key}).get("balance", 0.0))
