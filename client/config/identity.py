"""Initialize and load a private, project-local device identity."""
import getpass
import json
import os
from pathlib import Path
import re
import sys

from client.core.dictionary_format import component
from client.storage.filesystem import atomic_write
from client.storage.config_paths import safe_path


def valid_token(token):
    if not isinstance(token, str) or len(token) < 32 or not token.isascii() or not all(33 <= ord(c) <= 126 for c in token) or token.startswith('REPLACE_'):
        raise ValueError('设备令牌须为服务端配置的至少 32 字符令牌，不能使用占位符')
    return token


def load_identity(path):
    path = Path(os.path.abspath(Path(path).expanduser()))
    safe_path(path.parent, path.name)
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or set(value) != {'version', 'installation_id', 'token', 'target'}:
        raise ValueError('设备配置字段须为 version、installation_id、token、target；可使用 --init 初始化')
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('设备配置要求 version=1')
    if not isinstance(value['installation_id'], str):
        raise ValueError('installation_id 必须是字符串')
    component(value['installation_id'])
    valid_token(value['token'])
    if not isinstance(value['target'], str) or not Path(value['target']).is_absolute():
        raise ValueError('设备配置 target 必须为绝对路径')
    return value


def installation_id(target):
    path = Path(target) / 'installation.yaml'
    if not path.exists():
        return None
    # Rime writes a simple top-level scalar. Avoid parsing unrelated YAML fields.
    matches = [line for line in path.read_text(encoding='utf-8-sig').splitlines() if line.startswith('installation_id:')]
    if len(matches) != 1:
        raise ValueError('installation.yaml 的 installation_id 缺失或重复')
    match = re.fullmatch(r'''installation_id:[ \t]*(?:"([^"\\]*)"|'([^']*)'|([A-Za-z0-9_.-]+))[ \t]*(?:#.*)?''', matches[0])
    if not match:
        raise ValueError('无法读取 installation_id；请使用 Rime 生成的普通字符串格式')
    value = next(v for v in match.groups() if v is not None)
    component(value)
    return value


def initialize(path, target, device_id=None, token_stdin=False):
    path = Path(os.path.abspath(Path(path).expanduser()))
    target = Path(os.path.abspath(Path(target).expanduser()))
    old = load_identity(path)
    detected = installation_id(target)
    selected = device_id or detected or old.get('installation_id')
    if not selected:
        if not sys.stdin.isatty():
            raise ValueError('无法检测安装 ID，请使用 --device-id 指定')
        selected = input('Rime installation_id: ').strip()
    component(selected)
    if detected and selected != detected:
        raise ValueError('--device-id 与目标 Rime installation.yaml 不一致')
    if token_stdin:
        token = sys.stdin.readline(8193).rstrip('\r\n')
        if len(token) > 8192:
            raise ValueError('设备令牌过长')
    elif sys.stdin.isatty():
        token = getpass.getpass('设备令牌（隐藏输入' + ('，留空保留已有令牌' if old else '') + '）: ')
        if not token and old:
            token = old['token']
    elif old and old['installation_id'] == selected:
        token = old['token']
    else:
        raise ValueError('非交互初始化请用 --token-stdin 从标准输入读取令牌')
    if old and old['installation_id'] != selected and token == old['token']:
        raise ValueError('安装 ID 已变化，请提供该设备对应的新令牌')
    valid_token(token)
    value = {'version': 1, 'installation_id': selected, 'token': token, 'target': str(target)}
    safe_path(path.parent, path.name)
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())
    os.chmod(path, 0o600)
    print(f'设备配置已保存: {path}\n安装 ID: {selected}\n目标: {target}\n令牌已保存，未输出。', flush=True)
    return value
