"""boss-cli entry point.  Usage: python -m bosscli.cli {search|login} ... [opts]"""
from __future__ import annotations
import argparse, json, os, sys
from .client import BossClient

DEFAULT_SESSION = os.environ.get("BOSS_SESSION") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "session.local.json")

# common city codes (BOSS uses China weather-station codes as cityCode)
CITY_ALIASES = {
    "全国": "100010000", "北京": "101010100", "上海": "101020100", "广州": "101280100",
    "深圳": "101280600", "杭州": "101210100", "成都": "101270100", "南京": "101190100",
    "武汉": "101200100", "西安": "101110100", "苏州": "101190400", "天津": "101030100",
    "长沙": "101250100", "重庆": "101040100", "郑州": "101180100", "厦门": "101230200",
}


def resolve_city(s: str) -> tuple[str, str]:
    """return (label, code). accepts an alias name or a raw code."""
    if s in CITY_ALIASES:
        return s, CITY_ALIASES[s]
    return s, s  # assume raw code


def cmd_search(args):
    if not os.path.exists(args.session):
        sys.exit(f"session file not found: {args.session}\n"
                 f"Copy session.example.json -> session.local.json and fill in your t2 token "
                 f"and device profile (see README).")
    client = BossClient.from_file(args.session)
    if args.token:
        client.s["t2"] = args.token

    cities = [resolve_city(x.strip()) for x in (args.city.split(",") if args.city else [None]) if x is not None] \
        or [(None, None)]
    if not args.city:
        cities = [("默认", None)]

    all_jobs = []
    for label, code in cities:
        resp = client.search(args.query, city=code, page=args.page, sort=args.sort)
        card = resp.get("zpData", {}).get("/api/zpgeek/app/geek/search/cardlist", {})
        if resp.get("code") != 0 or card.get("code") != 0:
            print(f"[!] {label}: outer={resp.get('code')} {resp.get('message')} | "
                  f"cardlist={card.get('code')} {card.get('message')}")
            continue
        jobs = BossClient.parse_jobs(resp)
        if args.filter:
            kw = args.filter
            def hit(j):
                hay = (j.get("name") or "") + " " + " ".join(j.get("labels") or []) + " " + (j.get("company") or "")
                return kw in hay
            jobs = [j for j in jobs if hit(j)]
        for j in jobs:
            j["_city_label"] = label
        all_jobs.extend(jobs)

    if args.limit:
        all_jobs = all_jobs[:args.limit]

    if args.json:
        print(json.dumps(all_jobs, ensure_ascii=False, indent=2)); return

    flt = f" filter='{args.filter}'" if args.filter else ""
    print(f"# {len(all_jobs)} jobs for '{args.query}' "
          f"(cities={[c[0] for c in cities]}, page={args.page}{flt})")
    for j in all_jobs:
        labels = ' '.join(j['labels']) if isinstance(j['labels'], list) else (j['labels'] or '')
        print(f"- [{j.get('_city_label')}] {j['name']} | {j['salary']} | {j['company']}  [{labels}]")


def _auto_solve_captcha(lc, args):
    """--solve: drive a real stealth browser to solve whatever captcha man/machine demands and
    populate args.validate (+ challenge/seccode for Geetest). Routes by captchaType: 4 -> 网易易盾
    (gt3solver.netease_harvest), 0/1 -> Geetest GT3 (gt3solver.browser_harvest). Needs the optional
    heavy deps (patchright + Chrome + opencv/numpy); imported lazily so the manual --validate path
    works without them."""
    from .login import CAPTCHA_GEETEST, CAPTCHA_NETEASE
    mm = lc.man_machine(args.phone)
    if not mm["isMachine"]:
        print("[+] man/machine: isMachine=false，无需验证码"); return
    ct = mm.get("captchaType")
    headless = not args.headful
    if ct == CAPTCHA_NETEASE:
        from gt3solver.netease_harvest import harvest
        print("[*] 网易易盾：启动浏览器求解…（低频使用，勿密集重试）")
        got = harvest(args.session, phone=args.phone, attempts=args.attempts, headless=headless)
        if not (got and got.get("validate")):
            sys.exit("[✗] 网易易盾未解出；重试，或加 --headful 用有头浏览器")
        args.validate = got["validate"]
        print("[✓] 网易易盾已解出 validate")
    elif ct in CAPTCHA_GEETEST:
        from gt3solver.browser_harvest import harvest
        print("[*] Geetest GT3：启动浏览器求解…")
        got = harvest(args.session, phone=args.phone, attempts=args.attempts, headless=headless)
        if not (got and got.get("geetest_validate")):
            sys.exit("[✗] Geetest 未解出；重试，或加 --headful")
        args.challenge = got["geetest_challenge"]
        args.validate = got["geetest_validate"]
        args.seccode = got["geetest_seccode"]
        print("[✓] Geetest 已解出 challenge/validate/seccode")
    else:
        sys.exit(f"[✗] 未知 captchaType={ct}，无法自动求解")


