#!/usr/bin/env python3
"""Apply the repository's authoritative config to a local Rime directory."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

SOURCE = Path(__file__).resolve().parents[1] / 'config'
RESERVED = {'build', 'sync', 'installation.yaml', 'user.yaml'}


def default_target(system=None, release=None):
    from paths import discover, load_paths, platform_key
    return discover(load_paths(SOURCE.parent / 'paths.json'), platform_key(system, release))


def relative_name(name):
    p = Path(name)
    if not name or p.is_absolute() or '..' in p.parts or str(p) != name:
        raise ValueError(f'不安全的相对路径: {name}')
    if any(part in RESERVED or '.userdb' in part or part.endswith('.gram') for part in p.parts):
        raise ValueError(f'拒绝管理运行时数据: {name}')
    return p


def safe_path(root, name=''):
    path = root
    # Check ancestors as well: never traverse a destination symlink.
    for p in reversed((root, *root.parents)):
        if p.is_symlink():
            raise ValueError(f'拒绝符号链接: {p}')
        if p.exists() and not p.is_dir():
            raise ValueError(f'目录被文件阻挡: {p}')
    if name:
        parts = relative_name(name).parts
        for i, part in enumerate(parts):
            path /= part
            if path.is_symlink():
                raise ValueError(f'拒绝符号链接: {path}')
            if path.exists() and (not path.is_file() if i == len(parts) - 1 else not path.is_dir()):
                raise ValueError(f'路径类型冲突: {path}')
    return path


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.rime-sync-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def snapshot(source, includes=None, allow_empty=False):
    safe_path(source)
    if not source.is_dir():
        raise ValueError(f'配置源不存在: {source}')
    result = {}
    paths = sorted(source.rglob('*')) if includes is None else [source / name for name in includes]
    for p in paths:
        if includes is not None:
            safe_path(source, p.relative_to(source).as_posix())
            if not p.exists():
                continue
        if p.is_symlink():
            raise ValueError(f'配置源不能包含符号链接: {p}')
        if p.is_dir():
            continue
        if not p.is_file():
            raise ValueError(f'不支持的文件类型: {p}')
        name = p.relative_to(source).as_posix()
        relative_name(name)
        result[name] = p.read_bytes()
    if not result and not allow_empty:
        raise ValueError('配置源为空，拒绝应用以防止意外清空')
    return result


def apply(source, target, state, dry_run=False, includes=None, allow_empty=False):
    source, target, state = (Path(os.path.abspath(p)) for p in (source, target, state))
    roots = (source, target, state)
    for i, a in enumerate(roots):
        for b in roots[i + 1:]:
            if a == b or a in b.parents or b in a.parents:
                raise ValueError('源目录、目标目录和状态目录不能重叠')
    safe_path(target)
    safe_path(state)
    if not dry_run:
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with contextlib.ExitStack() as stack:
        # Dry-run is strictly read-only. Actual writers serialize per target.
        if not dry_run:
            lock_path = safe_path(state, 'lock')
            lock = stack.enter_context(lock_path.open('a'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        files = snapshot(source, includes, allow_empty)
        manifest_path = safe_path(state, 'manifest.json')
        old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        if old and (old.get('target') != str(target) or old.get('source') != str(source)):
            raise ValueError('状态目录属于不同源或目标，请另选 --state-dir')
        managed = old.get('files', [])
        if not isinstance(managed, list) or not all(isinstance(n, str) for n in managed):
            raise ValueError('状态清单无效')
        # Scope changes release excluded paths without deleting installed dependencies.
        if includes is not None:
            managed = [name for name in managed if name in includes]
        operations = []
        for name in sorted(set(files) | set(managed)):
            dest = safe_path(target, name)
            if name not in files:
                if dest.exists():
                    operations.append(('delete', name))
            elif not dest.exists() or dest.read_bytes() != files[name]:
                operations.append(('replace' if dest.exists() else 'create', name))
        for action, name in operations:
            print(f'{action}\t{name}', flush=True)
        if dry_run:
            return operations
        if not operations and old and old.get('files') == sorted(files):
            return operations
        session = state / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
        safe_path(session)
        session.mkdir(parents=True)
        # Back up every changed destination before starting any target writes.
        journal = {'source': str(source), 'target': str(target), 'operations': operations, 'status': 'prepared'}
        for action, name in operations:
            dest = safe_path(target, name)
            if dest.exists():
                backup = session / 'files' / name
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, backup)
        atomic_write(session / 'journal.json', json.dumps(journal, ensure_ascii=False, indent=2).encode())
        completed = []
        try:
            for action, name in operations:
                dest = safe_path(target, name)
                if action == 'delete':
                    dest.unlink()
                else:
                    atomic_write(dest, files[name])
                completed.append((action, name))
            manifest = {'source': str(source), 'target': str(target), 'files': sorted(files)}
            atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode())
        except BaseException:
            for action, name in reversed(completed):
                dest = safe_path(target, name)
                if action == 'create':
                    dest.unlink(missing_ok=True)
                else:
                    atomic_write(dest, (session / 'files' / name).read_bytes())
            raise
        journal['status'] = 'applied'
        atomic_write(session / 'journal.json', json.dumps(journal, ensure_ascii=False, indent=2).encode())
        print(f'备份与操作记录: {session}', flush=True)
        return operations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paths-config', type=Path, default=SOURCE.parent / 'paths.json', help='初次发现目录的候选路径配置')
    parser.add_argument('--paths-state', type=Path, help='私有路径记忆文件，默认与 device 配置同目录的 paths.local.json')
    parser.add_argument('--discover-target', action='store_true', help='仅发现/确认并记住目标目录，不同步或初始化令牌')
    parser.add_argument('--rediscover-target', action='store_true', help='忽略旧记忆和身份文件路径，重新按候选路径发现')
    parser.add_argument('--init', action='store_true', help='初始化项目内的本机安装 ID、设备令牌和目标目录，然后退出')
    parser.add_argument('--device-config', type=Path, default=SOURCE.parent / 'device.local.json', help='本机私有项目配置文件')
    parser.add_argument('--token-stdin', action='store_true', help='初始化时从标准输入读取一行设备令牌')
    parser.add_argument('--remote-config', type=Path, default=SOURCE.parent / 'remote.json', help='服务端连接及同步周期配置')
    parser.add_argument('--sync-now', action='store_true', help='立即进行一轮服务端同步')
    parser.add_argument('--resolve-conflicts', choices=['local', 'remote'], help='显式选择本轮配置冲突的本地或服务端版本')
    parser.add_argument('--sync-config', type=Path, default=SOURCE.parent / 'sync-manifest.json', help='配置与个人词典同步/应用范围文件')
    parser.add_argument('--third-party-config', type=Path, default=SOURCE.parent / 'third-party.json', help='第三方词典刷新配置文件')
    parser.add_argument('--refresh-third-party', action='store_true', help='立即检查第三方词典，仍遵守配置 enabled 开关')
    parser.add_argument('--third-party-only', action='store_true', help='只运行第三方词典刷新')
    parser.add_argument('--dictionary-store', type=Path, help='个人词典快照交换目录（可为私有同步盘）')
    parser.add_argument('--device-id', help='本机 installation.yaml 中的 installation_id')
    parser.add_argument('--rime-sync-dir', type=Path, help='Rime 原生同步根目录，默认目标目录下 sync')
    parser.add_argument('--native-sync-command', help='JSON 参数数组；需等待 Rime 原生同步完成再退出的命令')
    parser.add_argument('--target', type=Path, help='Rime 用户配置目录')
    parser.add_argument('--state-dir', type=Path, help='备份及管理清单目录')
    parser.add_argument('--dry-run', '--plan', action='store_true', help='只显示变更，不写文件')
    parser.add_argument('--watch', action='store_true', help='持续检查并应用配置')
    parser.add_argument('--interval', type=float, default=5, help='检查间隔秒数（默认 5）')
    parser.add_argument('--service', choices=['install', 'uninstall', 'status'], help='注册并启动、卸载或查询当前用户的自动同步服务')
    args = parser.parse_args()
    if args.service and (args.init or args.discover_target or args.watch or args.sync_now or args.resolve_conflicts or args.refresh_third_party or args.token_stdin):
        parser.error('--service 不能与初始化、路径发现或单次同步动作同用')
    if args.service == 'status' and args.dry_run:
        parser.error('--service status 不支持 --dry-run')
    if args.discover_target and (args.init or args.watch or args.sync_now or args.resolve_conflicts or args.refresh_third_party or args.third_party_only):
        parser.error('--discover-target 是独立路径操作')
    if args.token_stdin and not args.init:
        parser.error('--token-stdin 只能与 --init 同用')
    if args.init and (args.watch or args.dry_run or args.sync_now or args.resolve_conflicts or args.refresh_third_party or args.third_party_only):
        parser.error('--init 是独立初始化操作，不能与同步/预览选项同用')
    if args.interval <= 0 or not __import__('math').isfinite(args.interval):
        parser.error('--interval 必须为有限正数')
    if args.watch and args.dry_run:
        parser.error('--watch 不能与 --dry-run 同用')
    if args.third_party_only and args.dictionary_store:
        parser.error('--third-party-only 不能与个人词典选项同用')
    try:
        if args.service in ('uninstall', 'status'):
            from service import manage
            return manage(args.service, args, Path(__file__).resolve())
        from identity import load_identity, initialize
        device_config_path = Path(os.path.abspath(args.device_config.expanduser()))
        if device_config_path == SOURCE or device_config_path in SOURCE.parents or SOURCE in device_config_path.parents:
            raise ValueError('私有设备配置不能放入待同步的 config/ 目录')
        identity = load_identity(device_config_path)
        from paths import load_paths, resolve_target, remember_target, existing_target
        paths_config = load_paths(args.paths_config)
        paths_state = Path(os.path.abspath((args.paths_state or device_config_path.parent / 'paths.local.json').expanduser()))
        if paths_state == SOURCE or paths_state in SOURCE.parents or SOURCE in paths_state.parents or paths_state == device_config_path:
            raise ValueError('路径记忆文件不能与配置源或设备身份文件重叠')
        target, target_origin = resolve_target(paths_config, paths_state, args.target, identity.get('target'), args.rediscover_target)
        if target == SOURCE or target in SOURCE.parents or SOURCE in target.parents:
            raise ValueError('实际 Rime 目录不能与仓库 config/ 重叠')
        if paths_state == target or target in paths_state.parents:
            raise ValueError('路径记忆文件不能放入实际 Rime 目录')
        if args.service == 'install':
            from service import manage
            return manage('install', args, Path(__file__).resolve(), target)
        if args.discover_target:
            if not args.dry_run:
                remember_target(paths_state, target)
            print(f'实际配置目录: {target}（{target_origin}）', flush=True)
            return 0
        if args.init:
            initialize(device_config_path, target, args.device_id, args.token_stdin)
            remember_target(paths_state, target)
            return 0
        key = hashlib.sha256(str(target).encode()).hexdigest()[:16]
        state = (args.state_dir or Path.home() / '.local/state/rime-config' / key).expanduser()
        state = Path(os.path.abspath(state))
        if state == SOURCE or state in SOURCE.parents or SOURCE in state.parents:
            raise ValueError('状态目录不能与仓库 config/ 重叠')
        if not args.dry_run:
            remember_target(paths_state, target)
        print(f'配置源: {SOURCE}\n目标: {target}（{target_origin}）', flush=True)
        force_refresh = args.refresh_third_party
        force_remote = args.sync_now
        resolution = args.resolve_conflicts
        while True:
            existing_target(target)
            from scope import load_scope
            project_scope = load_scope(args.sync_config)
            config_scope = project_scope['configuration']
            dictionary_scope = project_scope['dictionaries']
            scope = config_scope['files']
            from third_party import load_config, refresh, RefreshError
            third_party_config = load_config(args.third_party_config, scope)
            from remote import load_remote, synchronize, RemoteError
            remote_config = load_remote(args.remote_config)
            identity = load_identity(device_config_path)
            device_id = args.device_id or identity.get('installation_id')
            if identity and args.device_id and args.device_id != identity['installation_id']:
                raise ValueError('--device-id 与私有设备配置不一致，请为另一设备指定独立 --device-config')
            if identity:
                remote_config['token'] = identity['token']
            if args.dictionary_store and not device_id:
                raise ValueError('共享目录同步需要安装 ID，请先 --init 或指定 --device-id')
            remote_active = remote_config['enabled'] and not args.third_party_only
            if remote_active and not device_id:
                raise ValueError('服务端同步需要安装 ID，请先运行 --init')
            if remote_active and args.dictionary_store:
                raise ValueError('服务端模式与 --dictionary-store 共享目录模式不能同时启用')
            if not remote_active and not args.third_party_only and not args.dictionary_store and (args.device_id or args.rime_sync_dir or args.native_sync_command):
                raise ValueError('个人词典选项需要启用服务端同步或 --dictionary-store')
            personal_ok = True
            if remote_active:
                try:
                    outcome = synchronize(remote_config, project_scope, SOURCE,
                                          args.rime_sync_dir or target / 'sync', device_id,
                                          state / 'remote', command=args.native_sync_command,
                                          dry_run=args.dry_run, force=force_remote, resolve=resolution)
                    personal_ok = outcome != 'blocked'
                except RemoteError as exc:
                    print(str(exc), file=sys.stderr)
                    personal_ok = False
            if personal_ok and not args.third_party_only and config_scope['enabled'] and scope:
                apply(SOURCE, target, state, args.dry_run, includes=scope, allow_empty=remote_active)
            if not remote_active and not args.third_party_only and args.dictionary_store and dictionary_scope['enabled'] and dictionary_scope['names']:
                from dictionaries import exchange
                exchange(args.rime_sync_dir or target / 'sync', args.dictionary_store,
                         device_id, state / 'dictionaries', args.dry_run,
                         args.native_sync_command, names=dictionary_scope['names'])
            elif not remote_active and not args.third_party_only and dictionary_scope['enabled'] and dictionary_scope['names'] and not args.dictionary_store:
                print('个人词典范围已启用，但未配置服务端或 --dictionary-store；本轮不交换或应用个人词典。', flush=True)
            try:
                refresh(third_party_config, target, state / 'third-party', args.dry_run, force_refresh)
            except RefreshError as exc:
                print(str(exc), file=sys.stderr)
                if not args.watch:
                    return 1
            force_refresh = False
            force_remote = False
            resolution = None
            if not args.watch:
                return 0 if personal_ok else 1
            time.sleep(args.interval)
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f'同步失败: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main())
