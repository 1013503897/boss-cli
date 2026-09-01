"""
Pluggable SMS-code source for `boss login`, so the code can come from something other than a
human typing it — e.g. a 接码 (SMS-rental) platform. The login flow only needs one thing from a
backend: given a phone number, return the received verification code.

Built-in backends (choose with --sms-backend / $BOSS_SMS_BACKEND):
  * manual            prompt on the terminal (default; what login always did).
  * http              poll an arbitrary REST endpoint, extract the code with a regex. Fully
                      configured by env vars, so any provider works without code changes:
                        BOSS_SMS_HTTP_URL     GET url; "{phone}" is substituted (required)
                        BOSS_SMS_HTTP_REGEX   regex whose 1st group is the code (default \\b(\\d{4,6})\\b)
                        BOSS_SMS_HTTP_TRIES   poll attempts (default 20)
                        BOSS_SMS_HTTP_INTERVAL seconds between polls (default 5)
  * env               read the code from $BOSS_SMS_CODE (handy for scripted/CI replays).
  * module:function   dotted path to your own callable(phone:str)->str|None.

A backend returns None to mean "no code yet / give up"; the caller then errors out.
"""
from __future__ import annotations
import importlib, os, re, time
from typing import Callable, Optional

Backend = Callable[[str], Optional[str]]


def manual(phone: str) -> Optional[str]:
    try:
        return input(f"    输入 {phone} 收到的短信验证码: ").strip() or None
    except (EOFError, KeyboardInterrupt):
        return None


def env(phone: str) -> Optional[str]:
    return (os.environ.get("BOSS_SMS_CODE") or "").strip() or None


def http(phone: str) -> Optional[str]:
    import requests
    url = os.environ.get("BOSS_SMS_HTTP_URL")
    if not url:
        raise ValueError("http backend 需要设置 BOSS_SMS_HTTP_URL（可含 {phone} 占位符）")
    pat = re.compile(os.environ.get("BOSS_SMS_HTTP_REGEX", r"\b(\d{4,6})\b"))
    tries = int(os.environ.get("BOSS_SMS_HTTP_TRIES", "20"))
    interval = float(os.environ.get("BOSS_SMS_HTTP_INTERVAL", "5"))
    target = url.replace("{phone}", phone)
    for i in range(tries):
        try:
            text = requests.get(target, timeout=15).text
            code = extract_code(text, pat)
            if code:
                return code
        except requests.RequestException:
            pass
        if i < tries - 1:
            time.sleep(interval)
    return None


def extract_code(text: str, pattern: re.Pattern) -> Optional[str]:
    """Pull the first regex-group match out of a provider response (split out for unit testing)."""
    m = pattern.search(text or "")
    if not m:
        return None
    return (m.group(1) if m.groups() else m.group(0)).strip() or None


_BUILTIN = {"manual": manual, "env": env, "http": http}


def resolve_backend(name: str | None) -> Backend:
    """Map a --sms-backend value to a callable. `module.path:func` loads a custom callable."""
    name = (name or os.environ.get("BOSS_SMS_BACKEND") or "manual").strip()
    if name in _BUILTIN:
        return _BUILTIN[name]
    if ":" in name:
        mod, _, fn = name.partition(":")
        return getattr(importlib.import_module(mod), fn)
    raise ValueError(f"未知 --sms-backend {name!r}；内置: {list(_BUILTIN)} 或 module:function")
