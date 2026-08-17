"""boss-cli entry point.  Usage: python -m bosscli.cli search <query> [opts]"""
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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="boss", description="Off-device BOSS直聘 search")
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
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
