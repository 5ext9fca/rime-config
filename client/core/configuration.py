#!/usr/bin/env python3
"""Apply the repository's authoritative config to a local Rime directory."""
import argparse
import contextlib
from client.storage.file_lock import lock_exclusive
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

from client.storage.filesystem import atomic_write, is_link
from client.storage.config_paths import safe_path, relative_name, windows_reserved

from client.project import SOURCE





def default_target(system=None, release=None):
    from client.config.paths import discover, load_paths, platform_key
    return discover(load_paths(SOURCE.parent / 'paths.json'), platform_key(system, release))










def snapshot(source, includes=None, allow_empty=False):
    safe_path(source)
    if not source.is_dir():
        raise ValueError(f'配置源不存在: {source}')
    result = {}
    paths = sorted(source.rglob('*')) if includes is None else [source / name for name in includes]
    for p in paths:
        if includes is not None:
            safe_path(source, p.relative_to(source).as_posix())
            if not p.exists():
                continue
        if is_link(p):
            raise ValueError(f'配置源不能包含符号链接: {p}')
        if p.is_dir():
            continue
        if not p.is_file():
            raise ValueError(f'不支持的文件类型: {p}')
        name = p.relative_to(source).as_posix()
        relative_name(name)
        result[name] = p.read_bytes()
    if not result and not allow_empty:
        raise ValueError('配置源为空，拒绝应用以防止意外清空')
    return result


def observe_configuration(source, target, state, includes=None, allow_empty=False):
    """Read-only observations for the shared planner; no plan replay API."""
    from client.core.plans import configuration
    from client.config.paths import platform_key
    source, target, state = (Path(os.path.abspath(p)) for p in (source, target, state))
    roots = (source, target, state)
    for i, a in enumerate(roots):
        for b in roots[i + 1:]:
            if a == b or a in b.parents or b in a.parents:
                raise ValueError('源目录、目标目录和状态目录不能重叠')
    safe_path(target)
    safe_path(state)
    files = snapshot(source, includes, allow_empty)
    manifest_path = safe_path(state, 'manifest.json')
    old = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    if old and (old.get('target') != str(target) or old.get('source') != str(source)):
        raise ValueError('状态目录属于不同源或目标，请另选 --state-dir')
    managed = old.get('files', [])
    if not isinstance(managed, list) or not all(isinstance(n, str) for n in managed):
        raise ValueError('状态清单无效')
    if includes is not None:
        managed = [name for name in managed if name in includes]
    destinations = {}
    for name in sorted(set(files) | set(managed)):
        dest = safe_path(target, name)
        destinations[name] = dest.read_bytes() if dest.exists() else None
    return files, old, configuration(platform_key(), files, destinations, managed)


def recheck_configuration(plan, source, target):
    from client.core.plans import validate, digest
    validate(plan, 'configuration-plan')
    for item in plan['steps']:
        for root, field in ((source, 'after'), (target, 'before')):
            path = safe_path(root, item['id'])
            if digest(path.read_bytes() if path.exists() else None) != item['details'][field]:
                raise ValueError('配置计划已过期，保留并发修改并在下一轮重建计划')


def apply(source, target, state, dry_run=False, includes=None, allow_empty=False):
    source, target, state = (Path(os.path.abspath(p)) for p in (source, target, state))
    roots = (source, target, state)
    for i, a in enumerate(roots):
        for b in roots[i + 1:]:
            if a == b or a in b.parents or b in a.parents:
                raise ValueError('源目录、目标目录和状态目录不能重叠')
    safe_path(target)
    safe_path(state)
    if not dry_run:
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with contextlib.ExitStack() as stack:
        # Dry-run is strictly read-only. Actual writers serialize per target.
        if not dry_run:
            lock_path = safe_path(state, 'lock')
            lock = stack.enter_context(lock_path.open('a'))
            lock_exclusive(lock)
        files, old, plan = observe_configuration(source, target, state, includes, allow_empty)
        manifest_path = safe_path(state, 'manifest.json')
        operations = [(item['action'], item['id']) for item in plan['steps'] if item['action'] != 'skip']
        for action, name in operations:
            print(f'{action}\t{name}', flush=True)
        if dry_run:
            return operations
        if not operations and old and old.get('files') == sorted(files):
            return operations
        recheck_configuration(plan, source, target)
        session = state / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
        safe_path(session)
        session.mkdir(parents=True)
        # Back up every changed destination before starting any target writes.
        journal = {'source': str(source), 'target': str(target), 'operations': operations,
                   'status': 'prepared', 'plan': plan}
        for action, name in operations:
            dest = safe_path(target, name)
            if dest.exists():
                backup = session / 'files' / name
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, backup)
        atomic_write(session / 'journal.json', json.dumps(journal, ensure_ascii=False, indent=2).encode())
        recheck_configuration(plan, source, target)
        completed = []
        try:
            for action, name in operations:
                dest = safe_path(target, name)
                if action == 'delete':
                    dest.unlink()
                else:
                    atomic_write(dest, files[name])
                completed.append((action, name))
            manifest = {'source': str(source), 'target': str(target), 'files': sorted(files)}
            atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode())
        except BaseException:
            for action, name in reversed(completed):
                dest = safe_path(target, name)
                if action == 'create':
                    dest.unlink(missing_ok=True)
                else:
                    atomic_write(dest, (session / 'files' / name).read_bytes())
            raise
        journal['status'] = 'applied'
        atomic_write(session / 'journal.json', json.dumps(journal, ensure_ascii=False, indent=2).encode())
        from client.maintenance.backup_retention import completed as complete_backup
        complete_backup(session)
        print(f'备份与操作记录: {session}', flush=True)
        return operations


