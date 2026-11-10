"""Independent backup scheduler. No HTTP traffic or network access required."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.backups import backups, validate_backup_policy
from client.storage.filesystem import atomic_write


def settings(path):
    path=Path(path)
    value=json.loads(path.read_text())
    policy=validate_backup_policy(value.get('backups',{'enabled':False,'interval_seconds':86400,'retention_days':30,'keep_minimum':7}))
    return (path.parent/value['database']).resolve(),policy


def tick(path,force=False):
    database,policy=settings(path)
    heartbeat=database.parent/'backup-worker.json'
    if not database.is_file():raise ValueError('Application database is not initialized')
    try:
        result=backups(database,policy,settings_path=path,force=force)
        with closing(sqlite3.connect(database)) as db:
            row=db.execute("SELECT timestamp FROM maintenance WHERE key='backup'").fetchone()
        result.update(checked_at=time.time(),last_success_at=row[0] if row else 0)
        atomic_write(heartbeat,json.dumps(result).encode())
        return result
    except Exception as exc:
        # Never log settings content, tokens, vocabulary or exception payloads.
        atomic_write(heartbeat,json.dumps({'status':'failed','checked_at':time.time(),'error_type':type(exc).__name__}).encode())
        raise


def healthy(path,poll_seconds):
    database,policy=settings(path)
    value=json.loads((database.parent/'backup-worker.json').read_text())
    return (value.get('status')!='failed' and time.time()-value['checked_at']<=max(180,poll_seconds*3)
            and (not policy['enabled'] or value.get('last_success_at',0)>0))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings',type=Path,default=Path(os.environ.get('RIME_SETTINGS','/config/settings.json')))
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--force',action='store_true',help='创建一份新备份；仍遵守并发锁和保留策略')
    parser.add_argument('--health',action='store_true')
    parser.add_argument('--poll-seconds',type=int,default=60)
    args=parser.parse_args()
    if args.poll_seconds<1 or (args.force and not args.once):parser.error('--force requires --once; poll interval must be positive')
    if args.health:
        try:return 0 if healthy(args.settings,args.poll_seconds) else 1
        except (OSError,ValueError,KeyError):return 1
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    while not stop.is_set():
        try:
            result=tick(args.settings,args.force)
            if args.once or result['status']=='success':print(json.dumps(result),flush=True)
            if args.once:return 0
        except Exception as exc:
            print(json.dumps({'status':'failed','error_type':type(exc).__name__}),flush=True)
            if args.once:return 1
        stop.wait(args.poll_seconds)
    return 0


if __name__=='__main__':sys.exit(main())
