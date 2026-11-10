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
PATH_OPTIONS = ('automation_config', 'device_config', 'paths_config', 'paths_state', 'sync_config',
                'remote_config', 'third_party_config', 'state_dir',
                'dictionary_store', 'rime_sync_dir', 'weasel_deployer', 'native_sync_config')


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
    for name in ('device_id', 'native_sync_command', 'native_sync_all_command'):
        value = getattr(args, name, None)
        if value is not None:
            if name in ('native_sync_command', 'native_sync_all_command'):
                native = json.loads(value)
                if (not isinstance(native, list) or not native or
                        not all(isinstance(x, str) for x in native) or
                        not Path(native[0]).is_absolute()):
                    raise ValueError('后台原生同步命令须为 JSON 参数数组，程序路径必须为绝对路径')
            result += ['--' + name.replace('_', '-'), value]
    if getattr(args,'native_sync_builtin',False):
        result.append('--native-sync-builtin')
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
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30,
                            **({'encoding': 'utf-8'} if os.name == 'nt' else {}))
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
    from client.platforms.platform_execution import get_executor
    return get_executor().service(action, args, script, target)
