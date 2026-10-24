import json
import unittest

from _path import FIXTURES

# _path must update sys.path before importing action/scripts modules.
# isort: split

import taxonomy
import validate

CATS = taxonomy.names(taxonomy.DEFAULT)
OK = json.loads((FIXTURES / "summary_ok.json").read_text(encoding="utf-8"))
SVG_OK = (FIXTURES / "svg_ok.svg").read_text(encoding="utf-8")


def summary_with(**changes):
    d = dict(OK)
    d.update(changes)
    return json.dumps(d, ensure_ascii=False)


def svg_with(fragment):
    return SVG_OK.replace("</svg>", fragment + "</svg>")


NEW_FIELDS = {
    "problems": ["協助開發者整理重複的工作流程。", "讓團隊可以集中管理專案資料。"],
    "strengths": ["以簡單的介面降低日常操作成本。", "整合現有工具而不需更換開發流程。"],
    "limitations": ["需要自行維護執行環境與相關設定。"],
    "alternatives": [
        {"name": name, "differs": f"{name} 提供不同的整合方式與部署選擇。", "source": source}
        for name, source in (("Firebase", "readme"), ("Appwrite", "model"), ("PocketBase", "model"))
    ],
}
FIT = {"tool": "pi agent", "verdict": "high", "reasons": ["可以整合現有的開發工作流程。"],
       "how": ["透過命令列工具連接專案服務。"]}


def full_summary(**changes):
    return summary_with(**(NEW_FIELDS | changes))


