"""Platform effects behind explicit adapters; never execute serialized plans."""
import json
import os
from pathlib import Path
import subprocess


class UnixExecutor:
    def __init__(self, platform):
        self.platform = platform

    def idle_seconds(self, deployer=None):
        if deployer:
            raise ValueError('小狼毫原生入口只能在 Windows 执行')
        # Unix wrappers observe their input frontend and may return deferred.
        return float('inf')

    def native(self, *, argv, deployer, target, sync_dir, device, names, session, idle_seconds):
        if deployer:
            raise ValueError('小狼毫原生入口只能在 Windows 执行')
        from dictionaries import checked
        receipt = session / 'receipt.json'
        env = dict(os.environ, RIME_SYNC_RECEIPT=str(receipt), RIME_USER_DIR=str(target),
                   RIME_SYNC_DIR=str(sync_dir), RIME_INSTALLATION_ID=device,
                   RIME_SYNC_DICTIONARIES=json.dumps(sorted(names)), RIME_SYNC_IDLE_SECONDS=str(idle_seconds))
        subprocess.run(argv, check=True, timeout=240, env=env)
        evidence = json.loads(checked(receipt).read_text(encoding='utf-8'))
        if evidence.get('status') == 'deferred':
            return evidence
        if evidence.get('status') != 'success' or set(evidence.get('names', [])) != set(names):
            raise ValueError('原生命令未提供本轮全部词典完成凭据')
        return evidence

    def service(self, action, args, script, target=None):
        from unix_service import manage_unix
        return manage_unix(action, args, script, target, 'Darwin' if self.platform == 'macos' else 'Linux')


class WindowsExecutor(UnixExecutor):
    def __init__(self):
        super().__init__('windows')

    def idle_seconds(self, deployer=None):
        if deployer:
            from weasel_sync import idle_seconds
            return idle_seconds()
        return super().idle_seconds()

    def native(self, **context):
        if context['deployer']:
            from weasel_sync import run
            return run(context['deployer'], context['target'], context['sync_dir'],
                       context['device'], context['names'], context['session'])
        return super().native(**context)

    def service(self, action, args, script, target=None):
        from windows_service import manage_windows
        return manage_windows(action, args, script, target)


def get_executor(system=None):
    if system is None:
        from paths import platform_key
        key = platform_key()
    else:
        key = {'Windows': 'windows', 'Darwin': 'macos', 'Linux': 'linux'}.get(system, system)
    if key == 'windows':
        return WindowsExecutor()
    if key in ('linux', 'wsl', 'macos'):
        return UnixExecutor(key)
    raise ValueError('不支持的执行平台')
