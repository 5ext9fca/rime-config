import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import client.core.plans as plans
import client.core.configuration as sync
import client.cli as cli
import client.application.runtime as runtime
from client.maintenance.native_sync import DEFAULT_SCHEDULE
from client.platforms.platform_execution import get_executor, WindowsExecutor, UnixExecutor


class PlanTests(unittest.TestCase):
    def workflow(self, platform='windows'):
        return plans.workflow(platform, remote=True, configuration=True, dictionaries=True,
                              store=False, third_party=True, native_backend='weasel')

    def test_cross_platform_configuration_and_native_decisions_match(self):
        expected = None
        for platform in ('windows','linux','macos'):
            files=plans.configuration(platform, {'a':b'new','b':b'same','d':b'create'},
                                      {'a':b'old','b':b'same','c':b'delete'}, ['a','b','c'])
            actual=[(s['id'],s['action']) for s in files['steps']]
            self.assertEqual(actual,[('a','replace'),('b','skip'),('c','delete'),('d','create')])
            native=plans.maintenance(platform,DEFAULT_SCHEDULE,{'last_attempt':10000,'last_success':10000},'x',10001)
            if expected is None:expected=native['steps']
            self.assertEqual(native['steps'],expected)
            self.assertNotIn('new',plans.dumps(files))  # contents never enter a plan

    def test_unknown_contracts_rejected_before_dispatch(self):
        handlers={k:Mock(return_value={'status':'success','reason':'test'}) for k in plans.STAGES}
        cases=[]
        for field,value in [('version',2),('version',True),('kind','unknown'),('platform','unknown'),('platform','wsl')]:
            plan=self.workflow();plan[field]=value;cases.append(plan)
        plan=self.workflow();plan['steps'][0]['action']='shell';cases.append(plan)
        plan=self.workflow();plan['steps'][0]['requires']=['configuration-apply'];cases.append(plan)
        plan=self.workflow();plan['steps'][0]['extra']='bad';cases.append(plan)
        for plan in cases:
            with self.assertRaises(ValueError):plans.execute_workflow(plan,handlers)
        for handler in handlers.values():handler.assert_not_called()

    def test_dependency_failure_does_not_block_independent_refresh(self):
        handlers={k:Mock(return_value={'status':'success','reason':'test'}) for k in plans.STAGES}
        handlers['remote-sync'].return_value={'status':'failed','reason':'network'}
        result=plans.execute_workflow(self.workflow(),handlers)
        handlers['configuration-apply'].assert_not_called()
        handlers['third-party-refresh'].assert_called_once()
        self.assertEqual(result['steps'][1]['status'],'blocked')
        self.assertEqual(result['steps'][2]['status'],'skipped')

    def test_report_marks_aborted_run_instead_of_old_success(self):
        published=[]
        handlers={k:Mock(return_value={'status':'success','reason':'test'}) for k in plans.STAGES}
        handlers['configuration-apply'].side_effect=OSError('simulated')
        with self.assertRaises(OSError):plans.execute_workflow(self.workflow(),handlers,publish=lambda r:published.append(copy.deepcopy(r)))
        self.assertEqual(published[0]['steps'][0]['status'],'pending')
        self.assertEqual(published[-1]['steps'][1]['status'],'failed')
        self.assertEqual(published[-1]['steps'][-1]['status'],'blocked')

    def test_platform_dispatch_is_explicit_and_preserves_service_arguments(self):
        with self.assertRaises(ValueError):get_executor('wsl')
        self.assertIsInstance(get_executor('windows'),WindowsExecutor)
        for name in ('linux','macos'):
            self.assertIsInstance(get_executor(name),UnixExecutor)
        with patch('client.platforms.windows.windows_service.manage_windows',return_value=0) as win:
            get_executor('windows').service('status',None,None)
            win.assert_called_once_with('status',None,None,None)
        with patch('client.services.unix_service.manage_unix',return_value=0) as unix:
            get_executor('macos').service('status',None,None)
            unix.assert_called_once_with('status',None,None,None,'Darwin')
        self.assertEqual(get_executor('linux').observe_idle(30,delegated=True).state,'delegated')

    def test_configuration_plan_is_read_only_and_rechecks_stale_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';target=root/'target';state=root/'state'
            source.mkdir();target.mkdir()
            (source/'a.yaml').write_text('new');(target/'a.yaml').write_text('old')
            _,_,plan=sync.observe_configuration(source,target,state)
            self.assertFalse(state.exists())
            (target/'a.yaml').write_text('concurrent edit')
            with self.assertRaises(ValueError):sync.recheck_configuration(plan,source,target)
            self.assertEqual((target/'a.yaml').read_text(),'concurrent edit')
            bad=copy.deepcopy(plan);bad['steps'][0]['action']='delete'
            with self.assertRaises(ValueError):plans.validate(bad)

    def test_plan_json_no_network_no_state_writes_and_no_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'Rime';target.mkdir()
            identity=root/'device.local.json'
            token='secret-test-only-'+'x'*40
            identity.write_text(json.dumps({'version':1,'installation_id':'test','token':token,'target':str(target)}))
            remote=root/'remote.json'
            remote.write_text(json.dumps({'enabled':True,'url':'https://invalid.test/rime/v1/state','interval_seconds':60,'retry_seconds':30,'timeout_seconds':1}))
            manifest=root/'manifest.json'
            manifest.write_text(json.dumps({'version':1,'configuration':{'enabled':True,'files':['weasel.custom.yaml']},
                                            'dictionaries':{'enabled':True,'names':['old']}}))
            (target/'new.userdb').mkdir()
            cmd=[sys.executable,str(ROOT/'rime.py'),'--plan-json','--target',str(target),
                 '--device-config',str(identity),'--remote-config',str(remote),'--sync-config',str(manifest),
                 '--paths-state',str(root/'paths.local.json'),'--state-dir',str(root/'state'),
                 '--native-sync-all-command',json.dumps([sys.executable,'-c','raise SystemExit(99)'])]
            before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            plan=json.loads(result.stdout);plans.validate(plan)
            self.assertEqual(plan['kind'],'workflow-plan')
            self.assertEqual(plan['steps'][0]['details']['native_preview']['steps'][0]['action'],'observe')
            self.assertNotIn(token,result.stdout)
            self.assertNotIn('SystemExit',result.stdout)
            self.assertFalse((root/'state').exists())
            after={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(after,before)


if __name__=='__main__':unittest.main()
