"""
Real-browser stealth harvester for BOSS直聘's login Geetest v3 (the man/machine captcha).

This is the *practical* path to a `validate` (the pure-Python `w` in geetest_slide.py is fully
reversed and byte-exact, but Geetest server-forbids an offline submit — see README). Here a
stealthed real Chrome (patchright) actually solves the slide and we harvest the token.

Pipeline:
  man/machine (BOSS app)  -> gt + challenge
  drive real Chrome, **inside the real https://www.zhipin.com origin** (critical, see below)
  inject Geetest with that gt/challenge -> radar click -> slide escalation
  detect the gap on the JS-rendered canvases -> human drag the real knob -> onSuccess -> validate
  (optional) feed validate straight into bosscli send_sms_code to prove BOSS accepts it.

════════════════════════════════════════════════════════════════════════════════════════════════
USAGE CONSTRAINTS — read before running (learned empirically, 2026-08-19):

1. MUST run inside the real zhipin.com origin. BOSS's gt has a domain whitelist; a 127.0.0.1 /
   file:// harness ALWAYS gets `error_113 服务端forbidden` (Origin not whitelisted). We navigate
   to https://www.zhipin.com and inject the widget there so Origin/Referer/domain all match.

2. LOW FREQUENCY only. `error_113` is *also* an IP rate/reputation response: a fresh, low-volume
   attempt from the zhipin origin passes and harvests a validate; hammering ajax.php (dozens of
   rapid solves) degrades the source IP's reputation and re-triggers error_113 regardless of a
   perfect solve. Real use (log in once, cache t2, re-login on expiry) is low-frequency = the
   regime that works. Do NOT loop this in tight retries. A clean/residential CN IP helps.

3. patchright runs page.evaluate() in an ISOLATED world → it cannot read main-world window
   globals. All state is signalled through the shared DOM (documentElement[data-gt] + #gtout).
   Canvas pixels are read via toDataURL (per-canvas, with alpha) — element.screenshot() would
   composite the stacked bg/slice canvases and is useless here.

4. knob px == piece px (movement ratio measured at 1.000). Gap detection is bg-vs-fullbg column
   diff (contiguous run ~piece-width wide, right of the resting piece), Canny template fallback.
════════════════════════════════════════════════════════════════════════════════════════════════

Requires: patchright (`pip install patchright` + a Chrome install), opencv-python, numpy.
"""
from __future__ import annotations
import os, sys, json, time, base64, argparse
import numpy as np
import cv2

try:
    from . import geetest_slide           # make_track (human trajectory shape)
except ImportError:
    import geetest_slide
try:
    from .chaojiying import Chaojiying, ChaojiyingError   # 九宫格点选 coordinate solver
except ImportError:
    from chaojiying import Chaojiying, ChaojiyingError

# make `bosscli` importable when run standalone from the repo (gt3solver/ is under boss-cli/)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

GT_JS = "https://static.geetest.com/static/tools/gt.js"

# main-world bootstrap injected into the live zhipin.com page (runs in the page origin). Signals
# back through the shared DOM because patchright's evaluate can't see main-world globals.
INJECT_TMPL = """(function(){
  try{
  var ta=document.createElement('textarea'); ta.id='gtout';
  ta.style.position='absolute'; ta.style.left='-9999px'; ta.style.top='0'; document.body.appendChild(ta);
  var box=document.createElement('div'); box.id='gtbox';
  box.style.position='fixed'; box.style.left='40px'; box.style.top='80px'; box.style.zIndex=999999;
  document.body.appendChild(box);
  function setState(s){document.documentElement.setAttribute('data-gt',s);}
  function setOut(v){try{document.getElementById('gtout').value=JSON.stringify(v);}catch(e){}}
  setState('boot');
  var s=document.createElement('script'); s.src=__GTJS__;
  s.onload=function(){
    if(typeof initGeetest!=='function'){setState('no-init');return;}
    initGeetest({gt:__GT__,challenge:__CH__,offline:false,new_captcha:true,product:'popup',
      width:'300px',https:true,lang:'zh-cn'}, function(cap){
      window.__cap=cap; setState('init'); cap.appendTo('#gtbox');
      cap.onReady(function(){setState('ready'); try{cap.verify();}catch(e){}});
      cap.onSuccess(function(){setOut(cap.getValidate()); setState('success');});
      cap.onError(function(e){setOut(e); setState('error');});
      cap.onClose(function(){setState('closed');});
    });
  };
  s.onerror=function(){setState('gtjs-fail');};
  document.body.appendChild(s);
  }catch(e){document.documentElement.setAttribute('data-gt','inject-err:'+e);}
})();"""

