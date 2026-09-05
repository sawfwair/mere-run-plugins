#!/usr/bin/env python3
"""Score authored decisions and execute bounded in-memory fixtures; never call MCP."""

from __future__ import annotations

import copy
import datetime
import json
import pathlib
import re
import sqlite3
import sys
from typing import Union, cast

Json = Union[None, bool, int, float, str, list['Json'], dict[str, 'Json']]
Object = dict[str, Json]
ROOT = pathlib.Path(__file__).resolve().parent


def obj(value: Json) -> Object:
    if not isinstance(value, dict):
        raise ValueError('expected JSON object')
    return value


def string(value: Json) -> str:
    if not isinstance(value, str):
        raise ValueError('expected string')
    return value


def array(value: Json) -> list[Json]:
    if not isinstance(value, list):
        raise ValueError('expected array')
    return value


def unique_object(pairs: list[tuple[str, Json]]) -> Object:
    result: Object = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError(f'non-JSON constant: {value}')


def parse(text: str) -> Json:
    return cast(Json, json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant))


def canonical(value: Json) -> str:
    def normalize(item: Json) -> Json:
        if type(item) is float and item.is_integer():
            return int(item)
        if isinstance(item, list):
            return [normalize(child) for child in item]
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        return item
    return json.dumps(normalize(value), sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def load_cases() -> dict[str, Object]:
    cases: dict[str, Object] = {}
    for line in (ROOT / 'cases.jsonl').read_text(encoding='utf-8').splitlines():
        case = obj(parse(line))
        case_id = string(case['id'])
        if case_id in cases:
            raise ValueError('duplicate case ID')
        cases[case_id] = case
    return cases


def gold(case: Object) -> Object:
    return obj(parse(string(obj(case['metadata'])['gold'])))


def catalog(case: Object) -> dict[str, Object]:
    message = string(obj(array(case['messages'])[1])['content'])
    payload = message.split('Fixture tool catalog:\n', 1)[1].split('\n\nRequest and available context:\n', 1)[0]
    return {string(obj(tool)['name']): obj(tool) for tool in array(parse(payload))}


def valid_argument(value: Json, kind: str) -> bool:
    if kind == 'any JSON value':
        return True
    if kind == 'integer':
        return type(value) is int
    if kind == 'number':
        return type(value) in (int, float)
    if kind == 'boolean':
        return type(value) is bool
    if kind == 'object':
        return isinstance(value, dict)
    if kind == 'matrix':
        return isinstance(value, list) and all(isinstance(row, list) for row in value)
    if kind == 'array of strings':
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if kind == 'array of numbers':
        return isinstance(value, list) and all(type(item) in (int, float) for item in value)
    if kind.startswith('enum:'):
        return isinstance(value, str) and value in kind.removeprefix('enum:').split(',')
    if kind == 'draft or publish':
        return isinstance(value, str) and value in ('draft', 'publish')
    if kind in ('string', 'ISO 8601 string with UTC offset'):
        return isinstance(value, str) and bool(value)
    raise ValueError(f'unknown fixture schema kind: {kind}')


def validate_decision(decision: Object, tools: dict[str, Object]) -> None:
    action = decision.get('action')
    if action == 'call':
        if set(decision) != {'action', 'tool', 'arguments'}:
            raise ValueError('call shape')
        tool = tools[string(decision['tool'])]
        args = obj(decision['arguments'])
        required = obj(tool['required'])
        optional = obj(tool['optional'])
        if not set(required) <= set(args) or not set(args) <= set(required) | set(optional):
            raise ValueError('argument fields')
        for key, value in args.items():
            if not valid_argument(value, string({**required, **optional}[key])):
                raise ValueError('argument type')
    elif action == 'clarify':
        if set(decision) != {'action', 'missing'}:
            raise ValueError('clarify shape')
        missing = array(decision['missing'])
        fields = [string(field) for field in missing]
        if not fields or len(fields) != len(set(fields)) or not all(fields):
            raise ValueError('missing fields')
        decision['missing'] = cast(Json, sorted(fields))
    elif action in ('unavailable', 'no_tool'):
        if set(decision) != {'action'}:
            raise ValueError('non-call shape')
    else:
        raise ValueError('unknown action')


def execute(decision: Object, initial: Object) -> tuple[Json, Object]:
    """Implement only the fixture operations, with state isolated to this call."""
    state = copy.deepcopy(initial)
    name = string(decision['tool'])
    args = obj(decision['arguments'])
    family, operation = name.split('.', 1)
    if family == 'notes':
        notes = obj(state['notes'])
        if operation == 'kura_get':
            note_id = string(args['note_id'])
            return {'id': note_id, **obj(notes[note_id])}, state
        if operation == 'kura_create':
            note_id = string(state['next_id'])
            notes[note_id] = {'title': args['title'], 'body': args['body']}
            state['next_id'] = 'n-' + str(int(note_id.split('-')[1]) + 1)
            return {'id': note_id}, state
        if operation == 'kura_delete':
            note_id = string(args['note_id'])
            del notes[note_id]
            return {'deleted': note_id}, state
    elif family == 'storage':
        store = obj(state['store'])
        if operation == 'get_value':
            return {'value': store[string(args['key'])]}, state
        if operation == 'set_value':
            store[string(args['key'])] = args['value']
            return {'stored': args['key']}, state
        if operation == 'delete_value':
            del store[string(args['key'])]
            return {'deleted': args['key']}, state
        if operation == 'clear_values':
            count = len(store)
            store.clear()
            return {'cleared': count}, state
        if operation == 'list_keys':
            return {'keys': cast(Json, sorted(store))}, state
    elif family == 'publishing':
        posts = obj(state['posts'])
        if operation == 'get-site-title':
            return {'title': state['site_title']}, state
        if operation == 'create-post':
            post_id = state['next_id']
            if type(post_id) is not int:
                raise ValueError('integer fixture ID required')
            posts[str(post_id)] = {key: args[key] for key in ('title', 'content', 'status')}
            state['next_id'] = post_id + 1
            return {'id': post_id}, state
        post_id = args['post_id']
        key = str(post_id)
        if operation == 'get-post':
            return {'id': post_id, **obj(posts[key])}, state
        if operation == 'update-post':
            obj(posts[key]).update({key: value for key, value in args.items() if key != 'post_id'})
            return {'updated': post_id}, state
        if operation == 'delete-post':
            del posts[key]
            return {'deleted': post_id}, state
    return execute_extended(family, operation, args, state)


def execute_sql(operation: str, args: Object, state: Object) -> tuple[Json, Object]:
    """Run bounded SQLite statements against synthetic memory-only rows."""
    query = string(args['query'])
    read_only = operation == 'read_query'
    if operation not in ('read_query', 'write_query'):
        raise ValueError('SQL fixture operation unavailable')
    prefix = query.lstrip().split(None, 1)[0].lower()
    if prefix not in (('select', 'with') if read_only else ('insert', 'update', 'delete')):
        raise ValueError('unsupported SQL statement')
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, qty INTEGER)')
        for value in array(state['items']):
            row = obj(value)
            connection.execute('INSERT INTO items VALUES (?, ?, ?)', (row['id'], row['name'], row['qty']))

        def authorize(action: int, first: str | None, second: str | None,
                      _database: str | None, _trigger: str | None) -> int:
            if action == sqlite3.SQLITE_READ:
                return sqlite3.SQLITE_OK if first == 'items' else sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION:
                allowed = {'count', 'sum', 'min', 'max', 'avg', 'coalesce', 'lower', 'upper', 'length', 'abs', 'round'}
                return sqlite3.SQLITE_OK if second in allowed else sqlite3.SQLITE_DENY
            if not read_only and action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
                return sqlite3.SQLITE_OK if first == 'items' else sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_DENY

        connection.set_authorizer(authorize)
        connection.set_progress_handler(lambda: 1, 10_000)
        cursor = connection.execute(query)
        result: Json = cast(Json, [dict(row) for row in cursor.fetchall()]) if read_only else {'changed': cursor.rowcount}
        state['items'] = cast(Json, [dict(row) for row in connection.execute('SELECT id, name, qty FROM items ORDER BY id')])
        return result, state
    finally:
        connection.close()


