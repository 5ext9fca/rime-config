import copy
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT)]
import client.maintenance.backup_retention as retention
from client.storage.file_lock import lock_exclusive
from server import backups, credentials, database, scopes, backup_worker
from server.app import create_app
import client.core.plans as plans


class ClientRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.now=time.time()
        self.policy={'enabled':True,'retention_days':30,'keep_minimum':2,'interval_seconds':86400}

    def old(self,path,kind='marker',index=0):
        path.mkdir(parents=True)
        (path/'data.txt').write_text('backup')
        stamp=self.now-86400*(40-index)
        if kind=='journal':(path/'journal.json').write_text(json.dumps({'status':'applied'}))
        elif kind=='native':(path/'result.json').write_text(json.dumps({'status':'success','completed_at':stamp}))
        else:retention.completed(path,stamp)
        for p in list(path.rglob('*'))+[path]:os.utime(p,(stamp,stamp))
        return path

    def test_completed_groups_keep_minimum_and_readonly_preview(self):
        paths=[self.old(self.root/'backups'/f'20260101-010101-{n:08x}','journal',n) for n in range(5)]
        failed=self.old(self.root/'backups'/'20260101-010101-ffffffff','journal')
        (failed/'journal.json').write_text(json.dumps({'status':'prepared'}))
        unrelated=self.root/'baseline.json';unrelated.write_text('keep')
        before={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        preview=retention.clean(self.root,self.policy,True,now=self.now)
        self.assertEqual(len(preview['planned']),3)
        self.assertEqual(before,{str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        report=retention.clean(self.root,self.policy,now=self.now)
        self.assertEqual(report['deleted'],3);self.assertTrue(paths[-1].exists());self.assertTrue(paths[-2].exists())
        self.assertTrue(failed.exists());self.assertTrue(unrelated.exists())
        self.assertEqual(retention.clean(self.root,self.policy,now=self.now+1)['status'],'not-due')

    def test_pending_remote_unmarked_backup_and_locked_writer_preserved(self):
        for n in range(4):self.old(self.root/'remote/backups'/f'{n:032x}',index=n)
        pending=self.root/'remote/pending.json';pending.write_text('{}')
        unmarked=self.root/'remote/backups'/('f'*32)
        unmarked.mkdir();(unmarked/'file').write_text('unconfirmed')
        self.assertEqual(retention.clean(self.root,self.policy,force=True)['deleted'],0)
        pending.unlink()
        with (self.root/'remote/lock').open('a') as lock:
            lock_exclusive(lock)
            self.assertEqual(retention.clean(self.root,self.policy,force=True)['deleted'],0)
        self.assertEqual(retention.clean(self.root,self.policy,force=True)['deleted'],2)
        self.assertTrue(unmarked.exists())

    def test_native_latest_failure_and_symlink_protection(self):
        paths=[self.old(self.root/'native-all/runs'/f'{n:032x}','native',n) for n in range(5)]
        latest=self.root/'native-all/latest.json';latest.write_bytes((paths[0]/'result.json').read_bytes())
        self.assertEqual(retention.clean(self.root,self.policy,force=True)['deleted'],2)
        self.assertTrue(paths[0].exists())
        (self.root/'native-all/schedule.json').write_text('{"unsafe":true}')
        self.assertEqual(retention.clean(self.root,self.policy,force=True)['deleted'],0)
        path=self.old(self.root/'theme/backups'/'1794300000000000000')
        try:(path/'link').symlink_to(self.root/'native-all')
        except OSError:self.skipTest('symlink unavailable')
        self.assertIsNone(retention.observe(path,'marker'))

    def test_new_backup_markers_and_scope_files(self):
        group=self.root/'native-all/scope-backups';group.mkdir(parents=True)
        for n in range(5):
            p=group/(f'{n:032x}'+'.json');p.write_text('{}')
            stamp=self.now-86400*(40-n);retention.completed(p,stamp);os.utime(p,(stamp,stamp))
        self.assertEqual(retention.clean(self.root,self.policy,force=True)['deleted'],3)
        self.assertEqual(len(list(group.glob('*.json'))),2)
        self.assertEqual(len(list((group/'.completed').glob('*.json'))),2)

    def test_workflow_v3_cleanup_independent_and_legacy_policy_opt_out(self):
        from client.config.automation import load
        config={'version':1,'linux_theme':True,'deployment':{'enabled':False,'idle_seconds':30,'retry_seconds':900,'commands':{}},
                'logs':{'enabled':True,'retention_days':30,'max_file_bytes':1000}}
        p=self.root/'auto.json';p.write_text(json.dumps(config));self.assertFalse(load(p)['backups']['enabled'])
        config['backups']=self.policy
        plan=plans.workflow('linux',remote=True,configuration=True,dictionaries=False,store=False,third_party=False,automation=config)
        self.assertEqual(plan['version'],3)
        handlers={k:lambda:{'status':'success','reason':'okay'} for k in plans.STAGES_V3}
        handlers['remote-sync']=lambda:{'status':'failed','reason':'offline'}
        result=plans.execute_workflow(plan,handlers)
        self.assertEqual(result['steps'][-1]['status'],'success')


class ServerBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.database=self.root/'live.sqlite3'
        self.policy={'enabled':True,'interval_seconds':86400,'retention_days':30,'keep_minimum':2}
        self.scope={'version':1,'configuration':{'enabled':True,'files':['a.yaml']},'dictionaries':{'enabled':True,'names':['rime_ice']}}
        (self.root/'scope.json').write_text(json.dumps(self.scope))
        self.settings={'database':str(self.database),'scope':'scope.json','max_request_bytes':10000,'max_state_bytes':100000,
                       'devices':[{'user':'test','device':'a','token':'x'*40}], 'backups':self.policy,'auto_expand_dictionaries':True}
        self.path=self.root/'settings.json';self.path.write_text(json.dumps(self.settings));create_app(self.path)
        with sqlite3.connect(self.database) as db:
            credentials.authenticate(db,self.settings['devices'],'x'*40)
            credentials.rotate(db,self.settings['devices'][0],'current','y'*40)
            scopes.extend_scope(db,'test',['extra'],['rime_ice'],128)
            db.execute('INSERT INTO states VALUES (?,?,?)',('test',5,json.dumps({'configuration':{},'dictionaries':{}})))

    def test_independent_worker_backup_restores_rotated_identity_and_scope(self):
        result=backup_worker.tick(self.path)
        self.assertEqual(result['status'],'success');self.assertTrue(backup_worker.healthy(self.path,60))
        self.assertEqual(backup_worker.tick(self.path)['status'],'not-due')
        manifest=self.root/'backups'/result['manifest'];self.assertIsNotNone(backups.backup_entry(manifest))
        prefix=manifest.name.removesuffix('.manifest.json');directory=self.root/'restore';directory.mkdir()
        import shutil
        shutil.copy2(manifest.parent/(prefix+'.sqlite3'),directory/'db.sqlite3')
        saved=json.loads((manifest.parent/(prefix+'.settings.json')).read_text());saved['database']='db.sqlite3';saved['scope']='scope.json'
        (directory/'settings.json').write_text(json.dumps(saved));shutil.copy2(manifest.parent/(prefix+'.scope.json'),directory/'scope.json')
        app=create_app(directory/'settings.json');status=[]
        data=b''.join(app({'PATH_INFO':'/rime/v1/state','REQUEST_METHOD':'GET','HTTP_AUTHORIZATION':'Bearer '+'y'*40},lambda s,h:status.append(s)))
        self.assertEqual(status,['200 OK']);value=json.loads(data);self.assertEqual(value['revision'],5);self.assertIn('extra',value['scope']['dictionaries']['names'])
        with sqlite3.connect(self.database) as db:self.assertEqual(db.execute('SELECT revision FROM states').fetchone()[0],5)
        self.assertEqual(set(json.loads(manifest.read_text())['files']),{prefix+'.sqlite3',prefix+'.settings.json',prefix+'.scope.json'})

    def test_failure_keeps_previous_and_releases_lease(self):
        first=backup_worker.tick(self.path);manifest=self.root/'backups'/first['manifest'];before=manifest.read_bytes()
        with patch('server.backups.file_hash',side_effect=OSError('injected disk failure')):
            with self.assertRaises(OSError):backup_worker.tick(self.path,True)
        self.assertEqual(manifest.read_bytes(),before);self.assertFalse(backup_worker.healthy(self.path,60))
        with sqlite3.connect(self.database) as db:self.assertIsNone(db.execute("SELECT * FROM maintenance WHERE key='backup-running'").fetchone())
        self.assertEqual(backup_worker.tick(self.path,True)['status'],'success')

    def test_lock_and_stale_lease(self):
        with (self.root/'backup.lock').open('a') as lock:
            lock_exclusive(lock);self.assertEqual(backup_worker.tick(self.path)['status'],'busy')
        with sqlite3.connect(self.database) as db:db.execute("INSERT INTO maintenance VALUES ('backup-running',?)",(time.time()-700,))
        self.assertEqual(backup_worker.tick(self.path)['status'],'success')

    def test_prune_sets_atomically_scoped_and_protect_corruption(self):
        made=[]
        for _ in range(4):
            result=backup_worker.tick(self.path,True);manifest=self.root/'backups'/result['manifest']
            entry=backups.backup_entry(manifest);made.append((manifest,entry[1]))
        old=time.time()-40*86400
        for manifest,files in made:
            value=json.loads(manifest.read_text());value['created_at']=old;manifest.write_text(json.dumps(value))
            for p in files+[manifest]:os.utime(p,(old,old))
        # Corrupt one old backup: it must not count towards retained usable sets.
        made[0][1][0].write_bytes(b'corrupt');os.utime(made[0][1][0],(old,old))
        result=backup_worker.tick(self.path,True)
        self.assertEqual(result['removed_sets'],2)
        self.assertTrue(made[0][0].exists())
        valid=[p for p in (self.root/'backups').glob('*.manifest.json') if backups.backup_entry(p)]
        self.assertEqual(len(valid),2)


if __name__=='__main__':unittest.main()
