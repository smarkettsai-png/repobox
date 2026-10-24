import json
import tempfile
import unittest
from pathlib import Path

from _path import SCRIPTS  # noqa: F401

# _path must update sys.path before importing action/scripts modules.
# isort: split

import index
import taxonomy
from helpers import write_entry


def s(at, sid="x"):
    return {"id": sid, "at": at}


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.lib = Path(tempfile.mkdtemp()) / "library"

    def test_collect_reads_svg_presence_and_last_seen(self):
        write_entry(self.lib, "A/One", 1, [s("2026-10-01T00:00:00+00:00"), s("2026-10-05T00:00:00+08:00", "y")], svg=True)
        write_entry(self.lib, "B/Two", 2)
        got = {e["repo"]: e for e in index.collect(self.lib)}
        self.assertEqual(got["A/One"]["svg"], "library/a__one.svg")
        self.assertEqual(got["A/One"]["md"], "library/a__one.md")
        self.assertEqual(got["A/One"]["last_seen"], "2026-10-05T00:00:00+08:00")
        self.assertEqual(got["A/One"]["sightings_n"], 2)
        self.assertNotIn("svg", got["B/Two"])
        self.assertEqual(got["B/Two"]["last_seen"], "2026-10-01T00:00:00+00:00")

    def test_collect_skips_invalid_frontmatter(self):
        self.lib.mkdir(parents=True)
        (self.lib / "junk.md").write_text("---\nrepo: '](http://e)'\nrepo_id: x\n---\nhi\n", encoding="utf-8")
        write_entry(self.lib, "A/One", 1)
        self.assertEqual([e["repo"] for e in index.collect(self.lib)], ["A/One"])

    def test_readme_groups_by_taxonomy_order_and_skips_empty(self):
        write_entry(self.lib, "A/One", 1, category="frontend")
        write_entry(self.lib, "B/Two", 2, category="mcp-server")
        text = index.render_readme(index.collect(self.lib), taxonomy.DEFAULT, today="2026-10-18")
        self.assertIn("2 個 repo · 更新 2026-10-18", text)
        self.assertLess(text.index("### mcp-server"), text.index("### frontend"))
        self.assertNotIn("### dev-tool", text)

    def test_readme_newest_first_within_category(self):
        write_entry(self.lib, "A/Old", 1, [s("2026-10-01T00:00:00+00:00")])
        write_entry(self.lib, "B/New", 2, [s("2026-10-09T00:00:00+00:00")])
        text = index.render_readme(index.collect(self.lib), taxonomy.DEFAULT, today="2026-10-18")
        section = text.split("### dev-tool", 1)[1]
        self.assertLess(section.index("B/New"), section.index("A/Old"))
        recent = text.split("## 最近收藏", 1)[1].split("## 分類", 1)[0]
        self.assertLess(recent.index("B/New"), recent.index("A/Old"))

    def test_readme_truncates_description(self):
        write_entry(self.lib, "A/One", 1, description="字" * 300)
        text = index.render_readme(index.collect(self.lib), taxonomy.DEFAULT, today="2026-10-18")
        line = next(row for row in text.splitlines() if "A/One" in row and "⭐" in row)
        self.assertIn("字" * 160 + "…", line)
        self.assertNotIn("字" * 161, line)

    def test_readme_escapes_hostile_description(self):
        write_entry(self.lib, "A/One", 1, description="[x](http://e) <img src=x>")
        text = index.render_readme(index.collect(self.lib), taxonomy.DEFAULT, today="2026-10-18")
        self.assertNotIn("](http://e)", text)
        self.assertNotIn("<img", text)

    def test_readme_unknown_category_goes_to_uncategorized(self):
        write_entry(self.lib, "A/One", 1, category="dev-tool")
        cats = [{"name": "alpha", "definition": "a"}]
        text = index.render_readme(index.collect(self.lib), cats, today="2026-10-18")
        self.assertIn("### 未分類", text)

    def test_index_json_sorted_by_last_seen(self):
        write_entry(self.lib, "A/Old", 1, [s("2026-10-01T00:00:00+00:00")])
        write_entry(self.lib, "B/New", 2, [s("2026-10-09T00:00:00+00:00")])
        data = json.loads(index.render_index(index.collect(self.lib)))
        self.assertEqual(data["count"], 2)
        self.assertEqual([e["repo"] for e in data["entries"]], ["B/New", "A/Old"])
        self.assertIn("generated_at", data)

    def test_readme_defuses_bare_url_in_description(self):
        write_entry(self.lib, "A/One", 1, description="Docs at https://evil.example/x")
        text = index.render_readme(index.collect(self.lib), taxonomy.DEFAULT, today="2026-10-18")
        self.assertIn("`https://evil.example/x`", text)

    def test_readme_survives_hand_edited_frontmatter(self):
        p = write_entry(self.lib, "A/One", 1)
        p.write_text(p.read_text(encoding="utf-8").replace("stars: 3", "stars: lots").replace("tags:", "tags: oops\nold_tags:"), encoding="utf-8")
        text = index.render_readme(index.collect(self.lib), taxonomy.DEFAULT, today="2026-10-18")
        self.assertIn("A/One", text)

    def test_index_entries_include_intro(self):
        write_entry(self.lib, "A/One", 1)
        data = json.loads(index.render_index(index.collect(self.lib)))
        self.assertTrue(data["entries"][0]["intro"])

    def test_index_entries_include_tagline_and_requirements(self):
        write_entry(self.lib, "A/One", 1)
        e = json.loads(index.render_index(index.collect(self.lib)))["entries"][0]
        self.assertTrue(e["tagline"])
        self.assertTrue(e["requirements"])


if __name__ == "__main__":
    unittest.main()
