"""Crash-safe client-generated token rotation; no device registration."""
import hashlib
import json
from pathlib import Path
import secrets
import time
from client.storage.file_lock import lock_exclusive
from client.config.identity import load_identity
from client.storage.filesystem import atomic_write
from client.storage.config_paths import safe_path


def refresh(config, identity_path, state, transport, now=None):
    interval=config.get('token_refresh_seconds',0)
    if not interval:return
    now=time.time() if now is None else now
    state=Path(state);safe_path(state);state.mkdir(parents=True,exist_ok=True,mode=0o700)
    with safe_path(state,'lock').open('a') as lock:
        lock_exclusive(lock)
        identity=load_identity(identity_path)
        if not identity:raise ValueError('Automatic rotation requires a private device identity')
        binding=[config['url'],identity['installation_id']]
        path=safe_path(state,'rotation.json')
        record=json.loads(path.read_text()) if path.exists() else {}
        if record and record.get('binding')!=binding:raise ValueError('Token state belongs to a different server or device')
        if not record.get('pending') and now<record.get('completed_at',0)+interval:
            config['token']=identity['token'];return
        pending=record.get('pending')
        if not pending:
            pending={'old_hash':hashlib.sha256(identity['token'].encode()).hexdigest(),'token':secrets.token_urlsafe(48)}
            atomic_write(path,json.dumps({'binding':binding,'pending':pending}).encode())
        if identity['token']!=pending['token']:
            if hashlib.sha256(identity['token'].encode()).hexdigest()!=pending['old_hash']:
                raise ValueError('Device token changed while rotation was pending')
            request=dict(config,token=identity['token'],url=config['url'].removesuffix('/state')+'/token/refresh')
            result=transport(request,'POST',{'token':pending['token']})
            if result!={'status':'rotated'}:raise ValueError('Invalid rotation receipt')
            # Do not overwrite a concurrently reinitialized identity.
            if load_identity(identity_path)!=identity:raise ValueError('Device identity changed during rotation')
            identity['token']=pending['token']
            atomic_write(Path(identity_path),(json.dumps(identity,indent=2)+'\n').encode())
        config['token']=identity['token']
        atomic_write(path,json.dumps({'binding':binding,'completed_at':now}).encode())
