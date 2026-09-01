"""
超级鹰 (chaojiying) coordinate-captcha client — submit an image, get back click coordinates.

Used for the Geetest 九宫格点选 (icon/word click) branch of BOSS's login man/machine (captchaType
0/1 that escalates to a 3x3 click challenge instead of a slide — see browser_harvest.solve_click).
The platform does ONLY the image→coordinate recognition; the Geetest session stays in our own
zhipin.com-origin browser, which is what makes the harvested validate acceptable to BOSS.

Credentials come from the environment (never commit them):
    CHAOJIYING_USER    account username
    CHAOJIYING_PASS    account password (sent as pass2 = md5(pass))
    CHAOJIYING_SOFTID  软件ID from the 超级鹰 user center (optional but recommended)

API (verified 2026-09-01, http://www.chaojiying.com/api-5.html):
    POST https://upload.chaojiying.net/Upload/Processing.php
        user, pass2=md5(pass), softid, codetype, file_base64=b64(image)
        codetype: 9004 = 1~4 点 / 9005 = 1~5 / 9008 = 1~8 (返回坐标)
      -> {"err_no":0, "err_str":"OK", "pic_id":..., "pic_str":"x1,y1|x2,y2|...", "md5":...}
    POST https://upload.chaojiying.net/Upload/ReportError.php
        user, pass2, softid, id=pic_id   -> 报错退题分 (3 分钟内有效)
"""
from __future__ import annotations
import os, base64, hashlib
import requests

UPLOAD_URL = "https://upload.chaojiying.net/Upload/Processing.php"
REPORT_URL = "https://upload.chaojiying.net/Upload/ReportError.php"
_HEADERS = {"Connection": "Keep-Alive", "User-Agent": "Mozilla/5.0"}


class ChaojiyingError(RuntimeError):
    pass


def _parse_coords(pic_str: str) -> list[tuple[int, int]]:
    """'x1,y1|x2,y2' -> [(x1,y1),(x2,y2)] (order preserved = click order). Tolerant of spaces."""
    out = []
    for part in (pic_str or "").replace(" ", "").split("|"):
        if not part:
            continue
        xy = part.split(",")
        if len(xy) == 2 and xy[0].lstrip("-").isdigit() and xy[1].lstrip("-").isdigit():
            out.append((int(xy[0]), int(xy[1])))
    return out


class Chaojiying:
    def __init__(self, user: str | None = None, password: str | None = None, softid: str | None = None):
        self.user = user or os.environ.get("CHAOJIYING_USER")
        pw = password or os.environ.get("CHAOJIYING_PASS")
        self.softid = softid or os.environ.get("CHAOJIYING_SOFTID", "")
        if not (self.user and pw):
            raise ChaojiyingError("缺少凭据：设置环境变量 CHAOJIYING_USER / CHAOJIYING_PASS "
                                  "(+ 可选 CHAOJIYING_SOFTID)")
        self.pass2 = hashlib.md5(pw.encode("utf-8")).hexdigest()
        self.http = requests.Session()

    def solve(self, image_bytes: bytes, codetype: str = "9004") -> dict:
        """Recognize a click captcha. Returns {pic_id, coords:[(x,y),...], raw}; coords are pixels
        within the submitted image (top-left origin)."""
        data = {"user": self.user, "pass2": self.pass2, "softid": self.softid,
                "codetype": codetype, "file_base64": base64.b64encode(image_bytes).decode()}
        r = self.http.post(UPLOAD_URL, data=data, headers=_HEADERS, timeout=30)
        r.raise_for_status()
        j = r.json()
        if j.get("err_no") != 0:
            raise ChaojiyingError(f"chaojiying err_no={j.get('err_no')} {j.get('err_str')}")
        return {"pic_id": j.get("pic_id"), "coords": _parse_coords(j.get("pic_str", "")), "raw": j}

    def report_error(self, pic_id: str) -> None:
        """Report a wrong solve to refund the 题分 (best-effort)."""
        if not pic_id:
            return
        try:
            self.http.post(REPORT_URL, headers=_HEADERS, timeout=15,
                           data={"user": self.user, "pass2": self.pass2, "softid": self.softid, "id": pic_id})
        except Exception:
            pass
