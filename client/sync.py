#!/usr/bin/env python3
"""Apply the repository's authoritative config to a local Rime directory."""
import argparse
import contextlib
from file_lock import lock_exclusive
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

SOURCE = Path(__file__).resolve().parents[1] / 'config'
RESERVED = {'build', 'sync', 'installation.yaml', 'user.yaml'}
WINDOWS_DEVICES = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} | {
    prefix + suffix for prefix in ('COM', 'LPT') for suffix in '123456789¹²³'}


def windows_reserved(name):
    return name.split('.')[0].rstrip(' ').upper() in WINDOWS_DEVICES


def default_target(system=None, release=None):
    from paths import discover, load_paths, platform_key
    return discover(load_paths(SOURCE.parent / 'paths.json'), platform_key(system, release))


def relative_name(name):
    p = Path(name)
    if (not name or p.is_absolute() or p.drive or '..' in p.parts
            or p.as_posix() != name or '\\' in name or ':' in name):
        raise ValueError(f'不安全的相对路径: {name}')
    # Reject Win32 aliases/streams on every platform so shared scopes stay portable.
    if any(part.endswith((' ', '.')) or windows_reserved(part)
           or any(ord(c) < 32 or c in '<>"|?*' for c in part) for part in p.parts):
        raise ValueError(f'不安全的相对路径: {name}')
    if any(part in RESERVED or '.userdb' in part or part.endswith('.gram') for part in p.parts):
        raise ValueError(f'拒绝管理运行时数据: {name}')
    return p


def is_link(path):
    return path.is_symlink() or (os.name == 'nt' and path.exists() and
            bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT))


def safe_path(root, name=''):
    path = root
    # Check ancestors as well: never traverse a destination symlink.
    for p in reversed((root, *root.parents)):
        if is_link(p):
            raise ValueError(f'拒绝符号链接: {p}')
        if p.exists() and not p.is_dir():
            raise ValueError(f'目录被文件阻挡: {p}')
    if name:
        parts = relative_name(name).parts
        for i, part in enumerate(parts):
            path /= part
            if is_link(path):
                raise ValueError(f'拒绝符号链接: {path}')
            if path.exists() and (not path.is_file() if i == len(parts) - 1 else not path.is_dir()):
                raise ValueError(f'路径类型冲突: {path}')
    return path


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.rime-sync-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            if os.name == 'nt':
                from windows_security import protect_file
                protect_file(temporary)
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
        if is_link(p):
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


def observe_configuration(source, target, state, includes=None, allow_empty=False):
    """Read-only observations for the shared planner; no plan replay API."""
    from plans import configuration
    from paths import platform_key
    source, target, state = (Path(os.path.abspath(p)) for p in (source, target, state))
    roots = (source, target, state)
    for i, a in enumerate(roots):
        for b in roots[i + 1:]:
            if a == b or a in b.parents or b in a.parents:
                raise ValueError('源目录、目标目录和状态目录不能重叠')
    safe_path(target)
    safe_path(state)
    files = snapshot(source, includes, allow_empty)
    manifest_path = safe_path(state, 'manifest.json')
    old = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    if old and (old.get('target') != str(target) or old.get('source') != str(source)):
        raise ValueError('状态目录属于不同源或目标，请另选 --state-dir')
    managed = old.get('files', [])
    if not isinstance(managed, list) or not all(isinstance(n, str) for n in managed):
        raise ValueError('状态清单无效')
    if includes is not None:
        managed = [name for name in managed if name in includes]
    destinations = {}
    for name in sorted(set(files) | set(managed)):
        dest = safe_path(target, name)
        destinations[name] = dest.read_bytes() if dest.exists() else None
    return files, old, configuration(platform_key(), files, destinations, managed)


