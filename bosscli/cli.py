"""boss-cli entry point.  Usage: boss {search|filters|login|whoami|detail} ... [opts]
(or `python -m bosscli.cli ...` without installing)."""
from __future__ import annotations
import argparse, json, os, sys, time
from .client import BossClient, AuthExpired
from . import output

DEFAULT_SESSION = os.environ.get("BOSS_SESSION") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "session.local.json")

# common city codes (BOSS uses China weather-station codes as cityCode)
CITY_ALIASES = {
    "全国": "100010000", "北京": "101010100", "上海": "101020100", "广州": "101280100",
    "深圳": "101280600", "杭州": "101210100", "成都": "101270100", "南京": "101190100",
    "武汉": "101200100", "西安": "101110100", "苏州": "101190400", "天津": "101030100",
    "长沙": "101250100", "重庆": "101040100", "郑州": "101180100", "厦门": "101230200",
}

# --sort names -> request value (server echoes internal codes 6/1/2; -1 = comprehensive request value)
SORT_ALIASES = {"综合": -1, "comprehensive": -1, "最新": 1, "latest": 1, "距离": 2, "distance": 2}

# convenience filter flags -> filterParams key. Values are BOSS codes (discover with `boss filters`);
# multi-value keys take a comma-separated string. --filter-param KEY=VAL is the raw escape hatch.
FILTER_FLAGS = {
    "salary": "salary", "experience": "experience", "degree": "degree",
    "scale": "scale", "stage": "stage", "jobtype": "jobType",
    "industry": "industry", "position": "position",
}

MAX_ALL_PAGES = 10  # safety cap for --all so we never hammer the API unbounded


def resolve_city(s: str) -> tuple[str, str]:
    """return (label, code). accepts an alias name or a raw code."""
    if s in CITY_ALIASES:
        return s, CITY_ALIASES[s]
    return s, s  # assume raw code


def _build_filter_params(args) -> dict:
    """Collect --filter-param KEY=VAL plus the convenience flags into one filterParams dict."""
    fp: dict = {}
    for item in (args.filter_param or []):
        if "=" not in item:
            sys.exit(f"--filter-param 需形如 KEY=VALUE，收到: {item!r}")
        k, v = item.split("=", 1)
        fp[k.strip()] = v.strip()
    for flag, key in FILTER_FLAGS.items():
        v = getattr(args, flag, None)
        if v is not None:
            fp[key] = v
    return fp


def _resolve_sort(v) -> int:
    if v is None:
        return -1
    if isinstance(v, str) and v in SORT_ALIASES:
        return SORT_ALIASES[v]
    try:
        return int(v)
    except (TypeError, ValueError):
        sys.exit(f"--sort 需为数字或 {list(SORT_ALIASES)}，收到 {v!r}")


def _client(args) -> BossClient:
    if not os.path.exists(args.session):
        sys.exit(f"session file not found: {args.session}\n"
                 f"Copy session.example.json -> session.local.json and fill in your t2 token "
                 f"and device profile (see README), or run `boss login --phone <号码> --solve`.")
    client = BossClient.from_file(args.session)
    if getattr(args, "token", None):
        client.s["t2"] = args.token
    return client


def _auth_hint():
    print("[!] 登录状态已失效 (t2 过期)。用以下命令刷新后重试：", file=sys.stderr)
    print("    boss login --phone <你的号码> --solve", file=sys.stderr)


