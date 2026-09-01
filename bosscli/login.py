"""
Off-device BOSS直聘 login: reproduce the SMS-code login flow (com.hpbr.bosszhipin.login),
so `t2` can be obtained programmatically instead of hand-captured from a logged-in device.

Two endpoints, both plain (non-batch) requests signed by net.bosszhipin.base.m.e():
    GET  /api/zppassport/phone/smsCode   send an SMS verify code (phone is encodePassword'd)
    POST /api/zppassport/user/codeLogin  exchange phone+code -> UserCodeLoginResponse{t2,t,wt,...}

Both are on m.f43051a (the m.j whitelist) so no secretKey is applied -> sign key is None,
exactly like search. The only new native primitive vs search is encodePassword (yzwg.f),
used for the phone number: send-code `phone` and login `account`. All of this is validated
byte-exact against the device (com.twl.signer.a) — see scratchpad/validate_login_signing.py.

Device identity (client_info / uniqid / v / user_agent) is reused from the session file: it
is device-bound, not account-bound, so the same profile that searches can also log in.
"""
from __future__ import annotations
import json, uuid
import requests
from . import signer
from .client import BossClient

HOST = "https://api5.zhipin.com"
MAN_MACHINE_PATH = "/api/zppassport/man/machine"
SMS_PATH = "/api/zppassport/phone/smsCode"
IMGCODE_PATH = "/api/zppassport/phone/imgCode"
CODELOGIN_PATH = "/api/zppassport/user/codeLogin"

# GetVerifyCodeRequest.REQUEST_TYPE_* — "3" = login (see net.bosszhipin.api.GetVerifyCodeRequest)
TYPE_LOGIN = "3"
SEND_SMS, SEND_VOICE = "0", "1"

# PostManMachineValidationResponse.captchaType
CAPTCHA_GEETEST = (0, 1)   # Geetest GT3 (startCaptcha carries gt/challenge)
CAPTCHA_NETEASE = 4        # 网易易盾 (wyCaptchaId/wyCaptchaType)


class LoginError(RuntimeError):
    def __init__(self, code, message, resp=None):
        super().__init__(f"[{code}] {message}")
        self.code, self.message, self.resp = code, message, resp


class CaptchaRequired(RuntimeError):
    """Raised when man/machine returns isMachine=true: a behavior captcha (Geetest GT3 or
    网易易盾) must be solved before the SMS code can be sent. Off-device from a flagged
    IP/device this is essentially always demanded — see this module's docstring. Carries the
    challenge material so a caller with a solver (or a device) can produce the geetest tokens."""
    def __init__(self, mm: dict):
        ct = mm.get("captchaType")
        kind = "Geetest-GT3" if ct in CAPTCHA_GEETEST else ("网易易盾" if ct == CAPTCHA_NETEASE else f"captchaType={ct}")
        super().__init__(f"man/machine demands a {kind} captcha before send-code (isMachine=true)")
        self.captcha_type = ct
        self.start_captcha = mm.get("startCaptcha")   # Geetest: {"gt":...,"challenge":...}
        self.wy_captcha_id = mm.get("wyCaptchaId")
        self.wy_captcha_type = mm.get("wyCaptchaType")
        self.mm = mm


