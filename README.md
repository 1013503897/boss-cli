# boss-cli

**English** | [中文](#中文)

Search **BOSS直聘 (com.hpbr.bosszhipin)** jobs from your terminal or from an AI agent — off-device,
pure Python, no phone/emulator needed to run. It reproduces the app's native request signing
(`libyzwg.so`) in Python, so a plain HTTP request gets accepted by the server.

![boss-cli searching real jobs from the terminal](docs/cli-search.png)

```bash
$ boss search "安卓逆向" --city 北京,上海,杭州
# 12 jobs for '安卓逆向' (cities=['北京', '上海', '杭州'], page=1)
- [北京] 资深Android逆向与风控对抗专家 | 70-100K·13薪 | PureblueAI
- [上海] 移动安全/逆向工程师 | 30-60K | ...
- [杭州] android逆向开发 | 50-75K | 小算科技
...
```

> Research / educational project. It searches with **your own logged-in account's token**; you are
> responsible for complying with BOSS直聘's Terms of Service. Don't hammer the API.

## Features

- **Off-device search** — no phone, emulator, or unidbg at runtime; just Python + your session token.
- **Off-device login** — SMS-code login reproduced end-to-end (`boss login`), so you can mint a fresh
  `t2` yourself; the man/machine behaviour captcha (Geetest / 网易易盾) can be auto-solved (`--solve`).
- **Multi-city in one call** — `--city 北京,上海,杭州`, by name or code.
- **Server-side filters** — `--salary` / `--experience` / `--degree` / `--industry` … (or the raw
  `--filter-param KEY=VAL`); discover valid codes with `boss filters`.
- **Pagination** — `--pages N` or `--all` (auto-dedup across pages and cities).
- **Keyword post-filter** — `--filter 远程` / `--filter 兼职` keeps only matching jobs.
- **Text / JSON / CSV / Markdown output** — `--format` (or `--json`), write to a file with `-o`.
- **More endpoints** — `boss whoami` (your job expectations), `boss detail <securityId>` (full JD),
  `boss recommend` (F1 feed), `boss cities` (code table), `boss chat` (打招呼, write — dry-run by default).
- **MCP server** — expose `boss_search` + `boss_filters` as tools to Claude / any MCP client.

## Install

```bash
pip install -e .                 # installs the `boss` command (deps: requests, lz4)
pip install -e ".[mcp]"          # + MCP server        (python -m bosscli.mcp_server)
pip install -e ".[captcha]"      # + login captcha solvers (patchright/opencv/numpy/pycryptodome)
```

Or run without installing: `python -m bosscli.cli <cmd> ...`.

## Get your session (one-time)

The client needs three things from a **logged-in** BOSS直聘 app on a device you control:

| field | where it comes from |
|---|---|
| `t2` | the `t2` **request header** — your login token |
| `client_info` | the `client_info` query param (a JSON blob: model / uniqid / did …) |
| `uniqid` | inside `client_info` |

Capture one `GET https://api5.zhipin.com/api/batch/requests` from the app with any HTTPS
interceptor (Reqable / Charles / mitmproxy; use a frida SSL-unpin script if the app pins), then copy
those values into `session.local.json`:

```bash
cp session.example.json session.local.json    # then paste your t2 / client_info / uniqid / cardlist_defaults
```

`session.local.json` is gitignored (it holds your token). `t2` expires — when searches start returning
`invalid auth`, grab a fresh `t2` the same way.

## Usage

```bash
# by city name or code, one or several
boss search "Python"                              # default city from your session
boss search "数据分析" --city 上海
boss search "安卓逆向" --city 北京,上海,杭州        # multi-city, results tagged [city]

# server-side filters + pagination + cap
boss search "Python" --city 上海 --salary 407      # filterParams.salary code (see `boss filters`)
boss search "逆向" --city 北京 --filter-param experience=104,105   # raw filterParams passthrough
boss search "Golang" --pages 3 --limit 30          # fetch 3 pages, dedup, keep 30
boss search "算法" --all                            # fetch until exhausted (cap 10 pages)

# output
boss search "AIGC" --city 深圳 --format md          # text | json | csv | md
boss search "数据" --format csv -o jobs.csv         # write to a file
boss search "逆向" --city 北京,上海 --filter 远程    # client-side post-filter on title/labels/company

# discover valid filter/sort codes (industry / position / sort names)
boss filters "Python" --city 上海

# run without installing (module form)
python -m bosscli.cli search "AIGC" --city 深圳
```

Search options: `--city` (name/code, comma-separated) · `--pages N` / `--all` · `--sort 综合|最新|距离`
· `--limit N` · `--filter <text>` (post-filter) · `--filter-param KEY=VAL` (raw, repeatable) ·
convenience filters `--salary/--experience/--degree/--scale/--stage/--jobtype/--industry/--position`
· `--format text|json|csv|md` (`--json` shorthand) · `-o <file>` · `--token <t2>` · `--session <path>`.

City names built in: 全国 / 北京 / 上海 / 广州 / 深圳 / 杭州 / 成都 / 南京 / 武汉 / 西安 / 苏州 / 天津 / 长沙 / 重庆 / 郑州 / 厦门 (others: pass the raw code).

### Login (obtain a fresh `t2` off-device)

```bash
boss login --phone 15900000000 --solve            # solve man/machine captcha → send SMS → prompt code → t2
boss login --phone 15900000000 --send             # only send the code
boss login --phone 15900000000 --code 1234        # exchange an already-received code for t2
```

`login` reuses the device profile in your session file and writes the new `t2` back into it.
The man/machine step almost always demands a behaviour captcha off-device — `--solve` handles both
Geetest (via CapSolver when `CAPSOLVER_KEY` is set, else a browser harvester) and 网易易盾 (browser).
The SMS code source is pluggable with `--sms-backend manual|env|http|module:func` (see
[`bosscli/smsbackend.py`](bosscli/smsbackend.py)). See [`gt3solver/README.md`](gt3solver/README.md) for the captcha internals.

### More commands

```bash
boss whoami                      # this account's job expectations (expectId/encryptExpectId …)
boss whoami --set-expect         # …and write the first one back into the session (fixes a stale expectId)
boss detail <securityId>         # full job detail (JD text, boss, company) for a search-result securityId
boss recommend --limit 20        # geek F1 recommendation feed
boss cities --grep 杭州           # BOSS city code/name table (filterable); good for finding a cityCode
boss chat <securityId>           # 打招呼: DRY-RUN by default; shows the request it would send
boss chat <securityId> --confirm # …actually send it (WRITE — starts a chat under your account)
```

These reuse the exact same signing as search/login: `whoami` / `detail` / `chat` sign with the
account `secretKey` (they're not on BOSS's no-key whitelist), while `recommend` / `cities` are
whitelisted and sign key-less like search. `boss chat` is a **write** action — it messages a boss on
your behalf, so it never sends without `--confirm`.

### MCP server

```bash
BOSS_SESSION=./session.local.json python -m bosscli.mcp_server
```

Register it in your MCP client (e.g. `~/.claude.json`); the tools are
`boss_search(query, city?, page?, sort?, filter_params?)` and `boss_filters(query?, city?)`.

## How it works (short version)

BOSS直聘's search goes through a batch endpoint whose params carry two anti-tamper values — `sp`
(an encrypted parameter blob) and `sig` (a signature) — both produced by the native library
`libyzwg.so`. This project reproduces that library's signing/encryption in pure Python
(`bosscli/yzwg.py`), assembles the batch request (`bosscli/signer.py`), sends it and decrypts the
reply (`bosscli/client.py`). Correctness is pinned by byte-exact tests against real captures
(`tests/`). That's the whole trick: once the signing is reproduced, the search is just an HTTP call.

```bash
python tests/test_yzwg.py       # native crypto — byte-exact vs real-device captures
python tests/test_signer.py     # request assembly round-trip
```

## Layout

```
bosscli/yzwg.py     signing / encryption primitives (pure Python)
bosscli/signer.py   request assembly (batch + plain branches)
bosscli/client.py   search + read/write endpoints (whoami/detail/recommend/cities/chat) + signed-call core
bosscli/login.py    off-device SMS-code login (man/machine → smsCode → codeLogin → t2)
bosscli/smsbackend.py  pluggable SMS-code source for login (manual / env / http / custom)
bosscli/output.py   text / json / csv / markdown rendering
bosscli/cli.py      the `boss {search,filters,login}` CLI
bosscli/mcp_server.py  MCP wrapper (tools: boss_search, boss_filters)
gt3solver/          login captcha solvers (Geetest GT3 + 网易易盾) — see its README
tests/              byte-exact regression tests + fixtures
session.example.json   template for your session
```

---

# 中文

[English](#boss-cli) | **中文**

在终端或 AI agent 里搜 **BOSS直聘（com.hpbr.bosszhipin）** 职位 —— 纯 Python、离设备，跑的时候不需要手机/模拟器。
它把 App 的 native 请求加签库（`libyzwg.so`）用 Python 复现了出来，所以一条普通 HTTP 请求就能被服务器接受。

![在终端里搜到真实职位](docs/cli-search.png)

```bash
$ boss search "安卓逆向" --city 北京,上海,杭州
# 12 jobs for '安卓逆向' (cities=['北京', '上海', '杭州'], page=1)
- [北京] 资深Android逆向与风控对抗专家 | 70-100K·13薪 | PureblueAI
- [杭州] android逆向开发 | 50-75K | 小算科技
...
```

> 研究 / 学习用途。它用的是**你自己登录账号的 token** 去搜；请自行遵守 BOSS直聘的服务条款，别高频打接口。

## 功能

- **离设备搜索** —— 运行时不需要手机 / 模拟器 / unidbg，只要 Python + 你的 session token。
- **离设备登录** —— 短信验证码登录全链路复现（`boss login`），可自己拿新 `t2`；man/machine 行为
  验证码（Geetest / 网易易盾）可 `--solve` 自动求解。
- **一条命令多城市** —— `--city 北京,上海,杭州`，支持城市名或城市码。
- **服务端过滤器** —— `--salary` / `--experience` / `--degree` / `--industry` …（或原样透传
  `--filter-param KEY=VAL`）；用 `boss filters` 查可用码表。
- **翻页** —— `--pages N` 或 `--all`（跨页跨城自动去重）。
- **关键词后筛** —— `--filter 远程` / `--filter 兼职`，只保留标题/标签/公司命中的岗位。
- **文本 / JSON / CSV / Markdown 输出** —— `--format`（或 `--json`），`-o` 落盘。
- **更多接口** —— `boss whoami`（你的求职期望）、`boss detail <securityId>`（完整 JD）、
  `boss recommend`（F1 推荐流）、`boss cities`（城市码表）、`boss chat`（打招呼，写操作，默认 dry-run）。
- **MCP 服务** —— 把 `boss_search` + `boss_filters` 暴露成工具给 Claude / 任意 MCP 客户端。

## 安装

```bash
pip install -e .                 # 装上 `boss` 命令（依赖：requests、lz4）
pip install -e ".[mcp]"          # + MCP 服务       （python -m bosscli.mcp_server）
pip install -e ".[captcha]"      # + 登录验证码求解器（patchright/opencv/numpy/pycryptodome）
```

也可不安装直接跑：`python -m bosscli.cli <命令> ...`。

## 获取 session

客户端需要从一台**已登录** BOSS直聘的设备上拿三个凭证：

| 字段 | 来源 |
|---|---|
| `t2` | 请求头里的 `t2` —— 你的登录 token |
| `client_info` | query 参数 `client_info`（一段 JSON：机型 / uniqid / did …） |
| `uniqid` | 在 `client_info` 里面 |

用任意 HTTPS 抓包工具
抓一条 App 发出的 `GET https://api5.zhipin.com/api/batch/requests`，把上面几个值填进 `session.local.json`：

```bash
cp session.example.json session.local.json    # 再把你的 t2 / client_info / uniqid / cardlist_defaults 粘进去
```

`t2` 会过期 —— 搜索开始返回 `invalid auth` 时，照上面再抓一个新的即可。

## 用法

```bash
# 按城市名或城市码，单个或多个
boss search "Python"                              # 用 session 里的默认城市
boss search "数据分析" --city 上海
boss search "安卓逆向" --city 北京,上海,杭州        # 多城市，结果带 [城市] 标签

# 服务端过滤器 + 翻页 + 限量
boss search "Python" --city 上海 --salary 407      # filterParams.salary 码（见 `boss filters`）
boss search "逆向" --city 北京 --filter-param experience=104,105   # 原样透传 filterParams
boss search "Golang" --pages 3 --limit 30          # 抓 3 页、去重、留 30 条
boss search "算法" --all                            # 抓到没有为止（最多 10 页）

# 输出
boss search "AIGC" --city 深圳 --format md          # text | json | csv | md
boss search "数据" --format csv -o jobs.csv         # 写到文件
boss search "逆向" --city 北京,上海 --filter 远程    # 客户端后筛（标题/标签/公司）

# 查可用的过滤/排序码表（行业 / 职位 / 排序名）
boss filters "Python" --city 上海

# 不安装、直接模块方式跑
python -m bosscli.cli search "AIGC" --city 深圳
```

搜索参数：`--city`（名/码，逗号分隔）· `--pages N` / `--all` · `--sort 综合|最新|距离` · `--limit N`
· `--filter <文本>`（后筛）· `--filter-param KEY=VAL`（原样，可重复）· 便捷过滤
`--salary/--experience/--degree/--scale/--stage/--jobtype/--industry/--position` ·
`--format text|json|csv|md`（`--json` 简写）· `-o <文件>` · `--token <t2>` · `--session <路径>`。

内置城市名：全国 / 北京 / 上海 / 广州 / 深圳 / 杭州 / 成都 / 南京 / 武汉 / 西安 / 苏州 / 天津 / 长沙 / 重庆 / 郑州 / 厦门（其它城市直接传城市码）。

### 登录（离设备拿新 `t2`）

```bash
boss login --phone 15900000000 --solve            # 解 man/machine 验证码 → 发短信 → 输入验证码 → t2
boss login --phone 15900000000 --send             # 只发验证码
boss login --phone 15900000000 --code 1234        # 用已收到的验证码换 t2
```

`login` 复用 session 里的设备档，把新 `t2` 写回 session。离设备时 man/machine 几乎必弹行为验证码：
`--solve` 同时支持 Geetest（配了 `CAPSOLVER_KEY` 走 CapSolver，否则走浏览器 harvester）和网易易盾（浏览器）。
短信验证码来源可插拔：`--sms-backend manual|env|http|module:func`（见
[`bosscli/smsbackend.py`](bosscli/smsbackend.py)）。验证码原理见 [`gt3solver/README.md`](gt3solver/README.md)。

### 更多命令

```bash
boss whoami                      # 当前账号的求职期望（expectId/encryptExpectId …）
boss whoami --set-expect         # …并把第一个写回 session（修掉过期/换号后残留的 expectId）
boss detail <securityId>         # 某岗位完整详情（JD 全文 / boss / 公司），securityId 来自搜索结果
boss recommend --limit 20        # geek F1 推荐职位流
boss cities --grep 杭州           # BOSS 城市码/名表（可筛），用来查 cityCode
boss chat <securityId>           # 打招呼：默认 dry-run，只打印将要发送的请求
boss chat <securityId> --confirm # …真正发送（写操作，会以你的账号发起沟通）
```

这些接口复用与 search/login 完全相同的加签：`whoami` / `detail` / `chat` 不在 BOSS 的免 key 白名单上，
用账号 `secretKey` 加签；`recommend` / `cities` 在白名单里，和 search 一样免 key。`boss chat` 是**写**操作
（以你名义给 boss 发消息），因此不加 `--confirm` 绝不发送。

### MCP 服务

```bash
BOSS_SESSION=./session.local.json python -m bosscli.mcp_server
```

在 MCP 客户端里注册（如 `~/.claude.json`）；工具名 `boss_search(query, city?, page?, sort?, filter_params?)`
和 `boss_filters(query?, city?)`。

## 原理

BOSS直聘的搜索走一个批量端点，参数里带两个防篡改值 —— `sp`（加密参数串）和 `sig`（签名），都由 native 库
`libyzwg.so` 生成。本项目把这个库的加签/加密**用纯 Python 复现**（`bosscli/yzwg.py`），装配批量请求
（`bosscli/signer.py`）、发出去再解密响应（`bosscli/client.py`）。正确性靠对真实抓包的字节级测试兜底
（`tests/`）。核心就这一点：加签一旦复现出来，搜索就只是一次普通 HTTP 请求。

## 免责声明

仅供安全研究与学习交流。请勿用于任何违反 BOSS直聘服务条款或相关法律法规的用途；因使用本项目产生的一切后果由使用者自负。
