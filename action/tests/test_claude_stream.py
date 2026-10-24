import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _path import FIXTURES, SCRIPTS

# _path must update sys.path before importing action/scripts modules.
# isort: split

import claude_stream

OK = (FIXTURES / "stream_ok.jsonl").read_text().splitlines()


class ResearchStreamTest(unittest.TestCase):
    def fixture(self, name, audit=None):
        lines = (FIXTURES / name).read_text(encoding="utf-8").splitlines()
        return claude_stream.summarize(lines, audit=audit)

    def test_denied_only_is_not_success(self):
        run = self.fixture("stream_denied_only.jsonl")
        self.assertTrue(run["tools"]["deepwiki"])
        self.assertFalse(run["tools"]["deepwiki_ok"])
        self.assertEqual(run["calls"][0]["status"], "denied")
        self.assertEqual(set(run["permission_denials"][0]), {"tool_name", "tool_use_id"})
        self.assertNotIn("tool_input", json.dumps(run))

    def test_fetch_error_status(self):
        run = self.fixture("stream_fetch_error.jsonl")
        self.assertTrue(run["tools"]["web"])
        self.assertFalse(run["tools"]["web_ok"])
        self.assertEqual(run["calls"][0]["status"], "error")

    def test_success_status_and_mask(self):
        run = self.fixture("stream_research_ok.jsonl")
        self.assertTrue(run["tools"]["deepwiki_ok"])
        self.assertTrue(run["tools"]["web_ok"])
        self.assertEqual([c["status"] for c in run["calls"]], ["ok", "ok"])
        self.assertIn("sk-ant-[MASKED]", json.dumps(run))
        self.assertIn("canary-visible", json.dumps(run))
        self.assertNotIn("sk-ant-abcdefgh12345", json.dumps(run))
        self.assertEqual(run["init"]["mcp_servers"], [{"name": "deepwiki", "status": "connected"}])

    def test_calls_truncated_flag(self):
        events = [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": str(i), "name": "WebSearch", "input": {"query": "x" * 300}}
        ]}} for i in range(61)]
        run = claude_stream.summarize(map(json.dumps, events))
        self.assertEqual(len(run["calls"]), 60)
        self.assertEqual(run["calls_total"], 61)
        self.assertTrue(run["calls_truncated"])
        self.assertEqual(len(run["calls"][0]["input"]), 200)
        self.assertEqual(run["calls"][0]["status"], "no_result")

    def test_read_probe_succeeded_is_failed(self):
        run = self.fixture("stream_read_probe_ok.jsonl", {"stage_meta": "/rt/stage/meta.json"})
        self.assertEqual(run["read_audit"], [{"id": "read", "code": "stage_meta", "status": "ok"}])
        verdict = claude_stream.read_verdict(run, ["stage_meta"])
        self.assertEqual(verdict["verdict"], "failed")
        self.assertEqual(verdict["codes"]["stage_meta"], "read_succeeded")

    def test_read_probe_absent_is_unverified(self):
        run = self.fixture("stream_read_probe_absent.jsonl", {"stage_meta": "/rt/stage/meta.json"})
        verdict = claude_stream.read_verdict(run, ["stage_meta"])
        self.assertEqual(verdict["codes"]["stage_meta"], "not_attempted")
        self.assertEqual(verdict["verdict"], "unverified")

    def test_read_probe_denied_is_passed(self):
        run = self.fixture("stream_read_probe_denied.jsonl", {"stage_meta": "/rt/stage/meta.json"})
        verdict = claude_stream.read_verdict(run, ["stage_meta"])
        self.assertEqual(verdict["codes"]["stage_meta"], "denied")
        self.assertEqual(verdict["verdict"], "passed")

    def test_read_audit_has_no_path_or_content(self):
        run = self.fixture("stream_read_probe_ok.jsonl", {"stage_meta": "/rt/stage/meta.json"})
        serialized = json.dumps(run)
        self.assertNotIn("/rt/stage", serialized)
        self.assertNotIn("PRIVATE_READ_RESULT", serialized)
        self.assertEqual(run["calls"], [])
        self.assertEqual(self.fixture("stream_read_probe_ok.jsonl")["read_audit"], [])

    def test_read_audit_truncated_is_unverified(self):
        lines = (FIXTURES / "stream_read_probe_denied.jsonl").read_text().splitlines() * 41
        run = claude_stream.summarize(lines, audit={"stage_meta": "/rt/stage/meta.json"})
        self.assertEqual(len(run["read_audit"]), 40)
        self.assertEqual(run["read_audit_total"], 41)
        self.assertTrue(run["read_audit_truncated"])
        self.assertEqual(claude_stream.read_verdict(run, ["stage_meta"])["verdict"], "unverified")

    def test_read_status_correlation_and_normalization(self):
        for status, text, error in (("error", "network error", True), ("denied", "Permission denied", True),
                                    ("ok", "Permission denied", False)):
            events = [{"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": "//rt/stage/./meta.json"}}
            ]}}, {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "r", "content": text, "is_error": error}
            ]}}]
            run = claude_stream.summarize(map(json.dumps, events), audit={"stage_meta": "/rt/stage/meta.json"})
            self.assertEqual(run["read_audit"][0]["status"], status)
        self.assertEqual(claude_stream.read_verdict({}, ["stage_meta"])["verdict"], "unverified")
        self.assertEqual(claude_stream.read_verdict({"read_audit_truncated": False}, [])["verdict"], "unverified")
        for status in ("error", "no_result"):
            run = {"read_audit": [{"code": "stage_meta", "status": status}], "read_audit_truncated": False}
            self.assertEqual(claude_stream.read_verdict(run, ["stage_meta"])["codes"]["stage_meta"], "inconclusive")

    def test_permission_denials_override_result_and_are_capped(self):
        events = [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": "/rt/stage/meta.json"}}
        ]}}, {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "r", "content": "not stored"}
        ]}}, {"type": "result", "permission_denials": [
            {"tool_name": "Read", "tool_use_id": "r", "tool_input": {"file_path": "/rt/stage/meta.json"}}
        ] * 41}]
        run = claude_stream.summarize(map(json.dumps, events), audit={"stage_meta": "/rt/stage/meta.json"})
        self.assertEqual(run["read_audit"][0]["status"], "denied")
        self.assertEqual(len(run["permission_denials"]), 40)
        self.assertNotIn("/rt/stage", json.dumps(run))
        self.assertNotIn("not stored", json.dumps(run))

    def test_missing_ids_cannot_prove_denial(self):
        events = [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/rt/stage/meta.json"}}
        ]}}, {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": "Permission denied", "is_error": True}
        ]}}, {"type": "result", "permission_denials": [{"tool_name": "Read"}]}]
        run = claude_stream.summarize(map(json.dumps, events), audit={"stage_meta": "/rt/stage/meta.json"})
        self.assertEqual(run["read_audit"][0]["status"], "no_result")
        self.assertEqual(claude_stream.read_verdict(run, ["stage_meta"])["verdict"], "unverified")

    def test_success_after_call_truncation_still_counts(self):
        uses = [{"type": "tool_use", "id": str(i), "name": "WebSearch", "input": {}} for i in range(60)]
        uses += [{"type": "tool_use", "id": "last", "name": "mcp__deepwiki__ask_question", "input": {}}]
        events = [{"type": "assistant", "message": {"content": uses}},
                  {"type": "user", "message": {"content": [
                      {"type": "tool_result", "tool_use_id": "last", "content": "ok"}]}}]
        run = claude_stream.summarize(map(json.dumps, events))
        self.assertTrue(run["calls_truncated"])
        self.assertTrue(run["tools"]["deepwiki_ok"])
        self.assertFalse(run["tools"]["web_ok"])

    def test_cli_audit_and_invalid_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run.json"
            source = str(FIXTURES / "stream_read_probe_denied.jsonl")
            self.assertEqual(claude_stream.main(["--audit=stage_meta=/rt/stage/meta.json", source, str(out)]), 0)
            run = json.loads(out.read_text())
            self.assertEqual(claude_stream.read_verdict(run, ["stage_meta"])["verdict"], "passed")
            for arg in ("--audit=Bad=/rt/stage/meta.json", "--audit=x=relative", "--audit=missing"):
                self.assertEqual(claude_stream.main([arg, source, str(out)]), 1)


