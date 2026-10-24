"""Resolve the trusted library profile once; share its state with prompts and validators."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TOOL_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff .+#/-]{0,29}")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_BODY = 4000


def load_profile(path: Path | None) -> tuple[str | None, str]:
    try:
        if path is None:
            raise ValueError("no profile supplied")
        body = CONTROL.sub("", path.read_text(encoding="utf-8"))
        heading = next((line for line in body.splitlines() if line.strip()), "")
        if not heading.startswith("# ") or not TOOL_RE.fullmatch(heading[2:]):
            raise ValueError("first nonblank line must be # <tool name>")
        tool = heading[2:]
        if len(body) > MAX_BODY:
            print("profile: truncated to 4000 characters", file=sys.stderr)
        return tool, body[:MAX_BODY]
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"profile: {exc}; omitting fit", file=sys.stderr)
        return None, ""


def load_state(path: Path) -> tuple[str | None, str]:
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or set(state) != {"tool", "body"}:
        raise ValueError("invalid profile state keys")
    tool, body = state["tool"], state["body"]
    if not isinstance(body, str) or len(body) > MAX_BODY or CONTROL.search(body):
        raise ValueError("invalid profile state body")
    if tool is None:
        if body:
            raise ValueError("null tool requires empty body")
    elif not isinstance(tool, str) or not TOOL_RE.fullmatch(tool):
        raise ValueError("invalid profile state tool")
    return tool, body


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("profile", type=Path)
    resolve.add_argument("state", type=Path)
    summary = commands.add_parser("summary-args")
    summary.add_argument("state", type=Path)
    summary.add_argument("--target", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "resolve":
            tool, body = load_profile(args.profile)
            args.state.write_text(json.dumps({"tool": tool, "body": body}, ensure_ascii=False), encoding="utf-8")
        else:
            tool, _ = load_state(args.state)
            values = ["--target", args.target, "--expect-tool", tool] if tool else ["--target", args.target, "--no-fit"]
            print("\n".join(values))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"profile: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