def cmd_search(args):
    client = _client(args)
    sort = _resolve_sort(args.sort)
    filter_params = _build_filter_params(args)

    cities = [resolve_city(x.strip()) for x in args.city.split(",")] if args.city else [("默认", None)]
    # page selection: --all > --pages N > --page P (single, back-compat) > page 1
    if args.all:
        page_nums = list(range(1, MAX_ALL_PAGES + 1))
    elif args.pages > 1:
        page_nums = list(range(1, args.pages + 1))
    else:
        page_nums = [args.page]
    last_page = page_nums[-1]
    seen: set = set()
    all_jobs: list[dict] = []

    try:
        for label, code in cities:
            for page in page_nums:
                resp = client.search(args.query, city=code, page=page, sort=sort,
                                     filter_params=filter_params or None)
                card = resp.get("zpData", {}).get("/api/zpgeek/app/geek/search/cardlist", {})
                if resp.get("code") != 0 or card.get("code") != 0:
                    print(f"[!] {label} p{page}: outer={resp.get('code')} {resp.get('message')} | "
                          f"cardlist={card.get('code')} {card.get('message')}", file=sys.stderr)
                    if resp.get("code") in (36, 37):   # 账户异常/频控 —— 降速或稍后再试
                        print("    [i] 触发 BOSS 风控/频控，请降低频率、隔一段时间再搜。", file=sys.stderr)
                    break
                jobs = BossClient.parse_jobs(resp)
                if not jobs:
                    break
                new = 0
                for j in jobs:
                    keyid = j.get("jobId") or j.get("securityId") or id(j)
                    if keyid in seen:
                        continue
                    seen.add(keyid)
                    j["_city_label"] = label
                    all_jobs.append(j)
                    new += 1
                if args.limit and len(all_jobs) >= args.limit:
                    break
                if new == 0 and page > 1:   # page returned only dups -> end of useful results
                    break
                if page < last_page:
                    time.sleep(0.5)          # be polite between pages
            if args.limit and len(all_jobs) >= args.limit:
                break
    except AuthExpired:
        _auth_hint(); sys.exit(2)

    if args.filter:
        kw = args.filter
        def hit(j):
            hay = (j.get("name") or "") + " " + output._labels(j.get("labels")) + " " + (j.get("company") or "")
            return kw in hay
        all_jobs = [j for j in all_jobs if hit(j)]

    if args.limit:
        all_jobs = all_jobs[:args.limit]

    fmt = "json" if args.json else args.format
    body = output.render(all_jobs, fmt)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(body + ("\n" if not body.endswith("\n") else ""))
        print(f"[✓] {len(all_jobs)} jobs -> {args.output} ({fmt})")
        return

    if fmt == "text":
        flt = f" filter='{args.filter}'" if args.filter else ""
        pg = f"pages=1..{last_page}" if last_page > 1 else "page=1"
        print(f"# {len(all_jobs)} jobs for '{args.query}' (cities={[c[0] for c in cities]}, {pg}{flt})")
    print(body)


def cmd_filters(args):
    """Probe the live search response and print the filter/sort options it advertises, so the
    user can discover valid codes for --industry / --position / --sort (and see the NLP tags)."""
    client = _client(args)
    _, code = resolve_city(args.city) if args.city else ("", None)
    try:
        resp = client.search(args.query, city=code, page=1)
    except AuthExpired:
        _auth_hint(); sys.exit(2)
    zp = BossClient.cardlist_data(resp)

    print("# sorts (--sort 值)")
    for s in zp.get("sorts") or []:
        print(f"    {s.get('code'):>3}  {s.get('name')}")

    def walk(node, depth, prefix_seen):
        subs = node.get("subLevelModelList")
        name = node.get("name"); val = node.get("value")
        if val:
            code = val.split(":", 1)[1] if ":" in val else val
            print(f"    {'  '*depth}{code:<10} {name}   ({val})")
        elif name:
            print(f"    {'  '*depth}{name}")
        for s in (subs or []):
            walk(s, depth + 1, prefix_seen)

    for cat in zp.get("nlpFilters") or []:
        print(f"\n# {cat.get('name')}  (--industry / --position 用左侧数字码)")
        for s in cat.get("subLevelModelList") or []:
            walk(s, 0, set())

    lf = zp.get("labelFilter") or {}
    if lf.get("tags"):
        print("\n# labelFilter tags")
        for t in lf["tags"]:
            print(f"    {t.get('code'):>8}  {t.get('tag')}  [{t.get('source','')}]")

    print("\n提示：薪资/经验/学历/规模/融资的码表不在此响应里；用 `--filter-param 键=值` 原样透传，"
          "或在 App 里对照。已知服务器认这些 filterParams 键：salary / experience / degree / "
          "scale / stage / jobType / industry / position。")


