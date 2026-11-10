"""Text-only cloud bundle, installed separately from the Rime user directory."""
import base64
import configparser
import hashlib
import json
import os
from pathlib import Path
import struct
from client.storage.file_lock import lock_exclusive
from client.storage.filesystem import atomic_write
from client.storage.config_paths import safe_path

BUNDLE='fcitx5/theme.json'
OPTIONS={'Vertical Candidate List','Font','Theme','DarkTheme','UseDarkTheme','UseAccentColor'}
FILES={f'{theme}/{name}' for theme in ('hx-light','hx-dark') for name in ('theme.conf','panel.png','highlight.png','blur.png')}


def decode(data):
    value=json.loads(data)
    if not isinstance(value,dict) or set(value)!={'version','settings','files'} or value['version']!=1:
        raise ValueError('Invalid theme bundle')
    if set(value['settings'])!=OPTIONS or set(value['files'])!=FILES:
        raise ValueError('Invalid theme scope')
    for key,item in value['settings'].items():
        if not isinstance(item,str) or not item or any(ord(c)<32 for c in item):raise ValueError('Invalid theme setting')
    if value['settings']['Theme']!='hx-light' or value['settings']['DarkTheme']!='hx-dark':raise ValueError('Invalid theme name')
    files={}
    for name,encoded in value['files'].items():
        raw=base64.b64decode(encoded,validate=True)
        if len(raw)>2*1024*1024:raise ValueError('Theme asset too large')
        if name.endswith('.png'):
            if not raw.startswith(b'\x89PNG\r\n\x1a\n') or len(raw)<24:raise ValueError('Invalid PNG')
            if any(n<1 or n>1024 for n in struct.unpack('>II',raw[16:24])):raise ValueError('PNG dimensions exceed limit')
        else:
            c=configparser.ConfigParser(interpolation=None);c.read_string(raw.decode('utf-8'))
            for section in c:
                for key,v in c[section].items():
                    if key in ('image','blurmask','overlay') and v and v not in ('panel.png','highlight.png','blur.png'):
                        raise ValueError('External theme resource rejected')
        files[name]=raw
    return value['settings'],files


def apply(source,state,dry_run=False,executor=None,config_home=None,data_home=None):
    path=safe_path(Path(source),BUNDLE)
    if not path.exists():raise ValueError('Theme bundle missing; generate it first')
    data=path.read_bytes();settings,files=decode(data)
    config_home=Path(config_home or os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')
    data_home=Path(data_home or os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')
    if not config_home.is_absolute() or not data_home.is_absolute():raise ValueError('XDG paths must be absolute')
    state=Path(state);safe_path(state)
    if not dry_run:state.mkdir(parents=True,exist_ok=True,mode=0o700)
    import contextlib
    with contextlib.ExitStack() as stack:
        if not dry_run:lock_exclusive(stack.enter_context(safe_path(state,'lock').open('a')))
        dest=safe_path(config_home/'fcitx5/conf','classicui.conf')
        original=dest.read_text() if dest.exists() else ''
        pending=dict(settings);lines=[]
        for line in original.splitlines():
            key=line.split('=',1)[0]
            if key in settings:
                if key in pending:lines.append(key+'='+pending.pop(key))
            else:lines.append(line)
        lines.extend(k+'='+v for k,v in pending.items())
        writes={dest:('\n'.join(lines)+'\n').encode()}
        writes.update({safe_path(data_home/'fcitx5/themes',n):v for n,v in files.items()})
        before={p:p.read_bytes() if p.exists() else None for p in writes}
        changed={p:v for p,v in writes.items() if before[p]!=v}
        receipt=safe_path(state,'receipt.json')
        fingerprint=hashlib.sha256(data).hexdigest()
        old=json.loads(receipt.read_text()) if receipt.exists() else {}
        if not changed and old.get('fingerprint')==fingerprint:return 'unchanged'
        if dry_run:return 'planned'
        import time
        backup=state/'backups'/str(time.time_ns())
        journal=[]
        for index,p in enumerate(changed):
            item={'path':str(p),'backup':str(index) if before[p] is not None else None}
            if before[p] is not None:atomic_write(backup/str(index),before[p])
            journal.append(item)
        atomic_write(backup/'manifest.json',json.dumps(journal).encode())
        if path.read_bytes()!=data:raise ValueError('Theme source changed during application')
        done=[]
        try:
            for p,v in changed.items():
                if (p.read_bytes() if p.exists() else None)!=before[p]:raise ValueError('Concurrent theme edit')
                atomic_write(p,v);done.append(p)
            if executor is None:
                from client.platforms.platform_execution import get_executor
                executor=get_executor()
            executor.reload_theme()
            atomic_write(receipt,json.dumps({'fingerprint':fingerprint}).encode())
        except BaseException:
            for p in reversed(done):
                if before[p] is None:p.unlink(missing_ok=True)
                else:atomic_write(p,before[p])
            raise
        from client.maintenance.backup_retention import completed as complete_backup
        complete_backup(backup)
        return 'applied'
