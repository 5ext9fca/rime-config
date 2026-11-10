"""Dependency boundaries that protect the refactored execution model."""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch
from client.maintenance.idle import IdleProvider,Observation
from client.core.plans import maintenance
from client.maintenance.native_sync import DEFAULT_SCHEDULE

ROOT=Path(__file__).resolve().parents[1]

class ArchitectureTests(unittest.TestCase):
    def test_core_merge_and_transport_have_no_frontend_dependency(self):
        for relative in ('client/core/merge.py','client/transport/http_transport.py','server/app.py','server/backups.py'):
            tree=ast.parse((ROOT/relative).read_text())
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom):
                    module=node.module or ''
                    self.assertFalse(module.startswith(('client.application','client.platforms','client.cli')), (relative,module))
    def test_no_module_imports_cli_as_utility(self):
        for path in (ROOT/'client').rglob('*.py'):
            if path.name=='cli.py':continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.ImportFrom):self.assertNotIn(node.module,('sync','client.cli'))
        self.assertFalse((ROOT/'client/sync.py').exists())
    def test_unknown_idle_cannot_authorize_maintenance(self):
        provider=IdleProvider('macos')
        with patch('client.maintenance.idle.macos_seconds',side_effect=OSError('unavailable')):
            observed=provider.observe(30)
        self.assertEqual(observed.state,'unknown')
        decision=maintenance('macos',DEFAULT_SCHEDULE,{},'changed',100000,observed.state)
        self.assertEqual(decision['steps'][0]['action'],'defer')
    def test_provider_lifecycle_closes_wayland_connection(self):
        from unittest.mock import Mock
        provider=IdleProvider('linux');monitor=Mock();provider.wayland=monitor
        provider.close();monitor.close.assert_called_once();self.assertIsNone(provider.wayland)

    def test_windows_sync_uses_shared_frontend_lock(self):
        from client.platforms.windows import weasel_sync
        from contextlib import contextmanager
        events=[]
        @contextmanager
        def lock(target):
            events.append('locked')
            yield
            events.append('released')
        def execute(*args):
            self.assertEqual(events,['locked'])
            return {'status':'deferred'}
        with patch('client.maintenance.lock.maintenance_lock',side_effect=lock),patch.object(weasel_sync,'_run',side_effect=execute):
            self.assertEqual(weasel_sync.run(None,Path('/target'),None,None,None,None)['status'],'deferred')
        self.assertEqual(events,['locked','released'])

    def test_deployment_keeps_native_receipt_when_resource_recheck_fails(self):
        import json,tempfile
        from client.maintenance.deployment import deploy
        class Executor:
            def deploy(self,target,policy,session):
                (target/'a.yaml').unlink()
                return {'status':'success','frontend_pid':123}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);target=root/'target';target.mkdir();(target/'a.yaml').write_text('value')
            state=root/'state'
            with self.assertRaisesRegex(ValueError,'Resources changed'):
                deploy(target,['a.yaml'],state,{'enabled':True,'retry_seconds':900},Executor(),now=1000)
            record=json.loads((state/'deployment.json').read_text())
            self.assertEqual(record['status'],'failed')
            self.assertEqual(record['failure_phase'],'resource-recheck')
            receipt=json.loads((state/'runs'/record['session']/'receipt.json').read_text())
            self.assertEqual(receipt['status'],'success')
            self.assertEqual(record['retry_at'],1900)
