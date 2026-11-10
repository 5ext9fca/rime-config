"""Opt-in integration check against installed librime, exclusively in new test dirs.

python tests/windows_native_acceptance.py --dll PATH/TO/rime.dll --workspace private
No Weasel IPC, registry changes, live databases, or active input sessions are used.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'client'))
from dictionaries import exchange, validate_snapshot, checked
from sync import safe_path


class Traits(C.Structure):
    _fields_ = [('data_size', C.c_int)] + [(n, C.c_char_p) for n in (
        'shared_data_dir', 'user_data_dir', 'distribution_name',
        'distribution_code_name', 'distribution_version', 'app_name')] + [
        ('modules', C.POINTER(C.c_char_p)), ('min_log_level', C.c_int),
        ('log_dir', C.c_char_p), ('prebuilt_data_dir', C.c_char_p),
        ('staging_dir', C.c_char_p)]


class Module(C.Structure):
    _fields_ = [('data_size', C.c_int), ('name', C.c_char_p),
                ('initialize', C.c_void_p), ('finalize', C.c_void_p),
                ('get_api', C.c_void_p)]


# Stable levers API prefix from librime's public rime_levers_api.h.
LEVER_NAMES = '''custom_settings_init custom_settings_destroy load_settings
save_settings customize_bool customize_int customize_double customize_string
is_first_run settings_is_modified settings_get_config switcher_settings_init
get_available_schema_list get_selected_schema_list schema_list_destroy get_schema_id
get_schema_name get_schema_version get_schema_author get_schema_description
get_schema_file_path select_schemas get_hotkeys set_hotkeys user_dict_iterator_init
user_dict_iterator_destroy next_user_dict backup_user_dict restore_user_dict
export_user_dict import_user_dict'''.split()


class Levers(C.Structure):
    _fields_ = [('data_size', C.c_int)] + [(n, C.c_void_p) for n in LEVER_NAMES]


def function(lib, name, result, *args):
    fn = getattr(lib, name)
    fn.restype, fn.argtypes = result, list(args)
    return fn


def worker(dll, user, dictionary):
    user = user.resolve()
    safe_path(user)
    if not (user / '.acceptance-only').is_file():
        raise ValueError('Refusing to use any directory without the isolated-test marker')
    if dictionary not in ('luna_pinyin', 'rime_ice'):
        raise ValueError('Unexpected test dictionary')
    shared, logs = user / 'shared', user / 'logs'
    shared.mkdir(exist_ok=True)
    logs.mkdir(exist_ok=True)
    lib = C.CDLL(str(dll.resolve()))
    traits = Traits()
    traits.data_size = C.sizeof(Traits) - C.sizeof(C.c_int)
    traits.shared_data_dir = str(shared).encode('utf-8')
    traits.user_data_dir = str(user).encode('utf-8')
    traits.app_name = b'rime.acceptance'
    traits.log_dir = str(logs).encode('utf-8')
    function(lib, 'RimeSetup', None, C.POINTER(Traits))(C.byref(traits))
    function(lib, 'RimeDeployerInitialize', None, C.c_void_p)(None)
    try:
        assert function(lib, 'RimeRunTask', C.c_int, C.c_char_p)(b'installation_update')
        module = function(lib, 'RimeFindModule', C.POINTER(Module), C.c_char_p)(b'levers')
        assert module and module.contents.get_api
        api = C.CFUNCTYPE(C.POINTER(Levers))(module.contents.get_api)().contents
        assert api.data_size + 4 >= Levers.restore_user_dict.offset + C.sizeof(C.c_void_p)
        restore = C.CFUNCTYPE(C.c_int, C.c_char_p)(api.restore_user_dict)
        backup = C.CFUNCTYPE(C.c_int, C.c_char_p)(api.backup_user_dict)
        for snapshot in sorted((user / 'sync').glob('*/' + dictionary + '.userdb.txt')):
            checked(snapshot)
            validate_snapshot(snapshot.read_bytes(), snapshot.parent.name, dictionary)
            assert restore(str(snapshot).encode('utf-8')), 'Native restore failed'
        assert backup(dictionary.encode()), 'Native backup failed'
    finally:
        function(lib, 'RimeFinalize', None)()


def snapshot(device, name, word, count):
    return (f'# Rime user dictionary\n#@/db_type\tuserdb\n#@/db_name\t{name}\n'
            f'#@/user_id\t{device}\n#@/tick\t100\n'
            f'yan shou \t{word}\tc={count} d=2 t=100\n').encode('utf-8')


def rows(path):
    return sorted(line for line in path.read_text(encoding='utf-8-sig').splitlines()
                  if line and not line.startswith('#'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dll', type=Path, required=True)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--user-dir', type=Path)
    parser.add_argument('--dictionary')
    args = parser.parse_args()
    if args.worker:
        worker(args.dll, args.user_dir, args.dictionary)
        return
    if not args.workspace:
        parser.error('--workspace is required')
    args.workspace.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='native-acceptance-', dir=args.workspace)).resolve()
    user, store = root / 'user', root / 'store'
    user.mkdir()
    (user / '.acceptance-only').touch()
    (user / 'installation.yaml').write_text('installation_id: acceptance-local\n', encoding='utf-8')
    peer = store / 'acceptance-peer'
    peer.mkdir(parents=True)
    for name in ('luna_pinyin', 'rime_ice'):
        (peer / (name + '.userdb.txt')).write_bytes(snapshot('acceptance-peer', name, '隔离验收', 3))
    hook = json.dumps([sys.executable, str(Path(__file__).resolve()), '--worker',
                       '--dll', str(args.dll.resolve()), '--user-dir', str(user),
                       '--dictionary', '{dictionary}'])
    def run(names):
        return exchange(user / 'sync', store, 'acceptance-local', root / 'state',
                        command=hook, names=names)
    assert run(['luna_pinyin']) == (1, 1)
    assert not (user / 'rime_ice.userdb').exists(), 'Hook ignored dictionary scope'
    assert run(['rime_ice']) == (1, 1)
    output = user / 'sync/acceptance-local'
    baseline = {n: rows(output / (n + '.userdb.txt')) for n in ('luna_pinyin', 'rime_ice')}
    for _ in range(3):
        run(['luna_pinyin', 'rime_ice'])
        assert all(rows(output / (n + '.userdb.txt')) == before for n, before in baseline.items()), 'Repeated native merge changed frequency'
    second = store / 'acceptance-peer-two'
    second.mkdir()
    (second / 'rime_ice.userdb.txt').write_bytes(snapshot('acceptance-peer-two', 'rime_ice', '另一设备', 5))
    run(['rime_ice'])
    merged = rows(output / 'rime_ice.userdb.txt')
    assert len(merged) == 2
    for _ in range(3):
        run(['rime_ice'])
        assert rows(output / 'rime_ice.userdb.txt') == merged
    result = {'native_merge': 'passed', 'dictionary_scope': 'passed',
              'repeat_merge_frequency': 'passed', 'second_device_merge': 'passed',
              'root': str(root), 'active_userdb_touched': False}
    (root / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
