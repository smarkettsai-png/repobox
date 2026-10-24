"""Validators for model output: summary.json schema and an SVG element/attribute allowlist.

CLI: validate.py summary <file> [--taxonomy <yml>] [--expect-tool <name> | --no-fit]
                         [--target <dir>] | validate.py svg <file>
Exit 0 with no output when valid; otherwise one error per line and exit 1.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import taxonomy
from entry import to_plain

CJK = re.compile(r"[一-鿿]")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,39}$")
STACK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .+#/-]{0,29}$")
REQUIRED_KEYS = {"tagline", "intro", "examples", "requirements", "summary", "category", "tags", "stack", "highlights",
                 "problems", "strengths", "limitations", "alternatives"}
OPTIONAL_KEYS = {"fit"}
SUMMARY_KEYS = REQUIRED_KEYS | OPTIONAL_KEYS
UNCHECKED = object()
ALT_NAME_RE = re.compile(r"^[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff .+#_-]{0,39}$")
TOOL_RE = re.compile(r"^[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff .+#/-]{0,29}$")
URL_RE = re.compile(r"(?:[a-z][a-z0-9+.-]*:\s*//|www\.|javascript\s*:|data\s*:|vbscript\s*:)")
NEW_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_SUMMARY_BYTES = 64 * 1024
SVG_MAX_BYTES = 2 * 1024 * 1024

# Everything arch-blueprint's example and icon library use, plus a few harmless shape/text
# elements. No style, script, foreignObject, image or a: those are how SVG reaches the network.
SVG_ELEMENTS = {
    "svg", "title", "desc", "defs", "symbol", "g", "rect", "path", "line", "polyline",
    "polygon", "circle", "ellipse", "text", "tspan", "use", "marker",
}
SVG_ATTRS = {
    "aria-hidden", "aria-labelledby", "class", "cx", "cy", "d", "data-edge", "fill",
    "fill-opacity", "font-family", "font-size", "font-weight", "height", "href", "id",
    "letter-spacing", "marker-end", "marker-start", "markerHeight", "markerWidth", "orient",
    "points", "r", "refX", "refY", "role", "rx", "ry", "stroke", "stroke-dasharray",
    "stroke-linecap", "stroke-linejoin", "stroke-opacity", "stroke-width", "text-anchor",
    "transform", "viewBox", "width", "x", "x1", "x2", "y", "y1", "y2", "dominant-baseline",
    "opacity", "xmlns", "version",
}
INTERNAL_URL = r"url\(#[A-Za-z0-9_-]+\)"
# Exact grammars: a CSS escape such as "\75 rl(...)" can never match these.
STRICT = {
    "marker-start": re.compile(rf"^{INTERNAL_URL}$"),
    "marker-end": re.compile(rf"^{INTERNAL_URL}$"),
    "fill": re.compile(rf"^(none|transparent|currentColor|#[0-9A-Fa-f]{{3}}|#[0-9A-Fa-f]{{6}}|#[0-9A-Fa-f]{{8}}|{INTERNAL_URL})$"),
    "stroke": re.compile(rf"^(none|transparent|currentColor|#[0-9A-Fa-f]{{3}}|#[0-9A-Fa-f]{{6}}|#[0-9A-Fa-f]{{8}}|{INTERNAL_URL})$"),
}
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _new_string(value: object, minimum: int, maximum: int, *, prose: bool = False) -> bool:
    return (isinstance(value, str) and minimum <= len(value) <= maximum
            and not NEW_CONTROL.search(value) and "<" not in value and ">" not in value
            and not URL_RE.search(to_plain(value).casefold())
            and (not prose or bool(CJK.search(value))))


def _prose_list(value: object, minimum: int, maximum: int) -> bool:
    return (isinstance(value, list) and minimum <= len(value) <= maximum
            and all(_new_string(v, 10, 120, prose=True) for v in value))


def validate_summary(text: str, categories: list[str], *, expect_tool=UNCHECKED,
                     readme_text: str | None = None) -> list[str]:
    if len(text.encode("utf-8")) > MAX_SUMMARY_BYTES:
        return ["summary exceeds 64 KiB"]
    try:
        data = json.loads(text)
    except ValueError as e:
        return [f"not a single JSON value: {e}"]
    if not isinstance(data, dict):
        return ["top level must be an object"]
    errors = []
    if missing := REQUIRED_KEYS - set(data):
        errors.append(f"keys: missing {sorted(missing)}")
    if unexpected := set(data) - SUMMARY_KEYS:
        errors.append(f"keys: unexpected {sorted(unexpected)}")
    tagline = data.get("tagline")
    if not (isinstance(tagline, str) and 4 <= len(tagline) <= 20 and CJK.search(tagline)):
        errors.append("tagline: 4-20 chars of plain Traditional Chinese")
    intro = data.get("intro")
    if not (isinstance(intro, str) and 30 <= len(intro) <= 300 and CJK.search(intro)):
        errors.append("intro: 30-300 chars of plain Traditional Chinese")
    ex = data.get("examples")
    if not (isinstance(ex, list) and 1 <= len(ex) <= 2
            and all(isinstance(e, str) and 10 <= len(e) <= 120 and CJK.search(e) for e in ex)):
        errors.append("examples: 1-2 Chinese sentences of 10-120 chars")
    req = data.get("requirements")
    if not (isinstance(req, list) and 1 <= len(req) <= 4
            and all(isinstance(r, str) and 2 <= len(r) <= 100 and CJK.search(r) for r in req)):
        errors.append("requirements: 1-4 Chinese lines of 2-100 chars")
    summary = data.get("summary")
    if not (isinstance(summary, str) and 20 <= len(summary) <= 600 and CJK.search(summary)):
        errors.append("summary: 20-600 chars with Traditional Chinese text")
    if data.get("category") not in categories:
        errors.append(f"category: must be one of {categories}")
    tags = data.get("tags")
    if not (isinstance(tags, list) and len(tags) <= 5
            and all(isinstance(t, str) and TAG_RE.match(t) for t in tags)):
        errors.append("tags: at most 5 lowercase tags")
    stack = data.get("stack")
    if not (isinstance(stack, list) and 1 <= len(stack) <= 8
            and all(isinstance(s, str) and STACK_RE.match(s) for s in stack)):
        errors.append("stack: 1-8 short names")
    hl = data.get("highlights")
    if not (isinstance(hl, list) and 2 <= len(hl) <= 3
            and all(isinstance(h, str) and 10 <= len(h) <= 120 and CJK.search(h) for h in hl)):
        errors.append("highlights: 2-3 Chinese sentences of 10-120 chars")
    for field, minimum in (("problems", 2), ("strengths", 2), ("limitations", 1)):
        if not _prose_list(data.get(field), minimum, 4):
            errors.append(f"{field}: {minimum}-4 Chinese sentences of 10-120 chars without URLs or HTML")
    alternatives = data.get("alternatives")
    if not isinstance(alternatives, list) or len(alternatives) > 4:
        errors.append("alternatives: 0-4 objects")
    else:
        seen = set()
        for i, alt in enumerate(alternatives):
            label = f"alternatives[{i}]"
            if not isinstance(alt, dict) or set(alt) != {"name", "differs", "source"}:
                errors.append(f"{label}: keys must be name, differs, source")
                continue
            name = alt["name"]
            if not (_new_string(name, 1, 40) and ALT_NAME_RE.fullmatch(name)):
                errors.append(f"{label}.name: invalid short name")
            else:
                folded = name.casefold()
                if folded in seen:
                    errors.append(f"{label}.name: duplicate name")
                seen.add(folded)
                if alt["source"] == "readme" and readme_text is not None and folded not in readme_text.casefold():
                    errors.append(f"{label}: source readme but name not found in README")
            if not _new_string(alt["differs"], 10, 120, prose=True):
                errors.append(f"{label}.differs: Chinese sentence of 10-120 chars without URLs or HTML")
            if alt["source"] not in ("readme", "model"):
                errors.append(f"{label}.source: must be readme or model")
    if expect_tool is None and "fit" in data:
        errors.append("fit: not allowed without a valid profile")
    elif expect_tool is not UNCHECKED and expect_tool is not None and "fit" not in data:
        errors.append("fit: required with a valid profile")
    if "fit" in data:
        fit = data["fit"]
        if not isinstance(fit, dict) or set(fit) != {"tool", "verdict", "reasons", "how"}:
            errors.append("fit: keys must be tool, verdict, reasons, how")
        else:
            tool = fit["tool"]
            if not (_new_string(tool, 1, 30) and TOOL_RE.fullmatch(tool)):
                errors.append("fit.tool: invalid short name")
            if expect_tool is not UNCHECKED and expect_tool is not None and tool != expect_tool:
                errors.append(f'fit.tool: expected "{expect_tool}"')
            if fit["verdict"] not in ("high", "medium", "low", "none"):
                errors.append("fit.verdict: must be high, medium, low or none")
            if not _prose_list(fit["reasons"], 1, 3):
                errors.append("fit.reasons: 1-3 Chinese sentences of 10-120 chars without URLs or HTML")
            how_min, how_max = (0, 0) if fit["verdict"] == "none" else (1, 3)
            if not _prose_list(fit["how"], how_min, how_max):
                errors.append(f"fit.how: {how_min}-{how_max} Chinese sentences of 10-120 chars without URLs or HTML")
    return errors


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def validate_svg(text: str) -> list[str]:
    if len(text.encode("utf-8")) > SVG_MAX_BYTES:
        return ["svg larger than 2 MiB"]
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.IGNORECASE):
        return ["DOCTYPE/ENTITY not allowed"]
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return [f"not well-formed XML: {e}"]
    errors = []
    for el in root.iter():
        tag = _local(el.tag) if isinstance(el.tag, str) else "?"
        if tag not in SVG_ELEMENTS:
            errors.append(f"{tag}: element not allowed")
            continue
        for raw_name, value in el.attrib.items():
            name = _local(raw_name)
            low = value.strip().lower()
            if (name.startswith("on") or name == "style"
                    or (name not in SVG_ATTRS and not raw_name.startswith("{http://www.w3.org/2000/xmlns/}"))):
                errors.append(f"{tag}@{name}: attribute not allowed")
            elif "\\" in value or CONTROL.search(value):
                errors.append(f"{tag}@{name}: escapes and control characters not allowed")
            elif name == "href" and not value.startswith("#"):
                errors.append(f"{tag}@{name}: only internal #references allowed")
            elif name in STRICT and not STRICT[name].match(value.strip()):
                errors.append(f"{tag}@{name}: value {value[:40]!r} not allowed")
            elif name not in STRICT and "url(" in low:
                errors.append(f"{tag}@{name}: url() not allowed here")
            elif "javascript:" in low or "data:" in low:
                errors.append(f"{tag}@{name}: script or data URI not allowed")
    return errors


def _read_target_readme(target: Path) -> str:
    for name in ("README.md", "README.MD", "readme.md", "README.rst", "README.txt", "README"):
        path = target / name
        try:
            if not path.is_symlink() and path.is_file() and path.stat().st_size <= 512 * 1024:
                return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return ""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["summary", "svg"])
    ap.add_argument("file", type=Path)
    ap.add_argument("--taxonomy", type=Path)
    fit_args = ap.add_mutually_exclusive_group()
    fit_args.add_argument("--expect-tool", default=UNCHECKED)
    fit_args.add_argument("--no-fit", action="store_const", const=None, dest="expect_tool")
    ap.add_argument("--target", type=Path)
    args = ap.parse_args(argv)
    try:
        limit = MAX_SUMMARY_BYTES if args.kind == "summary" else SVG_MAX_BYTES
        if args.file.stat().st_size > limit:
            print("summary exceeds 64 KiB" if args.kind == "summary" else "SVG exceeds 2 MiB")
            return 1
        text = args.file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"cannot read {args.file}: {e}")
        return 1
    if args.kind == "summary":
        readme_text = _read_target_readme(args.target) if args.target is not None else None
        errors = validate_summary(text, taxonomy.names(taxonomy.load_or_default(args.taxonomy)),
                                  expect_tool=args.expect_tool, readme_text=readme_text)
    else:
        errors = validate_svg(text)
    for e in errors:
        print(e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
