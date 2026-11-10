from client.maintenance.lock import maintenance_lock
"""Fcitx5 native maintenance; acknowledge only this frontend's completion events."""
import contextlib
import hashlib
import os
from pathlib import Path
import re
import subprocess
import time
from client.storage.filesystem import atomic_write
from client.storage.config_paths import safe_path
from client.storage.file_lock import lock_exclusive

def call(method,*args):
    return subprocess.run(['gdbus','call','--session','--dest','org.fcitx.Fcitx5','--object-path','/controller',
                           '--method','org.fcitx.Fcitx.Controller1.'+method,*args],
                          check=True,capture_output=True,text=True,timeout=15).stdout


def frontend_pid():
    output=subprocess.run(['gdbus','call','--session','--dest','org.freedesktop.DBus','--object-path','/org/freedesktop/DBus',
        '--method','org.freedesktop.DBus.GetConnectionUnixProcessID','org.fcitx.Fcitx5'],capture_output=True,text=True,check=True,timeout=10).stdout
    return int(re.search(r'(\d+),',output)[1])

def run(target, idle_seconds, session, operation, prepare=None, idle_provider=None):
    if operation not in ('deploy','sync'):raise ValueError('Unknown maintenance operation')
    from client.maintenance.idle import IdleProvider
    provider=idle_provider or IdleProvider('linux')
    try:
        with maintenance_lock(target):
            return _run(target,idle_seconds,session,operation,call,
                        lambda threshold:provider.observe(threshold).permits_maintenance,prepare)
    finally:
        if idle_provider is None:provider.close()

def _run(target,idle_seconds,session,operation,call,linux_idle,prepare=None):
    expected=Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')/'fcitx5/rime'
    if target!=expected:raise ValueError('Automatic Fcitx5 deployment target mismatch')
    if not linux_idle(idle_seconds):return {'status':'deferred','reason':'waiting-for-idle-or-lock'}
    if prepare is not None:prepare()
    # A cursor excludes old events and PID matching excludes a restarted frontend.
    owner=subprocess.run(['gdbus','call','--session','--dest','org.freedesktop.DBus','--object-path','/org/freedesktop/DBus',
                          '--method','org.freedesktop.DBus.GetConnectionUnixProcessID','org.fcitx.Fcitx5'],
                         capture_output=True,text=True,check=True,timeout=10).stdout
    pid=int(re.search(r'(\d+),',owner)[1])
    cursor=subprocess.run(['journalctl','--user','-n','0','--show-cursor','--no-pager'],capture_output=True,text=True,check=True,timeout=10).stdout
    match=re.search(r'-- cursor: (.+)',cursor)
    if not match:raise ValueError('Journal cursor unavailable')
    try:
        if not linux_idle(idle_seconds):return {'status':'deferred','reason':'waiting-for-idle-or-lock'}
        call('SetLogRule','rime=5')
        call('SetConfig','fcitx://config/addon/rime/'+operation,'<@a{sv} {}>')
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            time.sleep(.5)
            log=subprocess.run(['journalctl','--user','_PID='+str(pid),'--after-cursor='+match[1],'-o','cat','--no-pager'],
                               capture_output=True,text=True,check=True,timeout=10).stdout
            # Persist only completion events, never typed key or vocabulary logs.
            events=[line for line in log.splitlines() if 'Notification: 0 deploy ' in line or 'Rime Deploy' in line or 'Rime Sync user data' in line]
            atomic_write(session/'events.log',('\n'.join(events)+'\n').encode())
            if 'deploy failure' in log or (operation=='deploy' and 'Rime Sync user data' in log) or (operation=='sync' and 'Rime Deploy' in log):raise ValueError('Native deployment failed or overlapped synchronization')
            starts=sum('Notification: 0 deploy start' in l for l in events)
            if starts>1:raise ValueError('Concurrent native maintenance detected')
            start_index=next((i for i,l in enumerate(events) if 'Notification: 0 deploy start' in l),None)
            successes=[i for i,l in enumerate(events) if 'Notification: 0 deploy success' in l]
            if starts==1 and successes and successes[-1]>start_index and sum(('Rime Deploy' if operation=='deploy' else 'Rime Sync user data') in l for l in events)==1:
                if frontend_pid()!=pid:raise ValueError('Frontend restarted during maintenance')
                call('State')
                return {'status':'success','frontend_pid':pid}
        raise ValueError('Deployment timed out; output not acknowledged')
    finally:
        call('SetLogRule','rime=3')

