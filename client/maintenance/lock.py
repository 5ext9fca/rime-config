"""Shared frontend maintenance exclusion, independent of any frontend."""
import contextlib
import hashlib
from pathlib import Path
from client.storage.config_paths import safe_path
from client.storage.file_lock import lock_exclusive

@contextlib.contextmanager
def maintenance_lock(target):
    root=Path.home()/'.local/state/rime-config/frontend-locks'
    safe_path(root);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    key=hashlib.sha256(str(Path(target).resolve()).encode()).hexdigest()
    with safe_path(root,key+'.lock').open('a') as stream:
        lock_exclusive(stream)
        yield

