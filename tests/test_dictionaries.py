from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import subprocess
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import client.application.dictionaries as d


def snapshot(device, word='测试'):
    return (f'# Rime user dictionary\n#@/db_type\tuserdb\n#@/db_name\tluna_pinyin\n'
            f'#@/user_id\t{device}\nce shi \t{word}\tc=3 d=2 t=10\n').encode()


class DictionaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.local, self.store, self.state = (root / n for n in ('sync', 'store', 'state'))
        self.write(self.local / 'a/luna_pinyin.userdb.txt', snapshot('a'))
        self.write(self.store / 'b/luna_pinyin.userdb.txt', snapshot('b', '别词'))

    def write(self, p, data):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def exchange(self, **kw):
        return d.exchange(self.local, self.store, 'a', self.state, **kw)

    def test_two_way_snapshots_and_no_third_party(self):
        self.write(self.local / 'a/thirdparty.dict.yaml', b'library')
        self.write(self.store / 'b/default.yaml', b'foreign config')
        self.assertEqual(self.exchange(), (1, 1))
        self.assertEqual((self.local / 'b/luna_pinyin.userdb.txt').read_bytes(), snapshot('b', '别词'))
        self.assertEqual((self.store / 'a/luna_pinyin.userdb.txt').read_bytes(), snapshot('a'))
        self.assertFalse((self.store / 'a/thirdparty.dict.yaml').exists())
        self.assertFalse((self.local / 'b/default.yaml').exists())
        self.assertEqual(self.exchange(), (0, 0))

    def test_no_deletion_propagation_and_backup(self):
        self.exchange()
        (self.store / 'b/luna_pinyin.userdb.txt').unlink()
        self.exchange()
        self.assertTrue((self.local / 'b/luna_pinyin.userdb.txt').exists())
        self.write(self.local / 'a/luna_pinyin.userdb.txt', snapshot('a', '新词'))
        self.exchange()
        backup = next(self.state.glob('backups/*/push/a/*.userdb.txt'))
        self.assertEqual(backup.read_bytes(), snapshot('a'))

    def test_dry_run_never_invokes_native_hook(self):
        with patch.object(d.subprocess, 'run') as run:
            self.assertEqual(self.exchange(dry_run=True, command='["native-sync"]'), (1, 1))
            run.assert_not_called()
        self.assertFalse(self.state.exists())
        self.assertFalse((self.local / 'b').exists())
        self.assertFalse((self.store / 'a').exists())

    def test_hook_merges_after_pull_before_publish(self):
        def native(*args, **kwargs):
            self.assertTrue((self.local / 'b/luna_pinyin.userdb.txt').exists())
            self.write(self.local / 'a/luna_pinyin.userdb.txt', snapshot('a', '合并'))
        with patch.object(d.subprocess, 'run', side_effect=native):
            self.exchange(command='["native-sync"]')
        self.assertEqual((self.store / 'a/luna_pinyin.userdb.txt').read_bytes(), snapshot('a', '合并'))

    def test_failed_hook_does_not_publish(self):
        with patch.object(d.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'native')):
            with self.assertRaises(subprocess.CalledProcessError):
                self.exchange(command='["native-sync"]')
        self.assertFalse((self.store / 'a').exists())

    def test_invalid_snapshot_or_device_rejected(self):
        with self.assertRaises(ValueError):
            d.exchange(self.local, self.store, '../escape', self.state)
        self.write(self.store / 'b/luna_pinyin.userdb.txt', snapshot('wrong-device'))
        with self.assertRaises(ValueError):
            self.exchange()
        self.assertFalse((self.store / 'a').exists())

    def test_symlink_refused(self):
        (self.store / 'b/luna_pinyin.userdb.txt').unlink()
        try:
            (self.store / 'b/luna_pinyin.userdb.txt').symlink_to(self.local / 'a/luna_pinyin.userdb.txt')
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windows 未授予符号链接创建权限")
            raise
        with self.assertRaises(ValueError):
            self.exchange()

    def test_explicit_names_ignore_unlisted_invalid_snapshots(self):
        self.write(self.store / 'b/other.userdb.txt', b'not even a valid snapshot')
        self.write(self.local / 'a/other.userdb.txt', b'private unselected data')
        self.assertEqual(self.exchange(names=['luna_pinyin']), (1, 1))
        self.assertFalse((self.local / 'b/other.userdb.txt').exists())
        self.assertFalse((self.store / 'a/other.userdb.txt').exists())

    def test_empty_scope_no_writes_or_hook(self):
        with patch.object(d.subprocess, 'run') as run:
            self.assertEqual(self.exchange(names=[], command='["native-sync"]'), (0, 0))
            run.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_native_hook_only_gets_selected_names(self):
        with patch.object(d.subprocess, 'run') as run:
            self.exchange(names=['luna_pinyin'], command='["native-sync", "--dictionary", "{dictionary}"]')
            run.assert_called_once_with(['native-sync', '--dictionary', 'luna_pinyin'], check=True, timeout=300)
        with self.assertRaises(ValueError):
            self.exchange(names=['luna_pinyin'], command='["sync-everything"]')

    def test_scope_shrink_retains_existing_snapshots(self):
        self.exchange(names=['luna_pinyin'])
        before = (self.local / 'b/luna_pinyin.userdb.txt').read_bytes()
        self.exchange(names=['rime_ice'])
        self.assertEqual((self.local / 'b/luna_pinyin.userdb.txt').read_bytes(), before)
