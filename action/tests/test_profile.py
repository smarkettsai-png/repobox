import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _path import SCRIPTS

import profile_state  # isort: skip


class ProfileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "profile.md"
        self.state = self.root / "profile.json"

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / "profile_state.py"), *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8", check=False)

    def test_missing_file_invalid(self):
        self.assertEqual(profile_state.load_profile(self.path), (None, ""))
        self.assertEqual(profile_state.load_profile(None), (None, ""))

    def test_bad_heading_invalid(self):
        for heading in ("pi agent", "## pi agent", "# bad:name", "# " + "x" * 31):
            with self.subTest(heading=heading):
                self.path.write_text(heading, encoding="utf-8")
                self.assertEqual(profile_state.load_profile(self.path), (None, ""))

    def test_read_failure_invalid(self):
        self.assertEqual(profile_state.load_profile(self.root), (None, ""))
        self.path.write_bytes(b"\xff\xfe")
        self.assertEqual(profile_state.load_profile(self.path), (None, ""))

    def test_pi_agent_and_controls(self):
        self.path.write_text("\n# pi agent\nCLI\x00\tMCP\x7f", encoding="utf-8")
        self.assertEqual(profile_state.load_profile(self.path), ("pi agent", "\n# pi agent\nCLI\tMCP"))

    def test_truncated_but_valid(self):
        self.path.write_text("# pi agent\n" + "中" * 5000, encoding="utf-8")
        tool, body = profile_state.load_profile(self.path)
        self.assertEqual(tool, "pi agent")
        self.assertEqual(len(body), 4000)

    def test_resolve_invalid_is_success(self):
        result = self.cli("resolve", self.path, self.state)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.state.read_text()), {"tool": None, "body": ""})

    def test_resolve_write_failure(self):
        self.assertEqual(self.cli("resolve", self.path, self.root).returncode, 1)

    def summary_args(self, value):
        self.state.write_text(json.dumps(value), encoding="utf-8")
        return self.cli("summary-args", self.state, "--target", "a target")

    def test_summary_args_valid(self):
        self.path.write_text("# pi agent\nCLI", encoding="utf-8")
        result = self.cli("resolve", self.path, self.state)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli("summary-args", self.state, "--target", "a target")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["--target", "a target", "--expect-tool", "pi agent"])

    def test_summary_args_without_profile(self):
        result = self.summary_args({"tool": None, "body": ""})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["--target", "a target", "--no-fit"])

    def test_summary_args_invalid_profile(self):
        self.path.write_text("invalid", encoding="utf-8")
        self.assertEqual(self.cli("resolve", self.path, self.state).returncode, 0)
        result = self.cli("summary-args", self.state, "--target", "a target")
        self.assertEqual(result.stdout.splitlines(), ["--target", "a target", "--no-fit"])

    def test_summary_args_missing_state_exit_1(self):
        result = self.cli("summary-args", self.state, "--target", "t")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")

    def test_summary_args_corrupt_state_fail_closed(self):
        for value in ({}, [], {"tool": "bad\nname", "body": ""}, {"tool": 3, "body": ""},
                      {"tool": None, "body": "unexpected"}, {"tool": "pi agent", "body": 1},
                      {"tool": None, "body": "", "extra": True}):
            with self.subTest(value=value):
                result = self.summary_args(value)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
        self.state.write_text("{", encoding="utf-8")
        result = self.cli("summary-args", self.state, "--target", "t")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
