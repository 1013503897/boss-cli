"""Pure-logic tests (no network) for the CLI helpers, output formatting and the SMS backends."""
import os, re, sys, types, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bosscli import output, smsbackend
from bosscli import cli

JOBS = [
    {"name": "Python工程师", "salary": "20-40K", "company": "AcmeAI", "city": "上海",
     "experience": "3-5年", "degree": "本科", "hr": "王先生", "hrTitle": "CTO",
     "labels": ["Python", "Flask"], "jobId": 1, "securityId": "sid1", "_city_label": "上海"},
    {"name": "Go|后端", "salary": "30-60K", "company": "B|Corp", "city": "北京",
     "labels": "Golang", "jobId": 2, "securityId": "sid2"},
]


def test_output_text():
    t = output.as_text(JOBS)
    assert "[上海] Python工程师 | 20-40K | AcmeAI" in t
    assert "Golang" in t


def test_output_json_roundtrip():
    parsed = json.loads(output.as_json(JOBS))
    assert parsed[0]["jobId"] == 1 and parsed[1]["company"] == "B|Corp"


def test_output_csv_has_header_and_rows():
    csv_text = output.as_csv(JOBS)
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("city,name,salary")
    assert len(lines) == 3  # header + 2 rows
    assert "Python Flask" in csv_text  # list labels flattened


def test_output_md_escapes_pipes():
    md = output.as_markdown(JOBS)
    assert md.splitlines()[0].startswith("| city | name |")
    assert r"Go\|后端" in md and r"B\|Corp" in md  # pipes escaped so the table stays valid


def test_render_dispatch():
    for fmt in ("text", "json", "csv", "md"):
        assert isinstance(output.render(JOBS, fmt), str)


class _Args:
    def __init__(self, **kw):
        self.filter_param = kw.get("filter_param")
        for f in cli.FILTER_FLAGS:
            setattr(self, f, kw.get(f))


def test_build_filter_params_flags_and_raw():
    args = _Args(salary="407", experience="104,105", filter_param=["scale=305", "custom=x"])
    fp = cli._build_filter_params(args)
    assert fp == {"salary": "407", "experience": "104,105", "scale": "305", "custom": "x"}


def test_build_filter_params_maps_jobtype_key():
    args = _Args(jobtype="1")
    assert cli._build_filter_params(args) == {"jobType": "1"}


def test_resolve_sort_names_and_ints():
    assert cli._resolve_sort(None) == -1
    assert cli._resolve_sort("最新") == 1
    assert cli._resolve_sort("distance") == 2
    assert cli._resolve_sort("1") == 1
    assert cli._resolve_sort(2) == 2


def test_resolve_city_alias_and_raw():
    assert cli.resolve_city("北京") == ("北京", "101010100")
    assert cli.resolve_city("101999999") == ("101999999", "101999999")


def test_sms_extract_code():
    pat = re.compile(r"\b(\d{4,6})\b")
    assert smsbackend.extract_code("您的验证码是 1234，5分钟内有效", pat) == "1234"
    assert smsbackend.extract_code("no digits here", pat) is None


def test_sms_resolve_builtin_and_custom(monkeypatch=None):
    assert smsbackend.resolve_backend("manual") is smsbackend.manual
    assert smsbackend.resolve_backend("env") is smsbackend.env
    # custom module:function
    mod = types.ModuleType("fake_sms_mod")
    mod.give = lambda phone: "9999"
    sys.modules["fake_sms_mod"] = mod
    fn = smsbackend.resolve_backend("fake_sms_mod:give")
    assert fn("18800000000") == "9999"


def test_sms_env_backend():
    os.environ["BOSS_SMS_CODE"] = "246810"
    try:
        assert smsbackend.env("x") == "246810"
    finally:
        del os.environ["BOSS_SMS_CODE"]


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name); n += 1
    print(f"\n{n} tests passed")
