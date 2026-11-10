import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client.application.deployment_test import run
from client.cli import parse_args
from client.platforms.platform_execution import WindowsExecutor


class DeployNowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'; self.source.mkdir()
        self.target = self.root / 'target'; self.target.mkdir()
        self.state = self.root / 'state'
        (self.source / 'a.yaml').write_text('new')
        (self.target / 'a.yaml').write_text('old')
        scope = self.root / 'scope.json'
        scope.write_text(json.dumps({'version': 1, 'configuration': {'enabled': True, 'files': ['a.yaml']},
                                    'dictionaries': {'enabled': False, 'names': []}}))
        self.args = SimpleNamespace(sync_config=scope, third_party_config=ROOT/'third-party.json',
                                    automation_config=ROOT/'automation.json', dry_run=False)

    def test_preview_is_readonly_and_never_loads_executor(self):
        self.args.dry_run = True
        with patch('client.application.deployment_test.get_executor', side_effect=AssertionError('native access')):
            self.assertEqual(run(self.args, self.target, self.state, self.source), 0)
        self.assertFalse(self.state.exists())
        self.assertEqual((self.target/'a.yaml').read_text(), 'old')

    def test_backups_force_repeat_and_no_network_or_dictionary_state(self):
        executor = Mock(); executor.deploy.return_value = {'status': 'success'}
        with patch('client.application.deployment_test.get_executor', return_value=executor), \
                patch('client.transport.http_transport.request', side_effect=AssertionError('network')):
            for _ in range(2):
                self.assertEqual(run(self.args, self.target, self.state, self.source), 0)
        self.assertEqual(executor.deploy.call_count, 2)
        self.assertEqual(executor.deploy.call_args.kwargs, {'immediate': True})
        self.assertEqual((self.target/'a.yaml').read_text(), 'new')
        self.assertTrue(any(p.read_text() == 'old' for p in self.state.glob('backups/*/files/a.yaml')))
        self.assertFalse((self.state/'native-all').exists())
        self.assertFalse((self.state/'remote').exists())

    def test_failure_recorded_and_explicit_retry_bypasses_backoff(self):
        executor = Mock(); executor.deploy.side_effect = ValueError('native failure')
        with patch('client.application.deployment_test.get_executor', return_value=executor):
            with self.assertRaises(ValueError):run(self.args, self.target, self.state, self.source)
            report = json.loads((self.state/'deployment-test-result.json').read_text())
            self.assertEqual(report['status'], 'failed')
            executor.deploy.side_effect = None; executor.deploy.return_value = {'status': 'success'}
            self.assertEqual(run(self.args, self.target, self.state, self.source), 0)

    def test_cli_rejects_recurring_and_sync_combinations(self):
        for flags in (['--watch'], ['--service','install'], ['--sync-now'], ['--native-sync-builtin'], ['--plan-json']):
            with self.subTest(flags=flags), patch.object(sys, 'argv', ['rime.py','--deploy-now',*flags]), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parse_args()
        with patch.object(sys, 'argv', ['rime.py','--deploy-now','--dry-run']):
            self.assertTrue(parse_args().dry_run)

    def test_manual_idle_override_is_scoped_to_deployment(self):
        executor = WindowsExecutor()
        self.addCleanup(executor.close)
        policy = {'enabled': True, 'idle_seconds': 30, 'commands': {}}
        with patch('client.maintenance.deployment.execute_platform', return_value={'status':'success'}) as platform:
            executor.deploy(self.target, policy, self.root, immediate=True)
            args = platform.call_args.args
            self.assertEqual(args[2]['idle_seconds'], 0)
            self.assertTrue(args[4].observe(30).permits_maintenance)
            self.assertEqual(policy['idle_seconds'], 30)
            executor.deploy(self.target, policy, self.root)
            self.assertIs(platform.call_args.args[4], executor.idle_provider)


if __name__ == '__main__': unittest.main()
