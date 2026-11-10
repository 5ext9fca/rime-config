"""Resolve installation context and own the recurring execution loop."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
from client.project import SOURCE, ENTRY

def run(args):
    try:
        if args.service in ('uninstall', 'status'):
            from client.services.service import manage
            return manage(args.service, args, ENTRY)
        from client.config.identity import load_identity, initialize
        device_config_path = Path(os.path.abspath(args.device_config.expanduser()))
        if device_config_path == SOURCE or device_config_path in SOURCE.parents or SOURCE in device_config_path.parents:
            raise ValueError('私有设备配置不能放入待同步的 config/ 目录')
        identity = load_identity(device_config_path)
        from client.config.paths import load_paths, resolve_target, remember_target, existing_target
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
            from client.services.service import manage
            return manage('install', args, ENTRY, target)
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
        from client.application.workflow import run_cycle
        while True:
            outcome=run_cycle(args,target,state,device_config_path,force_refresh,force_remote,resolution)
            force_refresh = False
            force_remote = False
            resolution = None
            if not args.watch:
                return outcome
            time.sleep(args.interval)
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f'同步失败: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


