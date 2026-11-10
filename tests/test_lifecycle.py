import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT)]
from server import backups, credentials, database as schema, scopes
from server.app import create_app
from test_server_remote import ServerFixture
import client.application.cloud_sync as remote
import client.transport.http_transport as http_transport
import client.providers.token_refresh as token_refresh
import client.platforms.linux.theme as theme
import client.maintenance.deployment as deployment
import client.maintenance.logs as logs
import client.core.plans as plans


class LifecycleServerTests(ServerFixture):
    def test_rotation_retry_revoke_expiry_and_restart(self):
        new='new-secret-'+'z'*40
        url='/rime/v1/token/refresh'
        self.assertEqual(self.call('POST',{'token':new},route=url)[0],200)
        self.assertEqual(self.call('POST',{'token':new},route=url)[0],200)
        self.assertEqual(self.call('POST',{'token':'x'*40},route=url)[0],409)
        dbpath=self.root/'state.sqlite3'
        with sqlite3.connect(dbpath) as db:
            db.execute('UPDATE credentials SET previous_until=0')
            payload=str(db.execute('SELECT * FROM credentials').fetchall())
            self.assertNotIn(new,payload)
        self.assertEqual(self.call()[0],401)
        self.assertEqual(self.call('POST',{'token':new},route=url)[0],200)
        self.app=create_app(self.settings_path)
        self.assertEqual(self.call(headers={'HTTP_AUTHORIZATION':'Bearer '+new})[0],200)
        self.settings['devices'][0]['token']='replacement-'+'q'*40
        self.settings_path.write_text(json.dumps(self.settings));self.app=create_app(self.settings_path)
        self.assertEqual(self.call(headers={'HTTP_AUTHORIZATION':'Bearer '+new})[0],401)

    def test_scope_isolated_additive_limits_and_disabled(self):
        url='/rime/v1/scope/dictionaries'
        self.assertEqual(self.call('POST',{'names':['extra']},route=url)[0],403)
        self.settings.update(auto_expand_dictionaries=True,max_dictionaries=3)
        self.settings_path.write_text(json.dumps(self.settings));self.app=create_app(self.settings_path)
        self.assertEqual(self.call('POST',{'names':['extra']},route=url)[0],200)
        self.assertEqual(self.call('POST',{'names':['extra']},route=url)[0],200)
        self.assertIn('extra',self.call(device='b')[1]['scope']['dictionaries']['names'])
        self.assertNotIn('extra',self.call(device='c')[1]['scope']['dictionaries']['names'])
        for names in (['../bad'],['rime_ice.userdb'],['EXTRA'],['one','two','three']):
            self.assertEqual(self.call('POST',{'names':names},route=url)[0],400)
        self.scope['dictionaries']['enabled']=False;(self.root/'scope.json').write_text(json.dumps(self.scope))
        self.assertEqual(self.call('POST',{'names':['extra']},route=url)[0],403)


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def test_client_rotation_lost_reply_and_local_commit_interruption(self):
        identity=self.root/'device.local.json';old={'version':1,'installation_id':'a','token':'a'*40,'target':str(self.root/'rime')}
        identity.write_text(json.dumps(old))
        config={'url':'https://test.invalid/rime/v1/state','token_refresh_seconds':100,'token':old['token']}
        received=[]
        def lost(c,m,p):received.append(p['token']);raise remote.RemoteError('lost response')
        with self.assertRaises(remote.RemoteError):token_refresh.refresh(config,identity,self.root/'token',lost,1000)
        self.assertEqual(json.loads(identity.read_text()),old)
        def okay(c,m,p):received.append(p['token']);return {'status':'rotated'}
        token_refresh.refresh(config,identity,self.root/'token',okay,1001)
        self.assertEqual(received[0],received[1]);self.assertEqual(json.loads(identity.read_text())['token'],received[0])
        never=Mock(side_effect=AssertionError('not due'))
        token_refresh.refresh(config,identity,self.root/'token',never,1002)
        self.assertNotIn(received[0],(self.root/'token/rotation.json').read_text())

    def test_backup_retention_keeps_minimum_and_unmanaged_files(self):
        database=self.root/'state.sqlite3'
        with sqlite3.connect(database) as db:schema.initialize(db);db.execute('CREATE TABLE payload (value TEXT)');db.execute("INSERT INTO payload VALUES ('protected')")
        folder=self.root/'backups';folder.mkdir()
        for n in range(5):
            p=folder/f'auto-{n}.sqlite3';p.write_bytes(b'old');os.utime(p,(1,1))
            m=p.with_suffix('.manifest.json');m.write_text(json.dumps({'version':1,'status':'complete','created_at':1,'files':{p.name:backups.file_hash(p)}}));os.utime(m,(1,1))
        keep=folder/'accepted-original.sqlite3';keep.write_bytes(b'manual');os.utime(keep,(1,1))
        policy={'enabled':True,'interval_seconds':10,'retention_days':30,'keep_minimum':3}
        backups.backups(database,policy,now=time.time())
        auto=list(folder.glob('auto-*.sqlite3'));self.assertEqual(len(auto),3);self.assertTrue(keep.exists())
        new=max(auto,key=lambda p:p.stat().st_mtime)
        with sqlite3.connect(new) as db:self.assertEqual(db.execute('SELECT value FROM payload').fetchone()[0],'protected')
        backups.backups(database,policy,now=time.time());self.assertEqual(len(list(folder.glob('auto-*.sqlite3'))),3)

    def bundle(self):
        image=b'\x89PNG\r\n\x1a\n'+b'\0'*8+struct.pack('>II',24,24)
        value={'version':1,'settings':{k:'True' for k in theme.OPTIONS},'files':{}}
        value['settings'].update(Theme='hx-light',DarkTheme='hx-dark',Font='Sans 14')
        for n in theme.FILES:value['files'][n]=base64.b64encode(b'[InputPanel/Background]\nImage=panel.png\n' if n.endswith('.conf') else image).decode()
        source=self.root/'source';(source/'fcitx5').mkdir(parents=True)
        (source/theme.BUNDLE).write_text(json.dumps(value));return source,value

    def test_theme_preview_rollback_preserve_and_repeat(self):
        source,value=self.bundle();state=self.root/'state';config=self.root/'config';data=self.root/'data'
        dest=config/'fcitx5/conf/classicui.conf';dest.parent.mkdir(parents=True);dest.write_text('Unrelated=keep\nFont=Old 10\n')
        executor=Mock();executor.reload_theme.side_effect=OSError('D-Bus unavailable')
        kwargs=dict(config_home=config,data_home=data,executor=executor)
        self.assertEqual(theme.apply(source,state,True,**kwargs),'planned');self.assertFalse(state.exists())
        with self.assertRaises(OSError):theme.apply(source,state,**kwargs)
        self.assertEqual(dest.read_text(),'Unrelated=keep\nFont=Old 10\n')
        executor.reload_theme.side_effect=None
        self.assertEqual(theme.apply(source,state,**kwargs),'applied')
        self.assertIn('Unrelated=keep',dest.read_text());self.assertIn('Font=Sans 14',dest.read_text())
        self.assertEqual(theme.apply(source,state,**kwargs),'unchanged')
        value['files']['../escape']=value['files']['hx-light/panel.png']
        with self.assertRaises(ValueError):theme.decode(json.dumps(value))

    def test_deploy_retry_durable_and_no_duplicate_success(self):
        target=self.root/'rime';target.mkdir();(target/'a.yaml').write_text('a')
        state=self.root/'state';policy={'enabled':True,'retry_seconds':100,'idle_seconds':30,'commands':{}}
        executor=Mock();executor.deploy.side_effect=ValueError('failure')
        with self.assertRaises(ValueError):deployment.deploy(target,['a.yaml'],state,policy,executor,now=1000)
        self.assertEqual(deployment.deploy(target,['a.yaml'],state,policy,executor,now=1001),'deferred')
        executor.deploy.side_effect=None;executor.deploy.return_value={'status':'success'}
        self.assertEqual(deployment.deploy(target,['a.yaml'],state,policy,executor,now=1100),'success')
        count=executor.deploy.call_count
        self.assertEqual(deployment.deploy(target,['a.yaml'],state,policy,executor,now=2000),'unchanged');self.assertEqual(executor.deploy.call_count,count)
        (target/'a.yaml').write_text('b');executor.deploy.side_effect=lambda *args:((target/'a.yaml').write_text('c') or {})
        executor.deploy.side_effect=lambda *args:( (target/'a.yaml').write_text('c'), {'status':'success'})[1]
        with self.assertRaises(ValueError):deployment.deploy(target,['a.yaml'],state,policy,executor,now=3000)

    def test_new_configuration_after_success_does_not_wait_for_failure_backoff(self):
        target=self.root/'rime';target.mkdir();(target/'a.yaml').write_text('a')
        state=self.root/'state';policy={'enabled':True,'retry_seconds':900,'idle_seconds':30,'commands':{}}
        executor=Mock();executor.deploy.return_value={'status':'success'}
        self.assertEqual(deployment.deploy(target,['a.yaml'],state,policy,executor,now=1000),'success')
        (target/'a.yaml').write_text('b')
        self.assertEqual(deployment.deploy(target,['a.yaml'],state,policy,executor,now=1001),'success')
        self.assertEqual(executor.deploy.call_count,2)

    def test_server_logging_config_replaces_inherited_root_handlers(self):
        import io
        import runpy
        import logging.config
        stream=io.StringIO()
        with patch('client.maintenance.logs.DailyLog',return_value=stream):
            config=runpy.run_path(str(ROOT/'server/gunicorn.conf.py'))['logconfig_dict']
        # Gunicorn shallow-merges defaults; root must not retain a removed handler.
        merged={'version':1,'root':{'handlers':['console'],'level':'INFO'},'handlers':{'console':{'class':'logging.StreamHandler'}}}
        merged.update(config)
        logging.config.dictConfig(merged)
        logging.getLogger('gunicorn.error').error('startup-probe')
        self.assertIn('startup-probe',stream.getvalue())

    def test_log_expiry_never_touches_unmanaged_or_symlink(self):
        policy={'enabled':True,'retention_days':1,'max_file_bytes':10}
        log=logs.DailyLog(self.root,policy);log.write('a'*20);first=log.path;log.write('new');self.assertNotEqual(first,log.path)
        os.utime(first,(1,1));keep=self.root/'baseline.json';keep.write_text('important');os.utime(keep,(1,1))
        link=self.root/'rime-20000101-000000000000.log'
        try:link.symlink_to(keep)
        except OSError:pass
        self.assertEqual(logs.clean(self.root,policy),1);self.assertTrue(keep.exists());self.assertTrue(log.path.exists())

    def test_workflow_v2_rejects_missing_stage_and_orders_deploy(self):
        auto={'linux_theme':True,'deployment':{'enabled':True},'logs':{'enabled':True}}
        plan=plans.workflow('linux',remote=True,configuration=True,dictionaries=True,store=False,third_party=True,automation=auto,theme_enabled=True)
        self.assertEqual(plan['version'],2)
        handlers={k:Mock(return_value={'status':'success','reason':'ok'}) for k in plans.STAGES_V2}
        handlers['remote-sync'].return_value={'status':'failed','reason':'offline'}
        result=plans.execute_workflow(plan,handlers)
        handlers['theme-apply'].assert_not_called();handlers['frontend-deploy'].assert_not_called();handlers['log-cleanup'].assert_called_once()
        plan['steps'].pop()
        with self.assertRaises(ValueError):plans.validate(plan)

