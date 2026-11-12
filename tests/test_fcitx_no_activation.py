"""Desktop ownership must survive background sync during logout/login."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from client.platforms.linux import fcitx_maintenance


class NoActivationTests(unittest.TestCase):
    def test_maintenance_addresses_existing_unique_owner(self):
        with patch.object(fcitx_maintenance.subprocess, 'run', side_effect=[
            SimpleNamespace(stdout="(':1.123',)\n"), SimpleNamespace(stdout='ok')
        ]) as run:
            self.assertEqual(fcitx_maintenance.call('State'), 'ok')
        argv = run.call_args.args[0]
        self.assertEqual(argv[argv.index('--dest') + 1], ':1.123')

    def test_owner_disappearance_does_not_fallback_to_activation(self):
        with patch.object(fcitx_maintenance.subprocess, 'run', side_effect=[
            SimpleNamespace(stdout="(':1.123',)\n"), subprocess.CalledProcessError(1, 'gdbus')
        ]) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                fcitx_maintenance.call('State')
        self.assertEqual(run.call_count, 2)

    @unittest.skipUnless(shutil.which('dbus-run-session') and shutil.which('gdbus'), 'Requires D-Bus tools')
    def test_absent_frontend_is_never_activated_on_isolated_bus(self):
        try:
            import gi
        except ImportError:
            self.skipTest('Requires PyGObject')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            services = root / 'dbus-1/services'
            services.mkdir(parents=True)
            marker = root / 'activated'
            (services / 'org.fcitx.Fcitx5.service').write_text(
                '[D-BUS Service]\nName=org.fcitx.Fcitx5\nExec=/usr/bin/touch ' + str(marker) + '\n')
            code = '''
from gi.repository import GLib
from client.platforms.linux.frontend_preferences import FcitxConfig
from client.platforms.linux.fcitx_maintenance import call
from client.platforms.platform_execution import UnixExecutor
import subprocess
client = FcitxConfig()
for operation in (lambda: client.get('fcitx://config/global'),
                  lambda: client.set('fcitx://config/global', {}),
                  lambda: call('State'),
                  lambda: UnixExecutor('linux').reload_theme()):
    try:
        operation()
    except (GLib.Error, subprocess.CalledProcessError):
        pass
    else:
        raise AssertionError('Absent frontend unexpectedly accepted request')
'''
            result = subprocess.run(['dbus-run-session', '--', sys.executable, '-c', code],
                env=dict(os.environ, XDG_DATA_HOME=temp, XDG_DATA_DIRS=temp),
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists(), result.stderr)


if __name__ == '__main__':
    unittest.main()
