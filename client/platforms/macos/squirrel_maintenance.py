"""Squirrel CLI maintenance with fresh, PID-bound librime task evidence."""
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from client.storage.filesystem import atomic_write
from client.maintenance.lock import maintenance_lock


from client.maintenance.idle import IdleProvider


def frontend():
    apps=[Path('/Library/Input Methods/Squirrel.app'),Path.home()/'Library/Input Methods/Squirrel.app']
    binaries=[p/'Contents/MacOS/Squirrel' for p in apps if (p/'Contents/MacOS/Squirrel').is_file()]
    if len(binaries)!=1:raise ValueError('无法唯一定位鼠须管安装')
    result=subprocess.run(['pgrep','-x','Squirrel'],capture_output=True,text=True,check=True,timeout=10)
    pids=result.stdout.split()
    if len(pids)!=1:raise ValueError('鼠须管必须有且只有一个运行实例')
    pid=int(pids[0]);binary=binaries[0]
    command=subprocess.run(['ps','-p',str(pid),'-o','comm='],capture_output=True,text=True,check=True,timeout=10).stdout.strip()
    if command!=str(binary):raise ValueError('运行的鼠须管与安装路径不一致')
    return binary,pid


def verify_tasks(text,operation,names):
    if re.search(r'^E\d{4,8}\s',text,re.MULTILINE):raise ValueError('鼠须管原生维护日志包含错误')
    totals=re.findall(r'(\d+) tasks ran: (\d+) success, (\d+) failure',text)
    if not totals:return False
    starts=[m.start() for m in re.finditer('running deployment tasks:',text)]
    if len(starts)!=1 or starts[0]>text.index(totals[0][0]+' tasks ran:'):
        raise ValueError('缺少本轮任务开始或存在并发维护')
    if len(totals)!=1 or any(int(n)!=int(ok) or int(n)<1 or int(failed) for n,ok,failed in totals):
        raise ValueError('原生维护失败或存在并发任务')
    processed=set(re.findall(r"synchronize user dict '([^']+)'",text))
    if operation=='sync':
        if tuple(map(int,totals[0]))!=(3,3,0) or processed!=set(names):raise ValueError('原生同步完成范围不一致')
    elif processed or 'updating workspace.' not in text:raise ValueError('未确认本轮工作区部署')
    return True


def run(target,idle,session,operation,names=(),prepare=None,idle_provider=None):
    if operation not in ('sync','deploy'):raise ValueError('Unknown maintenance operation')
    if Path(target).resolve()!=(Path.home()/'Library/Rime').resolve():raise ValueError('鼠须管目标目录不一致')
    provider=idle_provider or IdleProvider('macos')
    if not provider.observe(idle).permits_maintenance:return {'status':'deferred','reason':'input-active'}
    with maintenance_lock(target):
        binary,pid=frontend()
        if prepare is not None:prepare()
        root=Path(tempfile.gettempdir())/'rime.squirrel'
        def files():
            return [p for p in root.glob(f'*.INFO.*.{pid}.log') if p.is_file() and not p.is_symlink()]
        before={p:(p.stat().st_ino,p.stat().st_size) for p in files()}
        if not before:raise ValueError('鼠须管本轮日志观测不可用')
        if not provider.observe(idle).permits_maintenance:return {'status':'deferred','reason':'input-active'}
        subprocess.run([str(binary),'--sync' if operation=='sync' else '--reload'],check=True,timeout=15,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            time.sleep(.5)
            if frontend()!=(binary,pid):raise ValueError('鼠须管维护期间重启')
            chunks=[]
            for p in files():
                stat=p.stat();inode,offset=before.get(p,(stat.st_ino,0))
                if stat.st_ino!=inode or stat.st_size<offset:raise ValueError('原生日志被替换或截断')
                with p.open('rb') as f:
                    f.seek(offset);chunks.append(f.read().decode('utf-8',errors='replace'))
            text='\n'.join(chunks)
            if verify_tasks(text,operation,names):
                # Persist aggregate task evidence, not dictionary contents.
                result={'status':'success','frontend_pid':pid,'names':sorted(names),'task_summary':re.findall(r'\d+ tasks ran: \d+ success, \d+ failure',text)}
                atomic_write(session/'receipt.json',json.dumps(result).encode());return result
        raise ValueError('鼠须管维护完成超时，保留待处理状态')


def sync_directory(target):
    # Only the Rime-written top-level scalar is accepted; unsupported YAML fails
    # closed rather than guessing a different directory for native full sync.
    lines=[line for line in (target/'installation.yaml').read_text(encoding='utf-8-sig').splitlines() if line.startswith('sync_dir:')]
    if not lines:return target/'sync'
    if len(lines)!=1:raise ValueError('sync_dir 重复')
    value=lines[0].split(':',1)[1].strip()
    if value.startswith('"'):
        value=json.loads(value)
    elif value.startswith("'") and value.endswith("'"):
        value=value[1:-1].replace("''", "'")
    elif not re.fullmatch(r'/[^#\[\]{}\r\n]+',value):
        raise ValueError('不支持的原生 sync_dir 格式')
    if not isinstance(value,str) or not Path(value).is_absolute():raise ValueError('原生 sync_dir 必须是绝对路径')
    return Path(value)
