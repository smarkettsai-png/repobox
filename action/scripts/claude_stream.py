"""Summarize Claude stream-json into a bounded, masked run record.

CLI: claude_stream.py [--audit=<code>=<absolute path> ...] <stream.jsonl> [...] <out.json>
Streams are concatenated in order (latest result wins). Exit 2 without a result event.
"""
from __future__ import annotations

import json
import posixpath
import re
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

RESULT_TEXT_MAX = 2000
MAX_STREAM_BYTES = 64 * 1024 * 1024
TOKEN_RE = re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}")
DENIED_RE = re.compile(
    r"permission.{0,40}(?:denied|not granted)|not allowed|access denied|"
    r"not authorized|unauthorized|tool.{0,40}(?:denied|disallowed)|"
    r"(?:denied|disallowed).{0,40}tool|haven't been granted permission|haven't granted it yet|not permitted",
    re.IGNORECASE,
)
AUDIT_CODE_RE = re.compile(r"^[a-z_]{1,20}$")


def mask(text: str) -> str:
    return TOKEN_RE.sub("sk-ant-[MASKED]", text)


def _path(path: str) -> str:
    return "/" + posixpath.normpath(path).lstrip("/")


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return json.dumps(content, ensure_ascii=False)


def read_verdict(run: dict, codes: Iterable[str]) -> dict:
    """Return {codes: {code: conclusion}, verdict: passed|failed|unverified}."""
    audit = run.get("read_audit", [])
    if not isinstance(audit, list):
        audit = []
    conclusions = {}
    for code in codes:
        statuses = [item.get("status") for item in audit if isinstance(item, dict) and item.get("code") == code]
        if not statuses:
            conclusion = "not_attempted"
        elif "ok" in statuses:
            conclusion = "read_succeeded"
        elif all(s == "denied" for s in statuses):
            conclusion = "denied"
        else:
            conclusion = "inconclusive"
        conclusions[code] = conclusion
    if "read_succeeded" in conclusions.values():
        verdict = "failed"
    elif (conclusions and run.get("read_audit_truncated") is False
          and all(c == "denied" for c in conclusions.values())):
        verdict = "passed"
    else:
        verdict = "unverified"
    return {"codes": conclusions, "verdict": verdict}


