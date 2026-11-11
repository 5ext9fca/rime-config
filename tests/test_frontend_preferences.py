import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from client.platforms.linux.frontend_preferences import desired, apply

@unittest.skipUnless(Path('config.example/fcitx5/input.json').exists(),'Personal source excluded from server image')
class PreferencesTests(unittest.TestCase):
    def test_preserves_other_shortcuts_and_idempotence(self):
        config=json.loads(Path('config.example/fcitx5/input.json').read_text())
        original={'Hotkey':{'TriggerKeys':{'0':'Control+space','1':'Hangul'},'AltTriggerKeys':{'0':'Shift_L'},'Other':'keep'},'Behavior':{'Other':'keep'}}
        g,r=desired(config,original,{'Other':'keep'})
        self.assertEqual(g['Hotkey']['TriggerKeys'],{'0':'Hangul','1':'Control+Alt+space'})
        self.assertEqual(g['Hotkey']['AltTriggerKeys'],'')
        self.assertEqual(r['SwitchInputMethodBehavior'],'Commit raw input')
        self.assertEqual(g['Behavior']['Other'],'keep')
        self.assertEqual(desired(config,g,r),(g,r))
        self.assertEqual(original['Hotkey']['TriggerKeys']['0'],'Control+space')
    def test_failed_readback_restores_settings(self):
        class Client:
            def __init__(self):self.values={'fcitx://config/global':{},'fcitx://config/addon/rime':{}};self.fail=True
            def get(self,uri):return copy.deepcopy(self.values[uri])
            def set(self,uri,value):
                self.values[uri]=copy.deepcopy(value)
                if self.fail:self.values[uri]['unexpected']='value';self.fail=False
        client=Client()
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):apply('config.example',temp,client=client)
        self.assertEqual(client.values,{'fcitx://config/global':{},'fcitx://config/addon/rime':{}})

    def test_preview_never_connects_to_desktop_or_writes_state(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'state'
            with patch('client.platforms.linux.frontend_preferences.FcitxConfig',side_effect=AssertionError('desktop access')):
                self.assertEqual(apply('config.example',state,dry_run=True),'planned')
            self.assertFalse(state.exists())

    def test_managed_workflow_is_linux_only_and_deployment_depends_on_it(self):
        from client.core.plans import workflow
        from client.config.automation import load
        auto=load(Path('automation.json'))
        for platform in ('linux','windows','macos'):
            plan=workflow(platform,remote=False,configuration=True,dictionaries=False,store=False,
                third_party=False,automation=auto,frontend_preferences=True)
            stages={item['id']:item for item in plan['steps']}
            self.assertEqual(plan['version'],4)
            self.assertEqual(stages['frontend-preferences']['action'],'evaluate' if platform=='linux' else 'skip')
            self.assertIn('frontend-preferences',stages['frontend-deploy']['requires'])

    def test_real_native_patch_survives_repeated_deployment(self):
        import ctypes.util,subprocess
        if not Path('/usr/share/rime-data/fcitx5.yaml').exists() or not ctypes.util.find_library('rime'):
            self.skipTest('Requires Fcitx5 shared config and librime')
        with tempfile.TemporaryDirectory() as temp:
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('fcitx_preferences_acceptance.py')),
                '--workspace',temp],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(json.loads(result.stdout)['patch_preserved'])
