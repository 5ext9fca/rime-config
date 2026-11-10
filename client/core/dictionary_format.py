import re
from client.storage.config_paths import windows_reserved

def component(value):
    if (not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*', value) or '..' in value
            or value.endswith('.') or windows_reserved(value)):
        raise ValueError(f'无效的设备或词典名称: {value}')
    return value


def validate_snapshot(data, device, name):
    component(device)
    component(name)
    path = f"{device}/{name}.userdb.txt"
    # Require snapshot metadata: plain exported phrase lists are not snapshots.
    header = data.decode('utf-8-sig').splitlines()
    if '#@/db_type\tuserdb' not in header:
        raise ValueError(f'不是 Rime userdb 快照: {path}')
    metadata = dict(line[2:].split('\t', 1) for line in header if line.startswith('#@/') and '\t' in line)
    # Match librime UserDbHelper::GetDbName (strip the LAST .userdb suffix).
    # A first-split would accept a snapshot that native restore opens under a
    # different dictionary name, bypassing the declared scope.
    db_name = metadata.get('/db_name', '').rsplit('.userdb', 1)[0]
    if metadata.get('/db_type') != 'userdb':
        raise ValueError(f'不是 Rime userdb 快照: {path}')
    if db_name != name:
        raise ValueError(f'快照词典名称与文件名不一致: {path}')
    if metadata.get('/user_id') != device:
        raise ValueError(f'快照设备标识与目录不一致: {path}')


