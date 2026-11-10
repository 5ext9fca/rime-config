from client.storage.filesystem import is_link
from client.core.dictionary_format import component,validate_snapshot

def checked(path, directory=False):
    for parent in (path, *path.parents):
        if is_link(parent):
            raise ValueError(f'个人词典路径不能包含符号链接: {parent}')
    for parent in path.parents:
        if parent.exists() and not parent.is_dir():
            raise ValueError(f'目录被阻挡: {parent}')
    if path.exists() and (not path.is_dir() if directory else not path.is_file()):
        raise ValueError(f'个人词典路径类型冲突: {path}')
    return path


def snapshots(root, devices, names=None):
    result = {}
    checked(root, directory=True)
    for device in devices:
        component(device)
        folder = checked(root / device, directory=True)
        if not folder.exists():
            continue
        paths = sorted(folder.glob('*.userdb.txt')) if names is None else [folder / (name + '.userdb.txt') for name in names]
        for path in paths:
            if not path.exists() and not path.is_symlink():
                continue
            checked(path)
            component(path.name.removesuffix('.userdb.txt'))
            before = path.stat()
            data = path.read_bytes()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise ValueError(f'词典快照正在变化，请等待 Rime 同步完成: {path}')
            validate_snapshot(data, device, path.name.removesuffix('.userdb.txt'))
            result[f'{device}/{path.name}'] = data
    return result