def _auto_solve_captcha(lc, args):
    """--solve: solve whatever captcha man/machine demands and populate args.validate (+
    challenge/seccode for Geetest). Routes by captchaType:
      4   网易易盾 -> gt3solver.netease_harvest (browser slide solve)
      0/1 Geetest -> CapSolver token mode (handles slide AND 九宫格点选, no browser) if CAPSOLVER_KEY
          is set, else fall back to the browser harvester (opencv slide / 超级鹰 click).
    All solvers are imported lazily so the manual --validate path works without their deps."""
    import json as _json
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
        sc = _json.loads(mm["startCaptcha"]) if mm.get("startCaptcha") else {}
        gt, chal = sc.get("gt"), sc.get("challenge")
        # 1) prefer CapSolver token mode — one API round-trip, covers slide + 九宫格点选, no browser
        try:
            from gt3solver.capsolver import CapSolver, CapSolverError
            if not (gt and chal):
                raise CapSolverError("man/machine 未返回 gt/challenge")
            print("[*] Geetest：CapSolver token 求解…（slide/九宫格通用）")
            got = CapSolver().solve_geetest_v3(gt, chal)
            if not got.get("validate"):
                raise CapSolverError("CapSolver 未返回 validate")
            args.challenge = got["challenge"] or chal
            args.validate = got["validate"]
            args.seccode = got["seccode"]
            print("[✓] CapSolver 解出 Geetest challenge/validate/seccode")
            return
        except Exception as e:
            print(f"[i] CapSolver 不可用/失败（{e}）；回退浏览器 harvester")
        # 2) fallback: browser harvester (opencv slide, or 九宫格点选 via 超级鹰)
        from gt3solver.browser_harvest import harvest
        print("[*] Geetest GT3：启动浏览器求解…")
        got = harvest(args.session, phone=args.phone, attempts=args.attempts, headless=headless)
        if not (got and got.get("geetest_validate")):
            sys.exit("[✗] Geetest 未解出；建议配置 CAPSOLVER_KEY，或重试/加 --headful")
        args.challenge = got["geetest_challenge"]
        args.validate = got["geetest_validate"]
        args.seccode = got["geetest_seccode"]
        print("[✓] Geetest 已解出（browser）")
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
            from .smsbackend import resolve_backend
            args.code = resolve_backend(args.sms_backend)(args.phone)
            if not args.code:
                sys.exit("[✗] 未取得短信验证码（backend 返回空）")

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
        print("    注：isMachine=true 是登录常态，非 IP 封锁；需要一次真正的验证码 token。可加 --solve 自动求解。")
        sys.exit(2)
    except LoginError as e:
        sys.exit(f"[登录失败] {e}")

    update_session_token(args.session, tokens)
    who = "新用户(注册)" if tokens.get("register") else "老用户"
    print(f"[✓] 登录成功 · uid={tokens.get('uid')} · {who} · t2 已写入 {args.session}")
    if not tokens.get("t2"):
        print("[!] 响应里没有 t2，请检查 --json 原始响应:")
        print(json.dumps(tokens.get("raw"), ensure_ascii=False, indent=2))


def _add_search_filters(sp):
    sp.add_argument("--city", help="city name(北京/上海/杭州...) or code; comma-separated for several")
    sp.add_argument("--filter", help="post-filter: keep only jobs whose title/labels/company contain this text")
    sp.add_argument("--page", type=int, default=1, help="(deprecated alias) start page; prefer --pages")
    sp.add_argument("--pages", type=int, default=1, help="fetch pages 1..N (default 1)")
    sp.add_argument("--all", action="store_true", help=f"fetch until exhausted (cap {MAX_ALL_PAGES} pages)")
    sp.add_argument("--sort", default=None, help="综合/最新/距离 or -1/1/2 (default 综合)")
    sp.add_argument("--limit", type=int, help="cap the number of jobs returned")
    sp.add_argument("--filter-param", action="append", metavar="KEY=VAL",
                    help="raw filterParams passthrough (repeatable), e.g. --filter-param salary=407")
    for flag in FILTER_FLAGS:
        sp.add_argument(f"--{flag}", help=f"filterParams.{FILTER_FLAGS[flag]} code (see `boss filters`)")
    sp.add_argument("--format", choices=["text", "json", "csv", "md"], default="text", help="output format")
    sp.add_argument("--json", action="store_true", help="shorthand for --format json")
    sp.add_argument("-o", "--output", help="write to this file instead of stdout")
    sp.add_argument("--token", help="override t2 auth token")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="boss", description="Off-device BOSS直聘 search + login")
    ap.add_argument("--session", default=DEFAULT_SESSION,
                    help="session json (default: session.local.json / $BOSS_SESSION)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search", help="search jobs by keyword")
    sp.add_argument("query")
    _add_search_filters(sp)
    sp.set_defaults(func=cmd_search)

    fp = sub.add_parser("filters", help="show available filter/sort codes (probes a live search)")
    fp.add_argument("query", nargs="?", default="Python", help="probe keyword (default Python)")
    fp.add_argument("--city", help="probe city (name or code)")
    fp.add_argument("--token", help="override t2 auth token")
    fp.set_defaults(func=cmd_filters)

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
                    help="auto-solve the man/machine captcha (网易易盾/Geetest); needs the captcha extras")
    lp.add_argument("--headful", action="store_true", help="show the browser while --solve (default headless)")
    lp.add_argument("--attempts", type=int, default=3, help="--solve captcha attempts (default 3)")
    lp.add_argument("--sms-backend", default=None,
                    help="where the SMS code comes from: manual(default)|env|http|module:func "
                         "(see bosscli/smsbackend.py; also $BOSS_SMS_BACKEND)")
    lp.set_defaults(func=cmd_login)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
