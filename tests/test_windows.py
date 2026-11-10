import argparse
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import client.storage.file_lock as file_lock
import client.config.paths as paths
import client.services.service as service
import client.core.configuration as sync
import client.cli as cli
import client.application.runtime as runtime
import client.platforms.windows.windows_service as windows_service


class PortableWindowsTests(unittest.TestCase):
    @unittest.skipUnless((Path(__file__).resolve().parents[1]/'config/default.custom.yaml').exists(),
                         'Personal configuration excluded from server image')
    def test_runner_imports_new_entry_from_unrelated_working_directory(self):
        # The runner's import and argv forwarding do not require pythonw or
        # Task Scheduler, so exercise them on every host instead of skipping.
        project=Path(__file__).resolve().parents[1]
        runner=project/'client/platforms/windows/windows_runner.py'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            target=root/'Rime';target.mkdir()
            remote=root/'remote.json'
            remote.write_text(json.dumps({'enabled':False,'url':'https://example.test/rime/v1/state',
                'interval_seconds':60,'retry_seconds':30,'timeout_seconds':5}))
            command=[sys.executable,str(runner),str(project/'rime.py'),'--dry-run',
                '--target',str(target),'--device-config',str(root/'device.local.json'),
                '--paths-state',str(root/'paths.local.json'),'--state-dir',str(root/'state'),
                '--remote-config',str(remote)]
            result=subprocess.run(command,cwd=root,env={**os.environ,'LOCALAPPDATA':str(root)},
                capture_output=True,text=True,timeout=30)
            log=(root/'rime-config/logs/service.log').read_text(encoding='utf-8')
            self.assertEqual(result.returncode,0,log+result.stderr)
            self.assertIn('配置源:',log)
            self.assertFalse((root/'state').exists())
            self.assertFalse((root/'paths.local.json').exists())
            self.assertEqual(list(target.iterdir()),[])


    def test_windows_discovery_and_legacy_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'Rime'
            target.mkdir()
            (target / 'installation.yaml').write_text('installation_id: test')
            config = root / 'paths.json'
            config.write_text(json.dumps({'version': 1, 'required_files': ['installation.yaml'],
                                         'candidates': dict(wsl=[], macos=[], linux=[])}))
            with patch.dict(os.environ, {'APPDATA': tmp}):
                self.assertEqual(paths.platform_key('Windows', 'test'), 'windows')
                migrated=paths.load_paths(config)
                self.assertNotIn('wsl',migrated['candidates'])
                self.assertEqual(paths.discover(migrated, 'windows'), target)

    def test_portable_scope_and_windows_aliases(self):
        self.assertEqual(sync.relative_name('lua/中文.lua').as_posix(), 'lua/中文.lua')
        for name in ('C:secret', 'a:stream', 'CON', 'aux.txt', 'folder./a',
                     'a ', 'x\\y', '//server/share', '../outside'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                sync.relative_name(name)

    def test_process_lock_contention_and_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'lock'
            code = ('import sys; sys.path.insert(0, sys.argv[1]); '
                    'from client.storage.file_lock import lock_exclusive; '
                    'f=open(sys.argv[2], "a"); lock_exclusive(f)')
            argv = [sys.executable, '-c', code, str(Path(__file__).resolve().parents[1]), str(path)]
            with path.open('a') as stream:
                file_lock.lock_exclusive(stream)
                self.assertNotEqual(subprocess.run(argv, capture_output=True).returncode, 0)
            self.assertEqual(subprocess.run(argv, capture_output=True).returncode, 0)

    def test_service_preview_precheck_and_payload(self):
        args = argparse.Namespace(interval=5, third_party_only=False, dry_run=True,
                                  device_config=Path('device.local.json'))
        script = Path(__file__).resolve().parents[1]/'rime.py'
        with patch.object(Path, 'is_file', return_value=True), \
                patch.object(service, 'run') as precheck, \
                patch.object(windows_service.subprocess, 'run') as manager, \
                contextlib.redirect_stdout(io.StringIO()):
            windows_service.manage_windows('install', args, script, script.parent / 'Rime')
            precheck.assert_not_called()
            manager.assert_not_called()
            args.dry_run = False
            precheck.return_value = subprocess.CompletedProcess([], 1, '', 'bad scope')
            with self.assertRaisesRegex(ValueError, '预检查失败'):
                windows_service.manage_windows('install', args, script, script.parent / 'Rime')
            manager.assert_not_called()
            precheck.return_value = subprocess.CompletedProcess([], 0, '', '')
            manager.return_value = subprocess.CompletedProcess([], 0, 'installed', '')
            windows_service.manage_windows('install', args, script, script.parent / 'Rime')
            cmd = manager.call_args.args[0]
            decoded = base64.b64decode(cmd[-1]).decode('utf-16-le')
            payload = json.loads(base64.b64decode(decoded.split("FromBase64String('")[1].split("'")[0]))
            self.assertIn('windows_runner.py', payload['arguments'])
            self.assertIn('--watch', payload['arguments'])
            self.assertNotIn('--token-stdin', payload['arguments'])
            self.assertEqual(payload['directory'], str(script.parent))


@unittest.skipUnless(os.name == 'nt', '需要 Windows PowerShell')
class NativeWindowsTests(unittest.TestCase):
    def test_real_directory_junction_is_rejected(self):
        # Junctions need no symbolic-link privilege, unlike the POSIX-style cases.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / 'outside'
            destination.mkdir()
            sentinel = destination / 'sentinel.txt'
            sentinel.write_text('unchanged')
            junction = root / 'junction'
            result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J',
                                     str(junction), str(destination)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            try:
                with self.assertRaises(ValueError):
                    sync.safe_path(junction, 'sentinel.txt')
                from client.application.dictionaries import checked
                with self.assertRaises(ValueError):
                    checked(junction / 'sentinel.txt')
                self.assertEqual(sentinel.read_text(), 'unchanged')
            finally:
                # Remove only the junction itself; never recurse into its target.
                os.rmdir(junction)

    def test_pythonw_runner_and_cli_preview_are_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / '中文 Rime'
            target.mkdir()
            (target / 'installation.yaml').write_text('installation_id: test')
            script = Path(__file__).resolve().parents[1]/'rime.py'
            remote = root / 'remote.json'
            remote.write_text(json.dumps({'enabled': False, 'url': 'https://example.test/rime/v1/state',
                                          'interval_seconds': 60, 'retry_seconds': 30, 'timeout_seconds': 5}))
            argv = [str(script), '--target', str(target), '--device-config',
                    str(root / 'device.local.json'), '--paths-state', str(root / 'paths.local.json'),
                    '--state-dir', str(root / 'state'), '--remote-config', str(remote), '--dry-run']
            before = sorted(str(p.relative_to(root)) for p in root.rglob('*'))
            result = subprocess.run([sys.executable, *argv, '--service', 'install'],
                                    capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('pythonw.exe', result.stdout)
            self.assertEqual(before, sorted(str(p.relative_to(root)) for p in root.rglob('*')))
            pythonw = Path(sys.executable).with_name('pythonw.exe')
            runner = script.parent/'client/platforms/windows/windows_runner.py'
            result = subprocess.run([str(pythonw), str(runner), *argv],
                                    env={**os.environ, 'LOCALAPPDATA': tmp}, timeout=30)
            self.assertEqual(result.returncode, 0)
            log = (root / 'rime-config/logs/service.log').read_text(encoding='utf-8')
            self.assertIn('配置源:', log)
            self.assertIn('中文 Rime', log)
            self.assertFalse((root / 'paths.local.json').exists())
            self.assertFalse((root / 'state').exists())
            self.assertEqual([p.name for p in target.iterdir()], ['installation.yaml'])

    def run_manager(self, operation, previous=False, failure=False, owned=True):
        # Execute the real registration script with simulated OS cmdlets. Never
        # register an actual task or start the user's sync client in these tests.
        prelude = r'''
$script:previous = PREVIOUS
$script:failure = FAILURE
function Get-ScheduledTask {
    if ($script:previous) { [pscustomobject]@{TaskName="rime-config-$sid"; State='Running'; Description='DESCRIPTION'} }
}
function Export-ScheduledTask { '<Task>old</Task>' }
function New-ScheduledTaskAction { Write-Host 'ACTION'; 'action' }
function New-ScheduledTaskTrigger { 'trigger' }
function New-ScheduledTaskPrincipal { 'principal' }
function New-ScheduledTaskSettingsSet { 'settings' }
function New-ScheduledTask { 'definition' }
function Stop-ScheduledTask { Write-Host 'STOP' }
function Register-ScheduledTask {
    param($TaskName, $TaskPath, $InputObject, $Xml, [switch]$Force)
    if ($Xml) { Write-Host 'RESTORE' } else { Write-Host 'REGISTER' }
    $script:previous = $true
}
function Start-ScheduledTask {
    Write-Host 'START'
    if ($script:failure) { $script:failure=$false; throw 'injected start failure' }
}
function Unregister-ScheduledTask { Write-Host 'DELETE'; $script:previous=$false }
function Get-ScheduledTaskInfo { [pscustomobject]@{LastTaskResult=0} }
'''.replace('PREVIOUS', '$true' if previous else '$false').replace(
            'FAILURE', '$true' if failure else '$false').replace(
            'DESCRIPTION', 'Managed by rime-config service installer v1' if owned else 'handwritten')
        cmd = windows_service.powershell_command(dict(operation=operation, executable='pythonw.exe',
                                                     arguments='runner.py', directory='C:\\test'))
        script = base64.b64decode(cmd[-1]).decode('utf-16-le')
        script = script.replace('# Payload is JSON', prelude + '\n# Payload is JSON', 1)
        cmd[-1] = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        return subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=30)

    def test_scheduler_install_update_uninstall_and_status(self):
        for operation, previous, expected in [('install', False, 'REGISTER'),
                                               ('install', True, 'STOP'),
                                               ('uninstall', True, 'DELETE'),
                                               ('uninstall', False, 'Not installed'),
                                               ('status', False, 'Not installed')]:
            with self.subTest(operation=operation, previous=previous):
                result = self.run_manager(operation, previous)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout)

    def test_scheduler_failure_restores_or_removes_and_refuses_unowned(self):
        for previous, expected in [(True, 'RESTORE'), (False, 'DELETE')]:
            result = self.run_manager('install', previous, failure=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(expected, result.stdout)
            self.assertIn('previous task restored', result.stderr)
        for operation in ('install', 'uninstall'):
            result = self.run_manager(operation, True, owned=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('STOP', result.stdout)
            self.assertNotIn('REGISTER', result.stdout)

    def test_utf8_atomic_file_has_protected_acl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '中文.json'
            sync.atomic_write(path, '中文'.encode('utf-8'))
            self.assertEqual(path.read_text(encoding='utf-8'), '中文')
            command = "$ErrorActionPreference='Stop'; $a=[IO.File]::GetAccessControl($env:RIME_TEST_FILE); $a.AreAccessRulesProtected; $a.Access | ForEach-Object { $_.IsInherited }"
            result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command],
                                    env={**os.environ, 'RIME_TEST_FILE': str(path)},
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ['True', 'False', 'False', 'False'])


if __name__ == '__main__':
    unittest.main()
