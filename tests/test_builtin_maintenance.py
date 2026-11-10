import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import client.platforms.linux.fcitx_maintenance as fcitx
from client.platforms.platform_execution import UnixExecutor


class FcitxCompletionTests(unittest.TestCase):
    def run_events(self,operation,events,pid=123):
        with tempfile.TemporaryDirectory() as temp:
            session=Path(temp)
            target=Path.home()/'.local/share/fcitx5/rime'
            def command(argv,**kwargs):
                if argv[0]=='gdbus':return SimpleNamespace(stdout='(uint32 123,)')
                if '--show-cursor' in argv:return SimpleNamespace(stdout='-- cursor: test-cursor')
                return SimpleNamespace(stdout=events)
            with patch.dict('os.environ',{'XDG_DATA_HOME':str(Path.home()/'.local/share')}),patch.object(fcitx.subprocess,'run',side_effect=command),patch.object(fcitx.time,'sleep'),patch.object(fcitx,'frontend_pid',return_value=pid):
                return fcitx._run(target,30,session,operation,lambda *args:None,lambda threshold:True)

    def test_sync_success_requires_operation_and_ordered_events(self):
        result=self.run_events('sync','Rime Sync user data\nNotification: 0 deploy start\nNotification: 0 deploy success')
        self.assertEqual(result['status'],'success')

    def test_sync_rejects_overlapping_deployment_and_failure(self):
        for text in ['Rime Deploy\nNotification: 0 deploy start\nNotification: 0 deploy success',
                     'Rime Sync user data\nNotification: 0 deploy failure',
                     'Rime Sync user data\nNotification: 0 deploy start\nNotification: 0 deploy start']:
            with self.subTest(text=text),self.assertRaises(ValueError):self.run_events('sync',text)

    def test_frontend_restart_not_acknowledged(self):
        with self.assertRaisesRegex(ValueError,'restarted'):
            self.run_events('sync','Rime Sync user data\nNotification: 0 deploy start\nNotification: 0 deploy success',456)

    def test_bootstrap_waits_for_idle(self):
        from unittest.mock import Mock
        prepare=Mock();call=Mock()
        with tempfile.TemporaryDirectory() as directory,patch.dict('os.environ',{'XDG_DATA_HOME':str(Path.home()/'.local/share')}):
            result=fcitx._run(Path.home()/'.local/share/fcitx5/rime',30,Path(directory),'sync',call,lambda _:False,prepare)
        self.assertEqual(result['status'],'deferred');prepare.assert_not_called();call.assert_not_called()

    def test_builtin_dispatch_does_not_launch_external_wrapper(self):
        with patch('client.maintenance.builtin_native.run',return_value={'status':'deferred'}) as run:
            result=UnixExecutor('linux').native(argv=None,deployer=None,target=Path('/target'),sync_dir=Path('/sync'),device='id',names={'a'},session=Path('/state'),idle_seconds=30)
            self.assertEqual(result['status'],'deferred');run.assert_called_once()


class OtherPlatformEvidenceTests(unittest.TestCase):
    def test_squirrel_requires_new_start_and_all_dictionaries(self):
        from client.platforms.macos.squirrel_maintenance import verify_tasks
        text="running deployment tasks:\nsynchronize user dict 'a'\n3 tasks ran: 3 success, 0 failure"
        self.assertTrue(verify_tasks(text,'sync',{'a'}))
        for value in [text.replace('running deployment tasks:',''),text.replace('0 failure','1 failure'),text+'\n'+text]:
            with self.assertRaises(ValueError):verify_tasks(value,'sync',{'a'})
        with self.assertRaises(ValueError):verify_tasks(text,'sync',{'a','b'})
        with self.assertRaises(ValueError):verify_tasks(text,'deploy',set())
        self.assertTrue(verify_tasks('running deployment tasks:\nupdating workspace.\n3 tasks ran: 3 success, 0 failure','deploy',set()))

    def test_windows_exit_without_task_and_resume_evidence_is_rejected(self):
        from client.platforms.windows.weasel_deploy import verify_log
        for text in ['', 'Resuming service.', '3 tasks ran: 3 success, 0 failure',
                     '3 tasks ran: 2 success, 1 failure\nResuming service.']:
            with self.assertRaises(ValueError):verify_log(text)
        verify_log('updating workspace.\nfinished updating schemas: 4 success, 0 failure\nResuming service.')
        with self.assertRaises(ValueError):
            verify_log('updating workspace.\nfinished updating schemas: 3 success, 1 failure\nResuming service.')
        with self.assertRaises(ValueError):
            verify_log('Resuming service.\nupdating workspace.\nfinished updating schemas: 4 success, 0 failure')

    def test_builtin_sync_does_not_accept_stale_exports(self):
        import client.maintenance.builtin_native as builtin_native
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'installation.yaml').write_text('installation_id: test\n')
            with patch.object(builtin_native.ctypes.util,'find_library',return_value='rime'),patch('client.platforms.rime_api.configured_sync_dir',return_value=root/'sync'),patch('client.platforms.linux.fcitx_maintenance.run',return_value={'status':'success'}),patch.object(builtin_native,'snapshots',return_value={}):
                with self.assertRaisesRegex(ValueError,'导出'):
                    builtin_native.run('linux',root,root/'sync','test',{'a'},root,30)

