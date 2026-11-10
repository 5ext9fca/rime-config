"""Nonblocking process locks; closing the stream releases the lock on both OSes."""
import os


def lock_exclusive(stream):
    if os.name == 'nt':
        import msvcrt
        # Always lock the same byte, even when the file was opened in append mode.
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