def recheck_configuration(plan, source, target):
    from plans import validate, digest
    validate(plan, 'configuration-plan')
    for item in plan['steps']:
        for root, field in ((source, 'after'), (target, 'before')):
            path = safe_path(root, item['id'])
            if digest(path.read_bytes() if path.exists() else None) != item['details'][field]:
                raise ValueError('配置计划已过期，保留并发修改并在下一轮重建计划')


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
            lock_exclusive(lock)
        files, old, plan = observe_configuration(source, target, state, includes, allow_empty)
        manifest_path = safe_path(state, 'manifest.json')
        operations = [(item['action'], item['id']) for item in plan['steps'] if item['action'] != 'skip']
        for action, name in operations:
            print(f'{action}\t{name}', flush=True)
        if dry_run:
            return operations
        if not operations and old and old.get('files') == sorted(files):
            return operations
        recheck_configuration(plan, source, target)
        session = state / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
        safe_path(session)
        session.mkdir(parents=True)
        # Back up every changed destination before starting any target writes.
        journal = {'source': str(source), 'target': str(target), 'operations': operations,
                   'status': 'prepared', 'plan': plan}
        for action, name in operations:
            dest = safe_path(target, name)
            if dest.exists():
                backup = session / 'files' / name
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, backup)
        atomic_write(session / 'journal.json', json.dumps(journal, ensure_ascii=False, indent=2).encode())
        recheck_configuration(plan, source, target)
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
    if os.name == 'nt':
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding='utf-8')
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
    parser.add_argument('--native-sync-all-command', help='Unix 等平台原生全量同步包装器 JSON 数组，完成后写入 RIME_SYNC_RECEIPT')
    parser.add_argument('--weasel-deployer', type=Path, help='Windows 原生 WeaselDeployer.exe；独立限频调度 /sync 并验证完成')
    parser.add_argument('--native-sync-config', type=Path, default=SOURCE.parent / 'native-sync.json', help='原生维护独立周期与空闲阈值')
    parser.add_argument('--target', type=Path, help='Rime 用户配置目录')
    parser.add_argument('--state-dir', type=Path, help='备份及管理清单目录')
    parser.add_argument('--dry-run', '--plan', action='store_true', help='只显示变更，不写文件')
    parser.add_argument('--plan-json', action='store_true', help='输出版本化 JSON 计划；只读、不联网、不调用平台执行器')
    parser.add_argument('--watch', action='store_true', help='持续检查并应用配置')
    parser.add_argument('--interval', type=float, default=5, help='检查间隔秒数（默认 5）')
    parser.add_argument('--service', choices=['install', 'uninstall', 'status'], help='注册并启动、卸载或查询当前用户的自动同步服务')
    args = parser.parse_args()
    if args.plan_json:
        if args.service or args.watch or args.init or args.discover_target or args.resolve_conflicts or args.token_stdin:
            parser.error('--plan-json 是独立的只读计划操作')
        args.dry_run = True
    if sum(bool(v) for v in (args.native_sync_command, args.native_sync_all_command, args.weasel_deployer)) > 1:
        parser.error('逐词典命令、全量命令和小狼毫入口只能选择一个')
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
        if state == target or state in target.parents or target in state.parents:
            raise ValueError('状态目录不能与实际 Rime 目录重叠')
        if not args.dry_run:
            remember_target(paths_state, target)
        if not args.plan_json:
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
            native = None
            if (args.native_sync_all_command or args.weasel_deployer) and not args.third_party_only:
                if not device_id or not (remote_active or args.dictionary_store):
                    raise ValueError('全量原生同步需要设备身份及远端或共享目录同步')
                from native_sync import FullNativeSync, load_schedule
                native = FullNativeSync(target, args.rime_sync_dir or target / 'sync', device_id,
                                        args.sync_config, state / 'native-all',
                                        command=args.native_sync_all_command, deployer=args.weasel_deployer,
                                        policy=load_schedule(args.native_sync_config))
                if args.plan_json:
                    import io
                    with contextlib.redirect_stdout(io.StringIO()):
                        project_scope = native.prepare(True)
                else:
                    project_scope = native.prepare(args.dry_run)
                dictionary_scope = project_scope['dictionaries']
            if remote_active and not device_id:
                raise ValueError('服务端同步需要安装 ID，请先运行 --init')
            if remote_active and args.dictionary_store:
                raise ValueError('服务端模式与 --dictionary-store 共享目录模式不能同时启用')
            if not remote_active and not args.third_party_only and not args.dictionary_store and (args.device_id or args.rime_sync_dir or args.native_sync_command):
                raise ValueError('个人词典选项需要启用服务端同步或 --dictionary-store')
            from plans import workflow, execute_workflow, dumps
            from paths import platform_key
            plan = workflow(platform_key(), remote=remote_active,
                            configuration=config_scope['enabled'] and bool(scope),
                            dictionaries=dictionary_scope['enabled'] and bool(dictionary_scope['names']),
                            store=bool(args.dictionary_store), third_party=third_party_config['enabled'],
                            third_party_only=args.third_party_only,
                            native_backend='weasel' if args.weasel_deployer else
                            'command' if args.native_sync_all_command else
                            'legacy-command' if args.native_sync_command else 'snapshots-only')
            if args.plan_json:
                if plan['steps'][1]['action'] != 'skip':
                    _, _, file_plan = observe_configuration(SOURCE, target, state, scope, remote_active)
                    plan['steps'][1]['details'] = {'source': str(SOURCE), 'target': str(target),
                                                 'local_preview': file_plan,
                                                 'rebuild_after_remote': remote_active}
                if native and dictionary_scope['enabled']:
                    owner = 0 if remote_active else 2
                    plan['steps'][owner]['details']['native_preview'] = native.preview(dictionary_scope['names'])
                print(dumps(plan))
                return 0

            def run_remote():
                try:
                    outcome = synchronize(remote_config, project_scope, SOURCE,
                                          args.rime_sync_dir or target / 'sync', device_id,
                                          state / 'remote', command=args.native_sync_command,
                                          dry_run=args.dry_run, force=force_remote, resolve=resolution, native=native)
                    status = 'blocked' if outcome == 'blocked' else 'skipped' if outcome in ('not-due', 'disabled', 'planned') else 'success'
                    return {'status': status, 'reason': outcome}
                except RemoteError as exc:
                    print(str(exc), file=sys.stderr)
                    return {'status': 'failed', 'reason': 'remote-error'}

            def run_configuration():
                apply(SOURCE, target, state, args.dry_run, includes=scope, allow_empty=remote_active)
                return {'status': 'success', 'reason': 'configuration-checked'}

            def run_dictionaries():
                from dictionaries import exchange
                exchange(args.rime_sync_dir or target / 'sync', args.dictionary_store,
                         device_id, state / 'dictionaries', args.dry_run,
                         args.native_sync_command, names=dictionary_scope['names'], native=native)
                return {'status': 'deferred' if native and native.application.get('status') == 'deferred' else 'success',
                        'reason': 'dictionary-exchange-checked'}

            def run_third_party():
                try:
                    refresh(third_party_config, target, state / 'third-party', args.dry_run, force_refresh)
                    return {'status': 'success', 'reason': 'third-party-checked'}
                except RefreshError as exc:
                    print(str(exc), file=sys.stderr)
                    return {'status': 'failed', 'reason': 'third-party-error'}

            if not args.dry_run:
                atomic_write(safe_path(state, 'workflow-plan.json'), dumps(plan).encode())
            def publish(report):
                atomic_write(safe_path(state, 'workflow-result.json'), json.dumps(report, ensure_ascii=False, indent=2).encode())
            result = execute_workflow(plan, {'remote-sync': run_remote, 'configuration-apply': run_configuration,
                                            'dictionary-exchange': run_dictionaries, 'third-party-refresh': run_third_party},
                                      publish=None if args.dry_run else publish)
            if not remote_active and not args.third_party_only and dictionary_scope['enabled'] and dictionary_scope['names'] and not args.dictionary_store:
                print('个人词典范围已启用，但未配置服务端或 --dictionary-store；本轮不交换或应用个人词典。', flush=True)
            personal_ok = not any(s['status'] in ('failed', 'blocked') for s in result['steps'])
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
