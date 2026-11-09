"""Register the client with the current user's systemd or launchd manager."""
import json
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import sys

UNIT = 'rime-config.service'
LABEL = 'local.rime-config'
MARKER = '# Managed by rime-config service installer v1\n'
PATH_OPTIONS = ('device_config', 'paths_config', 'paths_state', 'sync_config',
                'remote_config', 'third_party_config', 'state_dir',
                'dictionary_store', 'rime_sync_dir')


def absolute(value):
    return str(Path(os.path.abspath(Path(value).expanduser())))


def command(args, script, target):
    # An allowlist prevents one-shot conflict resolution or token input from
    # accidentally becoming a recurring action. Credentials stay in private files.
    result = [absolute(sys.executable), '-u', absolute(script), '--watch',
              '--interval', str(args.interval), '--target', str(target)]
    for name in PATH_OPTIONS:
        value = getattr(args, name, None)
        if name == 'paths_state' and value is None:
            value = Path(absolute(args.device_config)).parent / 'paths.local.json'
        if value is not None:
            result += ['--' + name.replace('_', '-'), absolute(value)]
    for name in ('device_id', 'native_sync_command'):
        value = getattr(args, name, None)
        if value is not None:
            if name == 'native_sync_command':
                native = json.loads(value)
                if (not isinstance(native, list) or not native or
                        not all(isinstance(x, str) for x in native) or
                        not Path(native[0]).is_absolute()):
                    raise ValueError('后台原生同步命令须为 JSON 参数数组，程序路径必须为绝对路径')
            result += ['--' + name.replace('_', '-'), value]
    if args.third_party_only:
        result.append('--third-party-only')
    return result


def quote_unit(value, exec_arg=False):
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('服务参数不能包含控制字符')
    value = value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    if exec_arg:
        value = value.replace('$', '$$')
    return '"' + value + '"'


def render(system, argv, project, home):
    if system == 'Darwin':
        log = home / 'Library/Logs/rime-config'
        return plistlib.dumps({
            'Label': LABEL, 'RimeConfigManaged': 1,
            'ProgramArguments': argv, 'WorkingDirectory': str(project),
            'RunAtLoad': True, 'KeepAlive': {'SuccessfulExit': False},
            'ThrottleInterval': 10, 'Umask': 0o077,
            'StandardOutPath': str(log / 'stdout.log'),
            'StandardErrorPath': str(log / 'stderr.log'),
        })
    # WorkingDirectory is a scalar path, not an ExecStart argument: systemd
    # does not strip quotes here. A final /. protects trailing space/backslash.
    directory = str(project)
    quote_unit(directory)  # Reject control characters.
    directory = directory.replace('%', '%%') + '/.'
    return (MARKER + '[Unit]\nDescription=Rime configuration and dictionary sync\n'
            'StartLimitIntervalSec=0\n\n[Service]\nType=simple\n'
            f'WorkingDirectory={directory}\n'
            'ExecStart=' + ' '.join(quote_unit(x, True) for x in argv) + '\n'
            'Restart=on-failure\nRestartSec=10\nUMask=0077\n\n'
            '[Install]\nWantedBy=default.target\n').encode()


def run(argv, check=True):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    if check and result.returncode:
        # Do not echo the command: a caller's native hook may contain private args.
        raise ValueError(f'服务管理命令失败 ({argv[0]}): '
                         f'{result.stderr.strip() or result.stdout.strip()}')
    return result


def owned(data, system):
    if system == 'Darwin':
        try:
            value = plistlib.loads(data)
            return value.get('RimeConfigManaged') == 1 and value.get('Label') == LABEL
        except (ValueError, plistlib.InvalidFileException, AttributeError):
            return False
    return data.startswith(MARKER.encode())


