"""Exchange Rime-owned text snapshots, never live userdb files or third-party data."""
import contextlib
from file_lock import lock_exclusive
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

from sync import atomic_write, is_link, windows_reserved


def component(value):
    if (not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*', value) or '..' in value
            or value.endswith('.') or windows_reserved(value)):
        raise ValueError(f'无效的设备或词典名称: {value}')
    return value


def checked(path, directory=False):
    for parent in (path, *path.parents):
        if is_link(parent):
            raise ValueError(f'个人词典路径不能包含符号链接: {parent}')
    for parent in path.parents:
        if parent.exists() and not parent.is_dir():
            raise ValueError(f'目录被阻挡: {parent}')
    if path.exists() and (not path.is_dir() if directory else not path.is_file()):
        raise ValueError(f'个人词典路径类型冲突: {path}')
    return path


def validate_snapshot(data, device, name):
    component(device)
    component(name)
    path = f"{device}/{name}.userdb.txt"
    # Require snapshot metadata: plain exported phrase lists are not snapshots.
    header = data.decode('utf-8-sig').splitlines()
    if '#@/db_type\tuserdb' not in header:
        raise ValueError(f'不是 Rime userdb 快照: {path}')
    metadata = dict(line[2:].split('\t', 1) for line in header if line.startswith('#@/') and '\t' in line)
    # Match librime UserDbHelper::GetDbName (strip the LAST .userdb suffix).
    # A first-split would accept a snapshot that native restore opens under a
    # different dictionary name, bypassing the declared scope.
    db_name = metadata.get('/db_name', '').rsplit('.userdb', 1)[0]
    if metadata.get('/db_type') != 'userdb':
        raise ValueError(f'不是 Rime userdb 快照: {path}')
    if db_name != name:
        raise ValueError(f'快照词典名称与文件名不一致: {path}')
    if metadata.get('/user_id') != device:
        raise ValueError(f'快照设备标识与目录不一致: {path}')


def snapshots(root, devices, names=None):
    result = {}
    checked(root, directory=True)
    for device in devices:
        component(device)
        folder = checked(root / device, directory=True)
        if not folder.exists():
            continue
        paths = sorted(folder.glob('*.userdb.txt')) if names is None else [folder / (name + '.userdb.txt') for name in names]
        for path in paths:
            if not path.exists() and not path.is_symlink():
                continue
            checked(path)
            component(path.name.removesuffix('.userdb.txt'))
            before = path.stat()
            data = path.read_bytes()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise ValueError(f'词典快照正在变化，请等待 Rime 同步完成: {path}')
            validate_snapshot(data, device, path.name.removesuffix('.userdb.txt'))
            result[f'{device}/{path.name}'] = data
    return result


def exchange(sync_dir, store, device, state, dry_run=False, command=None, names=None, native=None):
    """Pull other devices, let Rime merge/export, then publish only this device."""
    component(device)
    if names is not None:
        for name in names:
            component(name)
        if not names:
            return 0, 0
    sync_dir, store, state = [Path(os.path.abspath(p.expanduser())) for p in map(Path, (sync_dir, store, state))]
    for root in (sync_dir, store, state):
        checked(root, directory=True)
    roots = (sync_dir, store, state)
    for i, a in enumerate(roots):
        for b in roots[i + 1:]:
            if a == b or a in b.parents or b in a.parents:
                raise ValueError('词典同步目录、交换目录和状态目录不能重叠')
    if native and command:
        raise ValueError('不能同时使用全量和逐词典原生入口')
    if native and not dry_run:
        native.check(names)
    argv = json.loads(command) if command else None
    if command and (not isinstance(argv, list) or not argv or not all(isinstance(v, str) and v for v in argv)):
        raise ValueError('--native-sync-command 必须是非空 JSON 字符串数组')
    if argv and names is not None and not any('{dictionary}' in arg for arg in argv):
        raise ValueError('项目限定词典范围时，原生应用命令必须含 {dictionary} 占位符，且只处理该词典')
    with contextlib.ExitStack() as stack:
        if not dry_run:
            state.mkdir(parents=True, exist_ok=True, mode=0o700)
            lock = stack.enter_context(checked(state / 'lock').open('a'))
            lock_exclusive(lock)
        devices = [p.name for p in store.iterdir() if p.name != device and p.is_dir()] if store.exists() else []
        incoming = snapshots(store, devices, names)
        outgoing = snapshots(sync_dir, [device], names)
        session = state / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])

        def transfer(files, destination, direction):
            planned = []
            for name, data in files.items():
                target = checked(destination / name)
                if target.exists() and target.read_bytes() == data:
                    continue
                planned.append((name, target, data))
            for name, target, data in planned:
                print(f'dictionary-{direction}\t{name}', flush=True)
                if not dry_run:
                    if target.exists():
                        backup = checked(session / direction / name)
                        atomic_write(backup, target.read_bytes())
                    atomic_write(target, data)
            return len(planned)

        # Preflight both directions before touching either side.
        for name in incoming:
            checked(sync_dir / name)
        for name in outgoing:
            checked(store / name)
        pulled = transfer(incoming, sync_dir, 'pull')
        if native and not dry_run:
            native.run(names)
            outgoing = snapshots(sync_dir, [device], names) if native.publish_allowed else {}
        if argv and not dry_run:
            # shell=False avoids interpreting command text; hook must block until complete.
            commands = [argv] if names is None else [[arg.replace('{dictionary}', name) for arg in argv] for name in names]
            for invocation in commands:
                subprocess.run(invocation, check=True, timeout=300)
            outgoing = snapshots(sync_dir, [device], names)
        pushed = transfer(outgoing, store, 'push')
        if not outgoing and not native:
            print('个人词典尚无本机快照：请在 Rime 中执行“同步用户资料”。', flush=True)
        elif not argv and not native and pulled:
            print('已接收快照：请在 Rime 中执行“同步用户资料”以合并词条和词频。', flush=True)
        return pulled, pushed
