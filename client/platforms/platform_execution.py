"""Platform effects behind explicit adapters; never execute serialized plans."""
import json
import os
from pathlib import Path
import subprocess


class UnixExecutor:
    def __init__(self, platform):
        self.platform = platform
        from client.maintenance.idle import IdleProvider
        self.idle_provider=IdleProvider(platform)

    def observe_idle(self, threshold, delegated=False):
        if delegated:
            from client.maintenance.idle import Observation
            import time
            return Observation('delegated','external-wrapper',time.monotonic(),'wrapper-must-check')
        return self.idle_provider.observe(threshold)

    def close(self):
        self.idle_provider.close()

    def native(self, *, argv, deployer, target, sync_dir, device, names, session, idle_seconds):
        if deployer:
            raise ValueError('小狼毫原生入口只能在 Windows 执行')
        if argv is None:
            from client.maintenance.builtin_native import run
            return run(self.platform,target,sync_dir,device,names,session,idle_seconds,idle_provider=self.idle_provider)
        from client.storage.snapshots import checked
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

    def reload_theme(self):
        if self.platform!='linux':raise ValueError('Fcitx5 theme applies only to native Linux')
        subprocess.run(['gdbus','call','--session','--dest','org.fcitx.Fcitx5','--object-path','/controller',
                        '--method','org.fcitx.Fcitx.Controller1.ReloadAddonConfig','classicui'],
                       check=True,timeout=30,stdout=subprocess.DEVNULL)

    def deploy(self, target, policy, session, immediate=False):
        from client.maintenance.deployment import execute_platform
        provider = self.idle_provider
        if immediate:
            from client.maintenance.idle import Observation
            import time
            class ManualDeployment:
                def observe(self, threshold):
                    return Observation('idle', 'explicit-deploy-now', time.monotonic(), 'manual-request')
            provider = ManualDeployment()
            policy = dict(policy, idle_seconds=0)
        return execute_platform(self.platform, target, policy, session,provider)

    def service(self, action, args, script, target=None):
        from client.services.unix_service import manage_unix
        return manage_unix(action, args, script, target, 'Darwin' if self.platform == 'macos' else 'Linux')


class WindowsExecutor(UnixExecutor):
    def __init__(self):
        super().__init__('windows')

    def native(self, **context):
        if context['deployer']:
            from client.platforms.windows.weasel_sync import run
            return run(context['deployer'], context['target'], context['sync_dir'],
                       context['device'], context['names'], context['session'],
                       idle_provider=self.idle_provider,idle_threshold=context['idle_seconds'])
        return super().native(**context)

    def service(self, action, args, script, target=None):
        from client.platforms.windows.windows_service import manage_windows
        return manage_windows(action, args, script, target)


_executors={}

def close_executors():
    for executor in _executors.values():executor.close()
    _executors.clear()

def get_executor(system=None):
    if system is None:
        from client.config.paths import platform_key
        key = platform_key()
    else:
        key = {'Windows': 'windows', 'Darwin': 'macos', 'Linux': 'linux'}.get(system, system)
    if key in ('windows','linux','macos'):
        if key not in _executors:_executors[key]=WindowsExecutor() if key=='windows' else UnixExecutor(key)
        return _executors[key]
    raise ValueError('不支持的执行平台')
