import base64
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'client'))
from server.app import create_app
import remote
from sync import apply


def encoded(text):
    return base64.b64encode(text.encode()).decode()


def snapshot(device):
    return f'# Rime user dictionary\n#@/db_type\tuserdb\n#@/db_name\trime_ice\n#@/user_id\t{device}\nce shi \t测试\tc=1 d=1 t=1\n'.encode()


class ServerFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scope = {'version': 1, 'configuration': {'enabled': True, 'files': ['a.custom.yaml', 'b.custom.yaml']},
                      'dictionaries': {'enabled': True, 'names': ['rime_ice']}}
        (self.root / 'scope.json').write_text(json.dumps(self.scope))
        self.settings = {'database': 'state.sqlite3', 'scope': 'scope.json', 'max_request_bytes': 1024 * 1024,
                         'max_state_bytes': 2 * 1024 * 1024,
                         'devices': [{'user': 'hx', 'device': 'a', 'token': 'a' * 40},
                                     {'user': 'hx', 'device': 'b', 'token': 'b' * 40},
                                     {'user': 'other', 'device': 'c', 'token': 'c' * 40}]}
        self.settings_path = self.root / 'settings.json'
        self.settings_path.write_text(json.dumps(self.settings))
        self.app = create_app(self.settings_path)

    def call(self, method='GET', body=None, device='a', route='/rime/v1/state', headers=None):
        raw = json.dumps(body).encode() if body is not None else b''
        env = {'REQUEST_METHOD': method, 'PATH_INFO': route, 'HTTP_AUTHORIZATION': 'Bearer ' + device * 40,
               'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(raw)), 'wsgi.input': io.BytesIO(raw)}
        env.update(headers or {})
        status = []
        response = b''.join(self.app(env, lambda s, h: status.append((int(s.split()[0]), dict(h)))))
        self.assertEqual(status[0][1]['Cache-Control'], 'private, no-store')
        return status[0][0], json.loads(response)

    def upload(self, revision=0, config=None, dictionaries=None, device='a'):
        return self.call('PATCH', {'base_revision': revision, 'configuration': config or {}, 'dictionaries': dictionaries or {}}, device)

    def transport(self, device):
        def send(config, method, payload=None):
            status, body = self.call(method, payload, device)
            if status == 409:
                raise remote.RevisionChanged('revision conflict')
            if status != 200:
                raise remote.RemoteError(f'HTTP {status}')
            return body
        return send


class ServerTests(ServerFixture):
    def test_auth_health_isolation_persistence_and_idempotence(self):
        self.assertEqual(self.call(headers={'HTTP_AUTHORIZATION': 'Bearer invalid'})[0], 401)
        self.assertEqual(self.call(route='/healthz')[0], 200)
        self.assertEqual(self.upload(config={'a.custom.yaml': encoded('initial')})[1]['revision'], 1)
        self.assertEqual(self.upload(1, {'a.custom.yaml': encoded('initial')})[1]['revision'], 1)
        self.assertEqual(self.call(device='b')[1]['configuration']['a.custom.yaml'], encoded('initial'))
        self.assertEqual(self.call(device='c')[1]['configuration'], {})
        self.app = create_app(self.settings_path)
        self.assertEqual(self.call()[1]['revision'], 1)

    def test_stale_version_does_not_overwrite(self):
        self.upload(config={'a.custom.yaml': encoded('first')})
        self.assertEqual(self.upload(config={'a.custom.yaml': encoded('stale')})[0], 409)
        self.assertEqual(self.call()[1]['configuration']['a.custom.yaml'], encoded('first'))

    def test_scope_and_snapshot_ownership(self):
        for name in ('../outside', 'cn_dicts/base.dict.yaml', 'user.yaml'):
            self.assertEqual(self.upload(config={name: encoded('bad')})[0], 403)
        self.assertEqual(self.upload(dictionaries={'rime_ice': remote.encode(snapshot('b'))})[0], 400)
        self.assertEqual(self.upload(dictionaries={'rime_ice': remote.encode(snapshot('a'))})[0], 200)
        self.assertIn('a', self.call()[1]['dictionaries'])
        self.scope['dictionaries']['enabled'] = False
        (self.root / 'scope.json').write_text(json.dumps(self.scope))
        self.assertEqual(self.call()[1]['dictionaries']['a'], {})
        self.assertEqual(self.upload(1, dictionaries={'rime_ice': remote.encode(snapshot('a'))})[0], 403)

    def test_protocol_errors_and_limits(self):
        self.assertEqual(self.call('DELETE')[0], 405)
        self.assertEqual(self.call(route='/elsewhere')[0], 404)
        self.assertEqual(self.call('PATCH', {}, headers={'CONTENT_TYPE': 'text/plain'})[0], 415)
        self.assertEqual(self.call('PATCH', {}, headers={'CONTENT_LENGTH': ''})[0], 411)
        self.assertEqual(self.call('PATCH', {}, headers={'CONTENT_LENGTH': '999999999'})[0], 413)
        self.assertEqual(self.upload(config={'a.custom.yaml': 'not base64'})[0], 400)
        self.settings['max_state_bytes'] = 10
        self.settings_path.write_text(json.dumps(self.settings))
        self.app = create_app(self.settings_path)
        self.assertEqual(self.upload(config={'a.custom.yaml': encoded('too large')})[0], 413)
        self.assertEqual(self.call()[1]['revision'], 0)


class RemoteTests(ServerFixture):
    def setUp(self):
        super().setUp()
        self.config = {'enabled': True, 'url': 'https://example.test/rime/v1/state', 'token_env': 'RIME_SYNC_TOKEN',
                       'interval_seconds': 60, 'retry_seconds': 10, 'timeout_seconds': 5}
        for device in ('a', 'b'):
            source = self.root / device / 'config'
            source.mkdir(parents=True)
            (source / 'a.custom.yaml').write_text('initial-a')
            (source / 'b.custom.yaml').write_text('initial-b')

    def run_sync(self, device='a', **kw):
        root = self.root / device
        return remote.synchronize(self.config, self.scope, root / 'config', root / 'rime/sync', device,
                                  root / 'state', transport=kw.pop('transport', self.transport(device)), force=True, **kw)

    def test_two_clients_merge_apply_and_tombstone(self):
        self.run_sync('a')
        self.run_sync('b')
        (self.root / 'a/config/a.custom.yaml').write_text('edit-a')
        self.run_sync('a')
        (self.root / 'b/config/b.custom.yaml').write_text('edit-b')
        self.run_sync('b')
        self.run_sync('a')
        for device in ('a', 'b'):
            self.assertEqual((self.root / device / 'config/a.custom.yaml').read_text(), 'edit-a')
            self.assertEqual((self.root / device / 'config/b.custom.yaml').read_text(), 'edit-b')
        apply(self.root / 'b/config', self.root / 'b/rime', self.root / 'b/apply', includes=self.scope['configuration']['files'])
        (self.root / 'a/config/a.custom.yaml').unlink()
        self.run_sync('a')
        self.run_sync('b')
        self.assertFalse((self.root / 'b/config/a.custom.yaml').exists())
        apply(self.root / 'b/config', self.root / 'b/rime', self.root / 'b/apply', includes=self.scope['configuration']['files'])
        self.assertFalse((self.root / 'b/rime/a.custom.yaml').exists())
        self.assertIsNone(self.call()[1]['configuration']['a.custom.yaml'])

    def test_conflict_blocks_upload_and_explicit_local_resolution(self):
        self.run_sync('a')
        self.run_sync('b')
        (self.root / 'a/config/a.custom.yaml').write_text('A')
        (self.root / 'b/config/a.custom.yaml').write_text('B')
        self.run_sync('a')
        with self.assertRaises(remote.RemoteError):
            self.run_sync('b')
        self.assertEqual((self.root / 'b/config/a.custom.yaml').read_text(), 'B')
        self.assertTrue((self.root / 'b/state/conflicts.json').exists())
        self.assertEqual(self.call()[1]['configuration']['a.custom.yaml'], encoded('A'))
        self.run_sync('b', resolve='local')
        self.assertEqual(self.call()[1]['configuration']['a.custom.yaml'], encoded('B'))

    def test_snapshot_upload_download_and_exclusion(self):
        for device in ('a', 'b'):
            folder = self.root / device / 'rime/sync' / device
            folder.mkdir(parents=True)
            (folder / 'rime_ice.userdb.txt').write_bytes(snapshot(device))
            (folder / 'unselected.userdb.txt').write_text('invalid private ignored')
        self.run_sync('a')
        self.run_sync('b')
        self.run_sync('a')
        self.assertEqual((self.root / 'b/rime/sync/a/rime_ice.userdb.txt').read_bytes(), snapshot('a'))
        self.assertEqual((self.root / 'a/rime/sync/b/rime_ice.userdb.txt').read_bytes(), snapshot('b'))
        self.assertEqual(set(self.call()[1]['dictionaries']['a']), {'rime_ice'})

    def test_offline_and_lost_upload_response_can_retry(self):
        def offline(*args):
            raise remote.RemoteError('offline')
        with self.assertRaises(remote.RemoteError):
            self.run_sync(transport=offline)
        self.assertFalse((self.root / 'a/state/baseline.json').exists())
        send = self.transport('a')
        def lose_reply(config, method, payload=None):
            result = send(config, method, payload)
            if method == 'PATCH':
                raise remote.RemoteError('lost response')
            return result
        with self.assertRaises(remote.RemoteError):
            self.run_sync(transport=lose_reply)
        self.assertEqual(self.call()[1]['revision'], 1)
        self.run_sync()
        self.assertEqual(self.call()[1]['revision'], 1)

    def test_scope_disabled_dry_run_and_first_sync_conflict(self):
        with patch.object(remote, 'request') as request:
            self.run_sync(dry_run=True, transport=request)
            request.assert_not_called()
        self.assertFalse((self.root / 'a/state').exists())
        self.run_sync('a')
        (self.root / 'b/config/a.custom.yaml').write_text('different initial content')
        with self.assertRaises(remote.RemoteError):
            self.run_sync('b')
        self.scope['configuration']['enabled'] = False
        self.scope['dictionaries']['enabled'] = False
        self.assertEqual(self.run_sync('b'), 'disabled')

    def test_wrong_device_and_stale_cas_keep_baseline(self):
        with self.assertRaises(remote.RemoteError):
            self.run_sync('a', transport=self.transport('b'))
        send = self.transport('a')
        def race(config, method, payload=None):
            if method == 'PATCH':
                self.upload(payload['base_revision'], {'b.custom.yaml': encoded('racer')}, device='b')
            return send(config, method, payload)
        with self.assertRaises(remote.RevisionChanged):
            self.run_sync('a', transport=race)
        self.assertFalse((self.root / 'a/state/baseline.json').exists())
        self.assertEqual((self.root / 'a/config/b.custom.yaml').read_text(), 'initial-b')

    def test_lost_response_then_new_local_edits_recover_from_pending(self):
        folder = self.root / 'a/rime/sync/a'
        folder.mkdir(parents=True)
        (folder / 'rime_ice.userdb.txt').write_bytes(snapshot('a'))
        send = self.transport('a')
        def lose_reply(config, method, payload=None):
            result = send(config, method, payload)
            if method == 'PATCH':
                raise remote.RemoteError('lost response')
            return result
        with self.assertRaises(remote.RemoteError):
            self.run_sync(transport=lose_reply)
        (self.root / 'a/config/a.custom.yaml').write_text('new local edit')
        new_snapshot = snapshot('a').replace(b'c=1', b'c=2')
        (folder / 'rime_ice.userdb.txt').write_bytes(new_snapshot)
        self.run_sync()
        latest = self.call()[1]
        self.assertEqual(latest['configuration']['a.custom.yaml'], encoded('new local edit'))
        self.assertEqual(latest['dictionaries']['a']['rime_ice'], remote.encode(new_snapshot))
        self.assertFalse((self.root / 'a/state/pending.json').exists())

    def test_remote_changes_backup_local_and_all_file_deletion_applies(self):
        self.run_sync('a')
        self.run_sync('b')
        (self.root / 'a/config/a.custom.yaml').write_text('remote edit')
        self.run_sync('a')
        self.run_sync('b')
        backups = list((self.root / 'b/state/backups').glob('*/a.custom.yaml'))
        self.assertEqual(backups[0].read_text(), 'initial-a')
        apply(self.root / 'b/config', self.root / 'b/rime', self.root / 'b/apply', includes=self.scope['configuration']['files'])
        for name in self.scope['configuration']['files']:
            (self.root / 'a/config' / name).unlink()
        self.run_sync('a')
        self.run_sync('b')
        apply(self.root / 'b/config', self.root / 'b/rime', self.root / 'b/apply', includes=self.scope['configuration']['files'], allow_empty=True)
        for name in self.scope['configuration']['files']:
            self.assertFalse((self.root / 'b/rime' / name).exists())

    def test_dry_run_and_transport_enforce_https_and_refuse_redirect(self):
        self.assertIsNone(remote.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test'))
        path = self.root / 'remote.json'
        for url in ('http://example.test/rime/v1/state', 'https://token@example.test/rime/v1/state', 'https://example.test/rime/v1/state?token=x'):
            config = dict(self.config, url=url)
            path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                remote.load_remote(path)
