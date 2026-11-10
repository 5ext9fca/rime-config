"""Current-user Windows Task Scheduler registration, without shell interpolation."""
import base64
import json
from pathlib import Path
import subprocess


def powershell_command(payload):
    encoded = base64.b64encode(json.dumps(payload).encode('utf-8')).decode('ascii')
    script = ("$ErrorActionPreference = 'Stop'\n"
              "$ProgressPreference = 'SilentlyContinue'\n"
              "[Console]::OutputEncoding = [Text.UTF8Encoding]::new()\n"
              "$p = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
              + encoded + "')) | ConvertFrom-Json\n"
              + Path(__file__).with_suffix('.ps1').read_text(encoding='utf-8'))
    return ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
            base64.b64encode(script.encode('utf-16-le')).decode('ascii')]


def manage_windows(action, args, script, target=None):
    from client.services.service import command, run
    payload = {'operation': action}
    if action == 'install':
        argv = command(args, script, target)
        pythonw = Path(argv[0]).with_name('pythonw.exe')
        if not pythonw.is_file():
            raise ValueError('后台运行需要当前 Python 安装中的 pythonw.exe')
        runner = Path(__file__).with_name('windows_runner.py').resolve()
        payload.update(executable=str(pythonw),
                       arguments=subprocess.list2cmdline(['-u', str(runner), *argv[2:]]),
                       directory=str(script.parent))
    if args.dry_run:
        print('Windows 当前用户计划任务预览（登录启动，每分钟恢复检查，已有实例不重复启动）:')
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if action == 'install':
        preview = argv[:3] + argv[4:] + ['--dry-run']
        result = run(preview, check=False)
        if result.returncode:
            raise ValueError('客户端预检查失败: ' + (result.stderr or result.stdout).strip())
    result = subprocess.run(powershell_command(payload), capture_output=True,
                            text=True, encoding='utf-8', timeout=120,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('Windows 计划任务操作失败: ' + (result.stderr or result.stdout).strip())
    print(result.stdout, end='')
    if action == 'install':
        print('日志: %LOCALAPPDATA%\\rime-config\\logs\\service.log')
    return 0
