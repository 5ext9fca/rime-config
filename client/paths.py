"""Configurable first discovery and private, per-platform target memory."""
import json
import os
from pathlib import Path
import platform
import string
import subprocess

from sync import atomic_write, safe_path


def platform_key(system=None, release=None):
    system = system or platform.system()
    release = release or platform.release()
    if system == 'Darwin':
        return 'macos'
    if system == 'Linux':
        return 'wsl' if 'microsoft' in release.lower() or os.environ.get('WSL_DISTRO_NAME') else 'linux'
    raise ValueError('仅支持 WSL、macOS、Linux')


def load_paths(path):
    config = json.loads(Path(path).read_text())
    if not isinstance(config, dict) or set(config) != {'version', 'required_files', 'candidates'} or type(config['version']) is not int or config['version'] != 1:
        raise ValueError('paths.json 需要 version=1、required_files、candidates')
    if not isinstance(config['required_files'], list) or not all(isinstance(v, str) and v for v in config['required_files']):
        raise ValueError('required_files 必须是相对文件名列表')
    for name in config['required_files']:
        # installation.yaml is a discovery marker, not a managed file.
        p = Path(name)
        if p.is_absolute() or '..' in p.parts or str(p) != name or not p.parts:
            raise ValueError('发现标记路径无效')
    if not isinstance(config['candidates'], dict) or set(config['candidates']) != {'wsl', 'macos', 'linux'}:
        raise ValueError('candidates 必须配置 wsl、macos、linux')
    allowed = {'home', 'xdg_config_home', 'windows_appdata'}
    for entries in config['candidates'].values():
        if not isinstance(entries, list) or not all(isinstance(v, str) and v for v in entries):
            raise ValueError('候选路径必须是字符串列表')
        for value in entries:
            for _, field, spec, conversion in string.Formatter().parse(value):
                if field is not None and (field not in allowed or spec or conversion):
                    raise ValueError('路径模板仅支持 home、xdg_config_home、windows_appdata')
    return config


def windows_appdata():
    try:
        value = subprocess.check_output(['cmd.exe', '/c', 'echo', '%APPDATA%'], text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
        if not value or '%' in value:
            return None
        return subprocess.check_output(['wslpath', '-u', value], text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def existing_target(value):
    path = Path(os.path.abspath(Path(value).expanduser()))
    safe_path(path)
    if not path.is_dir():
        raise ValueError(f'实际配置目录不存在或不可访问: {path}；检查挂载，或使用 --rediscover-target/--target')
    return path


def discover(config, system=None):
    system = system or platform_key()
    fields = {'home': str(Path.home()), 'xdg_config_home': os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))}
    found = []
    for template in config['candidates'][system]:
        if '{windows_appdata}' in template and 'windows_appdata' not in fields:
            fields['windows_appdata'] = windows_appdata() if system == 'wsl' else None
        if '{windows_appdata}' in template and not fields.get('windows_appdata'):
            continue
        path = Path(template.format(**fields)).expanduser()
        if not path.is_absolute():
            raise ValueError(f'候选路径展开后必须是绝对路径: {path}')
        if not path.is_dir():
            continue
        safe_path(path)
        if all((path / name).is_file() and not (path / name).is_symlink() for name in config['required_files']):
            if path not in found:
                found.append(path)
    if not found:
        raise ValueError('未发现 Rime 配置目录，请编辑 paths.json 或用 --target 指定现有目录')
    if len(found) > 1:
        raise ValueError('发现多个 Rime 目录，请用 --target 选择：' + ', '.join(map(str, found)))
    return found[0]


def resolve_target(config, memory_path, explicit=None, identity_target=None, rediscover=False, system=None):
    system = system or platform_key()
    memory_path = Path(os.path.abspath(Path(memory_path).expanduser()))
    safe_path(memory_path.parent, memory_path.name)
    memory = json.loads(memory_path.read_text()) if memory_path.exists() else {'version': 1, 'targets': {}}
    if not isinstance(memory, dict) or set(memory) != {'version', 'targets'} or memory['version'] != 1 or not isinstance(memory['targets'], dict):
        raise ValueError('路径记忆文件无效')
    if explicit is not None:
        return existing_target(explicit), 'explicit'
    if not rediscover:
        if system in memory['targets']:
            value = memory['targets'][system]
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise ValueError('记忆路径必须是绝对路径')
            return existing_target(value), 'remembered'
        if identity_target:
            return existing_target(identity_target), 'identity'
    return discover(config, system), 'discovered'


def remember_target(memory_path, target, system=None):
    system = system or platform_key()
    memory_path = Path(os.path.abspath(Path(memory_path).expanduser()))
    safe_path(memory_path.parent, memory_path.name)
    data = json.loads(memory_path.read_text()) if memory_path.exists() else {'version': 1, 'targets': {}}
    if data.get('version') != 1 or not isinstance(data.get('targets'), dict):
        raise ValueError('路径记忆文件无效')
    if data['targets'].get(system) == str(target):
        return
    data['targets'][system] = str(target)
    atomic_write(memory_path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode())
