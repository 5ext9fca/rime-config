"""Project-owned scope shared by configuration apply and dictionary exchange."""
import json
from pathlib import Path

from client.storage.config_paths import relative_name
from client.core.dictionary_format import component


def load_scope(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict) or set(value) != {'version', 'configuration', 'dictionaries'}:
        raise ValueError('同步范围必须包含 version、configuration、dictionaries')
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('不支持的同步范围版本（要求 version=1）')
    for section, field in (('configuration', 'files'), ('dictionaries', 'names')):
        part = value[section]
        if not isinstance(part, dict) or set(part) != {'enabled', field}:
            raise ValueError(f'{section} 必须包含 enabled 和 {field}')
        if type(part['enabled']) is not bool:
            raise ValueError(f'{section}.enabled 必须为布尔值')
        items = part[field]
        if not isinstance(items, list) or not all(isinstance(n, str) and n for n in items):
            raise ValueError(f'{section}.{field} 必须是字符串列表')
        if len({n.casefold() for n in items}) != len(items):
            raise ValueError(f'{section}.{field} 不能包含重复或大小写冲突项')
        for name in items:
            if section == 'configuration':
                relative_name(name)
                relative_name(name.casefold())
                if any(c in name for c in '*?[]\\'):
                    raise ValueError('配置范围必须为明确的相对文件路径，不支持通配符')
            else:
                component(name)
                if '.userdb' in name.casefold():
                    raise ValueError('词典名称不应包含 .userdb 后缀')
    return value
