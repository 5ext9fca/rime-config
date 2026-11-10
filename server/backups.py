"""Persistent device rotation, per-user scope additions and managed backups."""
from contextlib import closing
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time


def validate_backup_policy(policy):
    fields={'enabled','interval_seconds','retention_days','keep_minimum'}
    if (not isinstance(policy,dict) or set(policy)!=fields or type(policy['enabled']) is not bool
            or any(type(policy[k]) is not int or policy[k]<1 for k in fields-{'enabled'})):
        raise ValueError('Invalid backup policy')
    return policy


def file_hash(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def backup_entry(manifest):
    import math
    import re
    if manifest.is_symlink() or not re.fullmatch(r'auto-[0-9]+\.manifest\.json',manifest.name):return None
    try:
        value=json.loads(manifest.read_text())
        prefix=manifest.name.removesuffix('.manifest.json')
        expected={prefix+'.sqlite3',prefix+'.settings.json',prefix+'.scope.json'}
        files=value['files']
        if (value.get('version')!=1 or value.get('status')!='complete' or not isinstance(files,dict)
                or set(files) not in ({prefix+'.sqlite3'},expected)):
            return None
        stamp=value['created_at']
        if type(stamp) not in (int,float) or not math.isfinite(stamp) or stamp<=0:return None
        paths=[manifest.parent/name for name in files]
        if any(p.is_symlink() or not p.is_file() or file_hash(p)!=files[p.name] for p in paths):return None
        return max(stamp,manifest.stat().st_mtime,*(p.stat().st_mtime for p in paths)), paths
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return None


def backups(database, policy, now=None, settings_path=None, force=False):
    from client.storage.file_lock import lock_exclusive
    from client.storage.config_paths import safe_path
    validate_backup_policy(policy)
    if not policy['enabled']:return {'status':'disabled'}
    path=safe_path(Path(database).parent,'backup.lock')
    with path.open('a') as lock:
        try:lock_exclusive(lock)
        except OSError:return {'status':'busy'}
        return _backups_locked(database,policy,now,settings_path,force)


def _backups_locked(database, policy, now=None, settings_path=None, force=False):
    """Publish a verified complete backup set, then prune only complete sets."""
    validate_backup_policy(policy)
    if not policy['enabled']:return {'status':'disabled'}
    from client.storage.filesystem import atomic_write
    now=time.time() if now is None else now
    root=Path(database).parent/'backups'
    if root.is_symlink():raise ValueError('Backup directory is a symlink')
    root.mkdir(mode=0o700,exist_ok=True)
    with closing(sqlite3.connect(database,timeout=20)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT timestamp FROM maintenance WHERE key='backup'").fetchone()
        required_format=2 if settings_path is not None else 1
        saved_format=db.execute("SELECT timestamp FROM maintenance WHERE key='backup-format'").fetchone()
        if not force and row and saved_format and saved_format[0]>=required_format and now-row[0]<policy['interval_seconds']:
            return {'status':'not-due','last_success_at':row[0]}
        running=db.execute("SELECT timestamp FROM maintenance WHERE key='backup-running'").fetchone()
        if running and now-running[0]<600:return {'status':'busy'}
        db.execute("INSERT OR REPLACE INTO maintenance VALUES ('backup-running',?)",(now,))
    temp=root/('auto-'+str(time.time_ns())+'.tmp')
    try:
        settings_data=scope_data=None
        if settings_path is not None:
            settings_path=Path(settings_path)
            settings_data=settings_path.read_bytes()
            settings=json.loads(settings_data)
            scope_path=(settings_path.parent/settings['scope']).resolve()
            from client.core.scope import load_scope
            load_scope(scope_path)
            scope_data=scope_path.read_bytes()
        # Restrict permissions before SQLite writes any private content.
        fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        deadline=time.monotonic()+300
        def progress(status,remaining,total):
            if time.monotonic()>deadline:raise TimeoutError('Backup exceeded time budget')
        with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(temp)) as dest:
            source.backup(dest,pages=256,progress=progress)
            if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup integrity failure')
        if settings_path is not None and (settings_path.read_bytes()!=settings_data or scope_path.read_bytes()!=scope_data):
            raise ValueError('Server configuration changed during backup')
        with temp.open('rb') as stream:os.fsync(stream.fileno())
        final=temp.with_suffix('.sqlite3');os.replace(temp,final)
        paths=[final]
        if settings_data is not None:
            for suffix,data in (('.settings.json',settings_data),('.scope.json',scope_data)):
                p=temp.with_suffix(suffix);atomic_write(p,data);paths.append(p)
        manifest=temp.with_suffix('.manifest.json')
        atomic_write(manifest,json.dumps({'version':1,'status':'complete','created_at':now,
            'files':{p.name:file_hash(p) for p in paths}},indent=2).encode())
        if backup_entry(manifest) is None:raise ValueError('Published backup verification failed')
        entries=[]
        for p in root.glob('auto-*.manifest.json'):
            entry=backup_entry(p)
            if entry is not None:entries.append((entry[0],p,entry[1]))
        entries.sort(key=lambda item:(item[0],item[1].name),reverse=True)
        removed=0
        for stamp,p,files in entries[policy['keep_minimum']:]:
            if stamp >= now-policy['retention_days']*86400 or p==manifest:continue
            for file in files:file.unlink()
            p.unlink();removed+=1
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("INSERT OR REPLACE INTO maintenance VALUES ('backup',?)",(now,))
            db.execute("INSERT OR REPLACE INTO maintenance VALUES ('backup-format',?)",(required_format,))
            db.execute("DELETE FROM maintenance WHERE key='backup-running' AND timestamp=?",(now,))
        return {'status':'success','manifest':manifest.name,'last_success_at':now,'removed_sets':removed}
    except BaseException:
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("DELETE FROM maintenance WHERE key='backup-running' AND timestamp=?",(now,))
        raise
    finally:
        temp.unlink(missing_ok=True)