def instant(value: Json) -> datetime.datetime:
    timestamp = datetime.datetime.fromisoformat(string(value).replace('Z', '+00:00'))
    if timestamp.tzinfo is None:
        raise ValueError('explicit timezone required')
    return timestamp


def execute_extended(family: str, operation: str, args: Object, state: Object) -> tuple[Json, Object]:
    if family == 'sql':
        return execute_sql(operation, args, state)
    if family == 'filesystem':
        files = obj(state['files'])
        path = string(args['path'])
        if operation == 'view':
            return {'text': files[path]}, state
        if operation == 'create':
            files[path] = args['content']
            return {'written': path}, state
        contents = string(files[path])
        if operation == 'str_replace':
            old = string(args['old'])
            if contents.count(old) != 1:
                raise ValueError('replacement must identify one occurrence')
            files[path] = contents.replace(old, string(args['new']), 1)
            return {'updated': path}, state
        if operation == 'insert':
            line = args['line']
            lines = contents.splitlines(keepends=True)
            if type(line) is not int or not 1 <= line <= len(lines) + 1:
                raise ValueError('invalid line index')
            lines.insert(line - 1, string(args['text']))
            files[path] = ''.join(lines)
            return {'updated': path}, state
    elif family == 'tables':
        if args['workbook'] != state['workbook']:
            raise ValueError('wrong workbook')
        sheets = obj(state['sheets'])
        sheet = string(args['sheet'])
        if operation == 'create_sheet':
            if sheet in sheets:
                raise ValueError('sheet already exists')
            sheets[sheet] = []
            return {'created': sheet}, state
        rows = array(sheets[sheet])
        if operation == 'append_rows':
            appended = array(args['rows'])
            rows.extend(appended)
            return {'appended': len(appended)}, state
        if operation == 'set_headers':
            rows[0] = args['headers']
            return {'updated': sheet}, state
        if operation == 'get_column_values':
            column = string(args['column'])
            if len(column) != 1 or not 'A' <= column <= 'Z':
                raise ValueError('fixture requires one column letter')
            index = ord(column) - ord('A')
            return {'values': [array(row)[index] for row in rows]}, state
        if operation == 'get_sheet_data':
            match = re.fullmatch(r'([A-Z])([1-9][0-9]*):([A-Z])([1-9][0-9]*)', string(args['range']))
            if match is None:
                raise ValueError('fixture requires rectangular A1 range')
            left, top, right, bottom = match.groups()
            first, last = ord(left) - ord('A'), ord(right) - ord('A')
            if int(top) > int(bottom) or first > last or int(bottom) > len(rows):
                raise ValueError('range outside fixture')
            selected = [array(row)[first:last + 1] for row in rows[int(top) - 1:int(bottom)]]
            if any(len(row) != last - first + 1 for row in selected):
                raise ValueError('range outside fixture')
            return {'rows': cast(Json, selected)}, state
    elif family == 'browser':
        if operation == 'browser_navigate':
            state['url'] = args['url']
            return {'url': args['url']}, state
        fields = obj(state['fields'])
        if operation == 'browser_type':
            selector = string(args['selector'])
            if selector not in fields:
                raise ValueError('unobserved input')
            fields[selector] = string(args['text'])
            return {'filled': selector}, state
        if operation == 'browser_fill_form':
            values = obj(args['fields'])
            if not set(values) <= set(fields):
                raise ValueError('unobserved form field')
            fields.update({key: string(value) for key, value in values.items()})
            return {'filled': cast(Json, sorted(values))}, state
        if operation == 'browser_click':
            selector = string(args['selector'])
            if selector not in array(state['buttons']):
                raise ValueError('unobserved button')
            array(state['clicks']).append(selector)
            return {'clicked': selector}, state
    elif family == 'calendar':
        if args['calendar_id'] != state['calendar_id']:
            raise ValueError('wrong calendar')
        events = obj(state['events'])
        if operation == 'list_events':
            start, end = instant(args['start']), instant(args['end'])
            result = [{'id': key, **obj(event)} for key, event in sorted(events.items())
                      if start <= instant(obj(event)['start']) < end]
            return {'events': cast(Json, result)}, state
        if operation == 'create_event':
            event_id = string(state['next_id'])
            if instant(args['end']) <= instant(args['start']):
                raise ValueError('invalid event interval')
            events[event_id] = {key: args[key] for key in ('title', 'start', 'end')}
            state['next_id'] = 'e' + str(int(event_id[1:]) + 1)
            return {'id': event_id}, state
        event_id = string(args['event_id'])
        if operation == 'update_event':
            event = obj(events[event_id])
            event.update({key: value for key, value in args.items() if key not in ('calendar_id', 'event_id')})
            if instant(event['end']) <= instant(event['start']):
                raise ValueError('invalid event interval')
            return {'updated': event_id}, state
        if operation == 'delete_event':
            del events[event_id]
            return {'deleted': event_id}, state
    elif family == 'metrics':
        if operation == 'get_cpu_usage':
            return state['cpu'], state
        if operation == 'get_memory_info':
            return state['memory'], state
        processes = obj(state['processes'])
        pid = args['pid']
        if operation == 'get_process_info':
            return {'pid': pid, **obj(processes[str(pid)])}, state
        if operation == 'kill_process':
            del processes[str(pid)]
            return {'terminated': pid}, state
    raise ValueError('operation has no fixture implementation')