class LoginClient:
    """Drives send-code + code-login off-device. `device` is the session dict (needs
    client_info / uniqid; v / user_agent / app_id / curidentity are optional with defaults)."""

    def __init__(self, device: dict):
        self.d = device
        self.http = requests.Session()

    @classmethod
    def from_file(cls, path: str) -> "LoginClient":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    # ---- common params, mirroring net.bosszhipin.base.m.c() (minus the account-bound bits) ----
    def _common_params(self) -> dict:
        ci = self.d["client_info"]
        ci = ci if isinstance(ci, str) else json.dumps(ci, separators=(",", ":"), ensure_ascii=False)
        return {
            "client_info": ci,
            "curidentity": self.d.get("curidentity", "0"),
            "req_time": signer.now_ms(),
            "uniqid": self.d["uniqid"],
            "v": self.d.get("v", "14.050"),
        }

    def _headers(self) -> dict:
        # pre-login: no t2. zp-accept-* mirror the app so the server picks an encoding _decode knows.
        return {
            "User-Agent": self.d.get("user_agent", "NetType/wifi Screen/1080X2209 BossZhipin/14.050 Android 36"),
            "zp-accept-encoding": "1", "zp-accept-compressing": "3", "zp-accept-encrypting": "1",
            "traceId": "A-" + str(uuid.uuid4()),
        }

    def _send(self, method: str, path: str, req_params: dict) -> dict:
        """Sign (m.e branch, key=None) and send. app_id is appended AFTER signing; the signed
        param string is sent verbatim (query for GET, form body for POST) so the server re-signs
        over the exact same strD."""
        params = {**self._common_params(), **{k: v for k, v in req_params.items() if v not in (None, "")}}
        s = signer.sign_request(params, path, key=None)
        wire = (s["strD"]
                + "&sp=" + requests.utils.quote(s["sp"], safe="")
                + "&sig=" + s["sig"]
                + "&app_id=" + self.d.get("app_id", "1003"))
        if method == "GET":
            r = self.http.get(HOST + path + "?" + wire, headers=self._headers(), timeout=20)
        else:
            h = self._headers(); h["Content-Type"] = "application/x-www-form-urlencoded"
            r = self.http.post(HOST + path, data=wire, headers=h, timeout=20)
        r.raise_for_status()
        return BossClient._decode(r.content, key=None)

    # ---- step 0: man/machine risk check (net.bosszhipin.utils.z1.h) ----
    def man_machine(self, phone: str, type: str = TYPE_LOGIN) -> dict:
        """POST man/machine. Mandatory precondition the app always runs before send-code.
        Returns {isMachine, captchaType, startCaptcha, wyCaptchaId, wyCaptchaType, raw}.
        isMachine=true means a behavior captcha (Geetest/网易) is demanded; captchaType 0/1 is
        Geetest GT3 (startCaptcha carries gt/challenge), 4 is 网易易盾."""
        from . import yzwg
        resp = self._send("POST", MAN_MACHINE_PATH,
                          {"phone": yzwg.native_encode_password(phone), "type": type})
        if resp.get("code") not in (0, None):
            raise LoginError(resp.get("code"), resp.get("message", "man/machine failed"), resp)
        z = resp.get("zpData") or {}
        return {"isMachine": bool(z.get("isMachine")), "captchaType": z.get("captchaType"),
                "startCaptcha": z.get("startCaptcha"), "wyCaptchaId": z.get("wyCaptchaId"),
                "wyCaptchaType": z.get("wyCaptchaType"), "raw": resp}

    # ---- step 1: send SMS code ----
    def send_sms_code(self, phone: str, region: str = "+86", voice: str = SEND_SMS,
                      img_code: str | None = None, challenge: str | None = None,
                      validate: str | None = None, seccode: str | None = None,
                      precheck: bool = True) -> dict:
        """Send an SMS verify code. Runs the man/machine precheck first (mirrors the app); if it
        demands a captcha and no geetest tokens were supplied, raises CaptchaRequired. Pass a
        solved captcha via challenge+validate+seccode (Geetest) to get past it. code==0 == SMS
        dispatched. Set precheck=False to skip the man/machine call (e.g. when replaying a solve)."""
        from . import yzwg
        if precheck and not (validate or seccode):
            mm = self.man_machine(phone, TYPE_LOGIN)
            if mm["isMachine"]:
                raise CaptchaRequired(mm)
        params = {
            "phone": yzwg.native_encode_password(phone),
            "regionCode": region,
            "type": TYPE_LOGIN,
            "voice": voice,
            "imgCode": img_code,
            "challenge": challenge, "validate": validate, "seccode": seccode,
        }
        resp = self._send("GET", SMS_PATH, params)
        if resp.get("code") not in (0, None):
            raise LoginError(resp.get("code"), resp.get("message", "send code failed"), resp)
        return resp

    # ---- step 2: exchange code -> t2 ----
    def code_login(self, phone: str, code: str, region: str = "+86", identity_type: str = "0") -> dict:
        """POST codeLogin. identity_type: '0' geek, '1' boss. On success returns the token bundle
        (t2/t/wt/zpAt/secretKey/uid/register). Raises LoginError otherwise."""
        from . import yzwg
        params = {
            "regionCode": region,
            "account": yzwg.native_encode_password(phone),
            "phoneCode": code,
            "identityType": identity_type,
        }
        resp = self._send("POST", CODELOGIN_PATH, params)
        if resp.get("code") != 0:
            raise LoginError(resp.get("code"), resp.get("message", "login failed"), resp)
        data = resp.get("zpData", resp)
        return {
            "t2": data.get("t2"), "t": data.get("t"), "wt": data.get("wt"),
            "zpAt": data.get("zpAt"), "secretKey": data.get("secretKey"),
            "uid": data.get("uid"), "identity": data.get("identity"),
            "register": data.get("register"), "raw": resp,
        }


def update_session_token(session_path: str, tokens: dict) -> None:
    """Write the freshly-obtained t2 (and friends) back into a session json, preserving the
    device profile and cardlist template already there."""
    with open(session_path, encoding="utf-8") as f:
        sess = json.load(f)
    for k in ("t2", "t", "wt", "zpAt", "secretKey"):
        if tokens.get(k) is not None:
            sess[k] = tokens[k]
    if tokens.get("uid") is not None:
        sess["uid"] = tokens["uid"]
    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(sess, f, ensure_ascii=False, indent=2)
