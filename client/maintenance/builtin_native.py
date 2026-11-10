"""Platform native full-sync entry points used by the shared scheduling contract."""
import ctypes.util
from pathlib import Path
import time
from client.config.identity import installation_id
from client.storage.snapshots import snapshots


def run(platform, target, sync_dir, device, names, session, idle_seconds, idle_provider=None):
    if platform not in ('linux','macos'):
        raise ValueError('此平台内置原生同步适配器尚不可用')
    if installation_id(target)!=device:
        raise ValueError('原生安装身份与项目不一致')
    if platform=='linux':
        from client.platforms.rime_api import configured_sync_dir
        library=ctypes.util.find_library('rime')
        if not library:raise ValueError('无法找到本机 librime')
        actual=configured_sync_dir(target,library)
        from client.platforms.linux.fcitx_maintenance import run as maintain
    else:
        from client.platforms.macos.squirrel_maintenance import sync_directory, run as squirrel
        actual=sync_directory(target)
        def maintain(target,idle,session,operation,prepare=None,idle_provider=None):
            return squirrel(target,idle,session,operation,names,prepare=prepare,idle_provider=idle_provider)
    if actual!=sync_dir:raise ValueError('原生同步目录与项目不一致')
    started=time.time()
    from client.maintenance.dictionary_bootstrap import ensure
    def prepare():ensure(target,sync_dir,device,names,session,platform)
    result=maintain(target,idle_seconds,session,'sync',prepare=prepare,idle_provider=idle_provider)
    if result['status']=='deferred':return result
    exported=snapshots(sync_dir,[device],names)
    for name in names:
        key=f'{device}/{name}.userdb.txt'
        if key not in exported or (sync_dir/key).stat().st_mtime < started-2:
            raise ValueError('未确认本轮全部原生词典导出')
    return dict(result,names=sorted(names))
