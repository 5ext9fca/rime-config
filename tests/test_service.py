import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'client'))
import service
import sync


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root / 'project space/client/sync.py'
        self.args = argparse.Namespace(interval=7, dry_run=False, third_party_only=False,
                                       device_id=None, native_sync_command=None)
        for name in service.PATH_OPTIONS:
            setattr(self.args, name, None)
        self.args.device_config = self.root / 'device.local.json'
        self.calls = []
        self.failure = None
        self.system = 'Linux'
        self.active = False
        self.enabled = False
        patch.object(service.os, 'getuid', return_value=1000, create=True).start()
        self.addCleanup(patch.stopall)
        patch.object(Path, 'home', return_value=self.root).start()
        patch.object(service.platform, 'system', side_effect=lambda: self.system).start()
        patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.root / 'xdg')}).start()
        patch.object(service, 'run', side_effect=self.fake_run).start()
        patch('sys.stdout', new=io.StringIO()).start()

    def fake_run(self, argv, check=True):
        self.calls.append(argv)
        if self.failure and self.failure in argv:
            self.failure = None
            raise ValueError('injected manager failure')
        rc = 0
        if 'is-active' in argv:
            rc = 0 if self.active else 3
        elif 'is-enabled' in argv:
            rc = 0 if self.enabled else 1
        elif argv[0] == 'launchctl' and 'print' in argv and argv[-1].endswith('/' + service.LABEL):
            rc = 0 if self.active else 113
        elif 'bootout' in argv or 'disable' in argv:
            self.active = False
        elif 'bootstrap' in argv or 'restart' in argv or 'start' in argv:
            self.active = True
        return subprocess.CompletedProcess(argv, rc, '', '')

    @property
    def unit(self):
        return self.root / 'xdg/systemd/user' / service.UNIT

    def manage(self, action='install'):
        return service.manage(action, self.args, self.script, self.root / 'Rime')

    def test_linux_install_update_and_uninstall(self):
        self.assertEqual(self.manage(), 0)
        text = self.unit.read_text()
        self.assertIn('--watch', text)
        self.assertIn('project space', text)
        self.assertIn(f'WorkingDirectory={self.script.parent.parent}/.\n', text)
        if __import__("os").name != "nt":
            self.assertEqual(self.unit.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.active)
        self.args.interval = 12
        self.manage()
        self.assertIn('"12"', self.unit.read_text())
        self.manage('uninstall')
        self.assertFalse(self.unit.exists())
        self.assertFalse(self.active)
        self.calls.clear()
        self.manage('uninstall')
        self.assertEqual(self.calls, [])

    def test_macos_plist_and_lifecycle(self):
        self.system = 'Darwin'
        self.manage()
        path = self.root / 'Library/LaunchAgents/local.rime-config.plist'
        doc = plistlib.loads(path.read_bytes())
        self.assertEqual(doc['ProgramArguments'][2], str(self.script))
        self.assertEqual(doc['Umask'], 0o077)
        self.assertTrue(self.active)
        self.assertTrue((self.root / 'Library/Logs/rime-config').is_dir())
        self.manage()
        self.assertTrue(any('bootout' in c for c in self.calls))
        self.manage('uninstall')
        self.assertFalse(path.exists())
        self.assertFalse(self.active)

    def test_dry_run_does_not_write_or_call_manager(self):
        for system in ('Linux', 'Darwin'):
            self.system = system
            self.args.dry_run = True
            self.manage()
            self.manage('uninstall')
        self.assertEqual(self.calls, [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unmanaged_file_and_symlink_are_not_replaced(self):
        self.unit.parent.mkdir(parents=True)
        self.unit.write_text('user supplied service')
        for action in ('install', 'uninstall'):
            with self.assertRaisesRegex(ValueError, '非本安装器'):
                self.manage(action)
        self.assertEqual(self.unit.read_text(), 'user supplied service')
        self.unit.unlink()
        try:
            self.unit.symlink_to(self.root / 'missing')
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windows 未授予符号链接创建权限")
            raise
        with self.assertRaisesRegex(ValueError, '符号链接'):
            self.manage()
        self.assertEqual(self.calls, [])

    def test_manager_unavailable_leaves_no_files(self):
        self.failure = 'show-environment'
        with self.assertRaisesRegex(ValueError, 'WSL'):
            self.manage()
        self.assertFalse(self.unit.exists())

    def test_failed_new_install_removes_definition(self):
        self.failure = 'restart'
        with self.assertRaisesRegex(ValueError, '已恢复'):
            self.manage()
        self.assertFalse(self.unit.exists())
        self.assertFalse(self.active)

    def test_failed_update_restores_definition_and_running_service(self):
        self.manage()
        original = self.unit.read_bytes()
        self.enabled = True
        self.args.interval = 100
        self.failure = 'restart'
        with self.assertRaisesRegex(ValueError, '已恢复'):
            self.manage()
        self.assertEqual(self.unit.read_bytes(), original)
        self.assertTrue(self.active)
        self.assertIn(['systemctl', '--user', 'enable', service.UNIT], self.calls)

    def test_failed_macos_update_restores_previous_agent(self):
        self.system = 'Darwin'
        self.manage()
        path = self.root / 'Library/LaunchAgents/local.rime-config.plist'
        original = path.read_bytes()
        self.args.interval = 100
        self.failure = 'bootstrap'
        with self.assertRaisesRegex(ValueError, '已恢复'):
            self.manage()
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue(self.active)

    def test_precheck_failure_does_not_register(self):
        with patch.object(service, 'run', side_effect=[
                subprocess.CompletedProcess([], 0, '', ''),
                subprocess.CompletedProcess([], 1, '', 'bad scope')]):
            with self.assertRaisesRegex(ValueError, '预检查失败'):
                self.manage()
        self.assertFalse(self.unit.exists())

    def test_argv_preserves_options_and_never_persists_one_shot_actions(self):
        self.args.paths_state = Path('relative state.json')
        self.args.native_sync_command = json.dumps([str(self.root / 'a b/wrapper'), '--dictionary', '{dictionary}'])
        self.args.resolve_conflicts = 'remote'
        self.args.sync_now = True
        argv = service.command(self.args, self.script, self.root / 'Rime')
        self.assertIn(os.path.abspath('relative state.json'), argv)
        self.assertIn(self.args.native_sync_command, argv)
        self.assertNotIn('--sync-now', argv)
        self.assertNotIn('--resolve-conflicts', argv)
        self.assertNotIn('--token-stdin', argv)
        self.args.native_sync_command = '["relative-wrapper"]'
        with self.assertRaisesRegex(ValueError, '绝对路径'):
            service.command(self.args, self.script, self.root)

    def test_systemd_escaping_and_launchd_argument_roundtrip(self):
        value = 'space "quote" \\ $HOME %h 中文'
        escaped = service.quote_unit(value, True)
        self.assertIn('$$HOME', escaped)
        self.assertIn('%%h', escaped)
        self.assertIn('\\"quote\\"', escaped)
        with self.assertRaises(ValueError):
            service.quote_unit('line\ninjection')
        doc = plistlib.loads(service.render('Darwin', [value], self.root, self.root))
        self.assertEqual(doc['ProgramArguments'], [value])

    def test_status_and_uninstall_bypass_target_and_identity(self):
        for action in ('status', 'uninstall'):
            with patch.object(sys, 'argv', ['sync.py', '--service', action]), \
                    patch('identity.load_identity', side_effect=AssertionError('must not load')), \
                    patch.object(service, 'manage', return_value=0) as manage:
                self.assertEqual(sync.main(), 0)
                self.assertEqual(manage.call_args.args[0], action)

    def test_cli_rejects_one_shot_action_with_service(self):
        with patch.object(sys, 'argv', ['sync.py', '--service', 'install', '--resolve-conflicts', 'remote']), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            sync.main()


if __name__ == '__main__':
    unittest.main()