OFFSETS = [0, 2, -2, 4, -4]   # target-x micro-sweep across retries (gap-notch shadow / anti-alias)


# ----------------------------------------------------------------------------- DOM channel helpers
def st(page):
    return page.evaluate("() => document.documentElement.getAttribute('data-gt')")


def out(page):
    return page.evaluate("() => (document.getElementById('gtout')||{}).value")


def canvas_png(page, sel):
    """Read a canvas's true backing store via toDataURL (per-canvas pixels WITH alpha)."""
    d = page.evaluate("""(sel)=>{const c=document.querySelector(sel);
        if(!c||!c.getContext)return null; try{return c.toDataURL('image/png');}catch(e){return 'ERR:'+e;}}""", sel)
    if not d or not d.startswith("data:"):
        return None
    return base64.b64decode(d.split(",", 1)[1])


# --------------------------------------------------------------------------------- gap detection
def _decode(b):
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_UNCHANGED)


def gap_distance(bg_png, slice_png, fullbg_png=None):
    """Distance (canvas px == css px) to drag the piece. piece rest-left from the slice alpha;
    gap-left from the bg-vs-fullbg column diff (contiguous run ≈ piece-width, right of the piece),
    with a Canny template-match fallback. Returns (distance, gap_left, piece_left, method)."""
    sl = _decode(slice_png)
    ys, xs = np.where(sl[:, :, 3] > 40) if (sl.ndim == 3 and sl.shape[2] == 4) \
        else np.where(cv2.cvtColor(sl, cv2.COLOR_BGR2GRAY) > 18)
    if len(xs) == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max())
    piece_w = x1 - x0 + 1
    bg = _decode(bg_png)[:, :, :3]
    if fullbg_png is not None:
        full = _decode(fullbg_png)[:, :, :3]
        prof = np.abs(bg.astype(int) - full.astype(int)).sum(2).mean(0)
        mask = prof > prof.max() * 0.30
        runs, i, n = [], 0, len(mask)
        while i < n:
            if mask[i]:
                j = i
                while j < n and mask[j]:
                    j += 1
                runs.append((i, j - 1)); i = j
            else:
                i += 1
        cand = [(a, b) for (a, b) in runs if a > x1 - 2 and (b - a + 1) >= max(12, piece_w * 0.45)]
        if cand:
            a, b = min(cand, key=lambda r: abs((r[1] - r[0] + 1) - piece_w))
            return int(a) - x0, int(a), x0, f"diff(w={b - a + 1})"
    y0, y1 = int(ys.min()), int(ys.max())
    tmpl = sl[y0:y1 + 1, x0:x1 + 1, :3]
    res = cv2.matchTemplate(cv2.Canny(bg, 100, 200), cv2.Canny(tmpl, 100, 200), cv2.TM_CCOEFF_NORMED)
    _, _, _, loc = cv2.minMaxLoc(res)
    return int(loc[0]) - x0, int(loc[0]), x0, "canny"


# ------------------------------------------------------------------------------ human interaction
def human_wander(page, n=10):
    for _ in range(n):
        page.mouse.move(320 + np.random.randint(-140, 140), 320 + np.random.randint(-100, 100), steps=3)
        page.wait_for_timeout(int(35 + 55 * np.random.rand()))


