"""Reserve a full analysis and cleanup before optional search/research."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

JOB_S = 1800
A_S = 1200
TAIL_S = 120
R_TAIL_S = 30
PRE_S = 60
SEARCH_S = 120
R_MIN_S = 60
R_MAX_S = 300


def plan(elapsed: int) -> dict:
    slack = JOB_S - elapsed - A_S - TAIL_S
    room = slack - R_TAIL_S
    mode = 'fail' if slack < 0 else 'none' if room < SEARCH_S + R_MIN_S else 'full'
    return {'mode': mode, 'room': room}


def rt(left: int) -> int:
    return 0 if left < R_MIN_S else min(left, R_MAX_S)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--job-start', required=True, type=int)
    p.add_argument('--status-out', required=True, type=Path)
    p.add_argument('--now', type=int)
    r = sub.add_parser('rt')
    r.add_argument('--deadline', required=True, type=int)
    r.add_argument('--now', type=int)
    args = parser.parse_args(argv)
    now = int(time.time()) if args.now is None else args.now
    if args.command == 'rt':
        print(rt(args.deadline - now))
        return 0
    elapsed = now - args.job_start + PRE_S
    result = plan(elapsed)
    mode = result['mode']
    print(f'mode={mode}')
    print(f'search={str(mode == "full").lower()}')
    print(f'deadline={now + result["room"]}')
    print(f'elapsed={elapsed}')
    if mode == 'fail':
        status = {'status': 'failed',
                  'error': f'pipeline: not enough job time left for a full analysis (elapsed {elapsed}s)',
                  'entry': None, 'repo_id': None, 'diagram': False, 'rounds': 0,
                  'wall_s': 0, 'claude_exit': None}
        try:
            with args.status_out.open('x', encoding='utf-8') as stream:
                json.dump(status, stream)
        except FileExistsError:
            pass
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
