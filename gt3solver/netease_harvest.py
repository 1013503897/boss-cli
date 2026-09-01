"""
Real-browser stealth harvester for BOSS直聘's login 网易易盾 (NetEase Yidun / NECaptcha) slide
captcha — the captchaType==4 branch of man/machine (net.bosszhipin.utils.z1.j → NECaptcha SDK).

This is the 网易 counterpart of browser_harvest.py (which handles the Geetest captchaType 0/1
branch). man/machine returns {wyCaptchaId, wyCaptchaType}; the app inits com.netease.nis.captcha
with captchaId=wyCaptchaId and, on solve, its onValidate(result, validate, msg) callback pushes
ONLY `validate` into the send-code request (see z1$c and AbsAuthCodeActivity.xf: r.validate =
validate, challenge/seccode left null). So all we must produce off-device is that single `validate`
string, then feed it to bosscli send_sms_code(validate=..., precheck=False).

Pipeline:
  man/machine (BOSS app)  -> wyCaptchaId (+ wyCaptchaType: 0 slider / 1 intelligent)
  drive real Chrome inside https://www.zhipin.com origin (mirror the app's referer/domain)
  load https://cstaticdun.126.net/load.min.js -> initNECaptcha({captchaId, mode:'embed'}) -> verify()
  detect the gap on the served bg image, closed-loop drag the knob until the jigsaw aligns
  -> onVerify(err,{validate}) -> harvest validate
  (optional) feed validate into bosscli send_sms_code to prove BOSS accepts it.

Ground-truth DOM (captured 2026-09-01, captchaId ae17e488…, wyCaptchaType=0 = MODE_CAPTCHA slide):
  .yidun_bg-img   IMG  bg puzzle,  natural==display (ratio 1.000, drag px == image px)
  .yidun_jigsaw   IMG  the piece,  rests at bg-left (jigsaw.left == bg.left)
  .yidun_slider   DIV  the draggable knob      .yidun_refresh  new-image button (free)
Images are plain necaptcha.nosdn.127.net URLs (bg is NOT column-scrambled, unlike Geetest) so a
straight Canny template-match on the downloaded bg finds the gap. The knob→piece movement ratio is
sidestepped entirely: we read the live .yidun_jigsaw left via getBoundingClientRect while dragging
and stop when the piece reaches the detected gap.

USAGE CONSTRAINTS (same spirit as browser_harvest.py):
  * Run inside the real zhipin.com origin (the widget is injected there; a file:// harness can trip
    domain checks / risk). * LOW FREQUENCY — solve once, cache the resulting t2, re-login on expiry;
    tight retry loops degrade the source IP. A clean/residential CN IP helps. * validate is single-use
    and short-lived (minutes) — feed it to send_sms_code immediately.

Requires: patchright (`pip install patchright` + a Chrome install), opencv-python, numpy, requests.
"""
from __future__ import annotations
import os, sys, json, time, argparse
import numpy as np
import cv2
import requests

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

LOAD_JS = "https://cstaticdun.126.net/load.min.js"

# main-world bootstrap injected into the live zhipin.com page. Signals back through the shared DOM
# (documentElement[data-nd] + #ndout) because patchright's evaluate runs in an isolated world and
# cannot read main-world globals. embed mode renders the slider inline in #ndbox.
INJECT_TMPL = r"""(function(){
  try{
    var ta=document.createElement('textarea'); ta.id='ndout';
    ta.style.position='absolute'; ta.style.left='-9999px'; document.body.appendChild(ta);
    var box=document.createElement('div'); box.id='ndbox';
    box.style.position='fixed'; box.style.left='40px'; box.style.top='80px'; box.style.zIndex=999999;
    box.style.width='320px'; document.body.appendChild(box);
    function setState(s){document.documentElement.setAttribute('data-nd',s);}
    function setOut(v){try{document.getElementById('ndout').value=JSON.stringify(v);}catch(e){}}
    setState('boot');
    var s=document.createElement('script'); s.src=__LOAD__;
    s.onload=function(){
      if(typeof initNECaptcha!=='function'){setState('no-init');return;}
      initNECaptcha({
        captchaId: __CID__, element: '#ndbox', mode: 'embed', width: '320px',
        onVerify: function(err, data){ if(err){setOut({err:''+err}); setState('verify-err'); return;}
                                       setOut(data); setState('success'); }
      }, function(instance){ window.__nd=instance; setState('ready'); try{instance.verify();}catch(e){} },
         function(err){ setOut({onerror:''+err}); setState('init-err'); });
    };
    s.onerror=function(){setState('loadjs-fail');};
    document.body.appendChild(s);
  }catch(e){document.documentElement.setAttribute('data-nd','inject-err:'+e);}
})();"""

OFFSETS = [0, 2, -2, 3, -3]   # target micro-sweep across retries (notch shadow / anti-alias)


# ----------------------------------------------------------------------------- DOM channel helpers
def st(page):
    return page.evaluate("() => document.documentElement.getAttribute('data-nd')")


