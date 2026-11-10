from client.core.dictionary_format import component,validate_snapshot
from client.storage.snapshots import checked,snapshots
"""Exchange Rime-owned text snapshots, never live userdb files or third-party data."""
import contextlib
from client.storage.file_lock import lock_exclusive
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

from client.storage.filesystem import atomic_write, is_link
from client.storage.config_paths import windows_reserved










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
        if not dry_run:
            from client.maintenance.backup_retention import completed as complete_backup
            complete_backup(session)
        return pulled, pushed