class CompatibilityTests(unittest.TestCase):
    def test_existing_native_schedule_binding_retains_rate_limit(self):
        from client.maintenance.native_sync import FullNativeSync
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/'state';state.mkdir()
            command=json.dumps(['/bin/true'])
            binding=[str(root/'target'),str(root/'sync'),'id',command,'None']
            old={'binding':binding,'last_attempt':123,'last_success':120,'unsafe':False}
            (state/'schedule.json').write_text(json.dumps(old))
            native=FullNativeSync(root/'target',root/'sync','id',root/'manifest',state,command=command)
            self.assertEqual(native.read_schedule()[1],old)

    def test_builtin_option_persisted_by_service_allowlist(self):
        from client.services.service import command
        args=SimpleNamespace(interval=60,device_config=Path('/identity'),third_party_only=False,native_sync_builtin=True)
        self.assertIn('--native-sync-builtin',command(args,Path('/client/sync.py'),Path('/target')))

class SquirrelLogObservationTests(unittest.TestCase):
    def exercise(self,change):
        import contextlib
        import client.platforms.macos.squirrel_maintenance as squirrel
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);session=root/'session';session.mkdir()
            logs=root/'rime.squirrel';logs.mkdir()
            log=logs/'rime.squirrel.host.user.log.INFO.20260101.123.log'
            log.write_text("running deployment tasks:\nsynchronize user dict 'a'\n3 tasks ran: 3 success, 0 failure\n")
            command=Path('/Library/Input Methods/Squirrel.app/Contents/MacOS/Squirrel')
            def invoke(argv,**kwargs):
                self.assertEqual(argv,[str(command),'--sync']);change(log)
                return SimpleNamespace(returncode=0)
            with patch.object(squirrel.Path,'home',return_value=root),patch.object(squirrel,'maintenance_lock',return_value=contextlib.nullcontext()),patch.object(squirrel,'frontend',return_value=(command,123)),patch.object(squirrel.tempfile,'gettempdir',return_value=str(root)),patch.object(squirrel.subprocess,'run',side_effect=invoke),patch.object(squirrel.time,'sleep'),patch.object(squirrel.time,'monotonic',side_effect=[0,1,181]):
                return squirrel.run(root/'Library/Rime',30,session,'sync',{'a'},idle_provider=SimpleNamespace(observe=lambda threshold:SimpleNamespace(permits_maintenance=True)))

    def test_old_success_is_not_acknowledged(self):
        with self.assertRaisesRegex(ValueError,'超时'):self.exercise(lambda path:None)

    def test_fresh_log_segment_is_acknowledged(self):
        def append(path):
            with path.open('a') as stream:stream.write("running deployment tasks:\nsynchronize user dict 'a'\n3 tasks ran: 3 success, 0 failure\n")
        self.assertEqual(self.exercise(append)['status'],'success')

    def test_log_truncation_is_not_acknowledged(self):
        with self.assertRaisesRegex(ValueError,'截断'):self.exercise(lambda path:path.write_text(''))

if __name__=='__main__':unittest.main()
