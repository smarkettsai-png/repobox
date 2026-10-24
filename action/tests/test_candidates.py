import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _path import SCRIPTS

# isort: split
import candidates

FIXTURES = Path(__file__).parent / 'fixtures'


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


class CandidatesTest(unittest.TestCase):
    def test_queries_topics_language(self):
        qs = candidates.queries({'topics': ['cli', 'agent', 'tool'], 'language': 'C++'})
        self.assertEqual(qs, ['topic:cli topic:agent language:C++ fork:false archived:false stars:>=20',
                              'topic:cli fork:false archived:false stars:>=20'])
        self.assertIn('language:"Jupyter Notebook"', candidates.queries({'language': 'Jupyter Notebook'})[0])

    def test_description_fallback_and_empty(self):
        qs = candidates.queries({'description': 'The useful workflow engine and platform'})
        self.assertTrue(qs)
        self.assertIn('in:description', qs[0])
        self.assertNotIn(' The ', ' ' + qs[0] + ' ')
        for value in ({}, {'topics': 'cli'}, {'language': 'Python" OR stars:0'},
                      {'description': '"fork:true" <html> x'}):
            self.assertEqual(candidates.queries(value), [])

    def test_hostile_fields_are_not_query_syntax(self):
        meta = fixture('meta_hostile.json')
        qs = candidates.queries(meta)
        self.assertLessEqual(len(qs), 2)
        for q in qs:
            self.assertLessEqual(len(q), 200)
            self.assertNotIn('\n', q)
            self.assertNotIn('fork:true', q)
            self.assertNotIn("'", q)
            self.assertNotIn('"', q)
            self.assertTrue(q.endswith('fork:false archived:false stars:>=20'))
        brief = candidates.brief(meta)
        self.assertEqual(brief['note'], candidates.NOTE)
        self.assertLessEqual(len(brief['description']), 300)
        self.assertNotIn('<', brief['description'])
        self.assertLessEqual(len(brief['topics']), 8)
        self.assertIsNone(brief['language'])

    def test_filter_excludes_sorts_deduplicates_and_sanitizes(self):
        meta = {'id': 1, 'full_name': 'target/repo'}
        result = candidates.filter_items(meta, [fixture('search_ok.json'), fixture('search_hostile.json')])
        items = result['items']
        self.assertEqual([v['repo'] for v in items], ['good/Best', 'good/Other'])
        self.assertEqual(items[0]['pushed'], '2026-10-20')
        self.assertNotIn('<', items[1]['description'])
        self.assertLessEqual(len(items[1]['description']), 200)
        self.assertEqual(items[1]['topics'], ['valid'])
        self.assertIsNone(items[1]['language'])
        self.assertEqual(candidates.filter_items(meta, [{}, [], {'items': 'bad'}])['items'], [])

    def test_size_and_top_ten(self):
        item = fixture('search_ok.json')['items'][0]
        raw = {'items': [dict(item, id=i+100, full_name=f'owner/repo{i}', stargazers_count=i,
                              description='字' * 1000) for i in range(30)]}
        result = candidates.filter_items({'id': 1}, [raw])
        self.assertEqual(len(result['items']), 10)
        self.assertEqual(result['items'][0]['stars'], 29)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode()), 16384)

    def test_cli_all_modes_and_failed_search(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            meta = root / 'meta.json'
            meta.write_text(json.dumps({'id': 1, 'full_name': 'target/repo', 'topics': ['cli']}))
            output = root / 'out.json'
            for args in [('queries', meta), ('brief', meta, output),
                         ('filter', meta, root / 'missing.json', output)]:
                p = subprocess.run([sys.executable, str(SCRIPTS / 'candidates.py'), *map(str, args)],
                                   capture_output=True, text=True, check=False)
                self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(output.read_text())['items'], [])