class ExpansionClientTests(ServerFixture):
    def test_client_expands_before_native_and_repulls(self):
        self.settings.update(auto_expand_dictionaries=True,max_dictionaries=128)
        self.settings_path.write_text(json.dumps(self.settings));self.app=create_app(self.settings_path)
        source=self.root/'config';source.mkdir();(source/'a.custom.yaml').write_text('a')
        config={'enabled':True,'url':'https://example.test/rime/v1/state','interval_seconds':60,'retry_seconds':10,'timeout_seconds':5,'auto_expand_dictionaries':True}
        scope=copy.deepcopy(self.scope);scope['dictionaries']['names'].append('new_dictionary')
        routes=[]
        def transport(c,m,p=None):
            route='/rime/v1/'+c['url'].split('/rime/v1/')[1];routes.append((m,route))
            status,body=self.call(m,p,route=route)
            if status!=200:raise remote.RemoteError(str(status))
            return body
        remote.synchronize(config,scope,source,self.root/'rime/sync','a',self.root/'state',transport=transport,force=True)
        self.assertEqual(routes[:3],[('GET','/rime/v1/state'),('POST','/rime/v1/scope/dictionaries'),('GET','/rime/v1/state')])
        self.assertIn('new_dictionary',self.call()[1]['scope']['dictionaries']['names'])


if __name__=='__main__':unittest.main()