class ClaudeStreamTest(unittest.TestCase):
    def test_init_with_null_or_scalar_lists_does_not_crash(self):
        for bad in (None, "x", 3, {}):
            line = json.dumps({"type": "system", "subtype": "init", "tools": bad, "mcp_servers": bad})
            with self.subTest(bad=bad):
                self.assertEqual(claude_stream.summarize([line])["init"], {"tools": [], "mcp_servers": []})

    def test_cli_caps_combined_sources_before_reading(self):
        from unittest.mock import patch

        source = str(FIXTURES / "stream_ok.jsonl")
        size = (FIXTURES / "stream_ok.jsonl").stat().st_size
        out = Path(tempfile.mkdtemp()) / "run.json"
        with (patch.object(claude_stream, "MAX_STREAM_BYTES", size),
              patch.object(Path, "open") as opened):
            self.assertEqual(claude_stream.main([source, source, str(out)]), 1)
            opened.assert_not_called()
        self.assertFalse(out.exists())

    def test_cli_accepts_exact_stream_byte_limit(self):
        from unittest.mock import patch

        source = FIXTURES / "stream_ok.jsonl"
        out = Path(tempfile.mkdtemp()) / "run.json"
        with patch.object(claude_stream, "MAX_STREAM_BYTES", source.stat().st_size):
            self.assertEqual(claude_stream.main([str(source), str(out)]), 0)
        self.assertEqual(json.loads(out.read_text())["result"]["session_id"], "sid-1")

    def test_cli_bounded_read_rejects_growth_after_stat(self):
        from unittest.mock import Mock, patch

        source = FIXTURES / "stream_ok.jsonl"
        out = Path(tempfile.mkdtemp()) / "run.json"
        with (patch.object(claude_stream, "MAX_STREAM_BYTES", 16),
              patch.object(Path, "stat", return_value=Mock(st_size=0))):
            self.assertEqual(claude_stream.main([str(source), str(out)]), 1)
        self.assertFalse(out.exists())

    def test_counts_tools(self):
        tools = claude_stream.summarize(OK)["tools"]
        self.assertEqual(tools["by_name"], {"Read": 2, "mcp__deepwiki__ask_question": 1, "Write": 1})
        self.assertEqual(tools["calls"], 4)
        self.assertTrue(tools["deepwiki"])
        self.assertEqual(tools["files_read"], 1)

    def test_result_text_truncated_to_2000(self):
        r = claude_stream.summarize(OK)["result"]
        self.assertEqual(len(r["result_text"]), 2000)
        self.assertNotIn("result", r)

    def test_session_id_kept(self):
        r = claude_stream.summarize(OK)["result"]
        self.assertEqual(r["session_id"], "sid-1")
        self.assertEqual(r["num_turns"], 3)

    def test_result_costs_listed_per_call_and_non_numbers_ignored(self):
        calls = [json.dumps({"type": "result", "total_cost_usd": 0.25}),
                 json.dumps({"type": "result", "total_cost_usd": True}),
                 json.dumps({"type": "result", "total_cost_usd": "1"}),
                 json.dumps({"type": "result", "total_cost_usd": 0.5})]
        self.assertEqual(claude_stream.summarize(calls)["result_costs_usd"], [0.25, 0.5])
        self.assertEqual(claude_stream.summarize([])["result_costs_usd"], [])

    def test_bad_line_skipped(self):
        s = claude_stream.summarize(["garbage", *OK, "{not json"])
        self.assertEqual(s["tools"]["calls"], 4)

    def test_no_result_exit_2(self):
        out = Path(tempfile.mkdtemp()) / "run.json"
        p = subprocess.run([sys.executable, str(SCRIPTS / "claude_stream.py"),
                            str(FIXTURES / "stream_noresult.jsonl"), str(out)], check=False)
        self.assertEqual(p.returncode, 2)
        self.assertIsNone(json.loads(out.read_text())["result"])

    def test_cli_merges_multiple_streams(self):
        out = Path(tempfile.mkdtemp()) / "run.json"
        ok = str(FIXTURES / "stream_ok.jsonl")
        p = subprocess.run([sys.executable, str(SCRIPTS / "claude_stream.py"), ok, ok, out.as_posix()], check=False)
        self.assertEqual(p.returncode, 0)
        rec = json.loads(out.read_text())
        self.assertEqual(rec["tools"]["by_name"]["Read"], 4)
        self.assertEqual(rec["tools"]["calls"], 8)
        self.assertEqual(rec["tools"]["files_read"], 1)
        self.assertEqual(rec["result"]["session_id"], "sid-1")
        self.assertEqual(rec["rounds_logged"], 2)

    def test_cli_last_result_wins_even_if_last_stream_lacks_one(self):
        out = Path(tempfile.mkdtemp()) / "run.json"
        p = subprocess.run([sys.executable, str(SCRIPTS / "claude_stream.py"), str(FIXTURES / "stream_ok.jsonl"),
                            str(FIXTURES / "stream_noresult.jsonl"), str(out)], check=False)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(json.loads(out.read_text())["result"]["session_id"], "sid-1")


if __name__ == "__main__":
    unittest.main()
