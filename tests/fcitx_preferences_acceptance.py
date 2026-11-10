"""Isolated native deployment of the Fcitx5 application-options patch."""
import argparse
import ctypes as C
import ctypes.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from windows_native_acceptance import Traits
from client.platforms.rime_api import function


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,default=Path(__file__).resolve().parents[1]/'private/refactor-acceptance')
    args=parser.parse_args()
    root=Path(tempfile.mkdtemp(prefix='fcitx-patch-',dir=args.workspace))
    source=Path(__file__).resolve().parents[1]/'config/fcitx5.custom.yaml'
    patch=root/source.name;shutil.copy2(source,patch);before=patch.read_bytes()
    lib=C.CDLL(ctypes.util.find_library('rime'))
    traits=Traits();traits.data_size=C.sizeof(Traits)-4
    traits.shared_data_dir=b'/usr/share/rime-data';traits.user_data_dir=str(root).encode()
    traits.app_name=b'rime.fcitx_patch_acceptance';traits.log_dir=str(root).encode()
    function(lib,'RimeSetup',None,C.POINTER(Traits))(C.byref(traits))
    function(lib,'RimeDeployerInitialize',None,C.POINTER(Traits))(C.byref(traits))
    deploy=function(lib,'RimeDeployConfigFile',C.c_int,C.c_char_p,C.c_char_p)
    for _ in range(2):
        assert deploy(b'fcitx5.yaml',b'config_version')
        assert patch.read_bytes()==before
        assert not (root/'fcitx5.yaml').exists()
    compiled=(root/'build/fcitx5.yaml').read_text()
    assert 'konsole:' in compiled and 'ascii_mode: true' in compiled and 'Code:' in compiled
    function(lib,'RimeFinalize',None)()
    result={'repeated_native_deploy':'passed','patch_preserved':True,'application_options_compiled':True,'active_userdb_touched':False}
    (root/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':main()
