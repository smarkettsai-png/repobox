import json
import re
import tempfile
import unittest
from pathlib import Path

from _path import SCRIPTS  # noqa: F401

# _path must update sys.path before importing action/scripts modules.
# isort: split

import entry

META = {
    "id": 42, "full_name": "Owner/Repo", "html_url": "https://github.com/Owner/Repo",
    "description": "A <b>tool</b>", "language": "Python", "stargazers_count": 7, "license": None,
}
ANALYSIS = {
    "tagline": "測試用的一句白話副標",
    "intro": "一個給人用的白話介紹，說明這個工具能幫你做什麼事情，以及為什麼你會想用它。", "examples": ["用它來整理下載資料夾裡的檔案。", "用它來幫專案自動寫測試。"],
    "requirements": ["平台：只支援 Windows", "費用：免費"],
    "summary": "這是一個工具，用來測試條目產生是否正確。", "category": "dev-tool", "tags": ["cli"],
    "stack": ["Python", "C#"], "highlights": ["第一個值得借鏡的地方。", "第二個值得借鏡的地方。"],
    "problems": ["協助開發者整理重複的工作流程。", "讓團隊可以集中管理專案資料。"],
    "strengths": ["以簡單的介面降低日常操作成本。", "整合現有工具而不需更換開發流程。"],
    "limitations": ["需要自行維護執行環境與相關設定。"],
    "alternatives": [{"name": "Firebase", "differs": "提供不同的整合方式與部署選擇。", "source": "readme"},
                     {"name": "Appwrite", "differs": "以不同的部署方式支援專案服務。", "source": "model"}],
    "fit": {"tool": "pi agent", "verdict": "high", "reasons": ["可以整合現有的開發工作流程。"],
            "how": ["透過命令列工具連接專案服務。"]},
}
RUN = {"model": "claude-opus-5-5", "turns": 3, "wall_s": 60, "rounds": 0, "deepwiki": False, "diagram": True}
END_ENCODINGS = [
    "<!-- repobox:auto:end -->",
    "&lt;!-- repobox:auto:end --&gt;",
    "&amp;lt;!-- repobox:auto:end --&amp;gt;",
    "<!-- REPOBOX:AUTO:END -->",
]


def write(path, fm, analysis=ANALYSIS, svg="owner__repo.svg", user=None, auto=None):
    entry.write_entry_files(path, fm, entry.render_entry(fm, analysis, svg, user, auto=auto))


