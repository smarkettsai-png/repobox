import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _path import FIXTURES, SCRIPTS

# _path must update sys.path before importing action/scripts modules.
# isort: split

import atd
import claude_stream

OWNER = "tester"


def fixture_run(name):
    return claude_stream.summarize((FIXTURES / name).read_text(encoding="utf-8").splitlines())


class AtdTest(unittest.TestCase):
    def setUp(self):
        self.record = fixture_run("stream_atd_scoped.jsonl")

    def test_all_denied_selects_scoped(self):
        result = atd.classify(self.record, OWNER)
        self.assertEqual(result["verdict"], "scoped")
        self.assertEqual(list(result["probes"].values()).count("success"), 3)
        self.assertEqual(list(result["probes"].values()).count("denied"), 6)

    def test_redirect_leak_selects_open(self):
        self.assertEqual(atd.classify(fixture_run("stream_atd_redirect_leak.jsonl"), OWNER)["verdict"], "open")
        self.assertEqual(atd.classify(fixture_run("stream_atd_missing.jsonl"), OWNER)["verdict"], "open")

    def test_incomplete_denied_and_errors_are_not_success(self):
        for status, category in (("error", "net_error"), ("no_result", "unknown"), ("ok", "unknown"),
                                 ("denied", "denied")):
            run = copy.deepcopy(self.record)
            run["calls"][0].update(status=status, result_head="unrelated response")
            result = atd.classify(run, OWNER)
            self.assertEqual(result["verdict"], "open")
            self.assertEqual(result["probes"]["allowed_github"], category)

    def test_redirect_reported_without_marker(self):
        self.record["calls"][3].update(status="ok", result_head="Redirected to https://release-assets.githubusercontent.com/file")
        self.assertEqual(atd.classify(self.record, OWNER)["probes"]["redirect_out"], "redirect_reported")
        self.assertEqual(atd.classify(self.record, OWNER)["verdict"], "scoped")
        self.record["calls"][3]["result_head"] = "Redirected to https://github.com/elsewhere"
        self.assertEqual(atd.classify(self.record, OWNER)["verdict"], "open")

    def test_extra_calls_and_truncation_fail_closed(self):
        for call in ({"tool": "WebSearch", "input": "q", "status": "error", "result_head": "RBX-ATD-REDIRECT"},
                     {"tool": "WebFetch", "input": "https://evil.example/", "status": "ok", "result_head": "hi"},
                     {"tool": "WebFetch", "input": "https://github.com.evil.example/", "status": "ok", "result_head": "hi"},
                     {"tool": "WebFetch", "input": "http://localhost:8080/", "status": "ok", "result_head": "RBX-ATD-LOOPBACK"}):
            self.assertEqual(atd.classify(dict(self.record, calls=self.record["calls"] + [call]), OWNER)["verdict"], "open")
        for truncated in (True, None):
            self.assertEqual(atd.classify(dict(self.record, calls_truncated=truncated), OWNER)["verdict"], "open")

    def test_exact_urls_and_repeated_attempts(self):
        run = copy.deepcopy(self.record)
        run["calls"][0]["input"] += "?other=1"
        self.assertEqual(atd.classify(run, OWNER)["probes"]["allowed_github"], "missing")
        run = copy.deepcopy(self.record)
        run["calls"].append(dict(run["calls"][4], status="no_result"))
        self.assertEqual(atd.classify(run, OWNER)["verdict"], "open")
        for data in ({}, {"calls": "invalid"}, {"calls": [None], "calls_truncated": False}):
            self.assertEqual(atd.classify(data, OWNER)["verdict"], "open")

    def test_cli_classify(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.json"
            path.write_text(json.dumps(self.record), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(SCRIPTS / "atd.py"), "classify", str(path), "--owner", OWNER],
                                  capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["verdict"], "scoped")

    def test_reads_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.json"
            for status, verdict, code in (("denied", "passed", 0), ("ok", "failed", 1), (None, "unverified", 2)):
                run = {"read_audit": [] if status is None else [{"id": "r", "code": "stage_meta", "status": status}],
                       "read_audit_truncated": False}
                path.write_text(json.dumps(run), encoding="utf-8")
                proc = subprocess.run([sys.executable, str(SCRIPTS / "atd.py"), "reads", str(path),
                                       "--expect-denied", "stage_meta"], capture_output=True, text=True, check=False)
                self.assertEqual(proc.returncode, code, proc.stderr)
                self.assertEqual(json.loads(proc.stdout)["verdict"], verdict)


if __name__ == "__main__":
    unittest.main()
