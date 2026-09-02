"""
Load a local, gitignored `.env` into the process environment so secrets (CAPSOLVER_KEY,
CHAOJIYING_USER/PASS/SOFTID, BOSS_SMS_* …) don't have to be pasted on every run.

Format: plain `KEY=VALUE` lines, `#` comments and blanks ignored, surrounding quotes stripped.
Only keys NOT already set in the real environment are filled, so an explicit `export` still wins.
The file lives next to the project (repo root) and is in .gitignore — never committed.
"""
from __future__ import annotations
import os

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _candidates() -> list[str]:
    seen, out = set(), []
    for p in (os.environ.get("BOSS_ENV"), os.path.join(os.getcwd(), ".env"),
              os.path.join(_REPO_ROOT, ".env")):
        if p and p not in seen:
            seen.add(p); out.append(p)
    return out


def load_local_env() -> None:
    for path in _candidates():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except OSError:
            pass


def save_local_env(values: dict, path: str | None = None) -> str:
    """Upsert KEY=VALUE pairs into the repo-root `.env` (create if missing), preserving other lines.
    Returns the file path. Caller is responsible for it being gitignored (it is, by default)."""
    path = path or os.path.join(_REPO_ROOT, ".env")
    lines: list[str] = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    keys = set(values)
    out, done = [], set()
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in keys:
                out.append(f"{k}={values[k]}"); done.add(k); continue
        out.append(line)
    for k in keys - done:
        out.append(f"{k}={values[k]}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    return path