class EntryTest(unittest.TestCase):
    def setUp(self):
        self.lib = Path(tempfile.mkdtemp())
        self.fm = entry.build_frontmatter(META, ANALYSIS, [], None, RUN, now="2026-10-18T00:00:00+00:00")

    def test_render_new_sections_and_sources(self):
        text = entry.render_entry(self.fm, ANALYSIS, None, None)
        headings = ["## 技術摘要", "## 解決什麼問題", "## 優勢", "## 限制", "## 同類比較", "## pi agent 適用性", "## 值得借鏡"]
        positions = [text.index(h) for h in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("- Firebase：提供不同的整合方式與部署選擇。（README 提及）", text)
        self.assertIn("- Appwrite：以不同的部署方式支援專案服務。（依模型知識，未驗證）", text)
        for verdict, label in (("high", "高"), ("medium", "中"), ("low", "低"), ("none", "不適用")):
            with self.subTest(verdict=verdict):
                analysis = dict(ANALYSIS, fit=dict(ANALYSIS["fit"], verdict=verdict))
                self.assertIn("結論：" + label, entry.render_entry(self.fm, analysis, None, None))
        self.assertIn("- 可以整合現有的開發工作流程。", text)
        self.assertIn("- 透過命令列工具連接專案服務。", text)

    def test_render_missing_fit_and_legacy_sections(self):
        analysis = {k: v for k, v in ANALYSIS.items() if k != "fit"}
        fm = entry.build_frontmatter(META, analysis, [], None, RUN)
        self.assertIsNone(fm["fit"])
        self.assertNotIn("適用性", entry.render_entry(fm, analysis, None, None))
        legacy = {k: v for k, v in analysis.items() if k not in ("problems", "strengths", "limitations", "alternatives")}
        fm = entry.build_frontmatter(META, legacy, [], None, RUN)
        text = entry.render_entry(fm, legacy, None, None)
        for heading in ("解決什麼問題", "優勢", "限制", "同類比較", "適用性"):
            self.assertNotIn("## " + heading, text)

    def test_alternatives_and_fit_plain_texted(self):
        hostile = "<b>文字</b> &amp;lt;!-- repobox:auto:end --&amp;gt; [點我](http://evil.example)"
        analysis: dict = dict(ANALYSIS, alternatives=[{"name": hostile, "differs": hostile, "source": "model"}],
                        fit={"tool": hostile, "verdict": "high", "reasons": [hostile], "how": [hostile]})
        for key in ("problems", "strengths", "limitations"):
            analysis[key] = [hostile]
        fm = entry.build_frontmatter(META, analysis, [], None, RUN)
        plain = entry.to_plain(hostile)
        self.assertEqual(fm["alternatives"], [{"name": plain, "differs": plain, "source": "model"}])
        self.assertEqual(fm["fit"], {"tool": plain, "verdict": "high", "reasons": [plain], "how": [plain]})
        for key in ("problems", "strengths", "limitations"):
            self.assertEqual(fm[key], [plain])
        text = entry.render_entry(fm, analysis, None, None)
        self.assertEqual(text.count(entry.START), 1)
        self.assertEqual(text.count(entry.END), 1)
        self.assertNotIn("<b>", text)
        self.assertNotIn("](http", text)
        self.assertIn(entry.safe_text(hostile), text)
        dedup = entry.build_frontmatter(META, None, [], fm, None)
        for key in ("problems", "strengths", "limitations", "alternatives", "fit"):
            self.assertEqual(dedup[key], fm[key])
        path = self.lib / "hostile.md"
        write(path, fm, analysis=analysis)
        stored = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(list(stored), list(entry.FM_KEYS))
        self.assertEqual(stored["alternatives"], fm["alternatives"])
        self.assertEqual(stored["fit"], fm["fit"])
        head = text.split(entry.START, 1)[0]
        for key in ("problems:", "strengths:", "limitations:", "alternatives:", "fit:"):
            self.assertNotIn(key, head)

    def test_slug(self):
        self.assertEqual(entry.slug("Owner/My.Repo"), "owner__my.repo")

    def test_to_plain_kills_marker_in_four_encodings(self):
        for raw in END_ENCODINGS:
            with self.subTest(raw=raw):
                out = entry.to_plain(f"前 {raw} 後")
                self.assertNotIn("<", out)
                self.assertNotIn("<!--", out)

    def test_to_plain_folds_whitespace_and_strips_tags(self):
        self.assertEqual(entry.to_plain(" a <b>bold</b>\n\n c "), "a bold c")

    def test_md_escape_neutralizes_link_and_image(self):
        out = entry.md_escape("[x](http://e) ![](http://e)")
        for ch in "[]()!":
            for i, c in enumerate(out):
                if c == ch:
                    self.assertEqual(out[i - 1], "\\", f"{ch} at {i} in {out!r}")

    def test_render_has_exactly_one_start_and_end(self):
        hostile = dict(ANALYSIS, summary="摘要內容藏了 <!-- repobox:auto:end --> 還有 <!-- repobox:auto:start --> 標記")
        text = entry.render_entry(self.fm, hostile, "owner__repo.svg", None)
        self.assertEqual(text.count(entry.START), 1)
        self.assertEqual(text.count(entry.END), 1)
        self.assertLess(text.index(entry.START), text.index(entry.END))

    def test_render_raises_if_markers_duplicated(self):
        with self.assertRaises(ValueError):
            entry.render_entry(self.fm, ANALYSIS, None, "\n" + entry.START + "\n")

    def test_render_without_svg_has_no_image_line(self):
        text = entry.render_entry(self.fm, ANALYSIS, None, None)
        self.assertNotIn("![architecture]", text)
        self.assertNotIn("## 架構圖", text)

    def test_render_escapes_model_text(self):
        hostile = dict(ANALYSIS, highlights=["看這裡 [點我](http://evil.example) 很好。", "第二點 ![](http://evil.example/t.png) 也好。"])
        text = entry.render_entry(self.fm, hostile, None, None)
        self.assertNotIn("](http", text)
        self.assertIn("C\\#", text)

    def test_user_section_preserved_bytewise(self):
        p = self.lib / "owner__repo.md"
        user = "\n## 我的筆記\n- 我的字\n\n  trailing  \n"
        write(p, self.fm, user=user)
        fm, got = entry.read_entry(p)
        self.assertEqual(got, user)
        self.assertEqual(fm["repo_id"], 42)
        write(p, entry.read_record(p), user=got)
        self.assertEqual(entry.read_entry(p)[1], user)

    def test_read_entry_splits_at_first_end(self):
        p = self.lib / "x.md"
        p.write_text("---\nrepo_id: 1\n---\n" + entry.START + "\nauto\n" + entry.END + "\nnote " + entry.END + " more\n", encoding="utf-8")
        _fm, user = entry.read_entry(p)
        self.assertEqual(user, "\nnote " + entry.END + " more\n")
        self.assertEqual(entry.read_auto(p), "\nauto\n")

    def test_read_entry_without_markers_or_frontmatter(self):
        p = self.lib / "x.md"
        p.write_text("just notes\n", encoding="utf-8")
        self.assertEqual(entry.read_entry(p), ({}, "just notes\n"))

    def test_find_entry_by_repo_id_when_slug_differs(self):
        old = self.lib / "oldowner__oldname.md"
        write(old, self.fm)
        self.assertEqual(entry.find_entry(self.lib, 42, "NewOwner/NewName"), old)

    def test_find_entry_by_slug_fallback(self):
        p = self.lib / "owner__repo.md"
        p.write_text("no frontmatter\n", encoding="utf-8")
        self.assertEqual(entry.find_entry(self.lib, 99, "Owner/Repo"), p)

    def test_find_entry_none(self):
        self.assertIsNone(entry.find_entry(self.lib, 99, "Owner/Repo"))

    def test_frontmatter_key_order_and_license_none(self):
        self.assertEqual(list(self.fm), [
            "repo", "repo_id", "url", "description", "language", "stars", "stars_at", "license", "category",
            "tags", "stack", "tagline", "intro", "examples", "requirements", "summary", "highlights",
            "problems", "strengths", "limitations", "alternatives", "fit", "sightings",
            "analyzed_at", "analysis",
        ])
        self.assertEqual(self.fm["stars_at"], "2026-10-18")
        self.assertIsNone(self.fm["license"])
        self.assertEqual(self.fm["description"], "A tool")
        self.assertEqual(self.fm["analysis"], RUN)
        fm2 = entry.build_frontmatter(dict(META, license={"spdx_id": "MIT"}), ANALYSIS, [], None, RUN)
        self.assertEqual(fm2["license"], "MIT")

    def test_dedup_keeps_prev_analysis_fields(self):
        meta = dict(META, stargazers_count=99, full_name="Owner/Renamed", html_url="https://github.com/Owner/Renamed")
        fm = entry.build_frontmatter(meta, None, [{"id": "a", "at": "2026-10-18T01:00:00+08:00"}], self.fm, None)
        for k in ("category", "tags", "stack", "analyzed_at", "analysis"):
            self.assertEqual(fm[k], self.fm[k])
        self.assertEqual(fm["stars"], 99)
        self.assertEqual(fm["repo"], "Owner/Renamed")

    def test_dedup_render_reuses_auto_block(self):
        p = self.lib / "owner__repo.md"
        write(p, self.fm, user="\n## 我的筆記\nkeep\n")
        auto = entry.read_auto(p)
        _, user = entry.read_entry(p)
        text = entry.render_entry(entry.read_record(p), None, None, user, auto=auto)
        self.assertEqual(text.split(entry.START, 1)[1], p.read_text(encoding="utf-8").split(entry.START, 1)[1])

    def test_write_sighting_and_merge(self):
        s1 = entry.write_sighting("20261018-1", {"captured_at": "2026-10-18T02:00:00+08:00", "source": "threads", "note": "x" * 900})
        self.assertEqual(s1["id"], "20261018-1")
        self.assertEqual(len(s1["note"]), 500)
        s2 = entry.write_sighting("20261018-2", {"captured_at": "2026-10-18T02:00:00+08:00"})
        legacy = {"at": "2026-10-17T00:00:00+08:00", "source": "x"}
        merged = entry.merge_sightings([legacy, s1], [s1, s2])
        self.assertEqual(merged, [legacy, s1, s2])
        self.assertEqual(entry.merge_sightings(merged, [s1, s2]), merged)

    def test_merge_sightings_orders_by_instant_not_string(self):
        a = {"id": "a", "at": "2026-10-18T00:30:00+00:00"}
        b = {"id": "b", "at": "2026-10-18T07:00:00+08:00"}
        self.assertEqual(entry.merge_sightings([], [a, b]), [b, a])

    def test_safe_text_defuses_bare_autolinks(self):
        cases = {
            "請查看 https://evil.example/a 吧": "`https://evil.example/a`",
            "或 http://e.example/x?y=1": "`http://e.example/x?y=1`",
            "還有 www.evil.example 喔": "`www.evil.example`",
            "寄信 a.b@evil.example 吧": "`a.b@evil.example`",
        }
        for raw, wrapped in cases.items():
            with self.subTest(raw=raw):
                out = entry.safe_text(raw)
                self.assertIn(wrapped, out)
                self.assertEqual(out.count("`"), 2)

    def test_safe_text_backtick_in_url_cannot_break_code_span(self):
        out = entry.safe_text("see https://e.example/`[x](http://f)")
        self.assertEqual(out.count("`"), 2)
        outside = re.sub(r"`[^`]*`", "", out)
        self.assertNotIn("](http", outside)
        self.assertNotIn("http", outside)

    def test_render_puts_intro_first_with_examples(self):
        text = entry.render_entry(self.fm, ANALYSIS, None, None)
        self.assertLess(text.index("## 這是什麼"), text.index("## 技術摘要"))
        self.assertIn("- **例如**：用它來整理下載資料夾裡的檔案。", text)
        self.assertNotIn("## 摘要\n", text)

    def test_render_has_no_notes_section(self):
        text = entry.render_entry(self.fm, ANALYSIS, None, None)
        self.assertNotIn("我的筆記", text)
        self.assertTrue(text.endswith(entry.END + "\n"))

    def test_legacy_empty_notes_heading_is_dropped(self):
        text = entry.render_entry(self.fm, ANALYSIS, None, "\n## 我的筆記\n\n")
        self.assertNotIn("我的筆記", text)

    def test_real_user_text_after_end_is_kept(self):
        text = entry.render_entry(self.fm, ANALYSIS, None, "\n## 我的筆記\n- 有寫東西\n")
        self.assertIn("- 有寫東西", text)

    def test_display_frontmatter_is_human_sized(self):
        rec = dict(self.fm, sightings=[{"id": "a", "at": "2026-10-17T22:03:40+08:00"},
                                       {"id": "b", "at": "2026-10-18T09:00:00+08:00"}])
        disp = entry.display_frontmatter(rec)
        self.assertEqual(list(disp), ["repo", "repo_id", "url", "description", "language", "stars", "license",
                                      "category", "tags", "stack", "收藏次數", "最後看到"])
        self.assertEqual(disp["stars"], "7（2026-10-18）")
        self.assertEqual(disp["收藏次數"], 2)
        self.assertEqual(disp["最後看到"], "2026-10-18")

    def test_last_seen_falls_back_to_analyzed_date(self):
        self.assertEqual(entry.display_frontmatter(self.fm)["最後看到"], "2026-10-18")

    def test_rendered_table_hides_machine_fields(self):
        text = entry.render_entry(self.fm, ANALYSIS, None, None)
        head = text.split(entry.START, 1)[0]
        for key in ("analysis:", "sightings:", "analyzed_at:", "stars_at:"):
            self.assertNotIn(key, head)

    def test_read_record_merges_sidecar(self):
        p = self.lib / "owner__repo.md"
        rec = dict(self.fm, sightings=[{"id": "a", "at": "2026-10-18T09:00:00+08:00"}])
        write(p, rec)
        self.assertTrue((self.lib / "owner__repo.json").exists())
        got = entry.read_record(p)
        self.assertEqual(got["sightings"], rec["sightings"])
        self.assertEqual(got["analysis"], RUN)
        self.assertEqual(got["stars"], 7)

    def test_read_record_legacy_frontmatter_only(self):
        p = self.lib / "old.md"
        p.write_text("---\nrepo: Owner/Repo\nrepo_id: 42\nstars: 3\nsightings:\n- id: a\n  at: '2026-10-17T00:00:00+08:00'\n"
                     "analysis:\n  model: m\n---\n" + entry.START + "\nx\n" + entry.END + "\n", encoding="utf-8")
        got = entry.read_record(p)
        self.assertEqual(got["sightings"][0]["id"], "a")
        self.assertEqual(got["analysis"], {"model": "m"})

    def test_read_record_rejects_corrupt_sidecar(self):
        p = self.lib / "owner__repo.md"
        write(p, self.fm)
        (self.lib / "owner__repo.json").write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            entry.read_record(p)

    def test_write_entry_files_handles_yaml_dates_and_writes_sidecar_first(self):
        import datetime as dt
        p = self.lib / "owner__repo.md"
        rec = dict(self.fm, analyzed_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
                   sightings=[{"id": "a", "at": dt.date(2026, 10, 1)}])
        entry.write_entry_files(p, rec, "md text")
        side = json.loads((self.lib / "owner__repo.json").read_text(encoding="utf-8"))
        self.assertEqual(side["analyzed_at"], "2026-10-01 00:00:00+00:00")
        self.assertEqual(side["sightings"][0]["at"], "2026-10-01")
        self.assertEqual(p.read_text(encoding="utf-8"), "md text")

    def symlink_or_skip(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as e:
            self.skipTest(f"OS cannot create symlinks: {e}")

    def test_write_rejects_symlink_siblings_before_changing_any_file(self):
        for i, suffix in enumerate((".md", ".json", ".svg")):
            for dangling in (False, True):
                with self.subTest(suffix=suffix, dangling=dangling):
                    library = self.lib / f"library-{i}-{dangling}"
                    library.mkdir()
                    md = library / "owner__repo.md"
                    outside = self.lib / f"outside-{i}-{dangling}"
                    if not dangling:
                        outside.write_text("outside sentinel", encoding="utf-8")
                    link = md.with_suffix(suffix)
                    self.symlink_or_skip(link, outside)
                    with self.assertRaises(ValueError):
                        entry.write_entry_files(md, self.fm, "new text")
                    self.assertEqual(list(library.iterdir()), [link])
                    self.assertTrue(link.is_symlink())
                    self.assertEqual(outside.read_text(encoding="utf-8") if outside.exists() else None,
                                     None if dangling else "outside sentinel")

    def test_write_rejects_symlink_library_root(self):
        outside = self.lib / "outside"
        outside.mkdir()
        sentinel = outside / "sentinel"
        sentinel.write_text("keep", encoding="utf-8")
        library = self.lib / "library"
        self.symlink_or_skip(library, outside, directory=True)
        with self.assertRaises(ValueError):
            entry.write_entry_files(library / "owner__repo.md", self.fm, "new text")
        self.assertEqual(list(outside.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_write_target_must_resolve_inside_library(self):
        outside = self.lib.parent / "outside.md"
        with self.assertRaises(ValueError):
            entry.check_write_paths(outside, self.lib)

    def test_md_untouched_when_sidecar_cannot_be_written(self):

        p = self.lib / "owner__repo.md"
        p.write_text("original", encoding="utf-8")
        (self.lib / "owner__repo.json").mkdir()
        with self.assertRaises(OSError):
            entry.write_entry_files(p, self.fm, "new text")
        self.assertEqual(p.read_text(encoding="utf-8"), "original")

    def test_sidecar_restored_when_markdown_write_fails(self):
        p = self.lib / "owner__repo.md"
        side = self.lib / "owner__repo.json"
        side.write_text('{"old": true}', encoding="utf-8")
        p.mkdir()
        with self.assertRaises(OSError):
            entry.write_entry_files(p, self.fm, "new text")
        self.assertEqual(side.read_text(encoding="utf-8"), '{"old": true}')

    def test_new_sidecar_removed_when_markdown_write_fails(self):
        p = self.lib / "fresh.md"
        p.mkdir()
        with self.assertRaises(OSError):
            entry.write_entry_files(p, self.fm, "new text")
        self.assertFalse((self.lib / "fresh.json").exists())

    def test_render_requirements_after_intro(self):
        text = entry.render_entry(self.fm, ANALYSIS, None, None)
        self.assertLess(text.index("## 這是什麼"), text.index("## 使用門檻"))
        self.assertLess(text.index("## 使用門檻"), text.index("## 技術摘要"))
        self.assertIn("- 平台：只支援 Windows\n- 費用：免費\n", text)

    def test_record_carries_reading_fields(self):
        for k in ("intro", "examples", "requirements", "summary", "highlights"):
            self.assertEqual(self.fm[k], [entry.to_plain(x) for x in ANALYSIS[k]] if isinstance(ANALYSIS[k], list) else entry.to_plain(ANALYSIS[k]))

    def test_reading_fields_are_plain(self):
        fm = entry.build_frontmatter(META, dict(ANALYSIS, intro="一個 <b>粗體</b> 的介紹文字，說明這個工具能做什麼事。"), [], None, RUN)
        self.assertEqual(fm["intro"], "一個 粗體 的介紹文字，說明這個工具能做什麼事。")

    def test_dedup_keeps_prev_reading_fields(self):
        fm = entry.build_frontmatter(META, None, [], self.fm, None)
        self.assertEqual(fm["requirements"], self.fm["requirements"])
        self.assertEqual(fm["intro"], self.fm["intro"])

    def test_dedup_without_prev_reading_fields_is_none(self):
        legacy = {k: v for k, v in self.fm.items() if k not in entry.READING_KEYS}
        fm = entry.build_frontmatter(META, None, [], legacy, None)
        self.assertIsNone(fm["intro"])
        self.assertIsNone(fm["highlights"])

    def test_display_frontmatter_hides_reading_fields(self):
        disp = entry.display_frontmatter(self.fm)
        for k in entry.READING_KEYS:
            self.assertNotIn(k, disp)

    def test_record_and_render_carry_tagline(self):
        self.assertEqual(self.fm["tagline"], ANALYSIS["tagline"])
        text = entry.render_entry(self.fm, ANALYSIS, None, None)
        self.assertIn("> " + ANALYSIS["tagline"], text)
        self.assertLess(text.index("> " + ANALYSIS["tagline"]), text.index("## 這是什麼"))


if __name__ == "__main__":
    unittest.main()
