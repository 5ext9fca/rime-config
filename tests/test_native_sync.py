import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'client'))
from native_sync import FullNativeSync, native_names
from weasel_sync import verify_log
from dictionaries import exchange


def snapshot(device, name):
    return f'#@/db_type\tuserdb\n#@/db_name\t{name}\n#@/user_id\t{device}\n'.encode()


class NativeSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'user'; self.target.mkdir()
        self.sync = self.target / 'sync'
        self.scope = self.root / 'scope.json'
        self.scope.write_text(json.dumps({'version': 1, 'configuration': {'enabled': True, 'files': []},
                                         'dictionaries': {'enabled': True, 'names': ['old']}}))
        self.native = FullNativeSync(self.target, self.sync, 'local', self.scope,
                                     self.root / 'state', command=json.dumps([sys.executable, '-c', 'pass']))

    def test_additive_scope_all_platforms_and_read_only_preview(self):
        (self.target / 'learned.userdb').mkdir()
        peer = self.sync / 'peer'; peer.mkdir(parents=True)
        (peer / 'other.userdb.txt').write_bytes(snapshot('peer', 'other'))
        (peer / 'default.yaml').write_text('native config backup')
        before = self.scope.read_bytes()
        planned = self.native.prepare(True)
        self.assertEqual(set(planned['dictionaries']['names']), {'old', 'learned', 'other'})
        self.assertEqual(self.scope.read_bytes(), before)
        self.assertFalse(self.native.state.exists())
        self.native.prepare()
        (peer / 'other.userdb.txt').unlink()
        self.assertEqual(set(self.native.prepare()['dictionaries']['names']), {'old', 'learned', 'other'})

    def test_disabled_does_not_enable_or_expand(self):
        value=json.loads(self.scope.read_text());value['dictionaries']['enabled']=False
        self.scope.write_text(json.dumps(value))
        (self.target/'extra.userdb').mkdir()
        self.assertEqual(self.native.prepare(), value)

    def test_snapshot_metadata_and_unknown_database_fail_closed(self):
        peer=self.sync/'peer';peer.mkdir(parents=True)
        (peer/'bad.userdb.txt').write_bytes(snapshot('different','bad'))
        with self.assertRaises(ValueError): self.native.prepare()
        (peer/'bad.userdb.txt').write_bytes(snapshot('peer','bad.userdb.other.userdb'))
        with self.assertRaises(ValueError): self.native.prepare()
        (peer/'bad.userdb.txt').unlink()
        (self.target/'.temp.userdb').mkdir()
        with self.assertRaises(ValueError): native_names(self.target,self.sync)

    def test_new_database_mid_round_blocks_and_updates_scope(self):
        self.native.prepare()
        (self.target/'new.userdb').mkdir()
        with self.assertRaises(ValueError): self.native.check(['old'])
        self.assertIn('new',json.loads(self.scope.read_text())['dictionaries']['names'])

    def test_unix_receipt_required_and_run_once_for_all_names(self):
        own=self.sync/'local';own.mkdir(parents=True)
        for name in ('one','two'):
            (self.target/(name+'.userdb')).mkdir()
            (own/(name+'.userdb.txt')).write_bytes(snapshot('local',name))
        scope=self.native.prepare()
        names=scope['dictionaries']['names']
        calls=[]
        def execute(*args,**kw):
            calls.append(args)
            env=kw['env']
            Path(env['RIME_SYNC_RECEIPT']).write_text(json.dumps({'status':'success','names':['one','two']}))
        with patch('native_sync.subprocess.run',side_effect=execute):
            exchange(self.sync,self.root/'store','local',self.root/'exchange',names=names,native=self.native)
        self.assertEqual(len(calls),1)
        self.assertEqual(json.loads((self.native.state/'latest.json').read_text())['status'],'success')
        with patch('native_sync.subprocess.run'), patch('native_sync.time.time', return_value=time.time() + 4000):
            with self.assertRaises(FileNotFoundError): self.native.run(names)
        self.assertEqual(json.loads((self.native.state/'latest.json').read_text())['status'],'failed')

    def test_receiving_without_database_is_not_import_success(self):
        peer=self.sync/'peer';peer.mkdir(parents=True)
        (peer/'other.userdb.txt').write_bytes(snapshot('peer','other'))
        names=self.native.prepare()['dictionaries']['names']
        def execute(*args,**kw):
            Path(kw['env']['RIME_SYNC_RECEIPT']).write_text(json.dumps({'status':'success','names':[]}))
        with patch('native_sync.subprocess.run',side_effect=execute):
            with self.assertRaisesRegex(ValueError,'尚无本机用户数据库'): self.native.run(names)

    def test_weasel_requires_native_task_success_scope_and_resume(self):
        good="synchronize user dict 'one'.\n3 tasks ran: 3 success, 0 failure.\nResuming service.\n"
        verify_log(good,{'one'})
        for bad in (good.replace('3 success, 0 failure','2 success, 1 failure'),
                    good.replace('one','two'),good+'E20261110 error\n'):
            with self.assertRaises(ValueError): verify_log(bad,{'one'})

    def test_schedule_cooldown_idle_change_and_restart(self):
        names=self.native.prepare()['dictionaries']['names']
        with patch.object(self.native,'execute',return_value={'status':'success'}) as run:
            self.native.run(names,now=10000)
            peer=self.sync/'peer';peer.mkdir(parents=True)
            (peer/'old.userdb.txt').write_bytes(snapshot('peer','old'))
            self.assertEqual(self.native.run(names,now=10060)['reason'],'interval')
            with patch.object(self.native,'idle_seconds',return_value=1):
                self.assertEqual(self.native.run(names,now=10901)['reason'],'input-active')
            self.native.run(names,now=10902)
            self.assertEqual(run.call_count,2)
        restarted=FullNativeSync(self.target,self.sync,'local',self.scope,self.root/'state',command=self.native.command)
        with patch.object(restarted,'execute') as run:
            self.assertEqual(restarted.run(names,now=10960)['reason'],'interval')
            self.assertEqual(restarted.run(names,now=11900)['reason'],'no-change')
            run.assert_not_called()
        with patch.object(restarted,'execute',return_value={'status':'success'}) as run:
            restarted.run(names,now=14503)
            run.assert_called_once()  # bounded flush for changes still cached in native memory

    def test_failed_attempt_quarantines_exports_and_survives_restart(self):
        names=self.native.prepare()['dictionaries']['names']
        with patch.object(self.native,'execute',side_effect=ValueError('failed')):
            with self.assertRaises(ValueError):self.native.run(names,now=10000)
        restarted=FullNativeSync(self.target,self.sync,'local',self.scope,self.root/'state',command=self.native.command)
        with patch.object(restarted,'execute') as run:
            self.assertEqual(restarted.run(names,now=10060)['reason'],'retry-wait')
            self.assertFalse(restarted.publish_allowed)
            run.assert_not_called()
        with patch.object(restarted,'execute',return_value={'status':'success'}):
            self.assertEqual(restarted.run(names,now=10901)['status'],'success')
            self.assertTrue(restarted.publish_allowed)

    def test_legacy_success_migrates_without_immediate_maintenance(self):
        names=self.native.prepare()['dictionaries']['names']
        (self.native.state/'latest.json').write_text(json.dumps({'status':'success','completed_at':10000}))
        with patch.object(self.native,'execute') as run:
            self.assertEqual(self.native.run(names,now=10030)['reason'],'interval')
            run.assert_not_called()

    def test_unix_idle_deferred_receipt_does_not_claim_import(self):
        names=self.native.prepare()['dictionaries']['names']
        def execute(*args,**kw):
            self.assertEqual(kw['env']['RIME_SYNC_IDLE_SECONDS'],'30')
            Path(kw['env']['RIME_SYNC_RECEIPT']).write_text(json.dumps({'status':'deferred'}))
        with patch('native_sync.subprocess.run',side_effect=execute):
            result=self.native.run(names,now=10000)
        self.assertEqual(result['status'],'deferred')
        self.assertEqual(result['last_success_at'],0)
        self.assertEqual(json.loads((self.native.state/'schedule.json').read_text())['last_attempt'],0)

    def test_policy_validation(self):
        from native_sync import load_schedule,DEFAULT_SCHEDULE
        path=self.root/'policy.json'
        for values in ({**DEFAULT_SCHEDULE,'idle_seconds':0},
                       {**DEFAULT_SCHEDULE,'interval_seconds':True},
                       {**DEFAULT_SCHEDULE,'max_interval_seconds':60}):
            path.write_text(json.dumps(values))
            with self.assertRaises(ValueError):load_schedule(path)


if __name__ == '__main__': unittest.main()
