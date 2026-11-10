import contextlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'client'))
import paths
import sync


class PathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'Rime'
        self.target.mkdir()
        (self.target / 'installation.yaml').write_text('installation_id: device\n')
        self.config = {'version': 1, 'required_files': ['installation.yaml'],
                       'candidates': {name: [str(self.target)] for name in ['wsl', 'macos', 'linux']}}
        self.memory = self.root / 'paths.local.json'

    def resolve(self, **kw):
        return paths.resolve_target(self.config, self.memory, system='linux', **kw)

    def test_discover_remember_and_reuse_without_search(self):
        target, origin = self.resolve()
        self.assertEqual((target, origin), (self.target, 'discovered'))
        self.assertFalse(self.memory.exists())
        paths.remember_target(self.memory, target, 'linux')
        if __import__("os").name != "nt":
            self.assertEqual(stat.S_IMODE(self.memory.stat().st_mode), 0o600)
        with patch.object(paths, 'discover', side_effect=AssertionError('must not search')):
            self.assertEqual(self.resolve(), (self.target, 'remembered'))

    def test_explicit_override_identity_fallback_and_rediscover(self):
        other = self.root / 'other'
        other.mkdir()
        paths.remember_target(self.memory, other, 'linux')
        self.assertEqual(self.resolve(identity_target=self.target)[0], other)
        self.assertEqual(self.resolve(explicit=self.target)[0], self.target)
        self.assertEqual(self.resolve(rediscover=True)[0], self.target)
        self.memory.unlink()
        self.assertEqual(self.resolve(identity_target=other), (other, 'identity'))

    def test_stale_memory_fails_without_creating_or_fallback(self):
        missing = self.root / 'missing'
        paths.remember_target(self.memory, missing, 'linux')
        with self.assertRaises(ValueError):
            self.resolve()
        self.assertFalse(missing.exists())
        self.assertEqual(self.resolve(rediscover=True)[0], self.target)

    def test_ambiguity_markers_and_deduplication(self):
        self.config['candidates']['linux'] *= 2
        self.assertEqual(self.resolve()[0], self.target)
        other = self.root / 'other'
        other.mkdir()
        self.config['candidates']['linux'].append(str(other))
        self.assertEqual(self.resolve()[0], self.target)
        (other / 'installation.yaml').write_text('installation_id: other\n')
        with self.assertRaises(ValueError):
            self.resolve()

    def test_platforms_and_wsl_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(paths.platform_key('Linux','generic'), 'linux')
            self.assertEqual(paths.platform_key('Linux','microsoft'), 'wsl')
            self.assertEqual(paths.platform_key('Darwin','test'), 'macos')
        self.config['candidates']['wsl'].insert(0, '{windows_appdata}/Rime')
        with patch.object(paths, 'windows_appdata', return_value=None):
            self.assertEqual(paths.discover(self.config, 'wsl'), self.target)
        with patch.object(paths, 'windows_appdata', return_value=str(self.root)):
            self.assertEqual(paths.discover(self.config, 'wsl'), self.target)

    def test_templates_and_validation(self):
        self.config['candidates']['macos'] = ['{home}/Rime']
        with patch.object(Path, 'home', return_value=self.root):
            self.assertEqual(paths.discover(self.config, 'macos'), self.target)
        path = self.root / 'paths.json'
        for template in ('{invalid}/Rime', '{home.__class__}/Rime', '{home!r}/Rime'):
            self.config['candidates']['linux'] = [template]
            path.write_text(json.dumps(self.config))
            with self.assertRaises(ValueError):
                paths.load_paths(path)

    def test_symlink_refused(self):
        alias = self.root / 'alias'
        try:
            alias.symlink_to(self.target)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windows 未授予符号链接创建权限")
            raise
        with self.assertRaises(ValueError):
            self.resolve(explicit=alias)

    def test_discovery_cli_is_offline_and_preview_does_not_write(self):
        config = self.root / 'paths.json'
        config.write_text(json.dumps(self.config))
        argv = ['sync.py', '--discover-target', '--paths-config', str(config), '--paths-state', str(self.memory),
                '--device-config', str(self.root / 'device.local.json')]
        with patch.object(sys, 'argv', argv + ['--dry-run']), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sync.main(), 0)
        self.assertFalse(self.memory.exists())
        with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sync.main(), 0)
        self.assertTrue(self.memory.exists())