def out(page):
    return page.evaluate("() => (document.getElementById('ndout')||{}).value")


def rect(page, sel):
    return page.evaluate("""(sel)=>{const e=document.querySelector(sel); if(!e)return null;
        const r=e.getBoundingClientRect();
        return {x:r.x, y:r.y, w:r.width, h:r.height, nw:e.naturalWidth||null, src:e.src||null};}""", sel)


# --------------------------------------------------------------------------------- gap detection
def _decode(b):
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_UNCHANGED)


def gap_distance(bg_png, piece_png):
    """Piece displacement (bg-image px) to align the jigsaw with the gap. bg is NOT scrambled, so a
    Canny template-match of the piece's opaque bbox against the bg locates the notch directly.
    Returns (distance, gap_left, piece_left)."""
    pc = _decode(piece_png)
    if pc.ndim == 3 and pc.shape[2] == 4:
        ys, xs = np.where(pc[:, :, 3] > 40)                     # opaque piece bbox from alpha
    else:
        ys, xs = np.where(cv2.cvtColor(pc, cv2.COLOR_BGR2GRAY) > 18)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    tmpl = pc[y0:y1 + 1, x0:x1 + 1, :3]
    bg = _decode(bg_png)[:, :, :3]
    res = cv2.matchTemplate(cv2.Canny(bg, 100, 200), cv2.Canny(tmpl, 100, 200), cv2.TM_CCOEFF_NORMED)
    _, _, _, loc = cv2.minMaxLoc(res)
    gap_left = int(loc[0])
    return gap_left - x0, gap_left, x0


def _download(url):
    return requests.get(url, timeout=15).content


# ------------------------------------------------------------------------------ human interaction
def _track(distance, steps=None):
    """Ease-out human-ish x deltas summing to `distance` (px)."""
    steps = steps or max(18, int(distance / 4))
    xs, cur = [], 0.0
    for i in range(steps):
        p = (i + 1) / steps
        e = 1 - (1 - p) ** 3                                    # cubic ease-out
        nx = distance * e
        xs.append(nx - cur); cur = nx
    return xs


def human_wander(page, n=8):
    for _ in range(n):
        page.mouse.move(300 + np.random.randint(-120, 120), 300 + np.random.randint(-90, 90), steps=3)
        page.wait_for_timeout(int(30 + 50 * np.random.rand()))


def refresh_puzzle(page):
    for sel in (".yidun_refresh", ".yidun_tips__answer", ".yidun_control .yidun_refresh"):
        b = page.query_selector(sel)
        if b and b.is_visible():
            try:
                b.click(timeout=1500); page.wait_for_timeout(600); return True
            except Exception:
                pass
    return False


def closed_loop_drag(page, target_bias=0):
    """mousedown the knob, step it right while reading the live .yidun_jigsaw left, release when the
    piece content reaches the detected gap. Sidesteps the knob→piece ratio. One drag == one submit."""
    bg = rect(page, ".yidun_bg-img")
    g = gap_distance(_download(rect(page, ".yidun_bg-img")["src"]),
                     _download(rect(page, ".yidun_jigsaw")["src"]))
    if not (bg and g):
        return None
    dist, gap_left, piece_left = g
    # piece content sits at (jigsaw.left + piece_left); we want it at (bg.left + gap_left)
    target_jig_left = bg["x"] + gap_left - piece_left + target_bias
    knob = page.query_selector(".yidun_slider")
    kb = knob.bounding_box()
    kx, ky = kb["x"] + kb["width"] / 2, kb["y"] + kb["height"] / 2
    page.mouse.move(kx, ky, steps=4)
    page.wait_for_timeout(int(90 + 70 * np.random.rand()))
    page.mouse.down()
    page.wait_for_timeout(int(80 + 50 * np.random.rand()))
    cur = kx
    # coarse: follow the ease-out track (knob px), correcting against the live jigsaw position
    for dx in _track(dist):
        cur += dx
        page.mouse.move(cur, ky + np.random.uniform(-1.2, 1.2), steps=1)
        time.sleep(0.008 + 0.006 * np.random.rand())
        jl = rect(page, ".yidun_jigsaw")["x"]
        if jl >= target_jig_left - 0.5:
            break
    # fine: nudge until the piece sits on the gap (knob and piece move together monotonically)
    for _ in range(40):
        jl = rect(page, ".yidun_jigsaw")["x"]
        err = target_jig_left - jl
        if abs(err) <= 0.6:
            break
        cur += max(-3, min(3, err))
        page.mouse.move(cur, ky + np.random.uniform(-0.8, 0.8), steps=1)
        time.sleep(0.01)
    page.wait_for_timeout(int(60 + 60 * np.random.rand()))
    page.mouse.up()
    return {"dist": dist, "gap_left": gap_left, "piece_left": piece_left, "target": target_jig_left}