def click_radar(page):
    btn = page.query_selector(".geetest_radar_btn")
    if not btn:
        return False
    bb = btn.bounding_box()
    page.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2, steps=6)
    page.wait_for_timeout(int(90 + 80 * np.random.rand()))
    page.mouse.down(); page.wait_for_timeout(int(40 + 40 * np.random.rand())); page.mouse.up()
    return True


def refresh_puzzle(page):
    """Click Geetest's refresh for a NEW image (does not consume a submit attempt)."""
    for sel in (".geetest_refresh_1", ".geetest_refresh", ".geetest_reset_tip_content"):
        b = page.query_selector(sel)
        if b and b.is_visible():
            try:
                b.click(timeout=1500); return True
            except Exception:
                pass
    return False


def human_drag(page, knob, distance_css):
    box = knob.bounding_box()
    kx, ky = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(kx, ky, steps=3)
    page.wait_for_timeout(int(60 + 40 * np.random.rand()))
    page.mouse.down()
    page.wait_for_timeout(int(90 + 60 * np.random.rand()))    # a beat before pulling
    t_prev = 0
    for x, y, t in geetest_slide.make_track(distance_css):
        page.mouse.move(kx + x, ky + y * 1.5, steps=1)
        time.sleep(max(0.006, (t - t_prev) / 1000.0)); t_prev = t
    page.wait_for_timeout(int(50 + 60 * np.random.rand()))
    page.mouse.up()


def solve_slide(page, max_tries=5):
    """Solve the slide. Each drag = one submit; Geetest locks after ~5 (error_12 尝试过多), so keep
    drags few and refresh the IMAGE (free) between tries for a cleaner puzzle. Returns final state."""
    for t in range(max_tries):
        page.wait_for_timeout(500)
        s = st(page)
        if s in ("success", "error", "closed"):
            return s
        knob = page.query_selector(".geetest_slider_button")
        bg = canvas_png(page, ".geetest_canvas_bg")
        sl = canvas_png(page, ".geetest_canvas_slice")
        full = canvas_png(page, ".geetest_canvas_fullbg")
        if not (knob and knob.bounding_box() and bg and sl):
            print(f"    try{t}: read/stale fail; refresh"); refresh_puzzle(page); continue
        g = gap_distance(bg, sl, full)
        if not g:
            print(f"    try{t}: gap fail; refresh"); refresh_puzzle(page); continue
        dist, gap_left, piece_left, method = g
        drag = dist + OFFSETS[t % len(OFFSETS)]
        print(f"    try{t}: [{method}] gap_left={gap_left} piece_left={piece_left} -> drag {drag}px")
        human_drag(page, knob, drag)
        for _ in range(18):
            page.wait_for_timeout(220)
            if st(page) in ("success", "error", "closed"):
                break
        s = st(page)
        if s == "success":
            return "success"
        if s == "error":
            print(f"    try{t}: hard error -> {(out(page) or '')[:90]}"); return "error"
        print(f"    try{t}: fail -> refresh new puzzle")
        refresh_puzzle(page)
    return st(page)


# --------------------------------------------------------------- 九宫格点选 (icon click) via 超级鹰
def click_challenge_present(page):
    return bool(page.query_selector(".geetest_item"))


def screenshot_challenge(page):
    """Screenshot the whole Geetest click window (the 3x3 grid AND the on-image prompt, which the
    solver needs) and return (png_bytes, ox, oy) where (ox,oy) is the clip's top-left in CSS px.
    With the context at device_scale_factor=1, screenshot px == CSS px, so a returned coordinate
    (cx,cy) maps to the page as (ox+cx, oy+cy)."""
    box = page.evaluate("""() => {
        const sels=['.geetest_window','.geetest_widget','.geetest_box_wrap','.geetest_popup_box','.geetest_wind'];
        for (const s of sels){ const e=document.querySelector(s); if(e){ const r=e.getBoundingClientRect();
            if(r.width>40 && r.height>40) return {x:r.x,y:r.y,w:r.width,h:r.height}; } }
        // fallback: union of the item cells, padded to include the prompt strip around them
        const it=[...document.querySelectorAll('.geetest_item')]; if(!it.length) return null;
        let x0=1e9,y0=1e9,x1=0,y1=0;
        it.forEach(e=>{const r=e.getBoundingClientRect(); x0=Math.min(x0,r.left);y0=Math.min(y0,r.top);x1=Math.max(x1,r.right);y1=Math.max(y1,r.bottom);});
        return {x:x0-10, y:y0-56, w:(x1-x0)+20, h:(y1-y0)+72};
    }""")
    if not box:
        return None
    clip = {"x": max(0.0, box["x"]), "y": max(0.0, box["y"]), "width": box["w"], "height": box["h"]}
    return page.screenshot(clip=clip), clip["x"], clip["y"]


