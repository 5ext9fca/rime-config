"""systemd / launchd effects; shared command construction lives in service.py."""
import os
import subprocess
from pathlib import Path


def manage_unix(action, args, script, target, system):
    from client.storage.filesystem import atomic_write
    from client.storage.config_paths import safe_path
    from client.services.service import command, render, run, owned, UNIT, LABEL
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
    data = render(system, argv, script.parent, home) if argv else None
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
                '请确认当前登录会话的 systemd 用户管理器可用。')
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