class ResearchTest(unittest.TestCase):
    def test_alternative_search_requires_candidate_repo(self):
        alt = {"name": "Other", "source": "search", "repo": "Owner/Other",
               "differs": "提供另外一種不同的部署與管理方式。"}
        text = full_summary(alternatives=[alt])
        self.assertEqual(validate.validate_summary(text, CATS, candidates={"owner/other"}), [])
        self.assertTrue(validate.validate_summary(text, CATS, candidates=set()))
        self.assertTrue(validate.validate_summary(full_summary(alternatives=[{k: v for k, v in alt.items()
                                                                          if k != "repo"}]), CATS))
        for repo in ("bad", "x/../y", 4, "x/y\n"):
            self.assertTrue(validate.validate_summary(full_summary(alternatives=[dict(alt, repo=repo)]), CATS))
        self.assertTrue(validate.validate_summary(full_summary(alternatives=[dict(alt, source="model")]), CATS))

    def test_research_sources_need_successful_result(self):
        for source in ("deepwiki", "web"):
            item = {"name": "Other", "source": source, "notes": "提供不同的部署方式與整合功能。"}
            text = json.dumps({"items": [item]})
            for status in ("denied", "error", "no_result"):
                run = {"tools": {source: True}, "calls": [{"status": status, "tool": source}]}
                self.assertTrue(validate.validate_research(text, set(), validate.research_sources(run)))
            sources = validate.research_sources({"tools": {source + "_ok": True}})
            self.assertEqual(sources, {source})
            self.assertEqual(validate.validate_research(text, set(), sources), [])
            self.assertEqual(validate.research_sources({"tools": {source + "_ok": 1}}), set())

    def test_research_schema_and_size(self):
        item = {"name": "Other", "source": "search", "repo": "Owner/Other",
                "notes": "提供不同的部署方式與整合功能。"}
        good = json.dumps({"items": [item]})
        self.assertEqual(validate.validate_research(good, {"OWNER/OTHER"}, set()), [])
        self.assertTrue(validate.validate_research(good, set(), set()))
        for data in ({}, [], {"items": [item] * 9}, {"items": [dict(item, extra=1)]},
                     {"items": [dict(item, notes="https://evil.example")]},
                     {"items": [dict(item, repo="bad")]}, {"items": [dict(item, source=[])]}):
            self.assertTrue(validate.validate_research(json.dumps(data), {"Owner/Other"}, set()))
        self.assertTrue(validate.validate_research(" " * (16 * 1024 + 1), set(), set()))
        self.assertTrue(validate.validate_research("not json", set(), set()))

    def test_research_membership_and_no_research(self):
        alt = {"name": "Other", "source": "web", "differs": "提供另外一種不同的部署與管理方式。"}
        text = full_summary(alternatives=[alt])
        research = {"items": [{"name": "OTHER", "source": "web", "notes": "提供不同的部署方式與整合功能。"}]}
        self.assertEqual(validate.validate_summary(text, CATS, research=research), [])
        self.assertEqual(validate.validate_summary(text, CATS), [])
        for unavailable in (None, {"items": []}, {"items": [dict(research["items"][0], source="deepwiki")]}):
            self.assertTrue(validate.validate_summary(text, CATS, research=unavailable))

    def test_differs_copying_readme_rejected(self):
        copied = "這是專案用來展示不同工具功能以及實際部署維護選擇與操作管理方式的完整說明文字"
        alt = {"name": "Other", "source": "model", "differs": copied}
        text = full_summary(alternatives=[alt])
        self.assertTrue(validate.validate_summary(text, CATS, readme_text="前文 " + copied + " 後文"))
        self.assertTrue(validate.validate_summary(text, CATS, description=" \n".join(copied)))
        self.assertEqual(validate.validate_summary(text, CATS, readme_text=copied[:29]), [])
        self.assertEqual(validate.validate_summary(text, CATS, description="不相同的介紹"), [])

    def test_differs_duplicate_ignores_whitespace_and_case(self):
        a = {"name": "One", "source": "model", "differs": "ABC 提供另外一種不同的部署與管理方式。"}
        b = dict(a, name="Two", differs="abc提供另外一種不同的部署與管理方式。")
        self.assertTrue(validate.validate_summary(full_summary(alternatives=[a, b]), CATS))

    def test_research_cli_and_summary_flags(self):
        import contextlib
        import io
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            candidates, research, run, summary, brief = [root / name for name in
                                                       ("candidates", "research", "run", "summary", "brief")]
            candidates.write_text(json.dumps({"items": [{"repo": "Owner/Other"}]}))
            item = {"name": "Other", "source": "web", "notes": "提供不同的部署方式與整合功能。"}
            research.write_text(json.dumps({"items": [item]}))
            run.write_text(json.dumps({"tools": {"web_ok": True}}))
            args = ["research", str(research), "--candidates", str(candidates), "--run-file", str(run)]
            self.assertEqual(validate.main(args), 0)
            run.write_text(json.dumps({"tools": {"web": True, "web_ok": False}}))
            self.assertEqual(validate.main(args), 1)
            alt = {"name": "Other", "source": "web", "differs": "提供另外一種不同的部署與管理方式。"}
            summary.write_text(full_summary(alternatives=[alt]), encoding="utf-8")
            brief.write_text(json.dumps({"description": "不同的介紹"}))
            base = ["summary", str(summary), "--candidates", str(candidates), "--description-file", str(brief)]
            self.assertEqual(validate.main(base + ["--research", str(research)]), 0)
            self.assertEqual(validate.main(base + ["--no-research"]), 1)
            research.write_text("not JSON")
            self.assertEqual(validate.main(base + ["--research", str(research)]), 1)


