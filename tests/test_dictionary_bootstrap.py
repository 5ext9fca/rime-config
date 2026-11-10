import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from client.maintenance.dictionary_bootstrap import ensure, publish_new
from client.application.dictionaries import validate_snapshot

MACOS_MANAGERS = [base/'Squirrel.app/Contents/MacOS/rime_dict_manager' for base in
                  (Path('/Library/Input Methods'), Path.home()/'Library/Input Methods')]
MACOS_MANAGER = next((path for path in MACOS_MANAGERS if path.is_file()), None)
NATIVE_MANAGER = (str(MACOS_MANAGER) if sys.platform == 'darwin' and MACOS_MANAGER
                  else shutil.which('rime_dict_manager') if sys.platform.startswith('linux') else None)


def snapshot(owner,name,word,count):
    return (f'# Rime user dictionary\n#@/db_type\tuserdb\n#@/db_name\t{name}\n#@/user_id\t{owner}\n#@/tick\t100\n'
            f'yan shou \t{word}\tc={count} d=2 t=100\n').encode()


class BootstrapTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt' and os.environ.get('RIME_TEST_DLL'), 'Requires installed Windows librime')
    def test_windows_native_first_import_and_retry(self):
        second = self.sync / 'second'
        second.mkdir()
        (second / 'remote_only.userdb.txt').write_bytes(snapshot('second', 'remote_only', '第二设备', 5))
        deployer = Path(os.environ['RIME_TEST_DLL']).with_name('WeaselDeployer.exe')
        self.assertEqual(ensure(self.target, self.sync, 'local', ['remote_only'], self.session,
                                'windows', deployer=deployer), ['remote_only'])
        database = self.target / 'remote_only.userdb'
        self.assertTrue(database.is_dir())
        before = {p.name: p.read_bytes() for p in database.iterdir() if p.is_file()}
        self.assertEqual(ensure(self.target, self.sync, 'local', ['remote_only'], self.session,
                                'windows', deployer=deployer), [])
        self.assertEqual(before, {p.name: p.read_bytes() for p in database.iterdir() if p.is_file()})

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.target=self.root/'user';self.target.mkdir();self.session=self.root/'session';self.session.mkdir()
        self.sync=self.target/'sync';self.peer=self.sync/'peer';self.peer.mkdir(parents=True)
        (self.target/'installation.yaml').write_text('installation_id: local\n')
        (self.peer/'remote_only.userdb.txt').write_bytes(snapshot('peer','remote_only','首次',3))

    def build(self,stage,name):
        (stage/(name+'.userdb')).mkdir();(stage/(name+'.userdb')/'data').write_text('native output')
        out=stage/'sync/local';out.mkdir(parents=True)
        (out/(name+'.userdb.txt')).write_bytes(snapshot('local',name,'首次',3))

    def run_bootstrap(self,builder=None,names=('remote_only',)):
        return ensure(self.target,self.sync,'local',names,self.session,'linux',builder=builder or self.build)

    def test_new_database_only_and_scope(self):
        (self.peer/'excluded.userdb.txt').write_bytes(snapshot('peer','excluded','未授权',3))
        self.assertEqual(self.run_bootstrap(),['remote_only'])
        self.assertFalse((self.target/'excluded.userdb').exists())
        self.assertEqual(self.run_bootstrap(lambda *_:self.fail('must not restore existing DB')),[])

    def test_native_failure_keeps_existing_and_does_not_publish(self):
        existing=self.target/'keep.userdb';existing.mkdir();(existing/'data').write_text('active')
        def failed(stage,name):self.build(stage,name);raise RuntimeError('native failure')
        with self.assertRaises(RuntimeError):self.run_bootstrap(failed)
        self.assertFalse((self.target/'remote_only.userdb').exists());self.assertEqual((existing/'data').read_text(),'active')
        self.assertEqual(json.loads((self.session/'bootstrap.json').read_text())['status'],'failed')
        self.assertFalse(list(self.target.glob('.rime-bootstrap-*')))

    def test_concurrent_creation_never_overwritten(self):
        def racing(stage,name):
            self.build(stage,name);(self.target/(name+'.userdb')).mkdir();(self.target/(name+'.userdb')/'data').write_text('other writer')
        with self.assertRaises(FileExistsError):self.run_bootstrap(racing)
        self.assertEqual((self.target/'remote_only.userdb/data').read_text(),'other writer')

    def test_atomic_publication_refuses_even_empty_destination(self):
        src=self.root/'source';src.mkdir();(src/'data').write_text('new')
        dest=self.root/'destination';dest.mkdir()
        with self.assertRaises(FileExistsError):publish_new(src,dest)
        self.assertTrue(src.exists());self.assertEqual(list(dest.iterdir()),[])
        dest.rmdir();publish_new(src,dest);self.assertEqual((dest/'data').read_text(),'new')

    def test_invalid_metadata_never_runs_builder(self):
        (self.peer/'remote_only.userdb.txt').write_bytes(snapshot('wrong-owner','remote_only','错误',3))
        with self.assertRaises(ValueError):self.run_bootstrap(lambda *_:self.fail('invalid input'))
        self.assertFalse((self.target/'remote_only.userdb').exists())

    @unittest.skipUnless(NATIVE_MANAGER, 'Requires installed Rime dictionary manager')
    def test_real_native_first_import_merge_and_idempotent_retry(self):
        platform = 'macos' if sys.platform == 'darwin' else 'linux'
        second=self.sync/'second';second.mkdir();(second/'remote_only.userdb.txt').write_bytes(snapshot('second','remote_only','第二设备',5))
        self.assertEqual(ensure(self.target,self.sync,'local',['remote_only'],self.session,platform),['remote_only'])
        def sync():
            subprocess.run([NATIVE_MANAGER,'--sync'],cwd=self.target,check=True,capture_output=True)
            path=self.sync/'local/remote_only.userdb.txt';data=path.read_bytes();validate_snapshot(data,'local','remote_only')
            return sorted(line for line in data.decode().splitlines() if line and not line.startswith('#'))
        original=sync();self.assertEqual(len(original),2)
        for _ in range(3):
            self.assertEqual(ensure(self.target,self.sync,'local',['remote_only'],self.session,platform),[])
            self.assertEqual(sync(),original)

    @unittest.skipUnless(sys.platform.startswith('linux') and __import__('ctypes.util',fromlist=['find_library']).find_library('rime'),'Requires librime')
    def test_levers_worker_uses_isolated_native_api(self):
        import ctypes.util
        import client.maintenance.dictionary_bootstrap as dictionary_bootstrap
        def build(stage,name):
            subprocess.run([sys.executable,str(Path(dictionary_bootstrap.__file__)), '--worker',ctypes.util.find_library('rime'),str(stage),name],check=True,capture_output=True)
        self.assertEqual(self.run_bootstrap(build),['remote_only'])
        self.assertTrue((self.target/'remote_only.userdb').is_dir())

if __name__=='__main__':unittest.main()
