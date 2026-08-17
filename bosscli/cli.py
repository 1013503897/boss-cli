"""boss-cli entry point.  Usage: python -m bosscli.cli search <query> [opts]"""
from __future__ import annotations
import argparse, json, os, sys
from .client import BossClient

DEFAULT_SESSION = os.environ.get("BOSS_SESSION") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "session.local.json")


def cmd_search(args):
    if not os.path.exists(args.session):
        sys.exit(f"session file not found: {args.session}\n"
                 f"Copy session.example.json -> session.local.json and fill in your t2 token "
                 f"and device profile (see README).")
    client = BossClient.from_file(args.session)
    if args.token:
        client.s["t2"] = args.token
    resp = client.search(args.query, city=args.city, page=args.page, sort=args.sort)
    if args.raw:
        print(json.dumps(resp, ensure_ascii=False, indent=2)); return
    outer = resp.get("code"); card = resp.get("zpData", {}).get(
        "/api/zpgeek/app/geek/search/cardlist", {})
    if outer != 0 or card.get("code") != 0:
        print(f"[!] outer={outer} {resp.get('message')} | cardlist={card.get('code')} {card.get('message')}")
    jobs = BossClient.parse_jobs(resp)
    if args.json:
        print(json.dumps(jobs, ensure_ascii=False, indent=2)); return
    print(f"# {len(jobs)} jobs for '{args.query}' (city={args.city or 'default'}, page={args.page})")
    for j in jobs:
        labels = ' '.join(j['labels']) if isinstance(j['labels'], list) else (j['labels'] or '')
        print(f"- {j['name']} | {j['salary']} | {j['company']} | {j['city']}  [{labels}]")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="boss", description="Off-device BOSS直聘 search")
    ap.add_argument("--session", default=DEFAULT_SESSION, help="session json (default: session.local.json / $BOSS_SESSION)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("search", help="search jobs by keyword")
    sp.add_argument("query")
    sp.add_argument("--city", help="city code, e.g. 101210100 (Hangzhou)")
    sp.add_argument("--page", type=int, default=1)
    sp.add_argument("--sort", type=int, default=-1, help="-1=comprehensive")
    sp.add_argument("--json", action="store_true", help="print parsed jobs as JSON")
    sp.add_argument("--raw", action="store_true", help="print full decrypted response JSON")
    sp.add_argument("--token", help="override t2 auth token")
    sp.set_defaults(func=cmd_search)
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