def manage(action, args, script, target=None):
    from sync import atomic_write, safe_path
    system = platform.system()
    if system not in ('Linux', 'Darwin'):
        raise ValueError('自动服务仅支持 WSL、Ubuntu/Linux 和 macOS')
    home = Path.home()
    if system == 'Darwin':
        path = home / 'Library/LaunchAgents' / (LABEL + '.plist')
        domain = f'gui/{os.getuid()}'
        service_id = domain + '/' + LABEL
        manager = ['launchctl']
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config')
        if not base.is_absolute():
            raise ValueError('XDG_CONFIG_HOME 必须为绝对路径')
        path = base / 'systemd/user' / UNIT
        manager = ['systemctl', '--user']
    safe_path(path.parent, path.name)
    previous = path.read_bytes() if path.exists() else None
    if action == 'status':
        print(f'服务文件: {path}（{"存在" if previous is not None else "未安装"}）')
        result = run(manager + (['print', service_id] if system == 'Darwin'
                               else ['status', UNIT, '--no-pager']), check=False)
        print(result.stdout or result.stderr, end='')
        return result.returncode
    if previous is not None and not owned(previous, system):
        raise ValueError(f'拒绝覆盖或删除非本安装器管理的服务文件，请先手动迁移: {path}')
    argv = command(args, script, target) if action == 'install' else None
    data = render(system, argv, script.parent.parent, home) if argv else None
    if args.dry_run:
        print(f'服务预览: {action} {path}')
        if data:
            print(data.decode())
        return 0
    if action == 'uninstall' and previous is None:
        print('服务文件不存在，无需卸载。')
        return 0
    # Fail before modifying anything if the user's manager/session is unavailable.
    try:
        run(manager + (['print', domain] if system == 'Darwin' else ['show-environment']))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        hint = ('请在已登录的 macOS 图形用户会话中执行。' if system == 'Darwin' else
                '请确认 systemd 用户管理器可用；WSL 需先启用 systemd 并重新启动发行版。')
        raise ValueError(f'{hint} {exc}') from exc
    if action == 'install':
        # Full local validation; no network, native sync, target or state writes.
        preview = argv[:3] + argv[4:] + ['--dry-run']
        result = run(preview, check=False)
        if result.returncode:
            raise ValueError('客户端预检查失败: ' + (result.stderr or result.stdout).strip())
    active = run(manager + (['print', service_id] if system == 'Darwin'
                            else ['is-active', UNIT]), check=False).returncode == 0
    enabled = (run(manager + ['is-enabled', UNIT], check=False).returncode == 0
               if system == 'Linux' else False)
    try:
        if system == 'Darwin':
            if active:
                run(manager + ['bootout', service_id])
            if action == 'install':
                log = home / 'Library/Logs/rime-config'
                safe_path(log, 'stdout.log')
                safe_path(log, 'stderr.log')
                log.mkdir(parents=True, exist_ok=True, mode=0o700)
                atomic_write(path, data)
                run(manager + ['enable', service_id])
                run(manager + ['bootstrap', domain, str(path)])
            else:
                path.unlink()
        else:
            if action == 'install':
                atomic_write(path, data)
                run(manager + ['daemon-reload'])
                run(manager + ['enable', UNIT])
                run(manager + ['restart', UNIT])
            else:
                run(manager + ['disable', '--now', UNIT])
                path.unlink()
                run(manager + ['daemon-reload'])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # Restore the prior definition and runtime state where possible. Report
        # recovery failure explicitly rather than claiming registration succeeded.
        errors = []

        def recover(fn):
            try:
                fn()
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                errors.append(str(error))

        if system == 'Darwin':
            def unload():
                if run(manager + ['print', service_id], check=False).returncode == 0:
                    run(manager + ['bootout', service_id])
            recover(unload)
        else:
            recover(lambda: run(manager + ['disable', '--now', UNIT]))
        # Restoring the file must still be attempted if the manager is down.
        recover(lambda: path.unlink(missing_ok=True) if previous is None
                else atomic_write(path, previous))
        if system == 'Darwin':
            if active:
                recover(lambda: run(manager + ['bootstrap', domain, str(path)]))
        else:
            recover(lambda: run(manager + ['daemon-reload']))
            if enabled:
                recover(lambda: run(manager + ['enable', UNIT]))
            if active:
                recover(lambda: run(manager + ['start', UNIT]))
        if errors:
            raise ValueError(f'{exc}；服务恢复未全部成功，请检查 {path}: '
                             + '；'.join(errors)) from exc
        raise ValueError(f'{exc}；已恢复原服务定义。') from exc
    print(f'服务已{"安装并启动" if action == "install" else "停止并卸载"}: {path}')
    if system == 'Linux':
        print('日志: journalctl --user -u rime-config.service -f')
    else:
        print(f'日志: {home / "Library/Logs/rime-config"}')
    return 0
