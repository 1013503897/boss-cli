"""
BOSS-MCP: thin MCP wrapper over BossClient. Exposes BOSS直聘 search as an MCP tool.

Run:  python -m bosscli.mcp_server        (stdio transport)
Register in an MCP client (e.g. ~/.claude.json) pointing at this module; set BOSS_SESSION
to your session.local.json path.
"""
from __future__ import annotations
import os
from mcp.server.fastmcp import FastMCP
from .client import BossClient

mcp = FastMCP("boss-search")

_SESSION = os.environ.get("BOSS_SESSION") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "session.local.json")


def _client() -> BossClient:
    return BossClient.from_file(_SESSION)


@mcp.tool()
def boss_search(query: str, city: str | None = None, page: int = 1, sort: int = -1) -> dict:
    """Search BOSS直聘 jobs off-device.

    Args:
        query: keyword, e.g. "Python" / "安卓逆向".
        city:  city code, e.g. "101210100" (Hangzhou); default = session city.
        page:  1-based page number.
        sort:  -1 comprehensive (default), others per BOSS.
    Returns: {count, jobs:[{name,salary,company,city,labels,jobId,securityId}], outer_code, cardlist_code}.
    """
    resp = _client().search(query, city=city, page=page, sort=sort)
    card = resp.get("zpData", {}).get("/api/zpgeek/app/geek/search/cardlist", {})
    jobs = BossClient.parse_jobs(resp)
    return {
        "count": len(jobs),
        "outer_code": resp.get("code"),
        "cardlist_code": card.get("code"),
        "message": card.get("message") or resp.get("message"),
        "jobs": jobs,
    }


def main():
    mcp.run()


if __name__ == "__main__":
    main()
