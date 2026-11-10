"""macOS 原生快照恢复验收，仅操作新建的隔离目录。

--manager 指定鼠须管 rime_dict_manager 可执行文件，--workspace 指定临时目录。
不操作活动输入法数据库。
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'client'))
from dictionaries import exchange, validate_snapshot, checked
from sync import safe_path


def worker(manager, user, dictionary):
    user = user.resolve()
    safe_path(user)
    if not (user / '.acceptance-only').is_file():
        raise ValueError('Isolated directory marker required')
    if dictionary not in ('luna_pinyin', 'rime_ice'):
        raise ValueError('Unexpected dictionary')
    def call(*args):
        subprocess.run([str(manager), *args], cwd=user, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
    for path in sorted((user / 'sync').glob('*/' + dictionary + '.userdb.txt')):
        validate_snapshot(path.read_bytes(), path.parent.name, dictionary)
        call('--restore', str(path))
    call('--backup', dictionary)


def snapshot(device, name, word, count):
    return (f'# Rime user dictionary\n#@/db_type\tuserdb\n#@/db_name\t{name}\n'
            f'#@/user_id\t{device}\n#@/tick\t100\n'
            f'yan shou \t{word}\tc={count} d=2 t=100\n').encode('utf-8')


def rows(path):
    return sorted(line for line in path.read_text(encoding='utf-8-sig').splitlines()
                  if line and not line.startswith('#'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manager', type=Path, required=True)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--user-dir', type=Path)
    parser.add_argument('--dictionary')
    args = parser.parse_args()
    if args.worker:
        worker(args.manager, args.user_dir, args.dictionary)
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
                       '--manager', str(args.manager.resolve()), '--user-dir', str(user),
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
