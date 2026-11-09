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
import identity
import remote
import sync


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'rime'
        self.target.mkdir()
        (self.target / 'installation.yaml').write_bytes(b'installation_id: "test-device"\r\n')
        self.path = self.root / 'device.local.json'
        self.token = 'test-token-' + 'x' * 40

    def init(self):
        output = io.StringIO()
        with patch.object(sys, 'stdin', io.StringIO(self.token + '\n')), contextlib.redirect_stdout(output):
            result = identity.initialize(self.path, self.target, token_stdin=True)
        self.assertNotIn(self.token, output.getvalue())
        return result

    def test_auto_detect_save_permissions_and_reinit(self):
        value = self.init()
        self.assertEqual(value['installation_id'], 'test-device')
        self.assertEqual(identity.load_identity(self.path), value)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        with patch.object(sys, 'stdin', io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            identity.initialize(self.path, self.target)
        self.assertEqual(identity.load_identity(self.path), value)

    def test_wrong_id_and_invalid_token_do_not_overwrite(self):
        value = self.init()
        with self.assertRaises(ValueError):
            identity.initialize(self.path, self.target, 'wrong-device')
        with patch.object(sys, 'stdin', io.StringIO('short\n')):
            with self.assertRaises(ValueError):
                identity.initialize(self.path, self.target, token_stdin=True)
        self.assertEqual(identity.load_identity(self.path), value)

    def test_scalar_formats_and_duplicate_id(self):
        for scalar in ('test-device', "'test-device'", '"test-device" # comment'):
            (self.target / 'installation.yaml').write_text(f'installation_id: {scalar}\n')
            self.assertEqual(identity.installation_id(self.target), 'test-device')
        (self.target / 'installation.yaml').write_text('installation_id: first\ninstallation_id: second\n')
        with self.assertRaises(ValueError):
            identity.installation_id(self.target)

    def test_symlink_refused(self):
        self.path.symlink_to(self.root / 'other.json')
        with self.assertRaises(ValueError):
            identity.load_identity(self.path)

    def test_cli_init_is_offline_and_exits_before_sync(self):
        argv = ['sync.py', '--init', '--token-stdin', '--device-config', str(self.path), '--target', str(self.target)]
        with patch.object(sys, 'argv', argv), patch.object(sys, 'stdin', io.StringIO(self.token + '\n')), \
             patch.object(remote, 'synchronize') as synchronize, patch.object(sync, 'apply') as apply, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sync.main(), 0)
            synchronize.assert_not_called()
            apply.assert_not_called()
        self.assertEqual(identity.load_identity(self.path)['token'], self.token)

    def test_cli_uses_saved_identity_token_and_target(self):
        self.init()
        cfg = {'enabled': True, 'url': 'https://example.test/rime/v1/state',
               'interval_seconds': 60, 'retry_seconds': 30, 'timeout_seconds': 30}
        remote_path = self.root / 'remote.json'
        remote_path.write_text(json.dumps(cfg))
        argv = ['sync.py', '--device-config', str(self.path), '--remote-config', str(remote_path),
                '--state-dir', str(self.root / 'state'), '--dry-run']
        with patch.object(sys, 'argv', argv), patch.object(remote, 'synchronize', return_value='planned') as synchronize, \
             patch.object(sync, 'apply') as apply, patch('third_party.refresh'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sync.main(), 0)
            args = synchronize.call_args.args
            self.assertEqual(args[0]['token'], self.token)
            self.assertEqual(args[4], 'test-device')
            self.assertEqual(args[3], self.target / 'sync')
            self.assertEqual(apply.call_args.args[1], self.target)

    def test_file_token_takes_precedence_over_legacy_environment(self):
        response = io.BytesIO(b'{}')
        response.status = 200
        config = {'url': 'https://example.test/rime/v1/state', 'token': self.token,
                  'token_env': 'TEST_RIME_TOKEN', 'timeout_seconds': 10}
        with patch.dict(os.environ, {'TEST_RIME_TOKEN': 'old-token-' + 'y' * 40}), \
             patch.object(remote.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = response
            remote.request(config, 'GET')
            sent = opener.return_value.open.call_args.args[0]
            self.assertEqual(sent.get_header('Authorization'), 'Bearer ' + self.token)
