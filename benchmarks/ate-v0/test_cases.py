"""Check fixture oracles, rejected mutations, split isolation, and scorer wiring."""

from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys
import unittest
from collections import Counter

import score


class CaseTests(unittest.TestCase):
    def test_coverage_inventory(self) -> None:
        cases = score.load_cases()
        counts = Counter(score.string(score.obj(case['metadata'])['family']) for case in cases.values())
        self.assertEqual(len(counts), 20)
        self.assertEqual(set(counts.values()), {12})
        behavior = Counter(score.string(tag) for case in cases.values() for tag in score.array(case['capability_tags'])
                           if score.string(tag) not in counts)
        coverage = json.loads((score.ROOT / 'coverage.json').read_text())
        self.assertEqual(coverage['behavior_counts'], dict(behavior))
        self.assertEqual(coverage['cases'], len(cases))
        self.assertEqual(behavior['result-followup'], 20)
        self.assertEqual(sum(len(score.array(score.gold(case).get('fixture_variants', [])))
                             for case in cases.values()), 8)

    def test_equivalent_sql_and_counterfactuals(self) -> None:
        case = score.load_cases()['ate-v0.sql.count-zero']
        def query_response(query: str) -> str:
            return json.dumps({'action': 'call', 'tool': 'sql.read_query', 'arguments': {'query': query}})
        self.assertTrue(score.score(case, query_response('select count(id) as count from items where 0 = qty'))['passed'])
        self.assertFalse(score.score(case, query_response('SELECT 1 AS count'))['passed'])
        self.assertFalse(score.score(case, query_response('SELECT load_extension("/tmp/extension")'))['passed'])
        self.assertFalse(score.score(case, query_response('SELECT 1; DELETE FROM items'))['passed'])

    def test_sql_write_scope_and_no_attachment(self) -> None:
        case = score.load_cases()['ate-v0.sql.update-one']
        for query in ['UPDATE items SET qty = 7', 'ATTACH DATABASE "/tmp/other.db" AS other',
                      'DROP TABLE items', 'UPDATE items SET qty = 7 WHERE name = "rope"']:
            response = json.dumps({'action': 'call', 'tool': 'sql.write_query', 'arguments': {'query': query}})
            self.assertFalse(score.score(case, response)['passed'])

    def test_all_authored_answers_and_fixture_outcomes(self) -> None:
        cases = score.load_cases()
        self.assertEqual(len(cases), 240)
        self.assertEqual(sum('fixture' in score.gold(case) for case in cases.values()), 60)
        for case_id, case in cases.items():
            with self.subTest(case=case_id):
                decision = score.gold(case)['decision']
                self.assertTrue(score.score(case, json.dumps(decision))['passed'])
                for alternate in score.array(score.gold(case).get('accepted_alternatives', [])):
                    self.assertTrue(score.score(case, json.dumps(alternate))['passed'])

    def test_missing_extra_and_wrong_values_fail(self) -> None:
        for case_id, case in score.load_cases().items():
            expected = score.obj(score.gold(case)['decision'])
            wrong_action = {'action': 'no_tool' if expected['action'] != 'no_tool' else 'unavailable'}
            mutants = [wrong_action, {**expected, 'explanation': 'unrequested'}, {}]
            if expected['action'] == 'call':
                mutants.append({**expected, 'tool': 'invented.execute'})
                args = score.obj(expected['arguments'])
                for key in args:
                    mutants.append({**expected, 'arguments': {**args, key: '__wrong__'}})
                mutants.append({**expected, 'arguments': {**args, 'unexpected': True}})
            for mutant in mutants:
                with self.subTest(case=case_id, mutant=mutant):
                    self.assertFalse(score.score(case, json.dumps(mutant))['passed'])

    def test_strict_json_and_integer_types(self) -> None:
        case = score.load_cases()['ate-v0.publishing.read-body']
        for response in ['null', '[]', '```json\n{}\n```', '{"action":"no_tool","action":"call"}',
                         '{"action":"call","tool":"publishing.get-post","arguments":{"post_id":41.0}}',
                         '{"action":"call","tool":"publishing.get-post","arguments":{"post_id":true}}',
                         '{"action":"call","tool":"publishing.get-post","arguments":{"post_id":NaN}}']:
            self.assertFalse(score.score(case, response)['passed'])

    def test_number_equivalence_without_boolean_coercion(self) -> None:
        case = score.load_cases()['ate-v0.geo.nearby']
        decision = copy.deepcopy(score.obj(score.gold(case)['decision']))
        score.obj(decision['arguments'])['radius_m'] = 1500.0
        self.assertTrue(score.score(case, json.dumps(decision))['passed'])
        score.obj(decision['arguments'])['radius_m'] = True
        self.assertFalse(score.score(case, json.dumps(decision))['passed'])

    def test_fixture_expectations_are_enforced_and_state_is_isolated(self) -> None:
        for case in score.load_cases().values():
            expected = score.gold(case)
            if 'fixture' not in expected:
                continue
            initial = copy.deepcopy(expected['fixture'])
            score.execute(score.obj(expected['decision']), score.obj(expected['fixture']))
            self.assertEqual(initial, expected['fixture'])
            for field in ('expected_state', 'expected_result'):
                changed = copy.deepcopy(case)
                corrupt = copy.deepcopy(expected)
                corrupt[field] = {'wrong': 'oracle'}
                score.obj(changed['metadata'])['gold'] = json.dumps(corrupt)
                self.assertFalse(score.score(changed, json.dumps(expected['decision']))['passed'])

    def test_sources_split_isolation_and_no_duplicate_requests(self) -> None:
        source = score.obj(score.parse((score.ROOT / 'sources.json').read_text()))
        known = {score.string(score.obj(item)['tool_id']) for item in score.array(source['tools'])}
        servers: dict[str, set[str]] = {}
        counts: dict[str, int] = {}
        requests: set[str] = set()
        for case in score.load_cases().values():
            split = score.string(case['split'])
            metadata = score.obj(case['metadata'])
            counts[split] = counts.get(split, 0) + 1
            ids = score.array(score.parse(score.string(metadata['source_tool_ids'])))
            self.assertTrue(set(score.string(item) for item in ids) <= known)
            self.assertEqual(len(ids), len(score.catalog(case)))
            servers.setdefault(split, set()).update(score.string(item).split(':')[0] for item in ids)
            request = score.string(score.obj(score.array(case['messages'])[1])['content'])
            self.assertNotIn(request, requests)
            requests.add(request)
            self.assertNotIn('expected_state', request)
            self.assertNotIn('expected_result', request)
        self.assertEqual(counts, {'development': 120, 'held-out': 120})
        self.assertFalse(servers['development'] & servers['held-out'])

    def test_scorer_subprocess_contract(self) -> None:
        case = score.load_cases()['ate-v0.storage.typed-object']
        request = {'schema_version': 1, 'pack_id': 'ate-derived-tool-decisions-v0', 'case_id': case['id'],
                   'response': json.dumps(score.gold(case)['decision'])}
        result = subprocess.run([sys.executable, str(pathlib.Path(score.__file__))], input=json.dumps(request),
                                text=True, capture_output=True, check=True, cwd='/tmp')
        self.assertTrue(json.loads(result.stdout)['passed'])
        self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