def solve_click(page, cjy, max_tries=4):
    """Solve the Geetest 3x3 icon/word-click via 超级鹰 coordinate mode: screenshot the window ->
    get ordered click coordinates -> click each cell + 确认 -> Geetest emits the validate. Refunds
    (report_error) and refreshes on a miss. Returns the final data-gt state."""
    for t in range(max_tries):
        page.wait_for_timeout(600)
        s = st(page)
        if s in ("success", "error", "closed"):
            return s
        if not click_challenge_present(page):
            page.wait_for_timeout(500); continue
        shot = screenshot_challenge(page)
        if not shot:
            print(f"    click try{t}: no window; refresh"); refresh_puzzle(page); continue
        png, ox, oy = shot
        try:
            res = cjy.solve(png, codetype="9004")
        except ChaojiyingError as e:
            print(f"    click try{t}: 超级鹰 error: {e}"); return "error"
        coords = res["coords"]
        print(f"    click try{t}: {len(coords)} pts {coords} (pic_id={res['pic_id']})")
        if not coords:
            cjy.report_error(res["pic_id"]); refresh_puzzle(page); continue
        for (cx, cy) in coords:                                   # click cells in returned order
            px, py = ox + cx, oy + cy
            page.mouse.move(px + np.random.uniform(-1.5, 1.5), py + np.random.uniform(-1.5, 1.5), steps=4)
            page.wait_for_timeout(int(180 + 160 * np.random.rand()))
            page.mouse.click(px, py)
            page.wait_for_timeout(int(220 + 180 * np.random.rand()))
        commit = page.query_selector(".geetest_commit")
        if commit:
            try:
                commit.click(timeout=2000)
            except Exception:
                pass
        for _ in range(16):
            page.wait_for_timeout(240)
            if st(page) in ("success", "error", "closed"):
                break
        s = st(page)
        if s == "success":
            return s
        print(f"    click try{t}: not solved (state={s}); report+refresh")
        cjy.report_error(res["pic_id"]); refresh_puzzle(page)
    return st(page)


