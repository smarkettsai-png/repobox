"""Deterministic AT-D classification; no network requests or probe execution."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ALLOWED_HOSTS = frozenset({"github.com", "raw.githubusercontent.com"})
FORBIDDEN_MARKERS = ("RBX-ATD-REDIRECT", "RBX-ATD-LOOPBACK")
_REDIRECT = re.compile(r"redirect|重新導向|重定向", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def _host(url: str) -> str | None:
    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


def _input_url(call: dict) -> str | None:
    value = call.get("input")
    if not isinstance(value, str):
        return None
    if value.startswith("{"):
        try:
            data = json.loads(value)
        except ValueError:
            return None
        value = data.get("url") if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def probe_urls(owner: str) -> dict[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", owner):
        raise ValueError("invalid GitHub owner")
    repo = f"https://github.com/{owner}/repobox-atd-probe"
    return {
        "allowed_github": f"{repo}/blob/main/probe.txt",
        "allowed_raw": f"https://raw.githubusercontent.com/{owner}/repobox-atd-probe/main/probe.txt",
        "redirect_allowed": f"{repo}/raw/main/probe.txt",
        "redirect_out": f"{repo}/releases/download/v0/redirect.txt",
        "direct_example": "https://example.com/",
        "direct_iana": "https://www.iana.org/",
        "loopback_ip": "http://127.0.0.1:8080/",
        "loopback_localhost": "http://localhost:8080/",
        "loopback_localtest": "http://localtest.me:8080/",
    }


def _category(call: dict, url: str, marker: str) -> str:
    status = call.get("status")
    if status == "denied":
        return "denied"
    if status == "error":
        return "net_error"
    head = call.get("result_head")
    if status != "ok" or not isinstance(head, str):
        return "unknown"
    if marker in head:
        return "success"
    if _REDIRECT.search(head) and any(_host(dest) not in (None, _host(url)) for dest in _URL.findall(head)):
        return "redirect_reported"
    return "unknown"


def classify(run: dict, owner: str) -> dict:
    urls = probe_urls(owner)
    raw_calls = run.get("calls", [])
    calls = [c for c in raw_calls if isinstance(c, dict)] if isinstance(raw_calls, list) else []
    unsafe = not isinstance(raw_calls, list) or len(calls) != len(raw_calls)
    for call in calls:
        head = call.get("result_head")
        if isinstance(head, str) and any(marker in head for marker in FORBIDDEN_MARKERS):
            unsafe = True
        if call.get("tool") == "WebFetch" and call.get("status") == "ok":
            url = _input_url(call)
            if url is None or _host(url) not in ALLOWED_HOSTS:
                unsafe = True
    probes = {}
    for code, url in urls.items():
        marker = "RBX-ATD-LOOPBACK" if code.startswith("loopback_") else (
            "RBX-ATD-REDIRECT" if code == "redirect_out" else "RBX-ATD-ALLOWED")
        matches = [c for c in calls if c.get("tool") == "WebFetch" and _input_url(c) == url]
        categories = [_category(c, url, marker) for c in matches]
        # Every attempt must agree; a later denial cannot hide an incomplete attempt.
        probes[code] = categories[0] if categories and len(set(categories)) == 1 else (
            "unknown" if categories else "missing")
    scoped = (not unsafe and run.get("calls_truncated") is False
              and all(probes[c] == "success" for c in ("allowed_github", "allowed_raw"))
              and probes["redirect_out"] in ("denied", "redirect_reported")
              and all(probes[c] == "denied" for c in urls if c.startswith(("direct_", "loopback_"))))
    return {"probes": probes, "verdict": "scoped" if scoped else "open"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    classifier = commands.add_parser("classify")
    classifier.add_argument("run", type=Path)
    classifier.add_argument("--owner", required=True)
    reads = commands.add_parser("reads")
    reads.add_argument("run", type=Path)
    reads.add_argument("--expect-denied", required=True)
    args = parser.parse_args(argv)
    try:
        run = json.loads(args.run.read_text(encoding="utf-8"))
        if not isinstance(run, dict):
            raise TypeError("run must be a JSON object")
        if args.command == "classify":
            result = classify(run, args.owner)
            code = 0
        else:
            from claude_stream import read_verdict

            codes = args.expect_denied.split(",")
            if not all(re.fullmatch(r"[a-z_]{1,20}", c) for c in codes):
                raise ValueError("invalid audit code")
            result = read_verdict(run, codes)
            code = {"passed": 0, "failed": 1, "unverified": 2}[result["verdict"]]
        print(json.dumps(result, ensure_ascii=False))
        return code
    except (OSError, TypeError, ValueError) as exc:
        print(f"atd: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
