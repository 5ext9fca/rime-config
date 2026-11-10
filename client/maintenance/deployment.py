"""Deploy changed resources with durable retries and explicit completion evidence."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
from client.storage.filesystem import atomic_write
from client.storage.config_paths import safe_path
from client.storage.file_lock import lock_exclusive


def execute_platform(platform,target,policy,session,idle_provider=None):
    argv=policy['commands'].get(platform)
    if argv:
        receipt=session/'receipt.json'
        subprocess.run(argv,check=True,timeout=240,env=dict(os.environ,RIME_USER_DIR=str(target),
            RIME_DEPLOY_RECEIPT=str(receipt),RIME_DEPLOY_IDLE_SECONDS=str(policy['idle_seconds'])))
        evidence=json.loads(safe_path(session,'receipt.json').read_text())
        if evidence.get('status') not in ('success','deferred'):raise ValueError('Missing deployment completion receipt')
        return evidence
    if platform=='windows':
        from client.platforms.windows.weasel_deploy import run
        return run(target,policy,session,idle_provider=idle_provider)
    if platform=='macos':
        from client.platforms.macos.squirrel_maintenance import run
        return run(target,policy['idle_seconds'],session,'deploy',idle_provider=idle_provider)
    if platform!='linux':
        raise ValueError('Unsupported deployment platform')
    from client.platforms.linux.fcitx_maintenance import run
    return run(target,policy['idle_seconds'],session,'deploy',idle_provider=idle_provider)


def fingerprint(target,names):
    values=[]
    for name in sorted(set(names)):
        p=safe_path(target,name)
        values.append([name,hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None])
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def deploy(target,names,state,policy,executor,dry_run=False,now=None):
    if not policy['enabled'] or not names:return 'disabled'
    target=Path(target);state=Path(state);safe_path(state)
    value=fingerprint(target,names)
    if dry_run:return 'planned'
    state.mkdir(parents=True,exist_ok=True,mode=0o700)
    with safe_path(state,'lock').open('a') as lock:
        lock_exclusive(lock)
        path=safe_path(state,'deployment.json');record=json.loads(path.read_text()) if path.exists() else {}
        if record.get('target',str(target))!=str(target):raise ValueError('Deployment state target mismatch')
        if record.get('fingerprint')==value and record.get('status')=='success':return 'unchanged'
        now=time.time() if now is None else now
        if now<record.get('retry_at',0):return 'deferred'
        session=state/'runs'/uuid.uuid4().hex;session.mkdir(parents=True,mode=0o700)
        record={'target':str(target),'status':'running','retry_at':now+policy['retry_seconds'],'session':session.name,'requested_fingerprint':value}
        atomic_write(path,json.dumps(record).encode())
        phase='frontend'
        try:
            result=executor.deploy(target,policy,session)
            atomic_write(session/'receipt.json',json.dumps(result).encode())
            phase='resource-recheck'
            actual=fingerprint(target,names) if result['status']=='success' else value
            if result['status']=='success' and actual!=value:raise ValueError('Resources changed during deployment')
            record.update(result)
            if result['status']=='success':record.update(fingerprint=value,completed_at=time.time())
            else:record['retry_at']=now+min(30,policy['retry_seconds'])
            atomic_write(path,json.dumps(record).encode());return result['status']
        except BaseException as exc:
            record.update(status='failed',failure_phase=phase,error_type=type(exc).__name__)
            atomic_write(path,json.dumps(record).encode());raise