def cmd_login(args):
    if not os.path.exists(args.session):
        sys.exit(f"session file not found: {args.session}\n"
                 f"login reuses the device profile (client_info/uniqid) from your session file; "
                 f"copy session.example.json -> session.local.json and fill the device profile first.")
    from .login import (LoginClient, LoginError, CaptchaRequired, update_session_token,
                        CAPTCHA_GEETEST, CAPTCHA_NETEASE)
    lc = LoginClient.from_file(args.session)
    identity = {"geek": "0", "boss": "1"}.get(args.identity, args.identity)

    # --solve: auto-solve the behavior captcha in a browser and fill args.validate before sending
    if args.solve and not args.code and not (args.validate or args.seccode):
        _auto_solve_captcha(lc, args)

    try:
        # --code X: code already sent, just log in.  --send: only send.  neither: full interactive.
        if not args.code:
            resp = lc.send_sms_code(
                args.phone, region=args.region, voice=("1" if args.voice else "0"),
                challenge=args.challenge, validate=args.validate, seccode=args.seccode)
            print(f"[+] 验证码已发送到 {args.region} {args.phone}")
            if args.send:
                print(f"    收到后用: boss login --phone {args.phone} --code <验证码>"
                      + (f" --region {args.region}" if args.region != '+86' else ""))
                return
            args.code = input("    输入收到的短信验证码: ").strip()

        tokens = lc.code_login(args.phone, args.code, region=args.region, identity_type=identity)
    except CaptchaRequired as e:
        # man/machine 对离设备请求几乎恒返回 isMachine=true —— 这是 BOSS 登录的必经步骤
        # (真机也弹验证码，人手解掉才发码)，与出口 IP 无关。captchaType 决定该解哪种：
        #   0/1 = Geetest GT3 (startCaptcha 带 gt/challenge) —— 解出后传 --challenge/--validate/--seccode
        #   4   = 网易易盾   —— App 的 onValidate 只回填 validate 一个字段，故解出后只需 --validate
        print(f"[风控拦截] {e}")
        if e.captcha_type in CAPTCHA_GEETEST:
            print(f"    Geetest GT3: {e.start_captcha}")
            print("    解出后：boss login --phone <号码> --challenge <c> --validate <v> --seccode <s>")
        elif e.captcha_type == CAPTCHA_NETEASE:
            print(f"    网易易盾: captchaId={e.wy_captcha_id} type={e.wy_captcha_type} (0=滑块/1=无感)")
            print("    解出后：boss login --phone <号码> --validate <网易validate>  (网易只需 validate)")
        else:
            print(f"    未知 captchaType={e.captcha_type}")
        print("    注：isMachine=true 是登录常态，非 IP 封锁；需要一次真正的验证码 token。")
        sys.exit(2)
    except LoginError as e:
        sys.exit(f"[登录失败] {e}")

    update_session_token(args.session, tokens)
    who = "新用户(注册)" if tokens.get("register") else "老用户"
    print(f"[✓] 登录成功 · uid={tokens.get('uid')} · {who} · t2 已写入 {args.session}")
    if not tokens.get("t2"):
        print("[!] 响应里没有 t2，请检查 --json 原始响应:")
        print(json.dumps(tokens.get("raw"), ensure_ascii=False, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="boss", description="Off-device BOSS直聘 search + login")
    ap.add_argument("--session", default=DEFAULT_SESSION,
                    help="session json (default: session.local.json / $BOSS_SESSION)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("search", help="search jobs by keyword")
    sp.add_argument("query")
    sp.add_argument("--city", help="city name(北京/上海/杭州...) or code; comma-separated for several")
    sp.add_argument("--filter", help="keep only jobs whose title/labels/company contain this text, e.g. 兼职/远程")
    sp.add_argument("--page", type=int, default=1)
    sp.add_argument("--sort", type=int, default=-1, help="-1=comprehensive")
    sp.add_argument("--limit", type=int, help="cap the number of jobs printed")
    sp.add_argument("--json", action="store_true", help="print parsed jobs as JSON")
    sp.add_argument("--token", help="override t2 auth token")
    sp.set_defaults(func=cmd_search)

    lp = sub.add_parser("login", help="SMS-code login -> obtain t2 into the session file")
    lp.add_argument("--phone", required=True, help="mobile number (without region code)")
    lp.add_argument("--region", default="+86", help="region code, e.g. +86 / +63 (default +86)")
    lp.add_argument("--code", help="the SMS code (skip sending; just exchange code->t2)")
    lp.add_argument("--send", action="store_true", help="only send the SMS code, then exit (two-step flow)")
    lp.add_argument("--identity", default="geek", help="geek|boss (or 0|1); default geek")
    lp.add_argument("--voice", action="store_true", help="request a voice call code instead of SMS")
    lp.add_argument("--challenge", help="solved Geetest geetest_challenge (to pass man/machine)")
    lp.add_argument("--validate", help="solved captcha validate (Geetest geetest_validate, or 网易易盾 validate)")
    lp.add_argument("--seccode", help="solved Geetest geetest_seccode")
    lp.add_argument("--solve", action="store_true",
                    help="auto-solve the man/machine captcha in a real browser (网易易盾/Geetest); "
                         "needs patchright + Chrome + opencv/numpy")
    lp.add_argument("--headful", action="store_true", help="show the browser while --solve (default headless)")
    lp.add_argument("--attempts", type=int, default=3, help="--solve captcha attempts (default 3)")
    lp.set_defaults(func=cmd_login)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
