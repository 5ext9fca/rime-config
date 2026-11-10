"""Atomic file writes and link checks; independent of CLI and workflow."""
import os
import stat
import tempfile


def is_link(path):
    return path.is_symlink() or (os.name == 'nt' and path.exists() and
            bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT))


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.rime-sync-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            if os.name == 'nt':
                from client.platforms.windows.windows_security import protect_file
                protect_file(temporary)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