# ------------------------------------------------------------------------------------ the harvest
def harvest(session_path, phone="13800138000", attempts=3, headless=False, send_phone=None):
    """Harvest a Geetest validate for BOSS's man/machine gate. Returns the validate dict
    {geetest_challenge, geetest_validate, geetest_seccode} (+ _boss_sendcode if send_phone given),
    or None. `phone` is only the man/machine risk probe; `send_phone` (if set, == phone) additionally
    feeds the validate into bosscli send_sms_code to prove BOSS accepts it (reads the response code).

    NB: run this at LOW FREQUENCY from a clean CN IP — see the module docstring."""
    from bosscli.login import LoginClient
    from patchright.sync_api import sync_playwright

    lc = LoginClient.from_file(session_path)
    probe_phone = send_phone or phone
    got = None
    try:                                     # 九宫格点选 needs 超级鹰 creds; slide does not
        cjy = Chaojiying()
    except ChaojiyingError as e:
        cjy = None
        print(f"[i] 超级鹰未配置 ({e}) — 只能解滑块；遇到九宫格点选会跳过")
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=headless)
        # device_scale_factor=1 -> screenshot px == CSS px, so 超级鹰 coords map 1:1 to page clicks
        ctx = br.new_context(locale="zh-CN", timezone_id="Asia/Shanghai", device_scale_factor=1)
        page = ctx.new_page()
        page.on("response", lambda r: print(f"    [ajax {r.status}]") if "ajax.php" in r.url else None)

        for i in range(1, attempts + 1):
            print(f"[{i}] navigating to real https://www.zhipin.com ...")
            page.goto("https://www.zhipin.com/", wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(2000)                 # fresh page each attempt -> no stale widget
            mm = lc.man_machine(probe_phone)
            if not mm["isMachine"]:
                print(f"[{i}] isMachine=FALSE — no captcha demanded"); got = {"no_captcha": True}; break
            sc = json.loads(mm["startCaptcha"]); gt, ch = sc["gt"], sc["challenge"]
            print(f"[{i}] origin={page.evaluate('() => location.origin')} gt={gt} ch={ch}")
            code = (INJECT_TMPL.replace("__GTJS__", json.dumps(GT_JS))
                    .replace("__GT__", json.dumps(gt)).replace("__CH__", json.dumps(ch)))
            page.evaluate("(c)=>{var s=document.createElement('script'); s.textContent=c; "
                          "document.documentElement.appendChild(s);}", code)

            for _ in range(25):
                page.wait_for_timeout(400)
                if st(page) and st(page) not in ("boot", "init", ""):
                    break
            s = st(page)
            if s and s.startswith(("inject-err", "no-init", "gtjs-fail")):
                print(f"    injection problem: {s}"); break
            for _ in range(15):
                if page.query_selector(".geetest_radar_btn") and st(page) == "ready":
                    break
                page.wait_for_timeout(300)
            human_wander(page, 8)
            if not click_radar(page):
                print("    no radar btn; retry"); continue

            final = None
            for _ in range(24):
                page.wait_for_timeout(400)
                s = st(page)
                if s in ("success", "error"):
                    final = s; break
                if page.query_selector(".geetest_slider_button"):
                    print("    slide escalated -> solving"); final = solve_slide(page); break
                if click_challenge_present(page):
                    if cjy is None:
                        print("    九宫格点选 escalated 但未配置超级鹰 — 跳过"); final = "no-solver"; break
                    print("    九宫格点选 escalated -> solving via 超级鹰"); final = solve_click(page, cjy); break
            s = final or st(page)
            if s == "success":
                got = json.loads(out(page) or "null")
                print(f"    *** SUCCESS *** {got}")
                if send_phone:
                    try:
                        r = lc.send_sms_code(send_phone, region="+86", challenge=ch,
                                             validate=got["geetest_validate"],
                                             seccode=got["geetest_seccode"], precheck=False)
                        print(f"    >>> BOSS send_sms_code: code={r.get('code')} message={r.get('message')}")
                        got["_boss_sendcode"] = {"code": r.get("code"), "message": r.get("message")}
                    except Exception as e:
                        print(f"    >>> BOSS send_sms_code response: {e}")
                        got["_boss_sendcode_err"] = str(e)
                break
            print(f"    verdict={s} out={(out(page) or '')[:140]}")
            page.wait_for_timeout(600)

        page.wait_for_timeout(800)
        ctx.close(); br.close()

    print("\n==== RESULT ====")
    print(json.dumps(got, ensure_ascii=False, indent=2) if got else "no validate harvested")
    return got


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Harvest a BOSS直聘 login Geetest validate via a real "
                                             "stealth browser (run low-frequency, from a clean CN IP).")
    ap.add_argument("--session", default=os.path.join(_REPO_ROOT, "session.local.json"),
                    help="session json with the device profile (default: ../session.local.json)")
    ap.add_argument("--phone", default="13800138000", help="man/machine risk-probe phone (no SMS)")
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--send", metavar="PHONE", default=None,
                    help="also feed the validate into BOSS send_sms_code for this phone (proves "
                         "server acceptance by reading the response code; sends a real SMS)")
    a = ap.parse_args()
    harvest(a.session, phone=a.phone, attempts=a.attempts, headless=a.headless, send_phone=a.send)
