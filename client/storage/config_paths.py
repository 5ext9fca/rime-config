"""Configuration-specific path policy; not a generic dictionary path validator."""
from pathlib import Path
from client.storage.filesystem import is_link
RESERVED = {'build', 'sync', 'installation.yaml', 'user.yaml'}
WINDOWS_DEVICES = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} | {
    prefix + suffix for prefix in ('COM', 'LPT') for suffix in '123456789¹²³'}


def windows_reserved(name):
    return name.split('.')[0].rstrip(' ').upper() in WINDOWS_DEVICES


def relative_name(name):
    p = Path(name)
    if (not name or p.is_absolute() or p.drive or '..' in p.parts
            or p.as_posix() != name or '\\' in name or ':' in name):
        raise ValueError(f'不安全的相对路径: {name}')
    # Reject Win32 aliases/streams on every platform so shared scopes stay portable.
    if any(part.endswith((' ', '.')) or windows_reserved(part)
           or any(ord(c) < 32 or c in '<>"|?*' for c in part) for part in p.parts):
        raise ValueError(f'不安全的相对路径: {name}')
    if any(part in RESERVED or '.userdb' in part or part.endswith('.gram') for part in p.parts):
        raise ValueError(f'拒绝管理运行时数据: {name}')
    return p


def safe_path(root, name=''):
    path = root
    # Check ancestors as well: never traverse a destination symlink.
    for p in reversed((root, *root.parents)):
        if is_link(p):
            raise ValueError(f'拒绝符号链接: {p}')
        if p.exists() and not p.is_dir():
            raise ValueError(f'目录被文件阻挡: {p}')
    if name:
        parts = relative_name(name).parts
        for i, part in enumerate(parts):
            path /= part
            if is_link(path):
                raise ValueError(f'拒绝符号链接: {path}')
            if path.exists() and (not path.is_file() if i == len(parts) - 1 else not path.is_dir()):
                raise ValueError(f'路径类型冲突: {path}')
    return path


