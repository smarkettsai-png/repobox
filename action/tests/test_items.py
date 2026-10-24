import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _path import SCRIPTS

# _path must update sys.path before importing action/scripts modules.
# isort: split

import items

GOOD = {"v": 1, "url": "https://github.com/a/b", "captured_at": "2026-10-18T10:00:00+08:00"}


class ItemsTest(unittest.TestCase):
    def setUp(self):
        self.inbox = Path(tempfile.mkdtemp()) / "inbox"
        self.inbox.mkdir()

    def put(self, name, content):
        (self.inbox / name).write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")

    def collect(self, url=""):
        return items.collect(self.inbox, url, "77")

    def test_capture_url_requires_full_match(self):
        for suffix in ("\n", "\r\n", " ", "/extra", "//"):
            with self.subTest(suffix=suffix):
                self.assertEqual(items._check_capture(dict(GOOD, url=GOOD["url"] + suffix)),
                                 "capture: url is not a GitHub repo URL")

    def test_capture_url_single_trailing_slash_still_accepted(self):
        # Behavior kept from before the fullmatch change: one trailing slash is allowed.
        self.assertIsNone(items._check_capture(dict(GOOD, url=GOOD["url"] + "/")))

    def test_id_suffixes_are_skipped(self):
        from unittest.mock import Mock, patch

        for suffix in ("\n", "\r\n", " ", "/"):
            with self.subTest(suffix=suffix):
                candidate = Mock(stem="abc" + suffix, name="capture")
                candidate.name = "abc" + suffix + ".json"
                with patch.object(Path, "glob", return_value=[candidate]):
                    self.assertEqual(self.collect(), [])
                candidate.read_text.assert_not_called()

    def test_eleventh_item_is_deferred_and_left_in_inbox(self):
        from contextlib import redirect_stderr
        from io import StringIO

        for n in range(items.MAX_ITEMS + 1):
            self.put(f"item-{n:02d}.json", GOOD)
        stderr = StringIO()
        with redirect_stderr(stderr):
            got = self.collect()
        self.assertEqual(items.MAX_ITEMS, 10)
        self.assertEqual(len(got), items.MAX_ITEMS)
        self.assertEqual(json.loads(stderr.getvalue()), {"skipped": [], "deferred": 1})
        self.assertNotIn(f"item-{items.MAX_ITEMS:02d}", [item["id"] for item in got])
        self.assertTrue((self.inbox / f"item-{items.MAX_ITEMS:02d}.json").exists())

    def test_dispatch_url_single_item_ignores_inbox(self):
        self.put("20261018-1.json", GOOD)
        self.assertEqual(self.collect("https://github.com/x/y"),
                         [{"id": "dispatch-77", "url": "https://github.com/x/y", "force": True}])

    def test_inbox_items_sorted(self):
        self.put("20261018-2.json", GOOD)
        self.put("20261018-1.json", dict(GOOD, url="https://github.com/c/d"))
        got = self.collect()
        self.assertEqual([i["id"] for i in got], ["20261018-1", "20261018-2"])
        self.assertEqual(got[0], {"id": "20261018-1", "url": "https://github.com/c/d", "force": False})

    def test_bad_json_yields_error_item(self):
        self.put("bad.json", "{not json")
        [it] = self.collect()
        self.assertEqual(set(it), {"id", "url", "force", "error"})
        self.assertIsNone(it["url"])
        self.assertTrue(it["error"])

    def test_json_null_and_array_yield_error_items(self):
        self.put("a.json", "null")
        self.put("b.json", "[1]")
        got = self.collect()
        self.assertEqual([i["id"] for i in got], ["a", "b"])
        self.assertTrue(all(i["error"] for i in got))

    def test_missing_url_yields_error_item(self):
        self.put("m.json", {k: v for k, v in GOOD.items() if k != "url"})
        [it] = self.collect()
        self.assertIn("url", it["error"])

    def test_long_url_rejected(self):
        self.put("l.json", dict(GOOD, url="https://github.com/a/" + "b" * 200))
        [it] = self.collect()
        self.assertIn("url", it["error"])

    def test_item_size_independent_of_capture_size(self):
        self.put("big.json", dict(GOOD, note="x" * 1_000_000))
        [it] = self.collect()
        self.assertLess(len(json.dumps(it)), 200)

    def test_items_capped_per_run(self):
        for n in range(items.MAX_ITEMS + 5):
            self.put(f"20261018-{n:04d}.json", GOOD)
        got = self.collect()
        self.assertEqual(len(got), items.MAX_ITEMS)
        self.assertEqual(got[-1]["id"], f"20261018-{items.MAX_ITEMS - 1:04d}")

    def test_gist_url_yields_error_item(self):
        self.put("g.json", dict(GOOD, url="https://gist.github.com/a/b"))
        self.put("u.json", dict(GOOD, url="https://github.com/cholateio"))
        self.assertTrue(all(i.get("error") for i in self.collect()))

    def test_missing_or_bad_captured_at_yields_error_item(self):
        self.put("c1.json", {"v": 1, "url": GOOD["url"]})
        self.put("c2.json", dict(GOOD, captured_at="yesterday"))
        self.put("c3.json", dict(GOOD, captured_at=5))
        got = self.collect()
        self.assertEqual(len(got), 3)
        self.assertTrue(all("captured_at" in i["error"] for i in got))

    def test_wrong_v_yields_error_item(self):
        self.put("v.json", dict(GOOD, v=2))
        [it] = self.collect()
        self.assertIn("v", it["error"])

    def test_unsafe_stem_skipped_not_in_items(self):
        self.put("bad name.json", GOOD)
        self.put("-lead.json", GOOD)
        self.assertEqual(self.collect(), [])

    def test_ignores_done_and_failed_subdirs(self):
        (self.inbox / "done").mkdir()
        (self.inbox / "done" / "x.json").write_text(json.dumps(GOOD))
        self.assertEqual(self.collect(), [])

    def test_cli_prints_one_json_line(self):
        self.put("20261018-1.json", GOOD)
        p = subprocess.run([sys.executable, str(SCRIPTS / "items.py"), "--inbox", str(self.inbox), "--url", "",
                            "--run-id", "5"], capture_output=True, text=True, check=False)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(len(p.stdout.strip().splitlines()), 1)
        self.assertEqual(json.loads(p.stdout)[0]["id"], "20261018-1")


if __name__ == "__main__":
    unittest.main()
