import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _path import SCRIPTS

# isort: split
import budget


class BudgetTest(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / 'budget.py'), *map(str, args)],
                              capture_output=True, text=True, check=False)

    def test_plan_boundaries(self):
        for elapsed, mode in [(0, 'full'), (120, 'full'), (270, 'full'), (271, 'none'),
                              (360, 'none'), (480, 'none'), (481, 'fail'), (600, 'fail')]:
            with self.subTest(elapsed=elapsed):
                self.assertEqual(budget.plan(elapsed)['mode'], mode)
        self.assertEqual(budget.plan(120)['room'], 330)
        self.assertEqual(budget.rt(330 - 120), 210)
        self.assertEqual(budget.rt(330), 300)

    def test_rt_floor_and_cap(self):
        self.assertEqual([budget.rt(n) for n in (-1, 0, 59, 60, 1000)], [0, 0, 0, 60, 300])

    def test_full_analysis_is_reserved(self):
        for elapsed in range(budget.JOB_S + 1):
            p = budget.plan(elapsed)
            if p['mode'] == 'fail':
                continue
            for search_used in (0, budget.SEARCH_S):
                research = (search_used + budget.rt(p['room'] - search_used) + budget.R_TAIL_S
                            if p['mode'] == 'full' else 0)
                self.assertLessEqual(elapsed + research + budget.A_S + budget.TAIL_S, budget.JOB_S)

    def test_cli_plan_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.cli('plan', '--job-start', 1000, '--now', 1060,
                              '--status-out', Path(directory) / 'status.json')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(),
                             ['mode=full', 'search=true', 'deadline=1390', 'elapsed=120'])
            self.assertEqual(self.cli('rt', '--deadline', 1390, '--now', 1180).stdout, '210\n')

    def test_cli_fail_writes_status_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'status.json'
            args = ('plan', '--job-start', 1000, '--now', 1540, '--status-out', path)
            result = self.cli(*args)
            self.assertEqual(result.returncode, 1, result.stderr)
            value = json.loads(path.read_text())
            self.assertEqual(value['status'], 'failed')
            self.assertIn('elapsed 600s', value['error'])
            self.assertEqual(set(value), {'status', 'error', 'entry', 'repo_id', 'diagram',
                                          'rounds', 'wall_s', 'claude_exit'})
            path.write_text('{"existing":true}')
            self.assertEqual(self.cli(*args).returncode, 1)
            self.assertEqual(json.loads(path.read_text()), {'existing': True})