class SummaryTest(unittest.TestCase):
    def test_summary_full_schema_ok(self):
        self.assertEqual(validate.validate_summary(full_summary(fit=FIT), CATS,
                         expect_tool="pi agent", readme_text="Supports FIREBASE."), [])
        self.assertEqual(validate.validate_summary(full_summary(alternatives=[]), CATS), [])

    def test_summary_new_keys_and_prose(self):
        data = json.loads(full_summary())
        del data["problems"]
        self.assertIn("keys: missing ['problems']", validate.validate_summary(json.dumps(data), CATS))
        for field in ("problems", "strengths", "limitations"):
            for value in ([], ["English only sentence long enough."] * 2, ["中" * 121] * 2, [1, 2]):
                with self.subTest(field=field, value=value):
                    self.assertTrue(validate.validate_summary(full_summary(**{field: value}), CATS))
        for field in ("differs",):
            alt = dict(NEW_FIELDS["alternatives"][0], **{field: "English only sentence long enough."})
            self.assertTrue(validate.validate_summary(full_summary(alternatives=[alt]), CATS))
        for field in ("reasons", "how"):
            self.assertTrue(validate.validate_summary(full_summary(fit=dict(FIT, **{field: ["English sentence long enough."]})), CATS))

    def test_alternatives_rules_and_readme_source(self):
        alt = NEW_FIELDS["alternatives"][0]
        for changes in ({"name": "bad/name"}, {"name": ""}, {"name": "x" * 41},
                        {"source": "unknown"}, {"source": []}, {"extra": 1}):
            with self.subTest(changes=changes):
                self.assertTrue(validate.validate_summary(full_summary(alternatives=[dict(alt, **changes)]), CATS))
        for alternatives in ([alt] * 5, [alt, dict(alt, name="FIREBASE")], [None], None):
            self.assertTrue(validate.validate_summary(full_summary(alternatives=alternatives), CATS))
        errors = validate.validate_summary(full_summary(), CATS, readme_text="not mentioned")
        self.assertIn("alternatives[0]: source readme but name not found in README", errors)

    def test_fit_required_with_profile(self):
        self.assertTrue(validate.validate_summary(full_summary(), CATS, expect_tool="pi agent"))
        self.assertIn('fit.tool: expected "pi agent"', validate.validate_summary(
            full_summary(fit=dict(FIT, tool="other")), CATS, expect_tool="pi agent"))
        self.assertTrue(validate.validate_summary(full_summary(fit=FIT), CATS, expect_tool="PI agent"))

    def test_fit_rejected_with_no_fit(self):
        self.assertEqual(validate.validate_summary(full_summary(), CATS, expect_tool=None), [])
        self.assertIn("fit: not allowed without a valid profile", validate.validate_summary(
            full_summary(fit=FIT), CATS, expect_tool=None))

    def test_fit_shape_only_when_unchecked(self):
        self.assertEqual(validate.validate_summary(full_summary(fit=FIT), CATS), [])
        for fit in (None, [], {}, dict(FIT, extra=1), dict(FIT, tool="bad@tool"),
                    dict(FIT, verdict=[]), dict(FIT, reasons=[])):
            with self.subTest(fit=fit):
                self.assertTrue(validate.validate_summary(full_summary(fit=fit), CATS))

    def test_fit_how_empty_only_for_none(self):
        self.assertEqual(validate.validate_summary(full_summary(fit=dict(FIT, verdict="none", how=[])), CATS), [])
        self.assertTrue(validate.validate_summary(full_summary(fit=dict(FIT, how=[])), CATS))
        self.assertTrue(validate.validate_summary(full_summary(fit=dict(FIT, verdict="none")), CATS))

    def test_new_fields_reject_urls_and_controls(self):
        for payload in ("https://evil.example", "HTTPS://evil.example", "https&#58;//evil.example",
                        "https&amp;#58;//evil.example", "JavaScript:alert(1)", "www.evil.example",
                        "data:text/plain,x", "vbscript:evil", "<b>文字</b>", "字\x00元", "字\n元", "字\x7f元",
                        "&lt;b&gt;文字&lt;/b&gt;", "&lt;a href=&quot;https://evil.example/x&quot;&gt;連結&lt;/a&gt;",
                        "&amp;lt;b&amp;gt;文字"):
            prose = "這是用來測試不安全資料的文字 " + payload
            variants = [{field: [prose, prose]} for field in ("problems", "strengths", "limitations")]
            variants += [{"alternatives": [dict(NEW_FIELDS["alternatives"][0], **{field: prose})]}
                         for field in ("name", "differs", "source")]
            variants += [{"fit": dict(FIT, **{field: [prose] if field in ("reasons", "how") else prose})}
                         for field in ("tool", "verdict", "reasons", "how")]
            for changes in variants:
                with self.subTest(payload=payload, changes=changes):
                    self.assertTrue(validate.validate_summary(full_summary(**changes), CATS))

    def test_summary_size_checked_in_bytes_before_json_parsing(self):
        from unittest.mock import patch

        for text in (" " * (validate.MAX_SUMMARY_BYTES + 1), "字" * (validate.MAX_SUMMARY_BYTES // 3 + 1)):
            with self.subTest(chars=len(text)), patch.object(validate.json, "loads") as loads:
                self.assertEqual(validate.validate_summary(text, CATS), ["summary exceeds 64 KiB"])
                loads.assert_not_called()
        text = json.dumps(OK, ensure_ascii=False)
        padded = " " * (validate.MAX_SUMMARY_BYTES - len(text.encode("utf-8"))) + text
        self.assertEqual(validate.validate_summary(padded, CATS), [])

    def test_summary_ok(self):
        self.assertEqual(validate.validate_summary(json.dumps(OK, ensure_ascii=False), CATS), [])

    def test_summary_rejects_two_json_values(self):
        one = json.dumps(OK, ensure_ascii=False)
        self.assertTrue(validate.validate_summary(one + "\n" + one, CATS))

    def test_summary_rejects_english_only(self):
        self.assertTrue(validate.validate_summary(summary_with(summary="An English only summary that is long enough."), CATS))

    def test_summary_rejects_extra_key(self):
        d = dict(OK, extra=1)
        self.assertTrue(validate.validate_summary(json.dumps(d, ensure_ascii=False), CATS))

    def test_summary_rejects_six_tags(self):
        self.assertTrue(validate.validate_summary(summary_with(tags=["a", "b", "c", "d", "e", "f"]), CATS))

    def test_summary_rejects_uppercase_tag(self):
        self.assertTrue(validate.validate_summary(summary_with(tags=["MCP"]), CATS))

    def test_summary_rejects_unknown_category(self):
        self.assertTrue(validate.validate_summary(summary_with(category="agent-runtime"), CATS))

    def test_summary_rejects_one_highlight(self):
        self.assertTrue(validate.validate_summary(summary_with(highlights=["只有一點值得借鏡的地方而已。"]), CATS))

    def test_summary_rejects_empty_stack(self):
        self.assertTrue(validate.validate_summary(summary_with(stack=[]), CATS))

    def test_summary_rejects_non_object(self):
        self.assertTrue(validate.validate_summary("[1, 2]", CATS))
        self.assertTrue(validate.validate_summary("not json", CATS))

    def test_summary_requires_intro_and_examples(self):
        d = {k: v for k, v in OK.items() if k != "intro"}
        self.assertTrue(validate.validate_summary(json.dumps(d, ensure_ascii=False), CATS))
        self.assertTrue(validate.validate_summary(summary_with(intro="Plain English intro that is long enough to pass."), CATS))
        self.assertTrue(validate.validate_summary(summary_with(examples=[]), CATS))
        self.assertTrue(validate.validate_summary(summary_with(examples=["例如一。", "例如二二。", "例如三三三。"]), CATS))
        self.assertTrue(validate.validate_summary(summary_with(examples=["例如" + "很長" * 70]), CATS))

    def test_summary_requirements_rules(self):
        d = {k: v for k, v in OK.items() if k != "requirements"}
        self.assertTrue(validate.validate_summary(json.dumps(d, ensure_ascii=False), CATS))
        self.assertTrue(validate.validate_summary(summary_with(requirements=[]), CATS))
        self.assertTrue(validate.validate_summary(summary_with(requirements=["一", "二二二二", "三三三三", "四四四四", "五五五五"]), CATS))
        self.assertTrue(validate.validate_summary(summary_with(requirements=["Windows only"]), CATS))
        self.assertTrue(validate.validate_summary(summary_with(requirements=["平台" + "很長" * 60]), CATS))
        self.assertEqual(validate.validate_summary(summary_with(requirements=["不需安裝，直接閱讀"]), CATS), [])

    def test_summary_tagline_rules(self):
        d = {k: v for k, v in OK.items() if k != "tagline"}
        self.assertTrue(validate.validate_summary(json.dumps(d, ensure_ascii=False), CATS))
        self.assertTrue(validate.validate_summary(summary_with(tagline="短"), CATS))
        self.assertTrue(validate.validate_summary(summary_with(tagline="這句副標寫得實在太長了已經超過二十個字的上限"), CATS))
        self.assertTrue(validate.validate_summary(summary_with(tagline="English only tagline"), CATS))


class SvgTest(unittest.TestCase):
    def test_svg_ok_example_passes(self):
        for name in ("svg_ok.svg", "svg_livesummary.svg", "svg_openchatx.svg"):
            with self.subTest(name=name):
                self.assertEqual(validate.validate_svg((FIXTURES / name).read_text(encoding="utf-8")), [])

    def test_svg_rejects_each_fixture(self):
        bad = {
            "script": '<script>alert(1)</script>',
            "onload": '<rect x="0" y="0" width="1" height="1" onload="alert(1)"/>',
            "foreign": '<foreignObject><div>x</div></foreignObject>',
            "ext_href": '<use href="https://evil.example/x.svg#a"/>',
            "style_import": '<style>@import url(http://evil.example/x.css);</style>',
            "image": '<image href="http://evil.example/p.png"/>',
            "fill_url": '<rect x="0" y="0" width="1" height="1" fill="url(http://evil.example/#g)"/>',
            "style_attr": '<rect x="0" y="0" width="1" height="1" style="fill:red"/>',
            "data_uri": '<use href="data:image/svg+xml;base64,AAAA"/>',
        }
        for name, frag in bad.items():
            with self.subTest(name=name):
                self.assertTrue(validate.validate_svg(svg_with(frag)))
        doctype = '<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "y">]>' + SVG_OK.split("?>", 1)[-1]
        self.assertTrue(validate.validate_svg(doctype))
        self.assertTrue(validate.validate_svg("<svg"))

    def test_svg_attribute_allowlist_exact_errors(self):
        # Pins validate_svg's attribute allow-list (event/style/unknown rejected, known and xmlns accepted)
        rect = '<rect x="0" y="0" width="1" height="1" %s/>'
        cases = {
            "onload": ('onload="alert(1)"', ["rect@onload: attribute not allowed"]),
            "style": ('style="fill:red"', ["rect@style: attribute not allowed"]),
            "unknown": ('mystery="1"', ["rect@mystery: attribute not allowed"]),
            "allowed": ('opacity="0.5"', []),
        }
        for name, (attr, expected) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(validate.validate_svg(svg_with(rect % attr)), expected)
        xmlns = '<g xmlns:foo="http://example.com/ns"><rect x="0" y="0" width="1" height="1"/></g>'
        self.assertEqual(validate.validate_svg(svg_with(xmlns)), [])

    def test_svg_rejects_oversize(self):
        self.assertTrue(validate.validate_svg(svg_with("<!--" + "x" * (2 * 1024 * 1024) + "-->")))

    def test_svg_allows_internal_href_and_url_hash(self):
        frag = '<use href="#icon-x"/><path d="M0 0" marker-end="url(#ah)"/>'
        self.assertEqual(validate.validate_svg(svg_with(frag)), [])

    def test_svg_rejects_css_escape_and_strict_paint_grammar(self):
        bad = [
            '<path d="M0 0" marker-end="\\75 rl(https://example.com/track.svg#ah)"/>',
            '<path d="M0 0" marker-end="url(#ah) url(https://e/x)"/>',
            '<rect x="0" y="0" width="1" height="1" fill="u\\rl(http://e)"/>',
            '<rect x="0" y="0" width="1" height="1" fill="expression(alert(1))"/>',
            '<rect x="0" y="0" width="1" height="1" stroke="red;background:url(http://e)"/>',
            '<text x="0" y="0" font-family="a\x01b">x</text>',
        ]
        for frag in bad:
            with self.subTest(frag=frag):
                self.assertTrue(validate.validate_svg(svg_with(frag)))

    def test_svg_accepts_palette_paint_values(self):
        frag = '<rect x="0" y="0" width="1" height="1" fill="none" stroke="#1a1a1a"/><circle cx="1" cy="1" r="1" fill="#FAF8F4"/>'
        self.assertEqual(validate.validate_svg(svg_with(frag)), [])

class CliTest(unittest.TestCase):
    def test_cli_expect_tool_and_target(self):
        import contextlib
        import io
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            summary = target / "summary.json"
            summary.write_text(full_summary(fit=FIT), encoding="utf-8")
            args = ["summary", str(summary), "--target", str(target), "--expect-tool", "pi agent"]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(validate.main(args), 1)
                (target / "README.md").write_text("Firebase", encoding="utf-8")
                self.assertEqual(validate.main(args), 0)
                self.assertEqual(validate.main(args[:-1] + ["other"]), 1)
                self.assertEqual(validate.main(args[:-2] + ["--no-fit"]), 1)
                summary.write_text(full_summary(), encoding="utf-8")
                self.assertEqual(validate.main(args[:-2] + ["--no-fit"]), 0)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                validate.main(args + ["--no-fit"])
            self.assertEqual(caught.exception.code, 2)

    def test_target_readme_candidate_order_and_limits(self):
        import contextlib
        import io
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            summary = target / "summary.json"
            summary.write_text(full_summary(), encoding="utf-8")
            first, second = target / "README.md", target / "README.rst"
            first.write_text("not mentioned", encoding="utf-8")
            second.write_bytes(b"Firebase\xff")
            args = ["summary", str(summary), "--target", str(target)]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(validate.main(args), 1)
                first.write_bytes(b"x" * (512 * 1024 + 1))
                self.assertEqual(validate.main(args), 0)
                first.unlink()
                first.mkdir()
                self.assertEqual(validate.main(args), 0)
                first.rmdir()
                try:
                    first.symlink_to(second)
                except OSError:
                    pass
                else:
                    self.assertEqual(validate.main(args), 0)
                    second.write_text("not mentioned", encoding="utf-8")
                    self.assertEqual(validate.main(args), 1)

    def test_oversize_files_rejected_before_reading(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        for kind, limit, message in (("summary", validate.MAX_SUMMARY_BYTES, "summary exceeds 64 KiB"),
                                     ("svg", validate.SVG_MAX_BYTES, "SVG exceeds 2 MiB")):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / kind
                with path.open("wb") as stream:
                    stream.truncate(limit + 1)
                with (patch.object(Path, "read_text") as read_text,
                      patch("builtins.print") as output):
                    self.assertEqual(validate.main([kind, str(path)]), 1)
                    read_text.assert_not_called()
                    output.assert_called_once_with(message)


    def test_summary_cli_survives_malformed_taxonomy(self):
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        from _path import SCRIPTS
        tmp = Path(tempfile.mkdtemp()) / "taxonomy.yml"
        tmp.write_text("categories: [unterminated\n", encoding="utf-8")
        p = subprocess.run([sys.executable, str(SCRIPTS / "validate.py"), "summary", str(FIXTURES / "summary_ok.json"),
                            "--taxonomy", str(tmp)], capture_output=True, text=True, check=False)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
