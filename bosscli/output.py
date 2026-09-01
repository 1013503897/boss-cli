"""Render parsed job lists in a few formats (text / json / csv / markdown)."""
from __future__ import annotations
import csv, io, json

# column order used by csv / markdown (keys of the dicts parse_jobs produces)
_COLS = ["city", "name", "salary", "company", "experience", "degree", "hr", "hrTitle",
         "labels", "jobId", "securityId"]


def _labels(v) -> str:
    return " ".join(v) if isinstance(v, list) else (v or "")


def _row(j: dict) -> dict:
    r = {k: j.get(k) for k in _COLS}
    r["labels"] = _labels(j.get("labels"))
    r["city"] = j.get("_city_label") or j.get("city") or ""
    return {k: ("" if v is None else v) for k, v in r.items()}


def as_text(jobs: list[dict]) -> str:
    lines = []
    for j in jobs:
        tag = f"[{j.get('_city_label') or j.get('city') or ''}] " if (j.get('_city_label') or j.get('city')) else ""
        lines.append(f"- {tag}{j.get('name')} | {j.get('salary')} | {j.get('company')}  [{_labels(j.get('labels'))}]")
    return "\n".join(lines)


def as_json(jobs: list[dict]) -> str:
    return json.dumps(jobs, ensure_ascii=False, indent=2)


def as_csv(jobs: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_COLS, extrasaction="ignore")
    w.writeheader()
    for j in jobs:
        w.writerow(_row(j))
    return buf.getvalue()


def as_markdown(jobs: list[dict]) -> str:
    head = "| " + " | ".join(_COLS) + " |"
    sep = "| " + " | ".join("---" for _ in _COLS) + " |"
    rows = []
    for j in jobs:
        r = _row(j)
        rows.append("| " + " | ".join(str(r[c]).replace("|", "\\|") for c in _COLS) + " |")
    return "\n".join([head, sep, *rows])


def render(jobs: list[dict], fmt: str) -> str:
    return {"text": as_text, "json": as_json, "csv": as_csv, "md": as_markdown}[fmt](jobs)
