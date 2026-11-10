"""Installed Weasel deployment with process logs and restored-service evidence."""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def installed_deployer():
    import winreg
    candidates=[]
    for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
        for flags in (winreg.KEY_READ|winreg.KEY_WOW64_32KEY,winreg.KEY_READ|winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive,r'Software\Rime\Weasel',0,flags) as key:
                    value,kind=winreg.QueryValueEx(key,'WeaselRoot')
                    if kind==winreg.REG_SZ:candidates.append(Path(value)/'WeaselDeployer.exe')
            except FileNotFoundError:pass
    candidates=list(dict.fromkeys(p.resolve() for p in candidates if p.is_file()))
    if len(candidates)!=1:raise ValueError('无法唯一定位注册的小狼毫部署器')
    return candidates[0]


def verify_log(text):
    # /deploy calls RimeDeployWorkspace synchronously; Deployer::Run's task
    # summary belongs to async maintenance and is not required here.
    summaries=list(re.finditer(r'finished updating schemas: (\d+) success, (\d+) failure',text))
    starts=list(re.finditer(r'updating workspace\.',text))
    resume=text.rfind('Resuming service.')
    if (len(starts)!=1 or len(summaries)!=1 or
            int(summaries[0][1])<1 or int(summaries[0][2])!=0 or
            not starts[0].start()<summaries[0].start() or
            (resume >= 0 and resume < summaries[0].start())):
        raise ValueError('未确认本轮方案编译成功')
    totals=re.findall(r'(\d+) tasks ran: (\d+) success, (\d+) failure',text)
    if any(int(n)!=int(ok) or int(n)<1 or int(failed) for n,ok,failed in totals):
        raise ValueError('小狼毫部署任务未全部成功')
    if re.search(r'^E\d{4,8}\s',text,re.MULTILINE) or 'aborting operation' in text:
        raise ValueError('小狼毫部署日志包含错误')


def run(target,policy,session,idle_provider=None):
    if os.name!='nt':raise ValueError('小狼毫部署需要 Windows Python')
    import client.platforms.windows.weasel_sync as native
    from client.maintenance.lock import maintenance_lock
    from client.storage.filesystem import atomic_write
    if Path(target).resolve()!=native.registered_target().resolve():raise ValueError('注册的小狼毫目录与目标不一致')
    from client.maintenance.idle import IdleProvider
    provider=idle_provider or IdleProvider('windows')
    if not provider.observe(policy['idle_seconds']).permits_maintenance:return {'status':'deferred','reason':'input-active'}
    deployer=installed_deployer()
    with maintenance_lock(target):
        if native.deployer_busy():return {'status':'deferred','reason':'native-maintenance-busy'}
        if not provider.observe(policy['idle_seconds']).permits_maintenance:return {'status':'deferred','reason':'input-active'}
        started=time.time()
        child=subprocess.Popen([str(deployer),'/deploy'],creationflags=subprocess.CREATE_NO_WINDOW,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            if child.wait(timeout=180)!=0:raise ValueError('小狼毫部署进程失败')
            logs=[p for p in (Path(os.environ['TEMP'])/'rime.weasel').glob(f'*.INFO.*.{child.pid}.log') if p.stat().st_mtime>=started-2]
            if len(logs)!=1:raise ValueError('未找到本次部署唯一日志')
            text=logs[0].read_text(encoding='utf-8',errors='replace');verify_log(text)
            subprocess.run([sys.executable,str(Path(native.__file__).resolve()),'--probe'],check=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            # Some installed builds omit Configurator INFO messages. Recovery
            # is independently verified by the mandatory IPC probe above.
            result={'status':'success','pid':child.pid,'log':str(logs[0]),'input_service_probe':'passed'}
            atomic_write(session/'receipt.json',json.dumps(result).encode());return result
        except BaseException:
            if child.poll() is None:child.kill()
            child.wait()
            subprocess.run([sys.executable,str(Path(native.__file__).resolve()),'--resume'],timeout=10,creationflags=subprocess.CREATE_NO_WINDOW,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            raise


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--target',required=True,type=Path);parser.add_argument('--session',required=True,type=Path);parser.add_argument('--idle',required=True,type=float)
    args=parser.parse_args();print(json.dumps(run(args.target,{'idle_seconds':args.idle},args.session)))
