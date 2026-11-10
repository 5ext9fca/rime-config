import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import client.core.configuration as sync


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source, self.target, self.state = (root / p for p in ('source', 'target', 'state'))
        self.source.mkdir()
        self.target.mkdir()
        (self.source / 'default.yaml').write_text('new')

    def apply(self, **kwargs):
        return sync.apply(self.source, self.target, self.state, **kwargs)

    def test_apply_backup_idempotence_and_drift(self):
        (self.target / 'default.yaml').write_text('old')
        (self.target / 'user.yaml').write_text('runtime')
        self.apply()
        backup = next(self.state.glob('backups/*/files/default.yaml'))
        self.assertEqual(backup.read_text(), 'old')
        self.assertEqual(self.apply(), [])
        (self.target / 'default.yaml').write_text('client edit')
        self.apply()
        self.assertEqual((self.target / 'default.yaml').read_text(), 'new')
        self.assertEqual((self.target / 'user.yaml').read_text(), 'runtime')
        self.assertEqual((self.source / 'default.yaml').read_text(), 'new')

    def test_prune_only_managed_files(self):
        (self.source / 'removed.yaml').write_text('remove')
        self.apply()
        (self.source / 'removed.yaml').unlink()
        (self.target / 'unmanaged.yaml').write_text('keep')
        self.apply()
        self.assertFalse((self.target / 'removed.yaml').exists())
        self.assertTrue((self.target / 'unmanaged.yaml').exists())

    def test_plan_no_writes(self):
        self.assertEqual(self.apply(dry_run=True), [('create', 'default.yaml')])
        self.assertFalse(self.state.exists())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_preflight_blocks_symlink_and_no_partial_write(self):
        (self.source / 'z.yaml').write_text('z')
        try:
            (self.target / 'z.yaml').symlink_to(self.source / 'z.yaml')
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windows 未授予符号链接创建权限")
            raise
        with self.assertRaises(ValueError):
            self.apply()
        self.assertFalse((self.target / 'default.yaml').exists())

    def test_source_symlink_and_runtime_rejected(self):
        bad = self.source / 'alias.yaml'
        try:
            bad.symlink_to(self.source / 'default.yaml')
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windows 未授予符号链接创建权限")
            raise
        with self.assertRaises(ValueError):
            self.apply()
        bad.unlink()
        (self.source / 'user.yaml').write_text('runtime')
        with self.assertRaises(ValueError):
            self.apply()

    def test_empty_source_and_overlap_rejected(self):
        with self.assertRaises(ValueError):
            sync.apply(self.source, self.source / 'nested', self.state)
        (self.source / 'default.yaml').unlink()
        with self.assertRaises(ValueError):
            self.apply()

    def test_failure_rolls_back_completed_operations(self):
        (self.target / 'default.yaml').write_text('old')
        (self.source / 'z.yaml').write_text('z')
        original = sync.atomic_write
        def fail(path, data):
            if path == self.target / 'z.yaml':
                raise OSError('simulated failure')
            original(path, data)
        with patch.object(sync, 'atomic_write', side_effect=fail):
            with self.assertRaises(OSError):
                self.apply()
        self.assertEqual((self.target / 'default.yaml').read_text(), 'old')
        self.assertFalse((self.state / 'manifest.json').exists())

    def test_manifest_cannot_delete_runtime_or_escape(self):
        self.state.mkdir()
        for name in ('../outside', 'user.yaml', 'x.userdb/data'):
            (self.state / 'manifest.json').write_text(json.dumps({
                'source': str(self.source), 'target': str(self.target), 'files': [name]}))
            with self.assertRaises(ValueError):
                self.apply()

    def test_scope_migration_preserves_third_party(self):
        (self.source / 'library.dict.yaml').write_text('third party')
        self.apply()
        scope = ['default.yaml']
        self.assertEqual(sync.apply(self.source, self.target, self.state, includes=scope), [])
        self.assertEqual((self.target / 'library.dict.yaml').read_text(), 'third party')
        self.assertEqual(json.loads((self.state / 'manifest.json').read_text())['files'], scope)
        (self.source / 'library.dict.yaml').write_text('new upstream')
        sync.apply(self.source, self.target, self.state, includes=scope)
        self.assertEqual((self.target / 'library.dict.yaml').read_text(), 'third party')

    def test_scoped_removal_only_when_still_declared(self):
        (self.source / 'personal.dict.yaml').write_text('personal')
        scope = ['default.yaml', 'personal.dict.yaml']
        sync.apply(self.source, self.target, self.state, includes=scope)
        (self.source / 'personal.dict.yaml').unlink()
        sync.apply(self.source, self.target, self.state, includes=scope)
        self.assertFalse((self.target / 'personal.dict.yaml').exists())



if __name__ == '__main__':
    unittest.main()
