import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from _path import SCRIPTS

FLAGS = '''FLAGS=(--model claude-haiku-5-5 --effort xhigh --max-budget-usd 4 --output-format stream-json --verbose
  --restricted --permission-mode dontAsk
  --tools Read Glob Grep Write Edit
  --strict-mcp-config
  --settings '{"permissions": {"blockReadsOutsideWorkingDirectories": true}}'
  --add-dir "$TARGET" --add-dir "$OUT" --add-dir "$AB"
  --allowedTools "Read(/$TARGET/**)" "Read(/$OUT/**)" "Read(/$AB/**)" "Edit(/$OUT/**)"
  --disallowedTools "Read(//proc/**)" "mcp__*")'''


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = SCRIPTS.parents[1] / ".github/workflows/analyze.yml"
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        steps = workflow["jobs"]["analyze"]["steps"]
        cls.analyze = next(step["run"] for step in steps if step.get("id") == "claude")
        cls.verify = next(step["run"] for step in steps if step.get("name") == "Verify outputs")

    def test_analyze_resolves_profile_once(self):
        command = 'python3 "$S/profile.py" resolve "$GITHUB_WORKSPACE/profile.md" "$RUNNER_TEMP/profile.json"'
        self.assertEqual(self.analyze.count(command), 1)
        self.assertLess(self.analyze.index(command), self.analyze.index('"$S/prompt.py" analyze'))
        self.assertIn(command + ' || exit 1', self.analyze)
        self.assertNotIn('"$S/profile.py" resolve', self.verify)

    def test_prompt_gets_profile_state(self):
        prompt_match = re.search(r'PROMPT=\$\((.*?)\)\n', self.analyze, re.DOTALL)
        assert prompt_match is not None
        prompt = prompt_match.group(1)
        self.assertIn('--profile "$RUNNER_TEMP/profile.json"', prompt)

    def test_both_validations_use_vargs(self):
        for step in (self.analyze, self.verify):
            with self.subTest(step=step[:30]):
                self.assertIn('VARGS=$(python3 "$S/profile.py" summary-args "$RUNNER_TEMP/profile.json" --target "$TARGET")', step)
                self.assertIn('mapfile -t VARGS <<< "$VARGS"', step)
                self.assertRegex(step, r'validate\.py" summary "\$OUT/summary\.json" "\$\{TAXARG\[@\]\}" "\$\{VARGS\[@\]\}"')
                self.assertLess(step.index('VARGS=$('), step.index('"$S/validate.py" summary'))
        self.assertIn('--status failed --error "profile:', self.verify)
        self.assertIn('exit 0;', self.verify)

    def test_flags_unchanged(self):
        match = re.search(r'FLAGS=\(.*?\)\n', self.analyze, re.DOTALL)
        assert match is not None
        flags = match.group(0).rstrip()
        self.assertEqual(flags, FLAGS)
        self.assertIn('--max-turns 80', self.analyze)

    def test_no_target_skip_branch(self):
        self.assertNotIn('unset TARGET', self.verify)
        self.assertNotIn('[ -d "$TARGET" ]', self.verify)
        self.assertIn('summary-args "$RUNNER_TEMP/profile.json" --target "$TARGET"', self.verify)

    def check_profile(self, content, expected):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "profile.md"
            state = root / "profile.json"
            target = root / "target with spaces"
            if content is not None:
                profile.write_text(content, encoding="utf-8")
            variables = {"$S": str(SCRIPTS), "$GITHUB_WORKSPACE/profile.md": str(profile),
                         "$RUNNER_TEMP/profile.json": str(state), "$TARGET": str(target)}
            resolve_match = re.search(r'python3 "\$S/profile.py" resolve [^\n]+', self.analyze)
            assert resolve_match is not None
            resolve = resolve_match.group(0)
            commands = [resolve.split(' ||')[0]]
            for step in (self.analyze, self.verify):
                match = re.search(r'VARGS=\$\((python3 .*?summary-args.*?)\)', step)
                assert match is not None
                commands.append(match.group(1))
            for index, command in enumerate(commands):
                args = shlex.split(command)
                args[0] = sys.executable
                args = [next((arg.replace(key, value) for key, value in variables.items() if key in arg), arg)
                        for arg in args]
                result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                if index:
                    self.assertEqual(result.stdout.splitlines(), ["--target", str(target), *expected])

    def test_args_without_profile(self):
        self.check_profile(None, ["--no-fit"])

    def test_args_valid_profile(self):
        self.check_profile("# pi agent\nCLI and MCP", ["--expect-tool", "pi agent"])

    def test_args_invalid_profile(self):
        self.check_profile("not a heading", ["--no-fit"])