def solve_slide(page, max_tries=5):
    for t in range(max_tries):
        page.wait_for_timeout(500)
        s = st(page)
        if s in ("success", "verify-err"):
            return s
        if not page.query_selector(".yidun_slider"):
            page.wait_for_timeout(500); continue
        info = closed_loop_drag(page, target_bias=OFFSETS[t % len(OFFSETS)])
        print(f"    try{t}: {info}")
        for _ in range(16):
            page.wait_for_timeout(220)
            if st(page) in ("success", "verify-err"):
                break
        s = st(page)
        if s == "success":
            return s
        print(f"    try{t}: not solved (state={s}) -> refresh")
        refresh_puzzle(page)
    return st(page)


# ------------------------------------------------------------------------------------ the harvest
def harvest(session_path, phone="15969236932", attempts=3, headless=False, send_phone=None):
    """Harvest a 网易易盾 validate for BOSS's man/machine gate. Returns {validate, ...} (the NECaptcha
    onVerify payload), plus _boss_sendcode if send_phone is given. `phone` drives the man/machine risk
    probe (to fetch wyCaptchaId); `send_phone`, if set, additionally feeds the harvested validate into
    bosscli send_sms_code (sends a real SMS to that number). Run LOW-FREQUENCY from a clean CN IP."""
    from bosscli.login import LoginClient
    from patchright.sync_api import sync_playwright

    lc = LoginClient.from_file(session_path)
    probe_phone = send_phone or phone
    got = None
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=headless)
        ctx = br.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
        page = ctx.new_page()

        for i in range(1, attempts + 1):
            print(f"[{i}] navigating to real https://www.zhipin.com ...")
            page.goto("https://www.zhipin.com/", wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(1500)
            mm = lc.man_machine(probe_phone)
            if not mm["isMachine"]:
                print(f"[{i}] isMachine=FALSE — no captcha demanded"); got = {"no_captcha": True}; break
            z = mm["raw"]["zpData"]
            if mm["captchaType"] != 4:
                print(f"[{i}] captchaType={mm['captchaType']} is NOT 网易易盾 (use browser_harvest.py "
                      f"for Geetest 0/1)"); break
            cid = z["wyCaptchaId"]
            print(f"[{i}] origin={page.evaluate('() => location.origin')} wyCaptchaId={cid} "
                  f"wyType={z.get('wyCaptchaType')}")
            code = INJECT_TMPL.replace("__LOAD__", json.dumps(LOAD_JS)).replace("__CID__", json.dumps(cid))
            page.evaluate("(c)=>{var s=document.createElement('script'); s.textContent=c; "
                          "document.documentElement.appendChild(s);}", code)

            for _ in range(30):
                page.wait_for_timeout(400)
                s = st(page)
                if s and s not in ("boot",):
                    if s in ("ready", "success", "verify-err", "init-err", "no-init", "loadjs-fail") \
                            or s.startswith("inject-err"):
                        break
            s = st(page)
            if s and s.startswith(("inject-err", "no-init", "loadjs-fail", "init-err")):
                print(f"    injection/init problem: {s}"); break
            human_wander(page, 6)

            final = solve_slide(page)
            if final == "success":
                got = json.loads(out(page) or "null")
                print(f"    *** SUCCESS *** validate={ (got or {}).get('validate') }")
                if send_phone and got and got.get("validate"):
                    try:
                        r = lc.send_sms_code(send_phone, region="+86", validate=got["validate"],
                                             precheck=False)
                        print(f"    >>> BOSS send_sms_code: code={r.get('code')} message={r.get('message')}")
                        got["_boss_sendcode"] = {"code": r.get("code"), "message": r.get("message")}
                    except Exception as e:
                        print(f"    >>> BOSS send_sms_code response: {e}")
                        got["_boss_sendcode_err"] = str(e)
                break
            print(f"    verdict={final} out={(out(page) or '')[:140]}")
            page.wait_for_timeout(600)

        page.wait_for_timeout(600)
        ctx.close(); br.close()

    print("\n==== RESULT ====")
    print(json.dumps(got, ensure_ascii=False, indent=2) if got else "no validate harvested")
    return got


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Harvest a BOSS直聘 login 网易易盾 validate via a real "
                                             "stealth browser (run low-frequency, from a clean CN IP).")
    ap.add_argument("--session", default=os.path.join(_REPO_ROOT, "session.local.json"),
                    help="session json with the device profile (default: ../session.local.json)")
    ap.add_argument("--phone", default="15969236932", help="man/machine risk-probe phone (no SMS)")
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--headless", action="store_true", help="(detectable; prefer headful for real solves)")
    ap.add_argument("--send", metavar="PHONE", default=None,
                    help="also feed the harvested validate into BOSS send_sms_code for this phone "
                         "(proves server acceptance; sends a real SMS)")
    a = ap.parse_args()
    harvest(a.session, phone=a.phone, attempts=a.attempts, headless=a.headless, send_phone=a.send)
