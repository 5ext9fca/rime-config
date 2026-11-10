import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import client.providers.third_party as t


def blob(data):
    return {'type': 'blob', 'mode': '100644', 'size': len(data),
            'sha': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target, self.state = self.root / 'target', self.root / 'state'
        self.target.mkdir()
        self.config_path = self.root / 'third-party.json'
        self.config = {'enabled': True, 'interval_seconds': 1000, 'retry_seconds': 30,
                       'timeout_seconds': 10, 'max_download_bytes': 10000,
                       'source': {'repository': 'iDvel/rime-ice', 'ref': 'main',
                                  'files': ['cn_dicts/test.dict.yaml', 'en_dicts/cn_en.txt']}}
        self.files = {'cn_dicts/test.dict.yaml': b'---\nname: test\n...\nword\tcode\n',
                      'en_dicts/cn_en.txt': b'word\tcode\n'}
        self.commit = 'a' * 40
        self.calls = []
        self.fetch = patch.object(t, 'get_bytes', side_effect=self.download)
        self.fetch.start()
        self.addCleanup(self.fetch.stop)

    def download(self, url, timeout, limit):
        self.calls.append(url)
        if '/commits/' in url:
            return json.dumps({'sha': self.commit, 'commit': {'tree': {'sha': 'b' * 40}}}).encode()
        if '/git/trees/' in url:
            return json.dumps({'tree': [dict(path=name, **blob(data)) for name, data in self.files.items()]}).encode()
        prefix = f'https://raw.githubusercontent.com/iDvel/rime-ice/{self.commit}/'
        self.assertTrue(url.startswith(prefix), 'Downloads must use immutable commit, not branch')
        return self.files[url.removeprefix(prefix)]

    def run_refresh(self, **kwargs):
        return t.refresh(self.config, self.target, self.state, now=kwargs.pop('now', 100), **kwargs)

    def test_download_backup_receipt_schedule_and_idempotence(self):
        dest = self.target / 'cn_dicts/test.dict.yaml'
        dest.parent.mkdir()
        dest.write_text('old')
        personal = self.target / 'custom_phrase.txt'
        personal.write_text('personal')
        self.assertEqual(self.run_refresh(), 'updated')
        self.assertEqual(dest.read_bytes(), self.files['cn_dicts/test.dict.yaml'])
        self.assertEqual(personal.read_text(), 'personal')
        self.assertEqual(next(self.state.glob('backups/*/files/cn_dicts/test.dict.yaml')).read_text(), 'old')
        self.assertEqual(json.loads((self.state / 'receipt.json').read_text())['commit'], self.commit)
        count = len(self.calls)
        self.assertEqual(self.run_refresh(now=101), 'not-due')
        self.assertEqual(len(self.calls), count)
        self.assertEqual(self.run_refresh(now=1101), 'unchanged')
        self.assertEqual(len(list((self.state / 'backups').iterdir())), 1)

    def test_dry_run_disabled_and_force(self):
        self.assertEqual(self.run_refresh(dry_run=True), 'planned')
        self.assertFalse(self.state.exists())
        self.assertEqual(self.calls, [])
        self.config['enabled'] = False
        self.assertEqual(self.run_refresh(force=True), 'disabled')
        self.assertEqual(self.calls, [])
        self.config['enabled'] = True
        self.run_refresh()
        self.assertEqual(self.run_refresh(force=True), 'unchanged')

    def test_download_failure_preserves_all_files_and_delays_retry(self):
        dest = self.target / 'cn_dicts/test.dict.yaml'
        dest.parent.mkdir()
        dest.write_text('old')
        original = self.download
        def fail(url, timeout, limit):
            if url.endswith('/en_dicts/cn_en.txt'):
                raise OSError('network failure')
            return original(url, timeout, limit)
        with patch.object(t, 'get_bytes', side_effect=fail):
            with self.assertRaises(t.RefreshError):
                self.run_refresh()
        self.assertEqual(dest.read_text(), 'old')
        self.assertFalse((self.state / 'receipt.json').exists())
        self.assertEqual(self.run_refresh(now=101), 'not-due')
        self.assertEqual(self.run_refresh(now=131), 'updated')

    def test_bad_hash_never_applies(self):
        original = self.download
        def corrupt(url, timeout, limit):
            data = original(url, timeout, limit)
            return b'corrupt' if 'raw.githubusercontent.com' in url else data
        with patch.object(t, 'get_bytes', side_effect=corrupt):
            with self.assertRaises(t.RefreshError):
                self.run_refresh()
        self.assertEqual(list(self.target.iterdir()), [])

    def test_write_failure_rolls_back(self):
        dest = self.target / 'cn_dicts/test.dict.yaml'
        dest.parent.mkdir()
        dest.write_text('old')
        original = t.atomic_write
        def fail(path, data):
            if path == self.target / 'en_dicts/cn_en.txt':
                raise OSError('write failure')
            original(path, data)
        with patch.object(t, 'atomic_write', side_effect=fail):
            with self.assertRaises(t.RefreshError):
                self.run_refresh()
        self.assertEqual(dest.read_text(), 'old')
        self.assertFalse((self.state / 'receipt.json').exists())

    def test_symlink_rejected_before_network(self):
        try:
            (self.target / 'cn_dicts').symlink_to(self.root)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windows 未授予符号链接创建权限")
            raise
        with self.assertRaises(ValueError):
            self.run_refresh()
        self.assertEqual(self.calls, [])

    def test_missing_upstream_and_size_limit(self):
        self.config['source']['files'].append('missing.dict.yaml')
        with self.assertRaises(t.RefreshError):
            self.run_refresh()
        self.config['source']['files'].pop()
        self.config['max_download_bytes'] = 1
        with self.assertRaises(t.RefreshError):
            self.run_refresh()
        self.assertEqual(list(self.target.iterdir()), [])

    def test_config_validation_protects_personal_and_runtime(self):
        for name in ('../escape.txt', 'custom_phrase.txt', 'x.userdb.txt', 'x.schema.yaml', 'lua/x.lua', 'user.yaml'):
            self.config['source']['files'] = [name]
            self.config_path.write_text(json.dumps(self.config))
            with self.assertRaises(ValueError):
                t.load_config(self.config_path, [])
        self.config['source']['files'] = ['personal.dict.yaml']
        self.config_path.write_text(json.dumps(self.config))
        with self.assertRaises(ValueError):
            t.load_config(self.config_path, ['personal.dict.yaml'])

    def test_changed_configuration_refreshes_immediately_without_pruning(self):
        self.run_refresh()
        self.config['source']['files'] = ['en_dicts/cn_en.txt']
        self.assertEqual(self.run_refresh(now=101), 'unchanged')
        self.assertTrue((self.target / 'cn_dicts/test.dict.yaml').exists())

    def test_project_config_is_valid_and_excludes_entrypoints(self):
        root = Path(__file__).resolve().parents[1]
        scope = json.loads((root / 'sync-manifest.json').read_text())['configuration']['files']
        config = t.load_config(root / 'third-party.json', scope)
        self.assertEqual(config['source']['repository'], 'iDvel/rime-ice')
        self.assertNotIn('rime_ice.dict.yaml', config['source']['files'])
        self.assertNotIn('melt_eng.dict.yaml', config['source']['files'])


if __name__ == '__main__':
    unittest.main()
