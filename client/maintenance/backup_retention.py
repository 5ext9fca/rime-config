"""Prune completed managed backups under their writers' nonblocking locks."""
import contextlib
import json
import math
from pathlib import Path
import re
import shutil
import time
from client.storage.file_lock import lock_exclusive
from client.storage.filesystem import atomic_write, is_link
from client.storage.config_paths import safe_path

DEFAULT={'enabled':False,'retention_days':30,'keep_minimum':7,'interval_seconds':86400}
NAME=re.compile(r'(?:\d{8}-\d{6}-[0-9a-f]{8}|[0-9a-f]{32}|\d{16,22})(?:\.json)?$')
# Only these groups are owned by this client. No recursive discovery of backups.
GROUPS=(
    ('configuration','backups',('lock',),'journal'),
    ('remote','remote/backups',('remote/lock',),'marker'),
    ('remote-dictionaries','remote/dictionary-apply/backups',('remote/lock','remote/dictionary-apply/lock'),'marker'),
    ('dictionaries','dictionaries/backups',('dictionaries/lock',),'marker'),
    ('third-party','third-party/backups',('third-party/lock',),'journal'),
    ('theme','theme/backups',('theme/lock',),'marker'),
    ('frontend-preferences','frontend-preferences/backups',('frontend-preferences/lock',),'marker'),
    ('native','native-all/runs',('native-all/native.lock',),'native'),
    ('scope','native-all/scope-backups',('native-all/scope.lock',),'marker'),
)


def completed(path, now=None):
    """Called only after successful publication, while the writer lock is held."""
    path=Path(path)
    if not path.exists():return
    safe_path(path.parent,path.name) if path.is_file() else safe_path(path)
    stamp=time.time() if now is None else now
    record={'version':1,'name':path.name,'completed_at':stamp}
    atomic_write(safe_path(path.parent/'.completed',path.name+'.json'),json.dumps(record).encode())


def observe(path, kind):
    if not NAME.fullmatch(path.name) or is_link(path):return None
    # Reject every link/reparse point, including within a candidate tree.
    entries=[path]+list(path.rglob('*')) if path.is_dir() else [path]
    if any(is_link(p) or not (p.is_file() or p.is_dir()) for p in entries):return None
    newest=max(p.stat().st_mtime for p in entries)
    marker=path.parent/'.completed'/(path.name+'.json')
    try:
        if marker.exists():
            safe_path(marker.parent,marker.name)
            data=json.loads(marker.read_text())
            if data.get('version')!=1 or data.get('name')!=path.name:return None
            stamp=data.get('completed_at')
        elif kind=='journal' and path.is_dir():
            journal=json.loads((path/'journal.json').read_text())
            if journal.get('status')!='applied':return None
            stamp=(path/'journal.json').stat().st_mtime
        elif kind=='native' and path.is_dir():
            result=json.loads((path/'result.json').read_text())
            if result.get('status')!='success':return None
            stamp=result.get('completed_at')
        else:return None
        if type(stamp) not in (int,float) or not math.isfinite(stamp) or stamp<=0:return None
        return max(stamp,newest)
    except (OSError,ValueError,TypeError,AttributeError):return None


def protected(state, category):
    if category.startswith('remote'):
        # Conflicts may refer to older content; never prune until resolved.
        if (state/'remote/pending.json').exists():return True
        if (state/'remote/conflicts.json').exists() and not (state/'remote/schedule.json').exists():return True
        schedule=state/'remote/schedule.json'
        if schedule.exists() and json.loads(schedule.read_text()).get('error'):return True
    if category=='native':
        schedule=state/'native-all/schedule.json'
        latest=state/'native-all/latest.json'
        if schedule.exists() and json.loads(schedule.read_text()).get('unsafe'):return True
        if latest.exists() and json.loads(latest.read_text()).get('status') in ('failed','running'):return True
    return False


def clean(state,policy,dry_run=False,now=None,force=False):
    if not policy['enabled']:return {'status':'disabled','deleted':0,'planned':[],'skipped':[]}
    state=Path(state);safe_path(state)
    now=time.time() if now is None else now
    report={'status':'planned' if dry_run else 'success','deleted':0,'planned':[],'skipped':[]}
    if not state.exists():return report
    schedule=safe_path(state,'backup-retention.json')
    with contextlib.ExitStack() as outer:
        if not dry_run:
            try:lock_exclusive(outer.enter_context(safe_path(state,'backup-retention.lock').open('a')))
            except OSError:return dict(report,status='busy')
            previous=json.loads(schedule.read_text()) if schedule.exists() else {}
            if not force and previous.get('policy')==policy and now<previous.get('next_run',0):return dict(report,status='not-due')
        for category,relative,locks,kind in GROUPS:
            group=state/relative
            if not group.exists():continue
            try:
                safe_path(group)
                with contextlib.ExitStack() as stack:
                    # Dry preview neither creates nor acquires writer lock files.
                    if not dry_run:
                        for name in locks:
                            p=state/name
                            safe_path(p.parent,p.name)
                            lock_exclusive(stack.enter_context(p.open('a')))
                    if protected(state,category):
                        report['skipped'].append(category+':pending-or-failed');continue
                    candidates=[]
                    for path in group.iterdir():
                        stamp=observe(path,kind)
                        if stamp is not None:candidates.append((stamp,path))
                    candidates.sort(key=lambda item:(item[0],item[1].name),reverse=True)
                    for stamp,path in candidates[policy['keep_minimum']:]:
                        if stamp>=now-policy['retention_days']*86400:continue
                        if category=='native' and (state/'native-all/latest.json').exists():
                            if json.loads((path/'result.json').read_text())==json.loads((state/'native-all/latest.json').read_text()):continue
                        report['planned'].append(str(path.relative_to(state)))
                        if dry_run:continue
                        # Reobserve immediately before removal under the same locks.
                        if observe(path,kind)!=stamp:continue
                        if path.is_dir():shutil.rmtree(path)
                        else:path.unlink()
                        marker=path.parent/'.completed'/(path.name+'.json')
                        safe_path(marker.parent,marker.name);marker.unlink(missing_ok=True)
                        report['deleted']+=1
            except (OSError,ValueError,TypeError):
                report['skipped'].append(category+':busy-or-invalid')
        if not dry_run:
            # Retry skipped groups sooner without postponing clean groups forever.
            delay=min(300,policy['interval_seconds']) if report['skipped'] else policy['interval_seconds']
            atomic_write(schedule,json.dumps({'policy':policy,'next_run':now+delay,'last_run':now,**report}).encode())
    return report
