"""Bounded application-owned daily logs; never prune state or backups."""
from datetime import datetime
from pathlib import Path
import re
import time
import threading
import uuid
from client.storage.config_paths import safe_path
from client.storage.filesystem import atomic_write

PATTERN=re.compile(r'rime-\d{8}-[0-9a-f]{12}\.log$')


def clean(root,policy,now=None):
    if not policy['enabled']:return 0
    now=time.time() if now is None else now
    root=Path(root);safe_path(root)
    if not root.exists():return 0
    cutoff=now-policy['retention_days']*86400;count=0
    for p in root.iterdir():
        if PATTERN.fullmatch(p.name) and not p.is_symlink() and p.is_file() and p.stat().st_mtime<cutoff:
            p.unlink();count+=1
    return count


class DailyLog:
    encoding='utf-8'
    def __init__(self,root,policy):
        self.root=Path(root);self.policy=policy;self.path=None;self.day=None;self.last_clean=0;self.lock=threading.RLock()
        safe_path(self.root);self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
    def write(self,text):
        with self.lock:
            if time.time()-self.last_clean>3600:
                clean(self.root,self.policy);self.last_clean=time.time()
            return self._write(text)
    def _write(self,text):
        if not text:return 0
        day=datetime.now().strftime('%Y%m%d')
        if self.path is None or self.day!=day or not self.path.exists() or self.path.stat().st_size>=self.policy['max_file_bytes']:
            self.path=self.root/f'rime-{day}-{uuid.uuid4().hex[:12]}.log';self.day=day
        safe_path(self.root,self.path.name)
        # Open each write so pruning never leaves the process on a deleted inode.
        import os
        if not self.path.exists():atomic_write(self.path,b'')
        fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        with os.fdopen(fd,'a',encoding='utf-8') as stream:stream.write(text)
        return len(text)
    def flush(self):pass
    def isatty(self):return False
