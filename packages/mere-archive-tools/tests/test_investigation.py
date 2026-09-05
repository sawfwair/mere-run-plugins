from __future__ import annotations

import json
import os
import pathlib
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from test_cli import REPO_ROOT, invoke, write_fake_mere_run

from mere_archive_tools.investigation_processes import Processes
from mere_archive_tools.pi_harness import DEFAULT_MODEL, InvestigationError, parse_pi_output, search_needs_server_pause

FAKE_SERVER = '''
import http.server, json, os, pathlib, subprocess, sys, time
args = sys.argv[1:]
if args[:2] == ['status', '--json']:
    capacity = int(os.environ.get('TEST_CAPACITY', '4' if os.environ.get('TEST_PI_MODE') == 'race' else '1'))
    queued = []
    if os.environ.get('TEST_PI_MODE') == 'race':
        counter = pathlib.Path(__file__).with_suffix('.counter')
        count = int(counter.read_text()) if counter.exists() else 0
        counter.write_text(str(count + 1))
        if count: queued = [{}]
    print(json.dumps({'machineAdmission':{'capacityPermits':capacity,'activePermits':min(capacity,2),
        'queued':queued,'memoryPressure':'nominal','availableMemoryBytes':64*1024**3}}))
    raise SystemExit(0)
if args[:2] == ['vision', 'embed'] and os.environ.get('TEST_PI_MODE') == 'tooltimeout':
    time.sleep(30)
if args[:2] == ['vision', 'embed'] and os.environ.get('TEST_PI_MODE') == 'race':
    time.sleep(1.5)
if args[:2] == ['api', 'serve']:
    if '--preflight' in args:
        print(json.dumps({'ok': True}))
        raise SystemExit(0)
    marker = os.environ.get('TEST_PROCESS_LOG')
    if marker:
        with open(marker, 'a') as handle: handle.write(str(os.getpid())+'\\n')
    if os.environ.get('TEST_SERVER_WAIT'):
        time.sleep(30)
    model = args[args.index('--model')+1]
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get('Authorization') != 'Bearer ' + args[args.index('--api-key')+1]:
                self.send_response(401); self.end_headers(); return
            self.send_response(200); self.end_headers()
            self.wfile.write(json.dumps({'data':[{'id':model}]}).encode())
        def log_message(self, *args): pass
    http.server.HTTPServer(('127.0.0.1', int(args[args.index('--port')+1])), Handler).serve_forever()
'''

FAKE_PI = '''
import json, os, pathlib, subprocess, sys, time
mode = os.environ.get('TEST_PI_MODE', 'success')
marker = os.environ.get('TEST_PROCESS_LOG')
if marker:
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    with open(marker, 'a') as handle:
        handle.write(str(os.getpid())+'\\n'+str(child.pid)+'\\n')
if mode == 'hang': time.sleep(30)
trace = pathlib.Path(os.environ['MERE_ARCHIVE_SEARCH_TRACE'])
events = pathlib.Path(os.environ['MERE_ARCHIVE_EVENTS'])
records = []
repaired = mode == 'repair' and trace.exists()
if repaired:
    assert os.environ['MERE_ARCHIVE_REPAIR'] == '1'
    assert 'Previously returned archive evidence' in sys.argv[-1]
    assert 'record.txt' in sys.argv[-1]
if mode != 'missing' and not repaired:
    existing = len(trace.read_text().splitlines()) if trace.exists() else 0
    for index, query in enumerate(['repair', 'warranty'], start=existing + 1):
        with events.open('a') as handle: handle.write(json.dumps({'event':'search_start'})+'\\n')
        directory = pathlib.Path(os.environ['MERE_ARCHIVE_REQUEST_DIRECTORY'])
        request = directory / f'request-{index}.json'
        pending = request.with_suffix('.tmp')
        pending.write_text(json.dumps({'query':query}))
        pending.rename(request)
        response = directory / f'response-{index}.json'
        while not response.exists(): time.sleep(0.02)
        payload = json.loads(response.read_text())
        paths = [path['relativePath'] for item in payload['results'] for path in item['paths']]
        records.append({'sequence':index, 'query':query, 'resultPaths':paths})
    if mode == 'budget':
        with trace.open('a') as handle:
            for record in records * 3: handle.write(json.dumps(record)+'\\n')
if mode == 'invalid' or (mode == 'repair' and not repaired):
    answer = 'invalid JSON'
else:
    source = 'invented.pdf' if mode == 'citation' else 'record.txt'
    answer = json.dumps({'contractVersion':'mere.run/archive-investigation.v1','answer':'Warranty evidence.',
        'claims':[{'id':'one','statement':'A repair has warranty evidence.', 'status':'supported','sources':[source]}]})
print(json.dumps({'type':'message_end','message':{'role':'assistant','stopReason':'stop',
    'content':[{'type':'thinking','thinking':'TEST_PRIVATE_REASONING'}, {'type':'text','text':answer}]}}))
print(json.dumps({'type':'agent_end'}))
'''


class InvestigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.fake = self.root / 'mere.py'
        write_fake_mere_run(self.fake)
        self.fake.write_text(FAKE_SERVER + self.fake.read_text())
        self.pi = self.root / 'pi.py'
        self.pi.write_text(FAKE_PI)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'record.txt').write_text('The repair is covered by a vendor warranty until June 3, 2027.')
        self.database = self.root / 'archive.sqlite3'
        self.command = shlex.join([sys.executable, str(self.fake)])
        code, _, detail = invoke(['index', '--source', str(self.source), '--database', str(self.database),
                                 '--output-dir', str(self.root / 'index'), '--mere-run-command', self.command])
        self.assertEqual(code, 0, detail)
        self.diagnostics = self.root / 'diagnostics.json'
        self.args = ['investigate', '--database', str(self.database), '--question', 'When does the warranty expire?',
                     '--mere-run-command', self.command, '--pi-command', shlex.join([sys.executable, str(self.pi)]),
                     '--diagnostics', str(self.diagnostics), '--server-timeout', '3', '--pi-timeout', '10']

    def launch(self, mode: str, extra: list[str] | None = None) -> subprocess.CompletedProcess[str]:
        with patch.dict(os.environ, {'TEST_PI_MODE': mode}):
            code, payload, diagnostic = invoke([*self.args, *(extra or [])])
        return subprocess.CompletedProcess(self.args, code, json.dumps(payload) if payload else '', diagnostic)

    def test_fake_pi_runs_multiple_real_archive_searches(self) -> None:
        database_before = self.database.read_bytes()
        result = self.launch('success')
        self.assertEqual(self.database.read_bytes(), database_before)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        schema = json.loads((REPO_ROOT / 'contracts/archive-investigation.v1.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        validator.validate(payload)
        validator.validate(json.loads((REPO_ROOT / 'examples/archive/investigation.result.json').read_text()))
        self.assertEqual([item['query'] for item in payload['searches']], ['repair', 'warranty'])
        self.assertEqual(payload['claims'][0]['sources'], ['record.txt'])
        events = [event['event'] for event in payload['metrics']['events']]
        self.assertEqual(events.count('server_start'), 3)
        self.assertEqual(events.count('server_stopped'), 3)
        diagnostic = self.diagnostics.read_text()
        self.assertNotIn('warranty', diagnostic)
        self.assertNotIn('record.txt', diagnostic)
        self.assertNotIn('TEST_PRIVATE_REASONING', diagnostic + result.stdout)
        self.assertGreater(payload['metrics']['peakProcessTreeRSSBytes'], 0)

    def test_contract_retry_reuses_returned_evidence_and_search_budget(self) -> None:
        result = self.launch('repair')
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['attempts'], 2)
        self.assertEqual(len(payload['searches']), 2)

    def test_frozen_runtime_dispatches_nested_searches_by_reviewed_module(self) -> None:
        executable = self.root / 'frozen-runtime'
        executable.write_text(f'#!{sys.executable}\n'
                              'import sys\n'
                              'assert sys.argv.pop(1) == "mere_archive_tools.cli"\n'
                              'from mere_archive_tools.cli import main\n'
                              'raise SystemExit(main())\n')
        executable.chmod(0o755)
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(executable)):
            result = self.launch('success')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)['searches']), 2)

    def test_memory_sampling_timeout_does_not_cancel_work(self) -> None:
        processes = Processes()
        with patch('mere_archive_tools.investigation_processes.subprocess.run',
                   side_effect=subprocess.TimeoutExpired(['ps'], 2)):
            result = processes.run([sys.executable, '-c', 'print("completed")'], timeout=3)
        self.assertEqual(result.stdout.strip(), 'completed')
        self.assertGreaterEqual(processes.missed_memory_samples, 1)
        self.assertFalse(processes.children)

    def test_rejects_missing_trace_fabrication_budget_and_invalid_json(self) -> None:
        for mode, message in [('missing', "didn't call"), ('citation', "weren't returned"),
                              ('budget', 'budget'), ('invalid', 'JSON')]:
            with self.subTest(mode=mode):
                result = self.launch(mode)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertIn(message, result.stderr)

    def test_reads_only_final_completed_assistant_text(self) -> None:
        def event(text: str, stop: str = 'stop') -> str:
            return json.dumps({'type': 'message_end', 'message': {'role': 'assistant', 'stopReason': stop,
                              'content': [{'type': 'thinking', 'thinking': 'PRIVATE_REASONING'},
                                          {'type': 'text', 'text': text}]}})
        stream = '\n'.join([event('{"intermediate":true}', 'toolUse'),
                             event('{"answer":"final"}'), '{"type":"agent_end"}'])
        self.assertEqual(parse_pi_output(stream), {'answer': 'final'})
        for invalid in [event('{"answer":"cut off"}', 'length') + '\n{"type":"agent_end"}',
                        event('{"answer":"unfinished"}'), 'not JSON']:
            with self.assertRaises(InvestigationError):
                parse_pi_output(invalid)

    def test_admission_uses_current_load(self) -> None:
        base = {'capacityPermits': 4, 'activePermits': 2, 'queued': [],
                'memoryPressure': 'nominal', 'availableMemoryBytes': 64 * 1024**3}
        self.assertFalse(search_needs_server_pause({'machineAdmission': base}))
        for change in [{'capacityPermits': 1, 'activePermits': 1}, {'capacityPermits': 2},
                       {'activePermits': 3}, {'queued': [{}]}, {'memoryPressure': 'warning'},
                       {'availableMemoryBytes': 10 * 1024**3}]:
            with self.subTest(change=change):
                self.assertTrue(search_needs_server_pause({'machineAdmission': {**base, **change}}))

    def test_keeps_server_when_search_has_admission_capacity(self) -> None:
        with patch.dict(os.environ, {'TEST_CAPACITY': '4'}):
            result = self.launch('success')
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [event['event'] for event in json.loads(result.stdout)['metrics']['events']]
        self.assertEqual(events.count('server_start'), 1)
        self.assertEqual(events.count('search_kept_server'), 2)

    def test_releases_server_when_work_queues_after_search_starts(self) -> None:
        result = self.launch('race')
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [event['event'] for event in json.loads(result.stdout)['metrics']['events']]
        self.assertIn('search_kept_server', events)
        self.assertIn('search_released_queued_server', events)

    def test_search_deadline_stops_nested_inference(self) -> None:
        result = self.launch('tooltimeout', ['--search-timeout', '1'])
        self.assertEqual(result.returncode, 1)
        self.assertIn('tool deadline', result.stderr)

    def test_first_search_and_pi_deadlines(self) -> None:
        for extra in [['--first-search-timeout', '1'], ['--pi-timeout', '1']]:
            with self.subTest(extra=extra):
                result = self.launch('hang', extra)
                self.assertEqual(result.returncode, 1)
                self.assertTrue('deadline' in result.stderr or 'within 1 seconds' in result.stderr)
                self.assertIn('server_stopped', self.diagnostics.read_text())

    def test_diagnostics_cannot_overwrite_sources_or_database(self) -> None:
        for path in [self.source / 'record.txt', self.database]:
            with self.subTest(path=path):
                before = path.read_bytes()
                result = self.launch('success', ['--diagnostics', str(path)])
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(before, path.read_bytes())

    def test_interrupt_stops_server_pi_and_grandchild(self) -> None:
        for sig in [signal.SIGINT, signal.SIGTERM]:
            for before_ready in [False, True]:
                with self.subTest(signal=sig, before_ready=before_ready):
                    marker = self.root / f'pids-{sig}-{before_ready}'
                    environment = {**os.environ, 'TEST_PI_MODE': 'hang', 'TEST_PROCESS_LOG': str(marker)}
                    if before_ready:
                        environment['TEST_SERVER_WAIT'] = '1'
                    process = subprocess.Popen([sys.executable, '-m', 'mere_archive_tools', *self.args],
                                               env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    try:
                        deadline = time.monotonic() + 5
                        expected = 1 if before_ready else 3
                        while time.monotonic() < deadline:
                            if marker.exists() and len(marker.read_text().splitlines()) >= expected:
                                break
                            time.sleep(0.05)
                        else:
                            self.fail('Investigation did not reach the interruption stage')
                        process.send_signal(sig)
                        stdout, stderr = process.communicate(timeout=8)
                        self.assertEqual(process.returncode, 128 + sig, stderr)
                        self.assertEqual(stdout, '')
                        for pid in marker.read_text().splitlines():
                            state = subprocess.run(['ps', '-o', 'stat=', '-p', pid], capture_output=True, text=True, check=False)
                            self.assertTrue(not state.stdout.strip() or state.stdout.strip().startswith('Z'), state.stdout)
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait()


@unittest.skipUnless(os.environ.get('MERE_ARCHIVE_HARBOURLINE_DATABASE'), 'opt-in installed-model acceptance')
class HarbourlineAcceptance(unittest.TestCase):
    def test_compound_warranty_question(self) -> None:
        database = os.environ['MERE_ARCHIVE_HARBOURLINE_DATABASE']
        model = os.environ.get('MERE_ARCHIVE_ACCEPTANCE_MODEL', DEFAULT_MODEL)
        entrypoint = shlex.split(os.environ['MERE_ARCHIVE_ACCEPTANCE_COMMAND']) if os.environ.get('MERE_ARCHIVE_ACCEPTANCE_COMMAND') else [
            sys.executable, '-m', 'mere_archive_tools']
        command = [
            *entrypoint, 'investigate', '--database', database, '--model', model,
            '--question', 'Was the Freezer 3 repair covered by warranty, and when does that warranty expire?',
        ]
        output_dir = os.environ.get('MERE_ARCHIVE_ACCEPTANCE_OUTPUT_DIR')
        pi_timeout = os.environ.get('MERE_ARCHIVE_ACCEPTANCE_PI_TIMEOUT')
        if pi_timeout:
            command.extend(['--pi-timeout', pi_timeout])
        if output_dir:
            output = pathlib.Path(output_dir)
            command.extend(['--output', str(output / 'result.json'), '--diagnostics', str(output / 'diagnostics.json')])
        result = subprocess.run(command, capture_output=True, text=True, timeout=int(pi_timeout or '300') + 450)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertGreaterEqual(len(payload['searches']), 2)
        schema = json.loads((REPO_ROOT / 'contracts/archive-investigation.v1.schema.json').read_text())
        Draft202012Validator(schema).validate(payload)
        paths = {path for search in payload['searches'] for path in search['resultPaths']}
        required = [
            {'Facilities/Halifax/Freezer 3/2024/WO-HFX-241842-corrective-repair.pdf'},
            {'Finance/Accounts Payable/Northshore Refrigeration/2024/INV-8841.pdf',
             'Old Backups/Email Attachments/2024/INV-8841-copy.pdf'},
            {'Vendors/Northshore Refrigeration/service-agreement-2024.docx'},
        ]
        for group in required:
            self.assertTrue(paths.intersection(group), (group, paths))
        self.assertTrue(payload['claims'])
        self.assertTrue(payload['unresolvedClaims'], 'The fixture does not establish repair reimbursement or labor exclusion')
        self.assertTrue(any(claim['status'] == 'supported' and '2026-02-17' in claim['statement']
                            for claim in payload['claims']), 'The returned work order establishes the parts expiry date')
