import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'client'))
import scope
import sync


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'scope.json'
        self.data = {'version': 1, 'configuration': {'enabled': True, 'files': ['default.custom.yaml']},
                     'dictionaries': {'enabled': True, 'names': ['rime_ice']}}
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.data))

    def test_valid_scope_and_empty_scope(self):
        self.assertEqual(scope.load_scope(self.path), self.data)
        self.data['configuration']['files'] = []
        self.data['dictionaries']['names'] = []
        self.save()
        self.assertEqual(scope.load_scope(self.path), self.data)

    def test_invalid_names_paths_versions_and_duplicate_cases(self):
        for names in (['../escape'], ['*'], ['rime_ice.userdb'], ['ice', 'ICE']):
            self.data['dictionaries']['names'] = names
            self.save()
            with self.assertRaises(ValueError):
                scope.load_scope(self.path)
        self.data['dictionaries']['names'] = ['ice']
        for files in (['../escape'], ['*.yaml'], ['USER.YAML'], ['a', 'A']):
            self.data['configuration']['files'] = files
            self.save()
            with self.assertRaises(ValueError):
                scope.load_scope(self.path)
        self.data['configuration']['files'] = []
        self.data['version'] = 2
        self.save()
        with self.assertRaises(ValueError):
            scope.load_scope(self.path)

    def test_cli_passes_scope_and_reload_disables_both(self):
        third = self.root / 'third.json'
        cfg = json.loads((Path(__file__).resolve().parents[1] / 'third-party.json').read_text())
        cfg['enabled'] = False
        third.write_text(json.dumps(cfg))
        (self.root / 'rime').mkdir()
        argv = ['sync.py', '--paths-state', str(self.root / 'paths.local.json'), '--sync-config', str(self.path), '--third-party-config', str(third),
                '--target', str(self.root / 'rime'), '--state-dir', str(self.root / 'state'),
                '--dictionary-store', str(self.root / 'store'), '--device-id', 'device', '--watch']
        rounds = []
        def sleep(_):
            rounds.append(1)
            if len(rounds) == 1:
                self.data['configuration']['enabled'] = False
                self.data['dictionaries']['enabled'] = False
                self.save()
            else:
                raise KeyboardInterrupt
        with patch.object(sys, 'argv', argv), patch.object(sync, 'apply') as apply, \
             patch('dictionaries.exchange') as exchange, patch.object(sync.time, 'sleep', side_effect=sleep), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sync.main(), 0)
            apply.assert_called_once()
            self.assertEqual(apply.call_args.kwargs['includes'], ['default.custom.yaml'])
            exchange.assert_called_once()
            self.assertEqual(exchange.call_args.kwargs['names'], ['rime_ice'])