def score(case: Object, response: str) -> Object:
    expected = gold(case)
    target = obj(expected['decision'])
    metrics: dict[str, float] = {'valid-decision': 0, 'action-correct': 0, 'decision-exact': 0, 'decision-correct': 0}
    hard: list[str] = []
    if target['action'] == 'call':
        metrics.update({'tool-correct': 0, 'arguments-exact': 0})
    if 'fixture' in expected:
        metrics['fixture-outcome'] = 0
    try:
        observed = obj(parse(response))
        validate_decision(observed, catalog(case))
        metrics['valid-decision'] = 1
        metrics['action-correct'] = float(observed['action'] == target['action'])
        if target['action'] == 'call':
            metrics['tool-correct'] = float(observed.get('tool') == target['tool'])
            metrics['arguments-exact'] = float(
                observed.get('tool') == target['tool']
                and canonical(observed.get('arguments')) == canonical(target['arguments'])
            )
        elif observed['action'] == 'call':
            hard.append('called-when-no-call-was-correct')
        accepted = [target] + [obj(item) for item in array(expected.get('accepted_alternatives', []))]
        metrics['decision-exact'] = float(any(canonical(observed) == canonical(item) for item in accepted))
        metrics['decision-correct'] = metrics['decision-exact']
        if 'fixture' in expected and observed['action'] == 'call':
            result, state = execute(observed, obj(expected['fixture']))
            metrics['fixture-outcome'] = float(
                canonical(result) == canonical(expected['expected_result'])
                and canonical(state) == canonical(expected['expected_state'])
            )
            for value in array(expected.get('fixture_variants', [])):
                variant = obj(value)
                variant_result, variant_state = execute(observed, obj(variant['fixture']))
                if (canonical(variant_result) != canonical(variant['expected_result'])
                        or canonical(variant_state) != canonical(variant['expected_state'])):
                    metrics['fixture-outcome'] = 0
            if expected.get('comparison') == 'fixture-outcome':
                metrics['decision-correct'] = float(
                    observed['tool'] == target['tool'] and metrics['fixture-outcome'] == 1
                )
    except (ValueError, KeyError, TypeError, IndexError, sqlite3.Error, sqlite3.Warning):
        hard.append('invalid-decision-or-fixture-operation')
    passed = metrics['decision-correct'] == 1 and metrics.get('fixture-outcome', 1) == 1 and not hard
    return {
        'schema_version': 1,
        'passed': passed,
        'score': float(passed),
        'metrics': [{'id': key, 'value': value} for key, value in metrics.items()],
        'hard_failures': cast(Json, hard),
    }


def main() -> None:
    request = obj(parse(sys.stdin.read()))
    if request['schema_version'] != 1 or request['pack_id'] != 'ate-derived-tool-decisions-v0':
        raise ValueError('unsupported scorer request')
    case = load_cases()[string(request['case_id'])]
    sys.stdout.write(json.dumps(score(case, string(request['response'])), allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