def summarize(lines: Iterable[str], *, audit: dict[str, str] | None = None) -> dict:
    by_name: Counter[str] = Counter()
    files: set[str] = set()
    result = None
    costs: list[float] = []
    uses: list[dict] = []
    results: dict[str, tuple[str, str]] = {}
    denied_ids: set[str] = set()
    denials: list[dict] = []
    init = {"tools": [], "mcp_servers": []}
    audit_paths = {code: _path(path) for code, path in (audit or {}).items()}
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        kind = ev.get("type")
        message = ev.get("message")
        blocks = message.get("content", []) if isinstance(message, dict) else []
        if not isinstance(blocks, list):
            blocks = []
        if kind == "system" and ev.get("subtype") == "init":
            init_tools, init_servers = ev.get("tools"), ev.get("mcp_servers")
            init = {
                "tools": [mask(t) for t in init_tools if isinstance(t, str)] if isinstance(init_tools, list) else [],
                "mcp_servers": [{k: mask(str(s.get(k, ""))) for k in ("name", "status")}
                                for s in init_servers if isinstance(s, dict)] if isinstance(init_servers, list) else [],
            }
        elif kind == "assistant":
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = str(block.get("name", "?"))
                by_name[name] += 1
                params = block.get("input")
                params = params if isinstance(params, dict) else {}
                path = params.get("file_path")
                if name == "Read" and isinstance(path, str):
                    files.add(path)
                tool_id = str(block.get("id", ""))
                if name in ("WebSearch", "WebFetch") or name.startswith("mcp__"):
                    uses.append({"id": tool_id, "tool": name,
                                 "input": mask(json.dumps(params, ensure_ascii=False))[:200]})
                elif name == "Read" and isinstance(path, str) and posixpath.isabs(path):
                    # shortcut: literal normalized paths only; aliases remain unverified.
                    for code, expected in audit_paths.items():
                        if _path(path) == expected:
                            uses.append({"id": tool_id, "code": code})
        elif kind == "user":
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                tool_id = block.get("tool_use_id")
                if not isinstance(tool_id, str) or not tool_id:
                    continue
                text = _content_text(block.get("content", ""))
                status = "ok"
                if block.get("is_error"):
                    status = "denied" if DENIED_RE.search(text) else "error"
                results[tool_id] = (status, mask(text)[:200])
        elif kind == "result":
            event_denials = ev.get("permission_denials", [])
            event_denials = event_denials if isinstance(event_denials, list) else []
            clean_denials = []
            for denial in event_denials:
                if not isinstance(denial, dict):
                    continue
                tool_id = str(denial.get("tool_use_id") or "")
                if tool_id:
                    denied_ids.add(tool_id)
                clean_denials.append({"tool_name": mask(str(denial.get("tool_name", ""))),
                                      "tool_use_id": mask(tool_id)})
            denials.extend(clean_denials)
            result = {k: v for k, v in ev.items() if k not in ("result", "permission_denials")}
            if "permission_denials" in ev:
                result["permission_denials"] = clean_denials[:40]
            cost = ev.get("total_cost_usd")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                costs.append(cost)
            result["result_text"] = mask(str(ev.get("result") or ""))[:RESULT_TEXT_MAX]
    calls = []
    reads = []
    deepwiki_ok = web_ok = False
    for use in uses:
        status, head = results.get(use["id"], ("no_result", ""))
        if use["id"] in denied_ids:
            status = "denied"
        if "code" in use:
            reads.append(dict(use, status=status))
        else:
            calls.append(dict(use, status=status, result_head=head))
            if status == "ok":
                deepwiki_ok |= use["tool"].startswith("mcp__deepwiki__")
                web_ok |= use["tool"] in ("WebSearch", "WebFetch")
    record = {
        "result": result,
        # Resumed sessions may report cumulative cost: do not sum.
        "result_costs_usd": costs,
        "tools": {
            "by_name": dict(by_name), "calls": sum(by_name.values()),
            "deepwiki": any(n.startswith("mcp__deepwiki") for n in by_name),
            "deepwiki_ok": deepwiki_ok,
            "web": any(n in ("WebSearch", "WebFetch") for n in by_name),
            "web_ok": web_ok, "files_read": len(files),
        },
        "calls": calls[:60], "calls_total": sum(by_name.values()), "calls_truncated": len(calls) > 60,
        "init": init, "permission_denials": denials[:40],
        "read_audit": reads[:40], "read_audit_total": len(reads), "read_audit_truncated": len(reads) > 40,
    }
    return json.loads(mask(json.dumps(record, ensure_ascii=False)))


def main(argv: list[str]) -> int:
    audit = {}
    while argv and argv[0].startswith("--audit="):
        code, sep, path = argv[0][len("--audit="):].partition("=")
        if not sep or not AUDIT_CODE_RE.fullmatch(code) or not posixpath.isabs(path) or "\x00" in path:
            print("invalid --audit: expected <code>=<absolute path>", file=sys.stderr)
            return 1
        if code in audit and audit[code] != _path(path):
            print("conflicting --audit code", file=sys.stderr)
            return 1
        audit[code] = _path(path)
        argv = argv[1:]
    if len(argv) < 2 or any(arg.startswith("--") for arg in argv):
        print("usage: claude_stream.py [--audit=<code>=<path> ...] <stream.jsonl> [...] <out.json>", file=sys.stderr)
        return 1
    *sources, out = [Path(a) for a in argv]
    lines: list[str] = []
    try:
        existing = [src for src in sources if src.exists()]
        if sum(src.stat().st_size for src in existing) > MAX_STREAM_BYTES:
            print("stream input exceeds 64 MiB", file=sys.stderr)
            return 1
        total = 0
        for src in existing:
            with src.open("rb") as stream:
                data = stream.read(MAX_STREAM_BYTES - total + 1)
            total += len(data)
            if total > MAX_STREAM_BYTES:
                print("stream input exceeds 64 MiB", file=sys.stderr)
                return 1
            lines += data.decode("utf-8", errors="replace").splitlines()
        record = summarize(lines, audit=audit)
        record["rounds_logged"] = len(sources)
        out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        print(f"cannot process stream: {e}", file=sys.stderr)
        return 1
    return 0 if record["result"] is not None else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
